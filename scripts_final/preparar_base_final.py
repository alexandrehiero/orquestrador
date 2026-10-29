"""Prepara a base final de um ano: confere, completa, desduplica e estrutura.

Para usar depois de terminar uma coleta com o orquestrador e copiar o JSONL para
`data_final/JSONL_final/base_final_<ano>.jsonl`:

  1 auditoria   (local) confronta o JSONL com data/por_ano/processos_tjsp_<ano>.txt
  2 coleta      (REDE)  busca no e-SAJ o que falta, os erro_persistente e os
                        sem_dados de 9xxx/0500, pelo próprio orquestrador
  3 consolidação(local) acrescenta a coleta ao JSONL e remove os duplicados
  4 índice PGE  (local) separa do processos_PGE.json os processos da base
  5 estrutura   (local) grava data_final/JSON_final/base_final_<ano>.json

Interromper é seguro em qualquer ponto. A coleta grava no banco do projeto
`faltantes_<ano>` e retoma de onde parou; todo arquivo de saída só troca de nome
no fim. Com a base já completa, rodar de novo não usa a rede nem reescreve o
JSONL: só refaz a estrutura final.

    uv run python scripts_final/preparar_base_final.py 2025
    uv run python scripts_final/preparar_base_final.py 2025 --sem-coleta
    uv run python scripts_final/preparar_base_final.py 2025 --amostra 2000
    uv run python scripts_final/preparar_base_final.py 2025 --recoletar lista.txt
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tqdm import tqdm

from scripts import menu
from src.aggregators import atos_pge, consolidacao, exportador_gpdr
from src.aggregators.exportador import exportar_jsonl
from src.scrapers.esaj_client import MonitorFalhas, Pacer
from src.status import ERRO_PERSISTENTE, ORIGEM_LISTA, SEM_DADOS, TETO_TENTATIVAS_PADRAO
from src.store.sqlite_store import PastaSincronizadaError, SqliteStore
from src.transformers import estrutura_gpdr, monetario
from src.transformers.vinculo import INDEFINIDO, VERSAO_REGRA, derivar_vinculo

DIR_FINAL = RAIZ / "data_final"
ATOS_PGE = menu.DIR_DADOS / "processos_PGE.json"
IPCA = menu.DIR_DADOS / "ipca_mensal.csv"
FOROS = menu.DIR_DADOS / "unidades_foro_tjsp.md"
NOME_FONTE = {consolidacao.FONTE_BASE: "base", consolidacao.FONTE_COLETA: "coleta"}

DESCRICAO = (
    "Base final do orquestrador na estrutura da v7 do GPDR, sem `metadados`. "
    "Conferida contra a lista do ano, completada pela coleta dos faltantes e "
    "desduplicada por número (fica o status mais informativo). Valor corrigido "
    f"pelo IPCA até {monetario.COMPETENCIA_REFERENCIA}, foro pelo código do CNJ, "
    "nomes formatados e entes do polo passivo unificados como no GPDR. "
    "`movimentos_pge`/`origem_pge` vêm de processos_PGE.json (null sem par). "
    "Status e situação ficam em `processo`, o juiz em `orgaoJulgador`, e "
    "`relacionamento` (filhos recalculados sobre a base inteira) e `observacoes` "
    "fecham o documento, no nível de `processo`."
)


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _barra(caminho, desc):
    return tqdm(total=Path(caminho).stat().st_size, unit="B", unit_scale=True, desc=desc)


def _relatorio(dir_auditoria, nome, cabecalho, linhas):
    """Visões regeneradas a cada execução, como os .txt do menu: nunca entrada."""
    menu._escrever_atomico(dir_auditoria / nome, [f"# {cabecalho}"] + list(linhas))


def _descricao(linha):
    return (f"{NOME_FONTE[linha.fonte]} linha {linha.posicao + 1} "
            f"({linha.status}, grau {linha.grau or '-'})")


def auditar(lista, jsonl, dir_auditoria):
    """Passo 1. Devolve (linhas da base, números da lista, a coletar)."""
    alvo, invalidos = menu.ler_numeros(lista)
    with _barra(jsonl, "1/5 auditoria   ") as barra:
        linhas = list(consolidacao.ler_linhas(jsonl, consolidacao.FONTE_BASE, ao_ler=barra.update))
    mantidas, descartadas = consolidacao.escolher(linhas)
    conjunto = set(alvo)
    faltantes = [n for n in alvo if n not in mantidas]
    sem_desfecho = [n for n in alvo if n in mantidas and mantidas[n].status == ERRO_PERSISTENTE]
    # sem_dados de uma origem que a coleta só passou a alcançar depois (Colégio
    # Recursal, DEPRE): o "não existe" pode ter vindo da rota errada. Voltam para
    # a coleta; se a rota certa confirmar, o empate fica com a base e o JSONL não
    # muda. A base inteira, não só a lista: o erro é do dado, não da lista.
    rotas_novas = sorted(n for n, l in mantidas.items()
                         if l.status == SEM_DADOS and menu.rota_nova(n))
    fora = sorted(set(mantidas) - conjunto)

    _relatorio(dir_auditoria, "faltantes.txt", "Na lista do ano e ausentes do JSONL.", faltantes)
    _relatorio(dir_auditoria, "sem_desfecho.txt",
               "No JSONL como erro_persistente: voltam para a coleta.", sem_desfecho)
    _relatorio(dir_auditoria, "rotas_novas.txt",
               "No JSONL como sem_dados, do Colégio Recursal (9xxx) ou do DEPRE (0500): "
               "voltam para a coleta pela rota nova.", rotas_novas)
    _relatorio(dir_auditoria, "fora_da_lista.txt",
               "No JSONL e fora da lista (ex.: órfãos da opção 3). Mantidos.", fora)
    _relatorio(dir_auditoria, "invalidos.txt", "Linhas da lista rejeitadas, com o motivo.", invalidos)

    print(f"\nLista do ano: {len(alvo):,} números válidos | inválidos: {len(invalidos):,}")
    print(f"JSONL:        {len(linhas):,} linhas | {len(mantidas):,} processos distintos")
    print(f"  faltantes:              {len(faltantes):,}")
    print(f"  sem desfecho (erro):    {len(sem_desfecho):,}")
    print(f"  sem dados de rota nova: {len(rotas_novas):,}")
    print(f"  duplicados a remover:   {len(descartadas):,}")
    print(f"  fora da lista (mantidos): {len(fora):,}")
    return linhas, alvo, faltantes + sem_desfecho + rotas_novas


def coletar(ano, a_coletar, forcados=frozenset()):
    """Passo 2. Busca no e-SAJ, PELO ORQUESTRADOR, o que a base não respondeu.

    Um projeto próprio do menu, `faltantes_<ano>` — lista, banco e saída isolados
    da coleta original. Se algo ficar pendente, o operador continua pelo menu
    normal (`menu.py faltantes_<ano>`). Devolve o JSONL exportado, ou None se a
    coleta foi interrompida (e-SAJ fora do ar, bloqueio ou Ctrl+C).

    `forcados` (--recoletar) são coletados mesmo com desfecho no banco.
    """
    menu.configurar_projeto(f"faltantes_{ano}")
    menu._escrever_atomico(menu.ENTRADA, [
        f"# Gerado por scripts_final/preparar_base_final.py em {_agora()}", *a_coletar
    ])
    try:
        store = SqliteStore(menu.BANCO)
    except PastaSincronizadaError as erro:
        print(f"\n{erro}\nDefina ORQUESTRADOR_DB_DIR apontando para disco local.")
        return None
    try:
        # Um banco de faltantes de antes das rotas novas guarda 9xxx/0500 como
        # sem_dados ou erro_persistente, e numeros_finalizados() os pularia.
        menu.reabrir_rotas_novas(store)
        feitos = store.numeros_finalizados()
        fila = [n for n in a_coletar if n not in feitos or n in forcados]
        print(f"\nProjeto faltantes_{ano}: {len(a_coletar):,} a responder | "
              f"já respondidos no banco: {len(a_coletar) - len(fila):,} | "
              f"a coletar: {len(fila):,}")
        fabrica = menu.fabrica_cliente(Pacer(), MonitorFalhas())
        parada = None
        if fila:
            _, parada = menu.executar_coleta(store, fabrica, fila, ORIGEM_LISTA, "2/5 coleta      ")
        # A opção 2 do menu, sem esperar o operador. Termina: cada falha soma uma
        # tentativa, e no teto o processo vira erro_persistente e sai da fila.
        alvo = set(a_coletar)
        for rodada in range(1, TETO_TENTATIVAS_PADRAO + 1):
            pendentes = [p["processo"] for p in store.numeros_com_erro_transitorio()
                         if p["processo"] in alvo]
            if parada or not pendentes:
                break
            _, parada = menu.executar_coleta(store, fabrica, pendentes, ORIGEM_LISTA,
                                             f"    recoleta {rodada}  ")
        menu.atualizar_arquivos_de_falha(store)
        print(f"Banco faltantes_{ano}: {store.contagem_por_status()}")
        if parada:
            print(f"\n!! COLETA INTERROMPIDA: {parada}")
            print("   Nada foi perdido. Rode o mesmo comando para retomar.")
            return None
        # A opção 4 do menu: reprojeta os vínculos ANTES de exportar.
        store.reprojetar_vinculos(derivar_vinculo, INDEFINIDO, VERSAO_REGRA, log=tqdm.write)
        exportar_jsonl(store, menu.JSONL, log=tqdm.write)
        return menu.JSONL
    finally:
        store.fechar()


def main():
    parser = argparse.ArgumentParser(description="Prepara a base final de um ano.")
    parser.add_argument("ano", help="sufixo do arquivo em data/por_ano (ex.: 2025)")
    parser.add_argument("--sem-coleta", action="store_true",
                        help="não usa a rede; os faltantes ficam só no relatório")
    parser.add_argument("--amostra", type=int, default=0,
                        help="smoke test: não coleta, não reescreve o JSONL e grava "
                             "os N primeiros documentos em data_final/_amostra/")
    parser.add_argument("--recoletar", metavar="ARQUIVO",
                        help="números (um por linha) a recoletar mesmo com desfecho; "
                             "com status igual, fica a coleta nova. Uso pontual, "
                             "quando muda uma regra de extração")
    args = parser.parse_args()
    ano = re.sub(r"[^A-Za-z0-9_.-]", "_", args.ano)
    amostra = args.amostra or None

    lista = menu.DIR_DADOS / "por_ano" / f"processos_tjsp_{ano}.txt"
    jsonl = DIR_FINAL / "JSONL_final" / f"base_final_{ano}.jsonl"
    destino = (DIR_FINAL / "_amostra" / f"base_final_{ano}_amostra.json" if amostra
               else DIR_FINAL / "JSON_final" / f"base_final_{ano}.json")
    dir_auditoria = DIR_FINAL / "auditoria" / ano
    for caminho in (lista, jsonl, ATOS_PGE, IPCA, FOROS):
        if not caminho.exists():
            print(f"ERRO: arquivo não encontrado: {caminho}", file=sys.stderr)
            return 1
    foros = estrutura_gpdr.carregar_foros(FOROS)
    ipca = monetario.carregar_ipca(IPCA)
    if monetario.COMPETENCIA_REFERENCIA not in ipca:
        print(f"ERRO: {monetario.COMPETENCIA_REFERENCIA} fora da tabela do IPCA.", file=sys.stderr)
        return 1
    print(f"Ano {ano} | foros: {len(foros)} códigos | IPCA: {len(ipca)} competências")
    if amostra:
        print(f"AMOSTRA de {amostra}: sem coleta, sem reescrever o JSONL. Saída: {destino}")

    forcados = []
    if args.recoletar:
        if not Path(args.recoletar).exists():
            print(f"ERRO: arquivo não encontrado: {args.recoletar}", file=sys.stderr)
            return 1
        forcados, invalidos = menu.ler_numeros(args.recoletar)
        print(f"Recoleta pedida: {len(forcados):,} números | inválidos: {len(invalidos):,}")

    contagens = Counter()
    linhas, alvo, a_coletar = auditar(lista, jsonl, dir_auditoria)
    ja = set(a_coletar)
    a_coletar += [n for n in forcados if n not in ja]
    fontes = [jsonl]
    if a_coletar and not (amostra or args.sem_coleta):
        exportado = coletar(ano, a_coletar, set(forcados))
        if exportado is None:
            return 1
        fontes.append(exportado)
        linhas += consolidacao.ler_linhas(exportado, consolidacao.FONTE_COLETA, apenas=set(a_coletar))
    elif a_coletar:
        print(f"\n[AVISO] {len(a_coletar):,} processos sem resposta e coleta desligada.")

    mantidas, descartadas = consolidacao.escolher(linhas, preferir_coleta=set(forcados))
    removidas = sum(1 for d in descartadas if d.fonte == consolidacao.FONTE_BASE)
    acrescentadas = sum(1 for l in mantidas.values() if l.fonte == consolidacao.FONTE_COLETA)
    filhos = consolidacao.mapa_filhos(mantidas)
    orfaos = consolidacao.orfaos(mantidas)
    # Pelos anos que a LISTA tem, não pelo argumento: '1913_1973' e 'ano_atipico'
    # cobrem vários anos.
    anos_da_lista = {n[9:13] for n in alvo}
    orfaos_do_ano = sum(1 for n in orfaos if n[9:13] in anos_da_lista)
    nao_respondidos = [n for n in alvo if n not in mantidas]
    # Códigos que a Resolução 65/2008 não traz (unidades criadas depois, como os
    # Núcleos 4.0). A capa não serve de substituta: ela mostra o foro ATUAL, e um
    # mesmo código aparece com foros diferentes.
    foros_fora = Counter(n[16:20] for n in mantidas if n[16:20] not in foros)
    _relatorio(dir_auditoria, "nao_coletados.txt",
               "Na lista e ainda sem registro depois da coleta.", nao_respondidos)
    _relatorio(dir_auditoria, "orfaos.txt", "Pais citados que não estão nesta base. "
               "Quase sempre são de outro ano e estão na base daquele ano.", orfaos)
    _relatorio(dir_auditoria, "duplicados.txt", "processo\tmantida\tdescartada",
               (f"{d.processo}\t{_descricao(mantidas[d.processo])}\t{_descricao(d)}"
                for d in descartadas))
    contagens.update(recoletados_a_pedido=len(forcados),
                     processos_na_lista=len(alvo), processos_na_base=len(mantidas),
                     nao_coletados=len(nao_respondidos), orfaos=len(orfaos),
                     orfaos_dos_anos_da_lista=orfaos_do_ano,
                     filhos_divergentes_no_jsonl=consolidacao.filhos_divergentes(mantidas, filhos))

    posicoes = None
    if (removidas or acrescentadas) and not amostra:
        removidos = dir_auditoria / f"removidos_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        total = sum(Path(f).stat().st_size for f in fontes)
        with tqdm(total=total, unit="B", unit_scale=True, desc="3/5 consolidação") as barra:
            contagens.update(consolidacao.consolidar(fontes, mantidas, filhos, jsonl, removidos,
                                                     ao_ler=barra.update))
        print(f"JSONL consolidado: +{acrescentadas:,} acrescentados | -{removidas:,} removidos "
              f"(guardados em {removidos.name})")
    else:
        print("\n3/5 consolidação: nada a acrescentar nem remover — JSONL intacto.")
        posicoes = {l.posicao for l in mantidas.values()}
    contagens.update(acrescentados=acrescentadas, duplicados_removidos=removidas)

    # Na amostra, o índice só guarda os processos que ela vai escrever: a
    # passada pelos 9 GB é a mesma, mas não grava 1,6 GB à toa.
    cnj = set(mantidas)
    if amostra:
        cnj = {l.processo for l in sorted(mantidas.values(), key=lambda l: l.posicao)[:amostra]}
    with atos_pge.IndicePge(menu.DIR_BANCOS / f"indice_pge_{ano}.db") as indice:
        with _barra(ATOS_PGE, "4/5 índice PGE  ") as barra:
            contagens.update(indice.montar(ATOS_PGE, cnj, ao_ler=barra.update))
        with _barra(jsonl, "5/5 estrutura   ") as barra:
            contagens.update(exportador_gpdr.exportar_estrutura_gpdr(
                jsonl, destino, foros, ipca, filhos, indice, posicoes, amostra,
                ao_ler=barra.update,
            ))

    escritos = contagens["documentos_escritos"]
    menu._escrever_atomico(destino.with_suffix(".meta.json"), [json.dumps({
        "gerado_em": _agora(),
        "script_gerador": "scripts_final/preparar_base_final.py",
        "arquivo_origem": str(jsonl),
        "arquivo_destino": str(destino),
        "arquivos_auxiliares": {"lista_do_ano": str(lista), "atos_pge": str(ATOS_PGE),
                                "ipca": str(IPCA), "foros": str(FOROS)},
        "descricao": DESCRICAO,
        "amostra_parcial": bool(amostra),
        "contagens": dict(sorted(contagens.items())),
        "foros_fora_da_tabela": dict(foros_fora.most_common()),
    }, ensure_ascii=False, indent=2)])

    print(f"\nDocumentos escritos: {escritos:,}"
          + ("" if amostra else f"  (deve ser {len(mantidas):,}, os processos distintos)"))
    print(f"  com movimentos_pge: {contagens['com_bloco_pge']:,} | sem par: "
          f"{contagens['sem_par_pge']:,} | movimentos enxertados: {contagens['movimentos_pge']:,}")
    print("  valor corrigido: " + ", ".join(
        f"{k.removeprefix('valor_')} {v:,}" for k, v in sorted(contagens.items())
        if k.startswith("valor_")))
    print(f"  foro fora da tabela: {contagens['foro_fora_da_tabela']:,} "
          f"({len(foros_fora)} códigos, no .meta.json) | "
          f"nomes unificados (entes): {contagens['nomes_unificados_ente']:,}")
    print(f"  não coletados: {len(nao_respondidos):,} | pais fora da base: {len(orfaos):,} "
          f"(dos anos da lista: {orfaos_do_ano:,})")
    print(f"\nBase:      {destino}\nMetadados: {destino.with_suffix('.meta.json')}"
          f"\nAuditoria: {dir_auditoria}")
    if not amostra and escritos != len(mantidas):
        print("!! A contagem não fecha — confira antes de usar a base.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
