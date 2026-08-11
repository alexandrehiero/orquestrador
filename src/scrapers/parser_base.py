"""Parser base da capa do e-SAJ. Retorna um DICT BRUTO — NÃO normaliza.

Por que bruto: este dict vai inteiro para o SQLite, e a base final é uma
PROJEÇÃO dele. Limpar aqui (tirar parênteses da classe, converter data, virar
float) destruiria o original e obrigaria a RECOLETAR quando uma regra de limpeza
mudasse. Com o bruto guardado, corrigir uma regra é reprojetar — sem rede.

Correções frente ao pipeline IAMSPE:
  - 'credor/credora' movidos para o polo ATIVO (em execução, o credor executa —
    estavam classificados como réu);
  - 'interessado/interessada' removidos do polo PASSIVO (rótulo neutro, sem polo);
  - flexões que faltavam e caíam em OUTRO em silêncio (apelada, recorrida,
    impetrada, suscitante/suscitado, devedor/devedora);
  - partes viram lista de dicts com o rótulo REAL preservado (Exeqte, Reqdo...),
    em vez de 5 listas paralelas que jogavam o rótulo fora;
  - campos novos: `situacao` (selo 'Extinto') e `data_distribuicao`;
  - `completude`: diz QUAIS blocos vieram. A validação antiga usava um AND de 4
    condições, então uma quebra só no seletor de partes passava despercebida e
    gravava o processo sem autores nem réus.
"""

import re
import unicodedata

from bs4 import BeautifulSoup


def _norm(texto):
    """Minúsculas, sem acento, espaços colapsados — para comparação robusta."""
    if not texto:
        return ""
    decomp = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomp if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


# Match EXATO sobre a célula de tipo (que é curta). Nunca sobre a linha inteira,
# senão padrões curtos como 'Ré' casam em qualquer lugar.
_ROTULOS_ATIVO = {
    "requerente", "reqte", "autor", "autora", "exequente", "exeqte",
    "reclamante", "reclte", "embargante", "embargte", "agravante", "agravte",
    "impetrante", "imptte", "apelante", "recorrente",
    "herdeiro", "herdeira", "suscitante",
    "credor", "credora",  # ATIVO: quem executa. Estava em PASSIVO por engano.
    "promovente", "demandante", "querelante", "outorgante", "inventariante",
}

_ROTULOS_PASSIVO = {
    "requerido", "requerida", "reqdo", "reqda",
    "reu", "re", "executado", "executada", "exectdo", "exectda",
    "reclamado", "reclamada", "recldo", "reclda",
    "embargado", "embargada", "embargdo", "embargda",
    "agravado", "agravada", "agravdo",
    "impetrado", "impetrada", "imptdo", "imptda",
    "apelado", "apelada", "recorrido", "recorrida",
    "devedor", "devedora", "suscitado", "suscitada",
    "promovido", "promovida", "demandado", "demandada", "querelado", "querelada",
}
# 'interessado/interessada' NÃO entram em nenhum dos dois: é rótulo neutro
# (jurisdição voluntária, terceiros). Vão para polo OUTRO.

_BLOCK_JUIZ = (
    "vara", "juizado", "foro", "camara", "turma", "colegio", "orgao",
    "distribuidor", "comarca", "secao", "gabinete", "area", "classe",
)

_ROTULO_REPRESENTANTE = re.compile(
    r"^(advogad[oa]s?|defensor|def\.?\s*publ|procurador|curador)"
)

# Confirmados no spike de 2026-08-10 contra HTML real: `.unj-tag` devolveu
# 'Extinto' e 'Suspenso' no 1º grau; `#situacaoProcesso` e `.unj-tag` devolveram
# 'Arquivado administrativamente' no 2º grau. `.unj-badge` e `.tag` seguem como
# rede de segurança não observada.
SELETORES_SITUACAO = ("#situacaoProcesso", ".unj-tag", ".unj-badge", ".tag")

# Ordem importa: incidentes/cumprimentos não têm 'Distribuição', têm 'Recebido em'.
ROTULOS_DISTRIBUICAO = ("Distribuição", "Recebido em", "Distribuido em")


class ParserCapaBase:
    GRAU = None  # 1 ou 2 — definido pela subclasse

    def __init__(self, html):
        self.soup = BeautifulSoup(html or "", "html.parser")

    # --- API pública ---------------------------------------------------------
    def parse(self):
        partes = self._extrair_partes()
        return {
            "classe": self._extrair_classe(),
            "assunto": self._extrair_assunto(),
            "foro": self._extrair_foro(),
            "vara": self._extrair_vara(),
            "juiz": self._extrair_juiz(),
            "valor": self._extrair_valor(),
            "situacao": self._extrair_situacao(),
            "data_distribuicao": self._extrair_distribuicao(),
            "partes": partes,
            "movimentacoes": self._extrair_movimentacoes(),
            "processo_principal": self._extrair_processo_principal(),
            "completude": self._completude(partes),
        }

    def _completude(self, partes):
        """Quais blocos vieram. A validação decide revisão a partir DISTO, não de
        um booleano único — capa com movimentações e ZERO partes é seletor
        quebrado, não processo sem partes."""
        return {
            "tem_classe": bool(self._extrair_classe()),
            "tem_partes": bool(partes),
            "tem_movimentacoes": bool(self.soup.select_one("#tabelaTodasMovimentacoes")),
        }

    # --- campos simples ------------------------------------------------------
    def _por_id(self, *seletores):
        for sel in seletores:
            el = self.soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if txt:
                    return txt
        return None

    def _extrair_classe(self):
        # Vem com o número entre parênteses em incidentes. Limpeza no transformer.
        return self._por_id("#classeProcesso", ".unj-larger") or self._rotulo_estrito("Classe")

    def _extrair_assunto(self):
        return self._por_id("#assuntoProcesso") or self._rotulo_estrito("Assunto")

    def _extrair_foro(self):
        return self._por_id("#foroProcesso") or self._rotulo_estrito("Foro")

    def _extrair_vara(self):
        return self._por_id("#varaProcesso") or self._rotulo_estrito("Vara")

    def _extrair_valor(self):
        return self._por_id("#valorAcaoProcesso") or self._rotulo_estrito("Valor da ação")

    def _extrair_situacao(self):
        el = self.soup.select_one(",".join(SELETORES_SITUACAO))
        if el:
            txt = el.get_text(" ", strip=True)
            if txt:
                return txt
        return self._rotulo_estrito("Situação")

    def _extrair_distribuicao(self):
        """Texto bruto: '09/01/2013 às 11:39 - Livre' ou '06/01/2024 às 13:58'.
        Devolve None quando a capa não exibe — nunca infere de movimentação."""
        for rotulo in ROTULOS_DISTRIBUICAO:
            valor = self._rotulo_estrito(rotulo)
            if valor:
                return valor
        return self._por_id("#dataHoraDistribuicaoProcesso", "#dataDistribuicaoProcesso")

    def _extrair_juiz(self):
        raise NotImplementedError("Subclasse define a extração do juiz/relator.")

    # --- juiz estrito --------------------------------------------------------
    def _juiz_valido(self, valor):
        """Compara por PALAVRA INTEIRA, não por substring.

        Substring gerava falso negativo em sobrenomes reais: 'Alvarado' contém
        'vara', 'Areal' contém 'area'. O juiz virava None sem aviso.

        Caso irredutível: um juiz de sobrenome 'Câmara' continua rejeitado — a
        palavra é literalmente igual à do órgão. É a escolha 'na dúvida,
        ausente' do projeto, e o dado bruto fica preservado no banco.
        """
        n = _norm(valor)
        if not n:
            return False
        palavras = set(re.findall(r"[a-z0-9]+", n))
        return not (palavras & set(_BLOCK_JUIZ))

    def _rotulo_estrito(self, rotulo):
        """Elemento cujo texto DIRETO é EXATAMENTE o rótulo (evita 'Juizado'
        casar com 'Juiz'); devolve o valor associado (irmão seguinte)."""
        alvo = _norm(rotulo)
        for el in self.soup.find_all(["span", "td", "dt", "th", "label", "div"]):
            direto = _norm(el.find(string=True, recursive=False) or "")
            if direto in (alvo, alvo + ":"):
                valor = self._valor_apos(el)
                if valor:
                    return valor
        return None

    def _valor_apos(self, el):
        irmao = el.find_next_sibling()
        if irmao:
            txt = irmao.get_text(" ", strip=True)
            if txt:
                return txt
        nxt = el.next_sibling
        while isinstance(nxt, str) and not nxt.strip():
            nxt = nxt.next_sibling
        if isinstance(nxt, str) and nxt.strip():
            return nxt.strip()
        return None

    # --- partes --------------------------------------------------------------
    def _extrair_partes(self):
        """Lista de {tipo_parte, polo, nome, representantes}. Percorre TODAS as
        linhas (fundoClaro E fundoEscuro) e classifica pela CÉLULA DE TIPO."""
        tabela = self.soup.select_one("#tableTodasPartes") or self.soup.select_one(
            "#tablePartesPrincipais"
        )
        partes = []
        if not tabela:
            return partes

        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            rotulo_bruto = tds[0].get_text(" ", strip=True)
            tipo = _norm(rotulo_bruto).rstrip(":")
            celula = tr.select_one("td.nomeParteEAdvogado") or tds[-1]
            nome, reps = self._parte_nome_e_reps(celula)
            if not nome:
                continue
            partes.append({
                "tipo_parte": rotulo_bruto.rstrip(":").strip(),  # 'Exeqte', 'Reqdo'
                "polo": self._classificar_polo(tipo),            # ATIVO/PASSIVO/OUTRO
                "nome": nome,
                "representantes": reps,
            })
        return partes

    def _classificar_polo(self, tipo_norm):
        if tipo_norm in _ROTULOS_ATIVO:
            return "ATIVO"
        if tipo_norm in _ROTULOS_PASSIVO:
            return "PASSIVO"
        return "OUTRO"

    def _parte_nome_e_reps(self, cell):
        # Nome = primeiro texto direto não vazio da célula.
        nome = ""
        for filho in cell.contents:
            if isinstance(filho, str) and filho.strip():
                nome = filho.strip()
                break
        if not nome:
            linhas = [l.strip() for l in cell.get_text("\n").split("\n") if l.strip()]
            nome = linhas[0] if linhas else ""

        reps = []
        for span in cell.find_all("span"):
            if _ROTULO_REPRESENTANTE.match(_norm(span.get_text())):
                seguinte = span.next_sibling
                if isinstance(seguinte, str):
                    txt = seguinte.strip()
                elif seguinte is not None:
                    txt = seguinte.get_text(" ", strip=True)
                else:
                    txt = ""
                if txt:
                    reps.append(txt)
        return nome, reps

    # --- movimentações -------------------------------------------------------
    def _extrair_movimentacoes(self):
        """Data + descrição. Título e complemento ficam JUNTOS numa string, por
        decisão do projeto."""
        tabela = self.soup.select_one("#tabelaTodasMovimentacoes")
        movs = []
        if not tabela:
            return movs
        for tr in tabela.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            data = tds[0].get_text(" ", strip=True)
            desc = re.sub(r"\s+", " ", tds[-1].get_text(" ", strip=True)).strip()
            if desc:
                movs.append({"data": data, "descricao": desc})
        return movs

    # --- relacionamento (só o topo!) ----------------------------------------
    def _extrair_processo_principal(self):
        """Pai = link 'Processo principal' do TOPO. NUNCA a aba Apensos."""
        el = self.soup.select_one("#linkProcessoPrincipalVinc") or self.soup.select_one(
            "#linkProcessoPrincipal"
        )
        if el:
            dig = re.sub(r"\D", "", el.get_text())
            if len(dig) == 20:
                return dig
        return None
    