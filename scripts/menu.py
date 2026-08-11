"""Orquestrador interativo de coleta TJSP / e-SAJ.

Menu:
  1 - coleta todos os processos da lista; falhas ficam na fila de recoleta
  2 - recoleta apenas os que falharam
  3 - coleta processos citados no relacionamento que não foram coletados
  4 - transforma os dados coletados na estrutura JSON final (local, sem rede)
  0 - sai

O BANCO é a fonte da verdade; os .txt são VISÕES regeneradas a cada execução.
Isso evita pedir que alguém edite à mão um arquivo com milhares de linhas — e
evita que um erro nessa edição destrua a lista de falhas, que representa semanas
de coleta.

Retomada: cada processo é uma transação. Interromper é seguro em qualquer ponto;
basta rodar a mesma opção de novo.

Um PROJETO = uma lista + um banco + uma pasta de saída, todos derivados do nome
passado na linha de comando. Bases diferentes com processos em comum não
interferem uma na outra.

O banco NÃO pode ficar em pasta sincronizada. Defina ORQUESTRADOR_DB_DIR
apontando para uma pasta em disco local se o projeto viver no OneDrive/Drive.
"""

import os
import re
import sys
import threading
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tqdm import tqdm

from src.aggregators.exportador import escrever_lista_orfaos, exportar_jsonl
from src.scrapers.coletor import coletar_um
from src.scrapers.esaj_client import EsajClient, MonitorFalhas, Pacer
from src.scrapers.exceptions import EsajIndisponivelError
from src.scrapers.numero_processo import NumeroProcesso
from src.status import ERRO_TRANSITORIO, ORIGEM_LISTA, ORIGEM_ORFAO
from src.store.sqlite_store import PastaSincronizadaError, SqliteStore
from src.transformers.vinculo import INDEFINIDO, VERSAO_REGRA, derivar_vinculo

DIR_DADOS = RAIZ / "data"
# Os bancos ficam fora de data/ se ORQUESTRADOR_DB_DIR apontar para disco local.
DIR_BANCOS = Path(os.environ.get("ORQUESTRADOR_DB_DIR") or (DIR_DADOS / "bancos"))

# Definidos por configurar_projeto(). Um PROJETO = um banco + uma saída, para
# que bases diferentes com processos em comum não interfiram uma na outra.
ENTRADA = SAIDA = JSONL = ORFAOS = FALHAS = REVISAO = INVALIDOS = BANCO = None


def configurar_projeto(nome):
    global ENTRADA, SAIDA, JSONL, ORFAOS, FALHAS, REVISAO, INVALIDOS, BANCO
    ENTRADA = DIR_DADOS / "entrada" / f"{nome}.txt"
    SAIDA = DIR_DADOS / "saida" / nome
    JSONL = SAIDA / "base_final.jsonl"
    ORFAOS = SAIDA / "orfaos.txt"
    FALHAS = SAIDA / "falhas_pendentes.txt"
    REVISAO = SAIDA / "revisao_manual.txt"
    INVALIDOS = SAIDA / "numeros_invalidos.txt"
    BANCO = DIR_BANCOS / f"{nome}.db"


# Workers NÃO aumentam a taxa vista pelo e-SAJ: o Pacer é global e o teto
# continua 1 requisição a cada 1,7-2,5s. Eles evitam que um pico de latência
# numa página deixe a fila ociosa e perca slots.
WORKERS = max(1, int(os.environ.get("ORQUESTRADOR_WORKERS") or 3))

_local = threading.local()


def fabrica_cliente(pacer, monitor):
    """Um EsajClient por thread (a Session do curl_cffi não é thread-safe);
    Pacer e monitor de falhas compartilhados por todas."""
    def obter():
        cliente = getattr(_local, "cliente", None)
        if cliente is None:
            cliente = EsajClient(pacer=pacer, monitor=monitor)
            _local.cliente = cliente
        return cliente
    return obter


def _agora_tag():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _escrever_atomico(caminho, linhas):
    """tmp + os.replace: interromper nunca deixa um arquivo pela metade — e a
    lista de falhas é o dado mais caro de reconstruir do pipeline."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(caminho) + ".tmp")
    tmp.write_text("\n".join(linhas) + ("\n" if linhas else ""), encoding="utf-8")
    os.replace(tmp, caminho)


def ler_numeros(caminho):
    """Lê o .txt (um número por linha) e devolve (válidos, inválidos).

    utf-8-sig remove o BOM que o Excel insere e que quebraria o primeiro número
    em silêncio. Dedup com set(). Valida o DV antes de gastar requisição.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return [], []

    texto = caminho.read_text(encoding="utf-8-sig")
    validos, invalidos, vistos = [], [], set()
    for bruto in texto.splitlines():
        linha = bruto.strip()
        if not linha or linha.startswith("#"):
            continue
        np = NumeroProcesso.tentar(linha)
        if np is None:
            invalidos.append(f"{linha}\t(não tem 20 dígitos)")
            continue
        if not np.dv_valido:
            invalidos.append(f"{linha}\t(DV inválido; esperado {np.dv_esperado})")
            continue
        if not np.do_tjsp:
            invalidos.append(f"{linha}\t(não é TJSP: J={np.segmento} TR={np.tribunal})")
            continue
        if np.digitos in vistos:
            continue
        vistos.add(np.digitos)
        validos.append(np.digitos)
    return validos, invalidos


def executar_coleta(store, fabrica, numeros, origem, descricao):
    """Laço de coleta com pool de workers.

    Os workers fazem SÓ rede e parse; quem grava no banco é a thread principal.
    Assim o SqliteStore não precisa ser thread-safe — menos código e menos risco
    do que um lock de escrita ou uma thread escritora dedicada.

    A submissão é LIMITADA a WORKERS*2 em voo: enfileirar 250 mil futures de uma
    vez estouraria a memória antes da primeira requisição sair.

    Nenhuma falha de um processo derruba o laço; só o circuit breaker (e-SAJ
    fora do ar / bloqueio) interrompe, de propósito.
    """
    resumo = Counter()
    parada = None
    barra = tqdm(total=len(numeros), desc=descricao, unit="proc")

    def tarefa(numero):
        np = NumeroProcesso.tentar(numero)
        if np is None:
            return numero, None
        return numero, coletar_um(np, fabrica())

    def gravar(numero, r):
        if r is None:
            resumo["invalido"] += 1
            return
        if r.status == ERRO_TRANSITORIO:
            st = store.registrar_erro(numero, r.motivo, origem=origem)
            resumo[st] += 1
            tqdm.write(f"[{st}] {numero}: {r.motivo}")
            return

        # `tipo` do relacionamento tem UM único escritor: derivar_vinculo.
        # Sem bruto (segredo de justiça, sem dados) o tipo é INDEFINIDO, não
        # sem_vinculo: nunca chegamos a olhar a capa, então "não há sinal de
        # pai" seria afirmação sobre algo que a coleta não observou.
        vinc = {"tipo": INDEFINIDO, "processo_pai": None,
                "processo_pai_grau": None, "observacoes": []}
        bruto = r.bruto
        if bruto:
            vinc = derivar_vinculo(bruto, r.grau, numero)
            bruto = dict(bruto)
            bruto["observacoes"] = vinc["observacoes"]

        store.registrar_resultado(
            numero, r.grau, r.status, bruto=bruto,
            processo_pai=vinc["processo_pai"],
            processo_pai_grau=vinc["processo_pai_grau"],
            tipo_vinculo=vinc["tipo"], origem=origem,
        )
        resumo[r.status] += 1
        tqdm.write(f"[{r.status}] {numero} (grau {r.grau})")

    pendentes = set()
    fila = iter(numeros)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        try:
            while True:
                while parada is None and len(pendentes) < WORKERS * 2:
                    try:
                        pendentes.add(pool.submit(tarefa, next(fila)))
                    except StopIteration:
                        break
                if not pendentes:
                    break
                prontos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
                for futuro in prontos:
                    try:
                        numero, r = futuro.result()
                    except EsajIndisponivelError as erro:
                        # Para de submeter, mas drena o que já está em voo:
                        # esses resultados foram pagos e não podem ser perdidos.
                        parada = str(erro)
                        continue
                    gravar(numero, r)
                    barra.update(1)
        except KeyboardInterrupt:
            parada = "interrompido pelo usuário (Ctrl+C)"
        finally:
            for futuro in pendentes:
                futuro.cancel()
            barra.close()
    return resumo, parada

def atualizar_arquivos_de_falha(store):
    """Regenera as VISÕES do banco. O usuário nunca edita estes arquivos."""
    pendentes = store.numeros_com_erro_transitorio()
    persistentes = store.numeros_com_erro_persistente()
    _escrever_atomico(FALHAS, [p["processo"] for p in pendentes])
    _escrever_atomico(
        REVISAO,
        ["# Estouraram o teto de tentativas e saíram da fila automática.",
         "# processo\ttentativas\túltimo_erro"]
        + [f"{p['processo']}\t{p['tentativas']}\t{p['ultimo_erro']}"
           for p in persistentes],
    )
    return len(pendentes), len(persistentes)


def escrever_relatorio(nome, cabecalho, linhas):
    caminho = SAIDA / f"{nome}_{_agora_tag()}.txt"
    _escrever_atomico(caminho, cabecalho + linhas)
    return caminho


def _mostrar(resumo, parada, store):
    print("\nResumo desta execução:")
    for chave, n in sorted(resumo.items()):
        print(f"  {chave:20} {n}")
    pend, persist = atualizar_arquivos_de_falha(store)
    print(f"\nFalhas pendentes (opção 2): {pend}  -> {FALHAS.name}")
    print(f"Revisão manual:             {persist}  -> {REVISAO.name}")
    print(f"Total no banco: {store.total()} | por status: {store.contagem_por_status()}")
    if parada:
        print(f"\n!! EXECUÇÃO INTERROMPIDA: {parada}")
        print("   Nada foi perdido. Rode a mesma opção para retomar de onde parou.")


# --- opções do menu ---------------------------------------------------------
def opcao_1(store, fabrica):
    validos, invalidos = ler_numeros(ENTRADA)
    if invalidos:
        _escrever_atomico(INVALIDOS, ["# número\tmotivo"] + invalidos)
        print(f"{len(invalidos)} números inválidos -> {INVALIDOS.name}")
    if not validos:
        print(f"Nenhum número válido em {ENTRADA}. Nada a fazer.")
        return

    feitos = store.numeros_finalizados()  # retomada: pula o que já tem resultado
    fila = [n for n in validos if n not in feitos]
    print(f"Lista: {len(validos)} | já finalizados: {len(feitos)} | "
          f"a coletar: {len(fila)}")
    if not fila:
        print("Tudo já coletado.")
        return

    resumo, parada = executar_coleta(store, fabrica, fila, ORIGEM_LISTA, "Coletando")
    _mostrar(resumo, parada, store)


def opcao_2(store, fabrica):
    pendentes = [p["processo"] for p in store.numeros_com_erro_transitorio()]
    if not pendentes:
        print("\nNão há falhas pendentes para recoletar.")
        print("Rode a opção 1 primeiro, ou confira revisao_manual.txt.")
        return

    print(f"Recoletando {len(pendentes)} processos que falharam...")
    resumo, parada = executar_coleta(
        store, fabrica, pendentes, ORIGEM_LISTA, "Recoletando"
    )

    ainda = {p["processo"] for p in store.numeros_com_erro_transitorio()}
    persist = {p["processo"] for p in store.numeros_com_erro_persistente()}
    linhas = []
    for numero in pendentes:
        if numero in persist:
            linhas.append(f"{numero}\t(falha - excedeu as tentativas)")
        elif numero in ainda:
            linhas.append(f"{numero}\t(falha)")
        else:
            linhas.append(f"{numero}\t(coletado com sucesso)")

    caminho = escrever_relatorio(
        "relatorio_recoleta",
        [f"# Recoleta de {_agora_tag()}",
         f"# {len(pendentes)} processos tentados.",
         "# Este arquivo é AUDITORIA: não precisa editar, apagar linhas nem",
         f"# renomear. A fila da opção 2 é regenerada em {FALHAS.name}.",
         ""],
        linhas,
    )
    print(f"\nRelatório: {caminho.name}")
    _mostrar(resumo, parada, store)


def opcao_3(store, fabrica):
    if not ORFAOS.exists():
        print(f"\n{ORFAOS.name} não existe. Rode a opção 4 primeiro para gerá-lo.")
        return
    numeros, _ = ler_numeros(ORFAOS)
    feitos = store.numeros_finalizados()
    fila = [n for n in numeros if n not in feitos]
    if not fila:
        print("\nNão há processos de relacionamento pendentes de coleta.")
        print("O grafo está completo. Voltando ao menu.")
        return
    print(f"Órfãos no arquivo: {len(numeros)} | a coletar: {len(fila)}")
    resumo, parada = executar_coleta(
        store, fabrica, fila, ORIGEM_ORFAO, "Coletando órfãos"
    )
    _mostrar(resumo, parada, store)


def opcao_4(store):
    """Local, sem rede. Reprojeta vínculos, exporta o JSONL e recalcula órfãos.

    A reprojeção vem PRIMEIRO porque orfaos() e o mapa de filhos são calculados
    a partir das colunas de vínculo: exportar antes de reprojetar produziria uma
    base final coerente com a regra ANTIGA de derivação.
    """
    SAIDA.mkdir(parents=True, exist_ok=True)
    rep = store.reprojetar_vinculos(
        derivar_vinculo, INDEFINIDO, VERSAO_REGRA, log=tqdm.write
    )
    if rep["pulado"]:
        print(f"Vínculos já na regra v{VERSAO_REGRA} — reprojeção dispensada.")
    else:
        print(f"Vínculos reprojetados para a regra v{VERSAO_REGRA}: "
              f"{rep['vistos']} lidos | {rep['alterados']} atualizados")

    print("Exportando base final...")
    resumo = exportar_jsonl(store, JSONL, log=tqdm.write)
    orfaos = escrever_lista_orfaos(store, ORFAOS)

    print(f"\nBase final: {resumo['arquivo']}")
    print(f"  registros:  {resumo['total']}")
    print(f"  por status: {resumo['por_status']}")
    print(f"  por grau:   {resumo['por_grau']}")
    print(f"  com pai: {resumo['com_pai']} | com filhos: {resumo['com_filhos']}")
    print(f"  pares (pai, grau) sem documento: {resumo['pares_pai_sem_documento']}")

    if orfaos:
        print(f"\n{len(orfaos)} processos aparecem no relacionamento mas não têm")
        print(f"registro -> {ORFAOS.name}. Rode a opção 3 para coletá-los.")
    else:
        print("\nNenhum órfão: todo processo citado no relacionamento tem registro.")


MENU = """
============================================================
 ORQUESTRADOR DE COLETA - TJSP / e-SAJ
============================================================
 COLOQUE O N° DOS PROCESSOS EM "entrada/nome_projeto.txt" 
 E SIGA O PASSO A PASSO A SEGUIR: 

 1 → 4 → 3 (se houver) → 4 de novo. 
 A opção 2 só faz sentido se a 1 reportar falhas.
============================================================
 1 - Coletar todos os processos da lista
 2 - Recoletar apenas os que falharam
 3 - Coletar processos que aparecem nos relacionamentos
 4 - Transformar os dados coletados na estrutura final
 0 - Sair
------------------------------------------------------------"""


def main():
    nome = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    while not nome:
        nome = input("Nome do projeto (ex.: iamspe_2026): ").strip()
    nome = re.sub(r"[^A-Za-z0-9_.-]", "_", nome)
    configurar_projeto(nome)

    try:
        store = SqliteStore(BANCO)
    except PastaSincronizadaError as erro:
        print(f"\n{erro}\n")
        print("Defina ORQUESTRADOR_DB_DIR apontando para uma PASTA em disco local:")
        print("  PowerShell:  $env:ORQUESTRADOR_DB_DIR = 'C:\\dados_coleta'")
        print("  bash:        export ORQUESTRADOR_DB_DIR=/home/voce/dados_coleta")
        return

    print(f"Projeto: {nome}")
    print(f"Banco:   {BANCO}")
    print(f"Entrada: {ENTRADA}")
    print(f"Saída:   {SAIDA}")
    print(f"Workers: {WORKERS} (cadência global: 1 requisição a cada 1,7-2,5s)")
    fabrica = None  # só criada quando alguma opção precisa de rede
    try:
        while True:
            print(MENU)
            escolha = input("Opção: ").strip()
            if escolha == "0":
                print("Até logo.")
                return
            if escolha == "4":
                opcao_4(store)
                continue
            if escolha not in ("1", "2", "3"):
                print("Opção inválida.")
                continue
            if fabrica is None:
                # Pacer e monitor criados UMA vez e compartilhados por todos os
                # workers — é isso que mantém a cadência e o circuito globais.
                fabrica = fabrica_cliente(Pacer(), MonitorFalhas())
            {"1": opcao_1, "2": opcao_2, "3": opcao_3}[escolha](store, fabrica)
    finally:
        store.fechar()


if __name__ == "__main__":
    main()
    