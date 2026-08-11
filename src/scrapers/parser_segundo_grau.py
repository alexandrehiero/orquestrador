"""Parser da capa de 2º grau (cposg).

Diferenças frente ao 1º grau:
  - Não existe 'Juiz'; por decisão do projeto, o RELATOR ocupa o campo juiz.
  - O número de 1ª instância é capturado em `processo_1a_instancia` de forma
    SEPARADA. Ele é o vínculo do RECURSO (relação lateral) e não pode ser
    confundido com 'Processo principal' (incidente, relação hierárquica) — os
    dois podem coexistir na mesma capa e cada um vai para seu campo.

ATENÇÃO: os seletores de cposg variam mais que os de cpopg. Confirmar num agravo
real antes da coleta em massa.
"""

import re

from .parser_base import ParserCapaBase

# Máscara CNJ aceitando '-' OU '.' após o sequencial (números antigos usam ponto)
# e ignorando sufixos como '/03'.
_MASCARA_CNJ = re.compile(r"\d{7}[-.]?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")

# Título da seção de origem. No HTML real ele é <h2 class="subtitle">, e o
# cabeçalho da tabela fica numa tabela SEPARADA da tabela de dados.
_PADRAO_SECAO_1A = re.compile(r"n[uú]meros?\s+de\s+1[ªaº]?\s*inst", re.I)


def _cnj_de_texto(texto):
    """Extrai 20 dígitos do texto, ou None. Número antigo ('26747/2005') não
    casa a máscara e vira None — vai para observação, não para vínculo."""
    m = _MASCARA_CNJ.search(texto or "")
    if not m:
        return None
    dig = re.sub(r"\D", "", m.group(0))
    return dig if len(dig) == 20 else None


class ParserSegundoGrau(ParserCapaBase):
    GRAU = 2

    def parse(self):
        dados = super().parse()
        celula = self._celula_1a_instancia()
        cnj = _cnj_de_texto(celula) if celula else None
        dados["processo_1a_instancia"] = cnj
        dados["processo_1a_instancia_bruto"] = celula if (celula and not cnj) else None
        return dados

    def _extrair_juiz(self):
        val = self._por_id("#relatorProcesso")
        if val and self._juiz_valido(val):
            return val
        val = self._rotulo_estrito("Relator") or self._rotulo_estrito("Relator(a)")
        if val and self._juiz_valido(val):
            return val
        return None

    def _extrair_foro(self):
        # No 2º grau não há foro/vara próprios. Só o id — SEM fallback por
        # rótulo, que pegaria os cabeçalhos da tabela 'Números de 1ª instância'.
        return self._por_id("#foroProcesso")

    def _extrair_vara(self):
        return self._por_id("#varaProcesso")

    def _celula_1a_instancia(self):
        """Texto da célula com o número de 1ª instância, ou None.

        O e-SAJ quebra a seção em DUAS tabelas: uma só com o cabeçalho
        ('Nº de 1ª instância | Foro | Vara | Juiz | Obs.') mais uma linha vazia
        de espaçamento, e OUTRA com os dados. Procurar 'a tabela cujo cabeçalho
        tem Foro e Vara' encontrava a primeira — que não tem dado nenhum.
        Por isso varremos as tabelas da SEÇÃO, não uma tabela só.
        """
        el = self.soup.select_one("#numeroProcessoPrimeiraInstancia")
        if el:
            txt = el.get_text(" ", strip=True)
            # Qualquer número serve, igual à varredura. Exigir CNJ aqui fazia o
            # atalho descartar em silêncio um formato antigo que ele mesmo havia
            # encontrado — e a varredura não o recuperava: numa página que só
            # tem o id, não existe tabela de seção para varrer.
            if re.search(r"\d{4,}", txt):
                return txt
        return self._varrer_secao_1a_instancia()

    def _cabecalho_secao_1a(self):
        """O título 'Números de 1ª Instância'. Prioriza h2/h3/h4; só depois cai
        para outros elementos, e aí exigindo texto DIRETO — senão um <div>
        contêiner casaria e a varredura começaria no lugar errado."""
        for tag in ("h2", "h3", "h4"):
            for el in self.soup.find_all(tag):
                if _PADRAO_SECAO_1A.search(el.get_text(" ", strip=True)):
                    return el
        for el in self.soup.find_all(["span", "div", "td", "p", "b", "strong"]):
            direto = el.find(string=True, recursive=False) or ""
            if _PADRAO_SECAO_1A.search(direto):
                return el
        return None

    def _varrer_secao_1a_instancia(self):
        """Primeira célula com QUALQUER número nas tabelas da seção de 1ª
        instância. Quem separa CNJ válido de formato antigo é o parse().

        Para no PRÓXIMO título: sem essa guarda a varredura invadiria as
        movimentações, onde despachos citam o número de origem no meio do texto
        ('Anote-se que os autos de origem possuem o nº ...') — e aí um número
        mencionado de passagem viraria vínculo de recurso.
        """
        cabecalho = self._cabecalho_secao_1a()
        if cabecalho is None:
            return None
        for elemento in cabecalho.find_all_next(["h2", "h3", "h4", "table"]):
            if elemento.name != "table":
                break  # começou outra seção
            for tr in elemento.find_all("tr"):
                if "label" in (tr.get("class") or []):
                    continue  # cabeçalho usa <td class="label">, não <th>
                celulas = tr.find_all("td")
                if not celulas:
                    continue
                texto = celulas[0].get_text(" ", strip=True)
                # Aceita QUALQUER número, não só CNJ válido: números anteriores
                # ao padrão CNJ ('26747/2005') precisam chegar ao parse() para
                # virar `processo_1a_instancia_bruto` e observação de vínculo.
                # Exigir CNJ aqui tornava esse caminho inalcançável. Quem impede
                # invadir as movimentações é a parada no próximo título, não
                # este filtro.
                if re.search(r"\d{4,}", texto):
                    return texto
        return None
    