"""Limpeza e normalização — módulo PURO (sem rede, sem I/O, testável isolado).

É aqui que o texto bruto do parser vira dado utilizável. Rodar sobre o bruto
guardado no SQLite significa que corrigir qualquer regra abaixo é uma
REPROJEÇÃO local — nenhuma requisição nova.

Substitui as QUATRO implementações de data espalhadas pelo pipeline IAMSPE
(_chave_data, _iso_para_br, _br_para_iso e nenhuma no normalizador).
"""

import re
import unicodedata
from datetime import date

_PARENTESES = re.compile(r"\([^()]*\)")
_DATA_BR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# Dois passos, e a ordem é o ponto. Alternação num regex só resolve pelo padrão
# MAIS À ESQUERDA, não pelo mais específico: em 'em 2024: R$ 3.724,16' o '2024'
# vencia e produzia 2024.0. Procurando primeiro QUALQUER valor com centavos em
# toda a string, o ano deixa de competir com o valor.
_VALOR_COM_CENTAVOS = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}")
_VALOR_SEM_CENTAVOS = re.compile(r"\d{1,3}(?:\.\d{3})+|\d+")


def limpar_texto(valor):
    """Colapsa espaços e devolve None (não string vazia) quando não há conteúdo.

    None em vez de sentinela: a sentinela era convertida para None no fim do
    pipeline de qualquer forma, e strings em campos numéricos quebram $avg/$sum
    no Mongo e forçam dtype=object no pandas.
    """
    if valor is None:
        return None
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto or None


def limpar_classe(valor):
    """Remove TODO conteúdo entre parênteses da classe.

    Cobre os três casos reais: o número do próprio processo
    ('Cumprimento de Sentença contra a Fazenda Pública (0000010-31...)'),
    sequenciais ('(06)') e referências legais ('(Lei nº 9.099/95)').
    O laço trata parênteses aninhados/múltiplos.
    """
    if valor is None:
        return None
    texto = str(valor)
    anterior = None
    while anterior != texto:  # múltiplos/aninhados
        anterior = texto
        texto = _PARENTESES.sub(" ", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" -–—:;,")
    return texto or None


def data_para_iso(valor):
    """'09/01/2013 às 11:39 - Livre' -> '2013-01-09'. None se não houver data.

    ISO porque é ordenável como string, filtrável por intervalo no Mongo e
    interpretável por qualquer ferramenta. Nunca 'inventa' data.
    """
    if not valor:
        return None
    # Validar por faixa (mes<=12, dia<=31) aceitava 31/02/2020 e devolvia
    # '2020-02-31' — string ISO que não corresponde a data nenhuma, gravada no
    # JSONL e quebrando só na importação. date() rejeita na origem e ainda
    # acerta ano bissexto (29/02/2024 passa, 30/02/2024 não).
    for m in _DATA_BR.finditer(str(valor)):
        dia, mes, ano = m.groups()
        try:
            return date(int(ano), int(mes), int(dia)).isoformat()
        except ValueError:
            continue  # data impossível: tenta a próxima ocorrência do texto
    return None


def valor_para_float(valor):
    """'R$ 3.724,16' -> 3724.16. Não convertível -> None (nunca string)."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    # Antes, re.sub removia tudo que não fosse dígito ou vírgula, sem olhar
    # POSIÇÃO: 'R$ 3.724,16 - atualizado em 2024' virava 3724.162024 — um número
    # plausível e errado, sem erro nem observação. Agora casamos o PRIMEIRO
    # padrão monetário e ignoramos o resto da string.
    texto = str(valor)
    m = _VALOR_COM_CENTAVOS.search(texto) or _VALOR_SEM_CENTAVOS.search(texto)
    if not m:
        return None
    try:
        return float(m.group(0).replace(".", "").replace(",", "."))
    except ValueError:
        return None


# --- desduplicação nativa (Teoria de Conjuntos) ------------------------------
def _chave_dedup(texto):
    """Chave de comparação: minúsculas, sem acento, espaços colapsados.
    Faz 'MICHELE DIAS' e 'Michele  Dias' colidirem como o mesmo nome."""
    decomp = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomp if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def dedup_nomes(itens):
    """Remove duplicatas e vazios preservando a ordem. A GRAFIA guardada é a da
    primeira aparição — nada é reescrito."""
    vistos = set()
    saida = []
    for item in itens or []:
        original = re.sub(r"\s+", " ", str(item or "")).strip()
        if not original:
            continue
        chave = _chave_dedup(original)
        if chave not in vistos:
            vistos.add(chave)
            saida.append(original)
    return saida


def dedup_movimentacoes(movs):
    """Dedup por (data ISO, descrição normalizada) e ordena da mais antiga para
    a mais recente. O e-SAJ entrega em ordem decrescente; a ordenação só é
    correta DEPOIS da conversão para ISO."""
    vistos = set()
    saida = []
    for mov in movs or []:
        data = data_para_iso(mov.get("data"))
        desc = limpar_texto(mov.get("descricao"))
        if not desc:
            continue
        chave = (data, _chave_dedup(desc))
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append({"data": data, "movimento": desc})
    saida.sort(key=lambda m: (m["data"] is None, m["data"] or ""))
    return saida
