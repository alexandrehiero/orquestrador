"""Exceções de domínio do pipeline de coleta TJSP/e-SAJ.

Centralizar as exceções aqui evita imports circulares entre o value object
`NumeroProcesso`, o cliente HTTP e os parsers.
"""


class EsajError(Exception):
    """Erro base de qualquer operação contra o e-SAJ."""


class EsajRequisicaoError(EsajError):
    """Falha de rede/HTTP que persistiu após todas as retentativas."""


class EsajIndisponivelError(RuntimeError):
    """Falhas consecutivas demais: o e-SAJ caiu ou bloqueou o acesso.

    NÃO herda de EsajError de propósito. O laço de coleta trata EsajError como
    'falha deste processo' e segue adiante; se esta exceção fosse EsajError,
    o script continuaria queimando ~12s por número numa fila de 500 mil,
    marcando tudo como falha. Ela precisa ABORTAR a execução.
    """


class NumeroProcessoInvalido(ValueError):
    """Número CNJ com formato inválido (após limpeza != 20 dígitos)."""
    