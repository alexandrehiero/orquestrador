"""Conversão de moedas históricas e correção pelo IPCA — a MESMA regra do GPDR.

Portado de `Codigos_dados_GPDR/src/monetary.py`, que gerou `processo.valorCorrigido`
na v2 daquela base. A cópia é deliberada: os dois projetos não compartilham pacote
(os dois se chamam `src`), e o campo precisa significar a mesma coisa nas duas
bases para que comparar valores entre elas seja honesto.

Duas operações independentes, e ambas necessárias:

1. Conversão de moeda: muda a unidade de conta. Cr$ 1.000 de 1981 e R$ 1.000 de
   hoje são unidades diferentes, como polegada e centímetro.
2. Correção pelo IPCA: repõe o poder de compra perdido pela inflação.

Fazer só a primeira produz números absurdos (Cr$ 620.000 viram R$ 0,0000002);
fazer só a segunda mistura unidades incompatíveis.

O que NÃO veio do GPDR: a competência conferida à mão no e-SAJ. É trabalho humano
sobre processos daquela base; aqui a competência sai só da regra automática.
"""

import csv
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

#: Data-base FIXA e igual à do GPDR. Mudá-la muda todos os valores corrigidos e
#: quebra a comparação com aquela base.
COMPETENCIA_REFERENCIA = "2026-06"
#: Mês usado quando só se conhece o ano: o meio do ano minimiza o erro médio.
MES_PADRAO = "06"
INDICE = "IPCA-1737"

#: Vocabulário de `fonteCompetencia` — o mesmo do GPDR, para que a consulta
#: "quantos valores foram corrigidos pelo mês da distribuição" valha nas duas.
FONTE_DISTRIBUICAO = "ultimaDistribuicao"
FONTE_ANO_CNJ = "ano_cnj"

CONVERTIDO = "convertido"
FORA_DA_SERIE = "fora_da_serie_ipca"
MOEDA_NAO_IDENTIFICADA = "moeda_nao_identificada"

#: O fator de 1981 até hoje passa de 10^11; 40 dígitos é a precisão do GPDR.
_PRECISAO = 40

# Prefixo de três letras: funciona com ou sem acento, e sobrevive a arquivo salvo
# em latin-1 ou utf-8.
_MESES = {
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12",
}


@dataclass(frozen=True)
class Era:
    """Uma moeda vigente num intervalo de anos, com o divisor até o Real."""

    nome: str
    simbolo: str
    ano_inicial: int
    ano_final: int
    divisor_para_real: Decimal


# ATENÇÃO: 'Cr$' e 'CR$' são moedas diferentes, separadas por fator 1.000.
# A comparação de símbolo é sensível a maiúsculas — nunca normalizar a caixa.
ERAS = (
    Era("Cruzeiro (1ª)", "Cr$", 1942, 1967, Decimal("2.75E+15")),
    Era("Cruzeiro Novo", "NCr$", 1967, 1970, Decimal("2.75E+12")),
    Era("Cruzeiro (2ª)", "Cr$", 1970, 1986, Decimal("2.75E+12")),
    Era("Cruzado", "Cz$", 1986, 1989, Decimal("2.75E+9")),
    Era("Cruzado Novo", "NCz$", 1989, 1990, Decimal("2.75E+6")),
    Era("Cruzeiro (3ª)", "Cr$", 1990, 1993, Decimal("2.75E+6")),
    Era("Cruzeiro Real", "CR$", 1993, 1994, Decimal("2750")),
    Era("Real", "R$", 1994, 9999, Decimal("1")),
)


def era_de(simbolo, ano):
    """O símbolo sozinho não basta ('Cr$' existiu em três períodos) e o ano
    sozinho também não (nos anos de troca convivem duas moedas). Juntos,
    resolvem todos os casos."""
    for era in ERAS:
        if era.simbolo == simbolo and era.ano_inicial <= ano <= era.ano_final:
            return era
    return None


def _texto_do_arquivo(caminho):
    bruto = caminho.read_bytes()
    for codec in ("utf-8-sig", "latin-1"):
        try:
            return bruto.decode(codec)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Não foi possível decodificar {caminho}.")


def _competencia_do_rotulo(texto):
    """'dezembro 1979' -> '1979-12'."""
    partes = texto.strip().strip('"').split()
    if len(partes) != 2:
        return None
    mes = _MESES.get(partes[0][:3].lower())
    ano = partes[1]
    if mes is None or not (ano.isdigit() and len(ano) == 4):
        return None
    return f"{ano}-{mes}"


def _numero(texto):
    limpo = texto.strip().strip('"').replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except Exception:
        return None


def carregar_ipca(caminho):
    """Lê a tabela 1737 do SIDRA e devolve {competência: número-índice}.

    O arquivo do SIDRA vem transposto: os meses são colunas. Uma linha traz os
    nomes dos meses e outra, começando por 'Brasil', os valores.
    """
    linhas = list(csv.reader(_texto_do_arquivo(caminho).splitlines(), delimiter=";"))
    cabecalho = valores = None
    for campos in linhas:
        if len(campos) < 3:
            continue
        if cabecalho is None and _competencia_do_rotulo(campos[1]):
            cabecalho = campos
        elif cabecalho is not None and campos[0].strip().strip('"') == "Brasil":
            valores = campos
            break
    if cabecalho is None or valores is None:
        raise ValueError(f"Layout inesperado em {caminho}: não achei a linha de "
                         "meses ou a linha 'Brasil'.")

    tabela = {}
    for rotulo, bruto in zip(cabecalho[1:], valores[1:]):
        chave = _competencia_do_rotulo(rotulo)
        indice = _numero(bruto)
        if chave and indice is not None and indice > 0:
            tabela[chave] = indice
    if not tabela:
        raise ValueError(f"Nenhum número-índice válido em {caminho}.")
    return tabela


def converter_valor(valor, simbolo, ano, competencia, referencia, tabela):
    """Leva um valor histórico ao Real e ao poder de compra da referência.

    Devolve (status, nominal em R$, corrigido). O status diz POR QUE uma etapa
    não foi possível, em vez de a ausência ficar sem explicação no documento.
    """
    era = era_de(simbolo, ano)
    if era is None:
        return MOEDA_NAO_IDENTIFICADA, None, None
    with localcontext() as ctx:
        ctx.prec = _PRECISAO
        nominal = valor / era.divisor_para_real
        origem, destino = tabela.get(competencia), tabela.get(referencia)
        if origem is None or destino is None:
            # Processos anteriores a dez/1979 (início da série) e competências
            # ainda não publicadas.
            return FORA_DA_SERIE, nominal, None
        atualizado = (nominal * destino / origem).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return CONVERTIDO, nominal, atualizado


def competencia_de(numero, data_distribuicao):
    """Escolhe a competência de correção e diz de onde ela veio.

    Quando a distribuição cai no mesmo ano do CNJ, o mês dela é confiável. Quando
    diverge, a data está marcando outro evento (redistribuição, tipicamente) e
    sobra o ano do CNJ — que é definicional — com o mês padrão.
    """
    ano = numero[9:13]
    if data_distribuicao and data_distribuicao[:4] == ano:
        return data_distribuicao[:7], FONTE_DISTRIBUICAO
    return f"{ano}-{MES_PADRAO}", FONTE_ANO_CNJ


def valor_corrigido(valor, simbolo, numero, data_distribuicao, tabela):
    """O bloco `processo.valorCorrigido`, com as chaves na ordem do GPDR.

    Os dois números-índice ficam no documento para que a conta seja refeita sem
    a tabela nem este código: basta nominal × referência ÷ origem.
    """
    competencia, fonte = competencia_de(numero, data_distribuicao)
    status, nominal, atualizado = converter_valor(
        Decimal(str(valor)), simbolo, int(numero[9:13]),
        competencia, COMPETENCIA_REFERENCIA, tabela,
    )
    return {
        "moedaOriginal": simbolo,
        "brlNominal": nominal,
        "brlAtualizado": atualizado,
        "competencia": competencia,
        "fonteCompetencia": fonte,
        "referencia": COMPETENCIA_REFERENCIA,
        "indice": INDICE,
        "indiceOrigem": tabela.get(competencia),
        "indiceReferencia": tabela.get(COMPETENCIA_REFERENCIA),
        "status": status,
    }
