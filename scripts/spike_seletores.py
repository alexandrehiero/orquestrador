"""Spike de seletores — diagnóstico ANTES da coleta em massa.

Não grava nada no banco. Para cada número, consulta os dois graus, salva o HTML
e reporta o que cada seletor pendente devolve.

Uso:
    python scripts/spike_seletores.py                       # lê data/entrada/processos.txt
    python scripts/spike_seletores.py 0000001-58.2013.8.26.0477 ...
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bs4 import BeautifulSoup

from src.scrapers.coletor import PARSER_POR_GRAU
from src.scrapers.esaj_client import EsajClient
from src.scrapers.exceptions import EsajError
from src.scrapers.numero_processo import NumeroProcesso
from src.scrapers.page_state import (
    ClassificadorPagina, EstadoPagina, escolher_na_selecao, verificar_identidade,
)
from src.scrapers.parser_base import ROTULOS_DISTRIBUICAO, SELETORES_SITUACAO

DIR_ENTRADA = RAIZ / "data" / "entrada"
SAIDA_HTML = RAIZ / "data" / "spike"

# O roteamento grau -> parser vem do coletor. Um dicionário próprio aqui podia
# divergir do usado na coleta real, e o spike deixaria de diagnosticar
# exatamente o caminho que a coleta percorre — que é a razão de ele existir.


def _txt(soup, seletor):
    el = soup.select_one(seletor)
    return el.get_text(" ", strip=True) if el else None


def _relatar_situacao(soup):
    print("  [situacao] — selo tipo 'Extinto'")
    achou = False
    for sel in SELETORES_SITUACAO:
        valor = _txt(soup, sel)
        if valor:
            print(f"    {sel} -> {valor!r}")
            achou = True
    if not achou:
        print("    NENHUM seletor candidato retornou valor.")
        for el in soup.find_all(string=re.compile(r"Extinto|Em andamento|Arquivado", re.I))[:3]:
            pai = el.parent
            print(f"    (texto) <{pai.name} class={pai.get('class')} id={pai.get('id')}> {el.strip()[:60]}")


def _relatar_distribuicao(soup):
    print("  [data_distribuicao]")
    for sel in ("#dataHoraDistribuicaoProcesso", "#dataDistribuicaoProcesso"):
        valor = _txt(soup, sel)
        if valor:
            print(f"    {sel} -> {valor!r}")
    for el in soup.find_all(string=re.compile(r"Distribui|Recebido em", re.I))[:4]:
        pai = el.parent
        contexto = re.sub(r"\s+", " ", pai.get_text(" ", strip=True))[:110]
        print(f"    (texto) <{pai.name} id={pai.get('id')}> {contexto}")
    print(f"    rótulos testados pelo parser: {ROTULOS_DISTRIBUICAO}")


def _relatar_selecao(soup, np, html):
    radios = soup.select('input[type="radio"][name="processoSelecionado"]')
    links = soup.select("a.linkProcesso")
    print(f"  [seleção] rádios={len(radios)} | links={len(links)}")
    for r in radios[:6]:
        linha = r.find_parent("tr")
        rotulo = re.sub(r"\s+", " ", linha.get_text(" ", strip=True))[:90] if linha else ""
        print(f"    value={r.get('value')!r} | {rotulo}")
    escolha = escolher_na_selecao(html, np)
    print(f"    ESCOLHA -> destino={escolha.destino!r} verificada={escolha.verificada}")
    print(f"               motivo={escolha.motivo}")


def _relatar_capa(html, np, grau):
    soup = BeautifulSoup(html, "html.parser")
    identidade, achados = verificar_identidade(html, np)
    print(f"  [identidade] {identidade} | CNJs no cabeçalho: {sorted(achados)}")
    _relatar_situacao(soup)
    _relatar_distribuicao(soup)
    dados = PARSER_POR_GRAU[grau](html).parse()
    print("  [parse]")
    for campo in ("classe", "assunto", "foro", "vara", "juiz", "valor",
                  "situacao", "data_distribuicao", "processo_principal"):
        print(f"    {campo:20}: {dados.get(campo)!r}")
    print(f"    completude          : {dados.get('completude')}")
    print(f"    partes ({len(dados['partes'])}):")
    for p in dados["partes"]:
        print(f"      {p['tipo_parte']!r:22} -> {p['polo']:8} | {p['nome'][:45]!r}")
        if p["representantes"]:
            print(f"        representantes: {p['representantes']}")
    movs = dados["movimentacoes"]
    print(f"    movimentações: {len(movs)}")
    for m in movs[:3]:
        print(f"      {m['data']!r} | {m['descricao'][:70]!r}")
    if grau == 2:
        print(f"    1ª instância: {dados.get('processo_1a_instancia')!r} "
              f"(bruto: {dados.get('processo_1a_instancia_bruto')!r})")


def diagnosticar(numero, client):
    print(f"\n{'=' * 72}\nPROCESSO {numero}")
    np = NumeroProcesso.tentar(numero)
    if np is None:
        print("  número inválido (não tem 20 dígitos)")
        return
    print(f"  dígitos={np.digitos} | origem={np.origem} | DV válido={np.dv_valido} "
          f"| graus a tentar={np.graus_a_tentar}")

    for grau in (1, 2):  # o spike consulta SEMPRE os dois, para comparar
        print(f"\n-- grau {grau} --")
        try:
            html = client.buscar(np, grau)
        except EsajError as erro:
            print(f"  FALHA: {erro!r}")
            continue

        destino = SAIDA_HTML / f"{np.digitos}_g{grau}.html"
        destino.write_text(html, encoding="utf-8")
        print(f"  html salvo: {destino.name} ({len(html)} bytes)")

        estado = ClassificadorPagina(html).classificar()
        print(f"  estado: {estado}")

        if estado == EstadoPagina.LISTA_SELECAO:
            _relatar_selecao(BeautifulSoup(html, "html.parser"), np, html)
        elif estado == EstadoPagina.DADOS_CAPA:
            _relatar_capa(html, np, grau)


def main():
    """Uso:
        python scripts/spike_seletores.py <projeto>      # lê data/entrada/<projeto>.txt
        python scripts/spike_seletores.py 0000001-58.2013.8.26.0477 ...
    """
    argumentos = sys.argv[1:]
    numeros = [a for a in argumentos if len(re.sub(r"\D", "", a)) == 20]
    projetos = [a for a in argumentos if a not in numeros]

    if not numeros:
        # Nome do projeto, coerente com o menu (um projeto = uma lista).
        nome = projetos[0] if projetos else "processos"
        entrada = DIR_ENTRADA / f"{nome}.txt"
        if not entrada.exists():
            print(f"Arquivo não encontrado: {entrada}")
            print("Passe o nome do projeto ou os números na linha de comando.")
            return
        print(f"Lendo {entrada.name}")
        numeros = [l.strip() for l in entrada.read_text(encoding="utf-8-sig").splitlines()
                   if l.strip() and not l.startswith("#")]
    SAIDA_HTML.mkdir(parents=True, exist_ok=True)
    client = EsajClient()
    for numero in numeros:
        try:
            diagnosticar(numero, client)
        except Exception as erro:
            print(f"  ERRO inesperado em {numero}: {erro!r}")
    print(f"\nHTMLs salvos em: {SAIDA_HTML}")
    print(f"Estatísticas do cliente: {client.estatisticas()}")


if __name__ == "__main__":
    main()
    