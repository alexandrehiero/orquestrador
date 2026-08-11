"""Classificador de estado da página do e-SAJ + invariante de identidade.

Cada estado é explícito, e DESCONHECIDO existe para o orquestrador mandar o caso
para recoleta em vez de gravar lixo silenciosamente.

Diferenças frente ao pipeline IAMSPE:
  - `verificar_identidade`: confere se a página ABERTA é a do processo PEDIDO.
    Sem isso, abrir a página errada grava os dados de um processo sob o número de
    outro — e nada no pipeline detecta.
  - `escolher_na_selecao` substitui `extrair_link_selecao` e NUNCA chuta em
    silêncio: devolve `verificada=False` quando não pôde conferir o número, e o
    orquestrador exige identidade confirmada antes de gravar.
  - `_e_selecao` só vale quando NÃO há dados de capa (a capa também tem links
    para incidentes, e isso classificaria uma capa legítima como seleção).
"""

import re
import unicodedata
from collections import namedtuple

from bs4 import BeautifulSoup

# Máscara CNJ aceitando '-' ou '.' após o sequencial (números antigos usam ponto).
_MASCARA_CNJ = re.compile(r"\d{7}[-.]?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")


def _norm(texto):
    """Minúsculas, sem acento, espaços colapsados — para comparação robusta."""
    if not texto:
        return ""
    decomp = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomp if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def cnjs_no_texto(texto):
    """Conjunto de CNJs (20 dígitos) presentes no texto. `set()` por decisão de
    projeto — dedup nativo, e a pergunta que fazemos é sempre de pertinência."""
    achados = set()
    for m in _MASCARA_CNJ.finditer(texto or ""):
        dig = re.sub(r"\D", "", m.group(0))
        if len(dig) == 20:
            achados.add(dig)
    return achados


class EstadoPagina:
    DADOS_CAPA = "DADOS_CAPA"
    LISTA_SELECAO = "LISTA_SELECAO"
    SENHA_SEGREDO = "SENHA_SEGREDO"
    NAO_ENCONTRADO = "NAO_ENCONTRADO"
    DESCONHECIDO = "DESCONHECIDO"


class Identidade:
    CONFERE = "CONFERE"              # o número pedido está na página
    DIVERGE = "DIVERGE"              # há número(s), mas não o pedido -> NÃO GRAVAR
    INDETERMINADO = "INDETERMINADO"  # não achou número algum para conferir


# Só o e-SAJ afirmando explicitamente que não existe autoriza gravar 'sem_dados'
# e avançar de grau. Se a frase mudar, o caso vira DESCONHECIDO -> erro
# transitório: falha para o lado SEGURO (nunca vira "não existe" por engano).
_FRASES_NAO_ENCONTRADO = (
    "nao existem informacoes disponiveis",
    "nao foram encontrados resultados",
    "nao foi encontrado processo",
)

# Onde o número do processo pode aparecer. Em incidentes ele vem DENTRO da
# classe, entre parênteses (ex.: 'Cumprimento de Sentença ... (0000010-31...)'),
# e não isolado em #numeroProcesso — por isso a busca é por pertinência.
_SELETORES_IDENTIDADE = (
    "#numeroProcesso",
    ".unj-larger",
    "#classeProcesso",
)

# Detector (_e_selecao) e resolvedor (escolher_na_selecao) usam ESTA lista.
# Antes o detector conhecia só `a.linkProcesso` e o resolvedor tinha um fallback
# a mais: uma página que só tivesse o segundo seletor jamais chegaria ao
# resolvedor — o fallback era inalcançável.
_SELETORES_LINK_SELECAO = ("a.linkProcesso", 'a[href*="processo.codigo="]')
_SELETOR_RADIO_SELECAO = 'input[type="radio"][name="processoSelecionado"]'


class ClassificadorPagina:
    def __init__(self, html):
        self.soup = BeautifulSoup(html or "", "html.parser")
        self._texto = _norm(self.soup.get_text(" "))

    def classificar(self):
        # Ordem importa: 'não encontrado' e 'seleção' primeiro; segredo só vale se
        # NÃO houver dados de capa; capa por último.
        if self._e_nao_encontrado():
            return EstadoPagina.NAO_ENCONTRADO
        if self._e_selecao():
            return EstadoPagina.LISTA_SELECAO
        if self._e_segredo():
            return EstadoPagina.SENHA_SEGREDO
        if self._e_capa():
            return EstadoPagina.DADOS_CAPA
        return EstadoPagina.DESCONHECIDO

    def _tem_dados_capa(self):
        return bool(
            self.soup.select_one(
                "#tableTodasPartes, #tablePartesPrincipais, #tabelaTodasMovimentacoes"
            )
        )

    def _e_segredo(self):
        # Bloqueio real = pede a "senha do processo" E não há dados de capa. NÃO
        # usar input[type=password]: o formulário 'Identificar-se' existe em TODA
        # página e marcaria todo mundo como segredo.
        return "senha do processo" in self._texto and not self._tem_dados_capa()

    def _e_nao_encontrado(self):
        return any(frase in self._texto for frase in _FRASES_NAO_ENCONTRADO)

    def _e_capa(self):
        return bool(self.soup.select_one("#numeroProcesso") or self._tem_dados_capa())

    def _e_selecao(self):
        # Guarda: se há tabela de partes/movimentações OU o número do processo
        # exibido isolado, isto é uma CAPA. A capa tem links para incidentes com
        # `processo.codigo=`, e sem esta guarda — agora que o detector conhece
        # esse seletor — uma capa legítima cairia no caminho do palpite.
        if self._tem_dados_capa() or self.soup.select_one("#numeroProcesso"):
            return False
        if "selecione o processo" in self._texto:
            return True
        if self.soup.select_one(_SELETOR_RADIO_SELECAO):
            return True
        return any(self.soup.select_one(sel) for sel in _SELETORES_LINK_SELECAO)


def verificar_identidade(html, numero_processo):
    """A página aberta é a do processo pedido? Devolve (Identidade, cnjs_achados).

    Chamar SEMPRE depois de abrir uma capa. Sem esta checagem, entrar no processo
    errado grava autores, réus e movimentações de um processo sob o número de
    outro — e o relacionamento é montado em cima disso.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    alvo = numero_processo.digitos

    encontrados = set()
    for seletor in _SELETORES_IDENTIDADE:
        for el in soup.select(seletor):
            encontrados |= cnjs_no_texto(el.get_text(" ", strip=True))

    if not encontrados:
        return Identidade.INDETERMINADO, encontrados
    if alvo in encontrados:
        return Identidade.CONFERE, encontrados
    return Identidade.DIVERGE, encontrados


#: destino: href ou processo.codigo | verificada: o número foi CONFERIDO?
EscolhaSelecao = namedtuple("EscolhaSelecao", "destino verificada motivo")


def escolher_na_selecao(html, numero_processo):
    """Na página/modal de seleção, decide COMO abrir o processo buscado.

    Ordem: (1) link cujo número bate exato; (2) rádio cuja LINHA contém o número
    exato; (3) primeiro rádio, marcado como PALPITE.

    O passo (2) é a correção central: o código antigo pegava `radios[0]`
    assumindo que o principal é a primeira opção. Quando não é, os dados do
    incidente eram gravados sob o número do principal. Aqui o número é conferido
    na linha do rádio; e mesmo no palpite (3) o chamador é obrigado a validar a
    identidade da página aberta antes de gravar qualquer coisa.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    alvo = numero_processo.digitos

    links = []
    for seletor in _SELETORES_LINK_SELECAO:
        links.extend(soup.select(seletor))
    for a in links:
        if alvo in cnjs_no_texto(a.get_text(" ", strip=True)) and a.get("href"):
            return EscolhaSelecao(a.get("href"), True, "link com número exato")

    radios = soup.select(_SELETOR_RADIO_SELECAO)
    for r in radios:
        if not r.get("value"):
            continue
        linha = r.find_parent("tr") or r.parent
        contexto = linha.get_text(" ", strip=True) if linha else ""
        if alvo in cnjs_no_texto(contexto):
            return EscolhaSelecao(r.get("value"), True, "rádio com número exato")

    if radios and radios[0].get("value"):
        return EscolhaSelecao(
            radios[0].get("value"), False,
            "PALPITE: primeiro rádio; número não conferido na modal",
        )

    return EscolhaSelecao(None, False, "nenhuma opção resolvível na seleção")
