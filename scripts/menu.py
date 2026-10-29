"""Orquestrador interativo de coleta TJSP / e-SAJ.

Menu:
  1 - coleta todos os processos da lista; falhas ficam na fila de recoleta
  2 - recoleta apenas os que falharam
  3 - coleta processos citados no relacionamento que não foram coletados
  4 - transforma os dados coletados na estrutura JSON final (local, sem rede)
  5 - recoleta os sem dado de Colégio Recursal (9xxx) e DEPRE (0500), gravados
      antes de a coleta conhecer essas rotas
  6 - recoleta a base inteira e atualiza os registros; falha mantém o anterior
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
from src.status import (
    ATUALIZACAO_DESISTIDA,
    ATUALIZACAO_FEITA,
    ATUALIZACAO_MANTIDA,
    ATUALIZACAO_PENDENTE,
    ERRO_TRANSITORIO,
    ORIGEM_LISTA,
    ORIGEM_ORFAO,
)
from src.store.sqlite_store import PastaSincronizadaError, SqliteStore
from src.transformers.vinculo import INDEFINIDO, VERSAO_REGRA, derivar_vinculo

DIR_DADOS = RAIZ / "data"
# Os bancos ficam fora de data/ se ORQUESTRADOR_DB_DIR apontar para disco local.
DIR_BANCOS = Path(os.environ.get("ORQUESTRADOR_DB_DIR") or (DIR_DADOS / "bancos"))

# Definidos por configurar_projeto(). Um PROJETO = um banco + uma saída, para
# que bases diferentes com processos em comum não interfiram uma na outra.
ENTRADA = SAIDA = JSONL = ORFAOS = FALHAS = REVISAO = INVALIDOS = BANCO = None
NAO_ATUALIZADOS = None


def configurar_projeto(nome):
    global ENTRADA, SAIDA, JSONL, ORFAOS, FALHAS, REVISAO, INVALIDOS, BANCO
    global NAO_ATUALIZADOS
    ENTRADA = DIR_DADOS / "entrada" / f"{nome}.txt"
    SAIDA = DIR_DADOS / "saida" / nome
    JSONL = SAIDA / "base_final.jsonl"
    ORFAOS = SAIDA / "orfaos.txt"
    FALHAS = SAIDA / "falhas_pendentes.txt"
    REVISAO = SAIDA / "revisao_manual.txt"
    INVALIDOS = SAIDA / "numeros_invalidos.txt"
    NAO_ATUALIZADOS = SAIDA / "atualizacao_nao_atualizados.txt"
    BANCO = DIR_BANCOS / f"{nome}.db"


# Workers NÃO aumentam a taxa vista pelo e-SAJ: o Pacer é global e o teto é o
# dele (1,1-1,6s por padrão); só os 'Mais' das movimentações ficam fora da
# cadência (ver esaj_client). Eles evitam que um pico de latência numa página
# deixe a fila ociosa e perca slots.
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


def _vinculo_do_resultado(numero, r):
    """(bruto, vínculo) prontos para gravar um resultado terminal.

    `tipo` do relacionamento tem UM único escritor: derivar_vinculo. Sem bruto
    (segredo de justiça, sem dados) o tipo é INDEFINIDO, não sem_vinculo: nunca
    chegamos a olhar a capa, então "não há sinal de pai" seria afirmação sobre
    algo que a coleta não observou.
    """
    vinc = {"tipo": INDEFINIDO, "processo_pai": None,
            "processo_pai_grau": None, "observacoes": []}
    bruto = r.bruto
    if bruto:
        vinc = derivar_vinculo(bruto, r.grau, numero)
        bruto = dict(bruto)
        bruto["observacoes"] = vinc["observacoes"]
    return bruto, vinc


def executar_coleta(store, fabrica, numeros, origem, descricao, gravar=None):
    """Laço de coleta com pool de workers.

    Os workers fazem SÓ rede e parse; quem grava no banco é a thread principal.
    Assim o SqliteStore não precisa ser thread-safe — menos código e menos risco
    do que um lock de escrita ou uma thread escritora dedicada.

    A submissão é LIMITADA a WORKERS*2 em voo: enfileirar 250 mil futures de uma
    vez estouraria a memória antes da primeira requisição sair.

    Nenhuma falha de um processo derruba o laço; só o circuit breaker (e-SAJ
    fora do ar / bloqueio) interrompe, de propósito.

    `gravar(numero, resultado)` persiste um resultado e devolve o rótulo do
    resumo. O padrão é o da coleta (opções 1, 2, 3 e 5), com `origem`; a opção 6
    passa o seu, que nunca toca o registro numa falha.
    """
    resumo = Counter()
    parada = None
    barra = tqdm(total=len(numeros), desc=descricao, unit="proc")

    def tarefa(numero):
        np = NumeroProcesso.tentar(numero)
        if np is None:
            return numero, None
        return numero, coletar_um(np, fabrica())

    def gravar_coleta(numero, r):
        if r.status == ERRO_TRANSITORIO:
            st = store.registrar_erro(numero, r.motivo, origem=origem)
            tqdm.write(f"[{st}] {numero}: {r.motivo}")
            return st
        bruto, vinc = _vinculo_do_resultado(numero, r)
        store.registrar_resultado(
            numero, r.grau, r.status, bruto=bruto,
            processo_pai=vinc["processo_pai"],
            processo_pai_grau=vinc["processo_pai_grau"],
            tipo_vinculo=vinc["tipo"], origem=origem,
        )
        tqdm.write(f"[{r.status}] {numero} (grau {r.grau})")
        return r.status

    gravar = gravar or gravar_coleta

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
                    resumo["invalido" if r is None else gravar(numero, r)] += 1
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
    _relatorio_recoleta(store, pendentes, "relatorio_recoleta")
    _mostrar(resumo, parada, store)


def _relatorio_recoleta(store, numeros, nome):
    """Auditoria de uma recoleta (opções 2 e 5): o desfecho de cada número."""
    ainda = {p["processo"] for p in store.numeros_com_erro_transitorio()}
    persist = {p["processo"] for p in store.numeros_com_erro_persistente()}
    linhas = []
    for numero in numeros:
        if numero in persist:
            linhas.append(f"{numero}\t(falha - excedeu as tentativas)")
        elif numero in ainda:
            linhas.append(f"{numero}\t(falha)")
        else:
            linhas.append(f"{numero}\t(coletado com sucesso)")

    caminho = escrever_relatorio(
        nome,
        [f"# Recoleta de {_agora_tag()}",
         f"# {len(numeros)} processos tentados.",
         "# Este arquivo é AUDITORIA: não precisa editar, apagar linhas nem",
         f"# renomear. A fila da opção 2 é regenerada em {FALHAS.name}.",
         ""],
        linhas,
    )
    print(f"\nRelatório: {caminho.name}")


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


#: Rotas do e-SAJ que a coleta aprendeu quando já havia bases coletadas. Antes
#: delas, o Colégio Recursal respondia "não existe" no cpopg e no cposg e virava
#: sem_dados — resultado FINAL, nunca mais tentado —, e o DEPRE respondia "sem
#: acesso" até estourar o teto e parar na revisão manual. Chave = propriedade de
#: NumeroProcesso que reconhece a origem; vai para `meta` quando a rota é
#: reaberta, então uma rota nova acrescentada aqui é a única reaberta na próxima
#: execução da opção 5.
ROTAS_NOVAS = {
    "colegio_recursal": "Colégio Recursal (foro 9xxx)",
    "requisitorio": "DEPRE (foro 0500)",
}
META_ROTAS = "rotas_reabertas"


def rota_nova(numero, rotas=ROTAS_NOVAS):
    """Chave da rota nova que atende o número, ou None."""
    np = NumeroProcesso.tentar(numero)
    return next((r for r in rotas if np and getattr(np, r)), None)


def reabrir_rotas_novas(store):
    """Uma vez por banco e por rota: devolve à fila da opção 2, com as
    tentativas zeradas, os registros sem dado das origens de ROTAS_NOVAS.
    Usada pela opção 5 e pelo preparar_base_final (banco `faltantes_<ano>`).

    Por que uma vez só: depois da reabertura, um sem_dados dessas origens já veio
    da rota certa e é resultado legítimo; reabrir de novo zeraria também as
    tentativas de quem falha de verdade, e a fila nunca esvaziaria.
    Devolve quantos registros foram reabertos.
    """
    feitas = set(filter(None, (store.ler_meta(META_ROTAS) or "").split(",")))
    novas = [r for r in ROTAS_NOVAS if r not in feitas]
    if not novas:
        return 0
    numeros, por_rota = [], Counter()
    for linha in store.numeros_sem_observacao():
        rota = rota_nova(linha["processo"], novas)
        if rota:
            numeros.append(linha["processo"])
            por_rota[rota, linha["status"]] += 1
    print("\nRegistros sem dado gravados antes destas rotas:")
    for rota in novas:
        detalhe = ", ".join(f"{st} {n}" for (r, st), n in sorted(por_rota.items())
                            if r == rota)
        print(f"  {ROTAS_NOVAS[rota]:30} {detalhe or 'nenhum'}")
    reabertos = store.reabrir(numeros, "reaberto: rota nova do e-SAJ")
    # A marca vem DEPOIS: uma queda entre as duas só repete a reabertura, que é
    # idempotente; na ordem inversa, deixaria registros sem reabrir.
    store.gravar_meta(META_ROTAS, ",".join(sorted(feitas | set(novas))))
    print(f"{reabertos} reabertos: voltam à fila da opção 2, tentativas zeradas.")
    return reabertos


def opcao_5(store, fabrica):
    """Reabre (uma vez por banco) os registros sem dado do Colégio Recursal e do
    DEPRE e recoleta os pendentes dessas origens — nesta e em toda execução
    seguinte —, como a opção 2: mesmo teto, mesmos arquivos de falha."""
    reabrir_rotas_novas(store)
    fila = [p["processo"] for p in store.numeros_com_erro_transitorio()
            if rota_nova(p["processo"])]
    if not fila:
        print("\nNenhum processo do Colégio Recursal ou do DEPRE pendente de coleta.")
        return
    print(f"Recoletando {len(fila)} processos do Colégio Recursal e do DEPRE...")
    resumo, parada = executar_coleta(store, fabrica, fila, ORIGEM_LISTA, "Rotas novas")
    _relatorio_recoleta(store, fila, "relatorio_rotas_novas")
    _mostrar(resumo, parada, store)
    if not parada:
        print("Rode a opção 4 para levar os dados recuperados à base final.")


def _gravar_atualizacao(store):
    """Gravador da opção 6. A falha conta tentativa na fila da rodada e NÃO toca
    o registro: o dado anterior continua valendo até chegar um resultado novo."""
    def gravar(numero, r):
        if r.status == ERRO_TRANSITORIO:
            sit = store.registrar_falha_atualizacao(numero, r.motivo)
            rotulo = "falhou" if sit == ATUALIZACAO_PENDENTE else sit
            tqdm.write(f"[{rotulo}] {numero}: {r.motivo}")
            return rotulo
        bruto, vinc = _vinculo_do_resultado(numero, r)
        sit = store.registrar_atualizacao(
            numero, r.grau, r.status, bruto=bruto,
            processo_pai=vinc["processo_pai"],
            processo_pai_grau=vinc["processo_pai_grau"],
            tipo_vinculo=vinc["tipo"],
        )
        tqdm.write(f"[{sit}] {numero} ({r.status}, grau {r.grau})")
        return sit
    return gravar


def _mostrar_atualizacao(resumo, parada, store):
    _mostrar(resumo, parada, store)
    nao = store.nao_atualizados()
    _escrever_atomico(
        NAO_ATUALIZADOS,
        ["# A atualização NÃO substituiu estes registros: o dado anterior continua.",
         "# mantido = o e-SAJ respondeu algo menos informativo que o gravado;",
         "# desistido = falhou em todas as tentativas da rodada.",
         "# processo\tsituação\ttentativas\tmotivo"]
        + [f"{p['processo']}\t{p['situacao']}\t{p['tentativas']}\t{p['ultimo_erro']}"
           for p in nao],
    )
    rod = store.rodada_atualizacao()
    print(f"\nRodada de atualização iniciada em {rod['iniciada_em']}:")
    print(f"  atualizados {rod[ATUALIZACAO_FEITA]} | mantidos {rod[ATUALIZACAO_MANTIDA]}"
          f" | desistidos {rod[ATUALIZACAO_DESISTIDA]}"
          f" | pendentes {rod[ATUALIZACAO_PENDENTE]} (já falharam: {rod['falharam']})")
    print(f"Não atualizados: {len(nao)} -> {NAO_ATUALIZADOS.name}")
    if parada:
        return
    if rod[ATUALIZACAO_PENDENTE]:
        print(f"\nRode a opção 6 de novo para tentar os {rod[ATUALIZACAO_PENDENTE]} "
              "que falharam.")
    else:
        print("\nRodada concluída. Rode a opção 4 para levar os dados novos à base")
        print("final (e a 3, se ela apontar órfãos novos).")


def opcao_6(store, fabrica):
    """Recoleta TODOS os números do banco, numa rodada retomável.

    A rodada é uma fila no banco (tabela `atualizacao`): interromper e rodar a 6
    de novo continua de onde parou. Uma rodada nova só começa quando a anterior
    não tem pendentes, e só com confirmação — oferecendo backup antes.

    O dado coletado nunca fica pior do que estava: uma falha só conta tentativa
    na fila (mesmo teto da opção 2) e um resultado menos informativo não
    substitui o anterior; os dois casos saem em NAO_ATUALIZADOS. A base final
    só muda quando a opção 4 roda.
    """
    rodada = store.rodada_atualizacao()
    if rodada and rodada[ATUALIZACAO_PENDENTE]:
        print(f"\nRetomando a rodada iniciada em {rodada['iniciada_em']}: "
              f"{rodada[ATUALIZACAO_PENDENTE]} pendentes "
              f"({rodada['falharam']} já falharam ao menos uma vez).")
    else:
        if rodada:
            print(f"\nA rodada iniciada em {rodada['iniciada_em']} terminou: "
                  f"{rodada[ATUALIZACAO_FEITA]} atualizados, "
                  f"{rodada[ATUALIZACAO_MANTIDA]} mantidos, "
                  f"{rodada[ATUALIZACAO_DESISTIDA]} desistidos.")
        total = store.total()
        if not total:
            print("\nO banco está vazio. Rode a opção 1 primeiro.")
            return
        print(f"\nIsto recoleta TODOS os {total} registros do banco, no mesmo ritmo")
        print("da coleta original — numa base grande, são dias. Pode ser")
        print("interrompida e retomada a qualquer momento pela própria opção 6.")
        print("Um registro só é substituído quando a recoleta dá certo.")
        if input("Iniciar uma rodada nova? [s/N] ").strip().lower() not in ("s", "sim"):
            print("Nada foi alterado.")
            return
        mb = BANCO.stat().st_size / 1e6
        if input(f"Fazer backup do banco antes ({mb:.0f} MB)? [S/n] ").strip().lower() \
                not in ("n", "nao", "não"):
            print("Copiando o banco...")
            destino = store.backup(
                DIR_BANCOS / f"{BANCO.stem}_antes_atualizacao_{_agora_tag()}.db"
            )
            print(f"Backup: {destino}")
        print(f"Rodada nova: {store.iniciar_atualizacao()} processos na fila.")

    resumo, parada = executar_coleta(
        store, fabrica, store.fila_atualizacao(), None, "Atualizando",
        gravar=_gravar_atualizacao(store),
    )
    _mostrar_atualizacao(resumo, parada, store)


MENU = """
============================================================
 ORQUESTRADOR DE COLETA - TJSP / e-SAJ
============================================================
 COLOQUE O N° DOS PROCESSOS EM "entrada/nome_projeto.txt" 
 E SIGA O PASSO A PASSO A SEGUIR: 

 1 → 4 → 3 (se houver) → 4 de novo.
 A opção 2 só faz sentido se a 1 reportar falhas.
 Base antiga, com 9xxx/0500 sem dados: 5 → 4.
 Renovar a base inteira: 6 (até concluir) → 4 → 3 → 4.
============================================================
 1 - Coletar todos os processos da lista
 2 - Recoletar apenas os que falharam
 3 - Coletar processos que aparecem nos relacionamentos
 4 - Transformar os dados coletados na estrutura final
 5 - Recoletar Colégio Recursal (9xxx) e DEPRE (0500)
 6 - Recoletar e atualizar a base inteira
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
    cadencia = Pacer()  # lê o padrão do Pacer, para a mensagem nunca divergir dele
    print(f"Workers: {WORKERS} (cadência global: 1 requisição a cada "
          f"{cadencia.minimo}-{cadencia.maximo}s)")
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
            opcoes = {"1": opcao_1, "2": opcao_2, "3": opcao_3,
                      "5": opcao_5, "6": opcao_6}
            if escolha not in opcoes:
                print("Opção inválida.")
                continue
            if fabrica is None:
                # Pacer e monitor criados UMA vez e compartilhados por todos os
                # workers — é isso que mantém a cadência e o circuito globais.
                fabrica = fabrica_cliente(Pacer(), MonitorFalhas())
            opcoes[escolha](store, fabrica)
    finally:
        store.fechar()


if __name__ == "__main__":
    main()
    