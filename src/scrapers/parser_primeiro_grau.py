"""Parser da capa de 1º grau (cpopg)."""

from .parser_base import ParserCapaBase


class ParserPrimeiroGrau(ParserCapaBase):
    GRAU = 1

    def _extrair_juiz(self):
        # 1) Caminho canônico: id estável.
        val = self._por_id("#juizProcesso")
        if val and self._juiz_valido(val):
            return val
        # 2) Layout unj sem id: rótulo EXATO 'Juiz' + blocklist.
        val = self._rotulo_estrito("Juiz")
        if val and self._juiz_valido(val):
            return val
        # 3) Na dúvida, ausente — jamais devolve a Vara.
        return None
    