"""Value object para o Número Único CNJ (Resolução CNJ 65/2008).

Estrutura: NNNNNNN-DD.AAAA.J.TR.OOOO  (20 dígitos)

Diferenças frente ao pipeline IAMSPE:
  - valida o dígito verificador (ISO 7064 MOD 97-10) — mas NÃO levanta exceção
    por DV inválido: o chamador decide (entrada -> numeros_invalidos.txt;
    relacionamento -> observação). Só o tamanho != 20 é erro duro.
  - fala em GRAU (1/2), não em instância. 'cpopg'/'cposg' é detalhe do cliente.
"""

import re

from .exceptions import NumeroProcessoInvalido

GRAU_PRIMEIRO = 1
GRAU_SEGUNDO = 2

_INSTANCIA_POR_GRAU = {GRAU_PRIMEIRO: "cpopg", GRAU_SEGUNDO: "cposg"}


def instancia_do_grau(grau):
    """1 -> 'cpopg', 2 -> 'cposg'. Ponto único de tradução domínio -> e-SAJ."""
    try:
        return _INSTANCIA_POR_GRAU[grau]
    except KeyError:
        raise ValueError(f"Grau desconhecido: {grau!r}") from None


def so_digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


class NumeroProcesso:
    __slots__ = ("_d",)

    def __init__(self, valor):
        digitos = so_digitos(valor)
        if len(digitos) != 20:
            raise NumeroProcessoInvalido(
                f"Número CNJ deve ter 20 dígitos após limpeza; "
                f"recebido {len(digitos)} a partir de {valor!r}."
            )
        self._d = digitos

    @classmethod
    def tentar(cls, valor):
        """Devolve NumeroProcesso ou None — para laços que não podem quebrar."""
        try:
            return cls(valor)
        except NumeroProcessoInvalido:
            return None

    # --- componentes ---------------------------------------------------------
    @property
    def digitos(self):
        return self._d

    @property
    def sequencial(self):
        return self._d[0:7]

    @property
    def dv(self):
        return self._d[7:9]

    @property
    def ano(self):
        return self._d[9:13]

    @property
    def segmento(self):
        return self._d[13:14]

    @property
    def tribunal(self):
        return self._d[14:16]

    @property
    def origem(self):
        return self._d[16:20]

    # --- validação -----------------------------------------------------------
    @property
    def dv_esperado(self):
        """DV recalculado (ISO 7064 MOD 97-10): 98 - (base sem DV + '00') % 97."""
        base = int(
            self.sequencial + self.ano + self.segmento
            + self.tribunal + self.origem + "00"
        )
        return f"{98 - (base % 97):02d}"

    @property
    def dv_valido(self):
        return self.dv == self.dv_esperado

    @property
    def do_tjsp(self):
        """Justiça Estadual (8) de São Paulo (26). Fora disso, o e-SAJ do TJSP
        não responde — vale avisar na entrada em vez de gastar requisição."""
        return self.segmento == "8" and self.tribunal == "26"

    # --- formatações ---------------------------------------------------------
    @property
    def numero_digito_ano(self):
        return f"{self.sequencial}-{self.dv}.{self.ano}"

    @property
    def mascara(self):
        return (
            f"{self.sequencial}-{self.dv}.{self.ano}."
            f"{self.segmento}.{self.tribunal}.{self.origem}"
        )

    # --- roteamento de grau --------------------------------------------------
    @property
    def originario_segundo_grau(self):
        """Origem '0000' = autuado originariamente no 2º grau (Res. 65/2008,
        art. 1º §1º-A). Ex.: Agravo de Instrumento, Ação Rescisória."""
        return self.origem == "0000"

    @property
    def graus_a_tentar(self):
        """Ordem de tentativa. Originário do 2º grau vai direto ao 2º — os demais
        começam no 1º. O orquestrador só avança para o grau seguinte se o e-SAJ
        disser NAO_ENCONTRADO explicitamente; erro de rede NUNCA faz avançar."""
        if self.originario_segundo_grau:
            return (GRAU_SEGUNDO,)
        return (GRAU_PRIMEIRO, GRAU_SEGUNDO)

    # --- params de busca -----------------------------------------------------
    def params_busca(self, grau):
        """Query string do search.do. ÚNICO ponto a ajustar se o e-SAJ mudar."""
        instancia = instancia_do_grau(grau)
        if instancia == "cpopg":
            return {
                "conversationId": "",
                "cbPesquisa": "NUMPROC",
                "dadosConsulta.localPesquisa.cdLocal": "-1",
                "dadosConsulta.tipoNuProcesso": "UNIFICADO",
                "numeroDigitoAnoUnificado": self.numero_digito_ano,
                "foroNumeroUnificado": self.origem,
                "dadosConsulta.valorConsultaNuUnificado": self.mascara,
                "dadosConsulta.valorConsulta": "",
            }
        return {
            "conversationId": "",
            "cbPesquisa": "NUMPROC",
            "tipoNuProcesso": "UNIFICADO",
            "numeroDigitoAnoUnificado": self.numero_digito_ano,
            "foroNumeroUnificado": self.origem,
            "dePesquisaNuUnificado": self.mascara,
            "dePesquisa": "",
        }

    # --- dunder --------------------------------------------------------------
    def __eq__(self, outro):
        return isinstance(outro, NumeroProcesso) and outro._d == self._d

    def __hash__(self):
        return hash(self._d)

    def __repr__(self):
        return f"NumeroProcesso({self.mascara})"

    def __str__(self):
        return self._d
    