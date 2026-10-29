"""Formatação e unificação de nomes das partes — as MESMAS regras do GPDR.

Portado de `Codigos_dados_GPDR/src/normalize.py` (v1) e `src/unificacao.py` (v7),
para que um nome designe a mesma pessoa nas duas bases: uma consulta por
'Fazenda Pública do Estado de São Paulo (FESP)' precisa achar os processos das
duas. Na lista de 2025, 276 mil nomes do polo passivo caem numa das grafias que
a v7 unificou.

Duas etapas, na ordem do GPDR:

1. **Forma** — primeira letra de cada palavra em maiúscula, partículas em
   minúscula, siglas preservadas, espaços colapsados. Acentuação diferencia.
2. **Unificação** — só as duas regras da v7 que são TABELAS FECHADAS: grafias de
   advogado conferidas na OAB e os entes do polo passivo. A terceira (sociedade
   individual de advocacia -> nome do titular) fica de fora: ela depende de o
   nome sem sufixo existir na própria base, e foi medida e decidida para a base
   do GPDR, não para qualquer base.
"""

import re
import unicodedata

# Em minúsculo quando não abrem o nome: "Maria da Silva", não "Maria Da Silva".
PARTICULAS = frozenset(
    {"de", "da", "do", "das", "dos", "e", "a", "ao", "aos", "à", "às",
     "em", "na", "no", "nas", "nos"}
)
SIGLAS = frozenset({"IAMSPE", "S/A", "LTDA"})
# Texto que o e-SAJ devolve para dizer "não existe". Title case fabricaria a
# pessoa "Não Há Registro".
SENTINELAS = frozenset({"NÃO HÁ REGISTRO"})

REGRA_GRAFIA = "grafia"
REGRA_ENTE = "ente"

# Chave e valor na forma em que a formatação deixa os nomes.
GRAFIAS_UNIFICADAS = {
    "Manuel Donizeti Ribeiro": "Manuel Donizete Ribeiro",
    "Nilceia Aparecida Luiz Matheus": "Nilceia Aparecida Luis Matheus",
}

# As grafias de origem estão como o GPDR as listou; a comparação passa as duas
# pontas por `chave_comparacao`, e é assim que 9 grafias alcançam as dezenas de
# variantes reais ('SÃO PAULO PREVIDÊNCIA - SPPREV', 'Spprev - São Paulo...').
# Exceção deliberada ao "acentuação diferencia", só para esta lista fechada de
# instituições, nunca para nome de pessoa.
ENTES_POLO_PASSIVO = {
    "Fazenda Pública do Estado de São Paulo (FESP)": (
        "FAZENDA PUBLICA DO ESTADO DE SAO PAULO",
        "FAZENDA DO ESTADO DE SAO PAULO",
        "FAZENDA DO ESTADO DE SAO PAULO FESP",
        "ESTADO DE SAO PAULO",
    ),
    "São Paulo Previdência (SPPREV)": (
        "SPPREV SAO PAULO PREVIDENCIA",
        "SAO PAULO PREVIDENCIA SPPREV",
    ),
    "Caixa Beneficente da Polícia Militar (CBPM)": (
        "CAIXA BENEFICENTE DA POLICIA MILITAR DO ESTADO DE SAO PAULO CBPM",
        "CAIXA BENEFICENTE DA POLICIA MILITAR",
        "CAIXA BENEFICENTE DA POLICIA MILITAR DO ESTADO DE SAO PAULO",
    ),
}

_ESPACOS = re.compile(r"\s+")
_NAO_ALFANUMERICO = re.compile(r"[^0-9a-z]+")


def _formatar_palavra(palavra, primeira):
    if palavra.upper().strip(".") in SIGLAS:
        return palavra.upper()
    if not primeira and palavra.lower() in PARTICULAS:
        return palavra.lower()
    return palavra.capitalize()


def formatar_nome(valor):
    """'MARIA  DA SILVA' -> 'Maria da Silva'. Vazio ou não-texto -> None."""
    if not isinstance(valor, str):
        return None
    palavras = valor.split()
    if not palavras:
        return None
    if " ".join(palavras).upper() in SENTINELAS:
        return " ".join(palavras)
    return " ".join(
        _formatar_palavra(palavra, indice == 0) for indice, palavra in enumerate(palavras)
    )


def chave_comparacao(texto):
    """Sem acento, minúsculo, e toda pontuação reduzida a um espaço."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    minusculo = _ESPACOS.sub(" ", sem_acento).strip().lower()
    return " ".join(_NAO_ALFANUMERICO.sub(" ", minusculo).split())


_ENTE_POR_CHAVE = {
    chave_comparacao(grafia): alvo
    for alvo, grafias in ENTES_POLO_PASSIVO.items()
    for grafia in grafias
}


def unificar(nome, pessoa_do_polo_passivo):
    """Devolve (nome final, regra que o trocou) — regra None se nada mudou.

    A regra do ente vale só para PESSOAS do polo PASSIVO: 'Estado de São Paulo'
    no polo ativo é outro papel processual, e o GPDR o deixou intacto.
    """
    if nome in GRAFIAS_UNIFICADAS:
        return GRAFIAS_UNIFICADAS[nome], REGRA_GRAFIA
    if pessoa_do_polo_passivo:
        alvo = _ENTE_POR_CHAVE.get(chave_comparacao(nome))
        if alvo is not None:
            return alvo, REGRA_ENTE
    return nome, None


def normalizar_nomes(nomes, pessoa_do_polo_passivo, contadores):
    """Formata, unifica e desduplica uma lista de nomes.

    Desduplica de novo DEPOIS das trocas, com dict.fromkeys (ordem de primeira
    aparição, estável entre execuções): duas grafias que viram a mesma pessoa
    deixam de contar como duas.
    """
    finais = {}
    for bruto in nomes or ():
        nome = formatar_nome(bruto)
        if nome is None:
            continue
        final, regra = unificar(nome, pessoa_do_polo_passivo)
        if regra is not None:
            contadores[f"nomes_unificados_{regra}"] += 1
        if final in finais:
            contadores["nomes_colapsados"] += 1
            continue
        finais[final] = None
    return list(finais)
