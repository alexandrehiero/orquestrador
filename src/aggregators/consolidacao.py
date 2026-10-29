"""Auditoria e consolidação da base JSONL de um ano.

A base de uma coleta chega como JSONL, colocado à mão em `data_final/JSONL_final/`.
Antes de virar a estrutura do GPDR, ela é confrontada com a lista do ano
(`data/por_ano/`) para responder três perguntas: falta algum processo? algum
aparece mais de uma vez? o grafo de relacionamento continua fechando depois de
acrescentar os que faltavam?

Desduplicação por NÚMERO, não por `_id`: o orquestrador decide o grau sozinho,
então um número tem um único registro — a mesma premissa de
`SqliteStore.numeros_finalizados`. Duas linhas do mesmo número são duas respostas
à mesma pergunta, e fica a mais informativa.

Nada é destruído: as linhas descartadas da base saem num arquivo à parte, byte a
byte como estavam. A base consolidada mais esse arquivo reconstituem a original.

Leitura e escrita em BINÁRIO: as linhas mantidas são copiadas sem passar por
json.loads/dumps e chegam idênticas, inclusive no fim de linha. Só o registro
cujos filhos mudaram é decodificado e reescrito.
"""

import json
import os
from collections import Counter, namedtuple
from pathlib import Path

from ..status import (
    COLETADO,
    ERRO_PERSISTENTE,
    GRAU_INDETERMINADO,
    SEGREDO_JUSTICA,
    SEM_DADOS,
)
from ..transformers.projecao import inverter_filhos

#: A base (o JSONL colocado à mão) e a coleta nova (o export dos faltantes).
FONTE_BASE = 0
FONTE_COLETA = 1

# Quanto mais o status diz sobre o processo, mais alto. `sem_dados` fica acima
# de `erro_persistente` pela regra do projeto inteiro: "perguntei e não existe"
# vale mais que "não consegui perguntar".
PRIORIDADE = {COLETADO: 4, SEGREDO_JUSTICA: 3, SEM_DADOS: 2, ERRO_PERSISTENTE: 1}

#: O mínimo de cada registro que a auditoria precisa — o documento inteiro é
#: descartado logo após a leitura. `filhos` é None quando vazio (memória).
Linha = namedtuple("Linha", "fonte posicao processo grau status pai pai_grau filhos")


def _grau(valor):
    return valor or GRAU_INDETERMINADO


def ler_linhas(caminho, fonte, apenas=None, ao_ler=None):
    """Uma `Linha` por registro do JSONL, com a posição (linha física, base 0).

    `apenas` restringe a um conjunto de números — é assim que a coleta nova
    entra: só os processos que esta execução foi buscar. `ao_ler(n)` recebe os
    bytes de cada linha, para a barra de progresso.
    """
    with open(caminho, "rb") as arquivo:
        for posicao, bruto in enumerate(arquivo):
            if ao_ler is not None:
                ao_ler(len(bruto))
            if not bruto.strip():
                continue
            try:
                doc = json.loads(bruto)
            except ValueError as erro:
                raise ValueError(f"{caminho}, linha {posicao + 1}: JSON inválido "
                                 f"({erro}).") from erro
            if apenas is not None and doc["processo"] not in apenas:
                continue
            rel = doc.get("relacionamento") or {}
            pai = rel.get("processo_pai") or {}
            filhos = frozenset(
                (f["processo"], _grau(f.get("grau"))) for f in rel.get("processos_filhos") or ()
            )
            yield Linha(
                fonte, posicao, doc["processo"], _grau(doc.get("grau")), doc.get("status"),
                pai.get("processo"), _grau(pai.get("grau")) if pai.get("processo") else None,
                filhos or None,
            )


def _ordem(linha, preferir_coleta):
    """Status mais informativo vence.

    Empate entre a base e a coleta nova fica com a BASE: só um desfecho melhor
    justifica reescrever gigabytes, e é isso que faz uma segunda execução não
    mudar nada. Empate dentro da mesma fonte fica com a ÚLTIMA linha — a
    acrescentada por último é a mais recente.

    Número em `preferir_coleta` inverte o empate entre as fontes: é a recoleta
    pedida (quando uma regra de extração mudou e a linha da base ficou velha).
    Status pior continua perdendo: uma falha nunca troca a capa da base.
    """
    fonte = linha.fonte if linha.processo in preferir_coleta else -linha.fonte
    return (PRIORIDADE.get(linha.status, 0), fonte, linha.posicao)


def escolher(linhas, preferir_coleta=frozenset()):
    """Devolve ({processo: Linha mantida}, [Linhas descartadas])."""
    mantidas, descartadas = {}, []
    for linha in linhas:
        atual = mantidas.get(linha.processo)
        if atual is None:
            mantidas[linha.processo] = linha
        elif _ordem(linha, preferir_coleta) > _ordem(atual, preferir_coleta):
            descartadas.append(atual)
            mantidas[linha.processo] = linha
        else:
            descartadas.append(linha)
    return mantidas, descartadas


def mapa_filhos(mantidas):
    """{(pai, grau): {(filho, grau)}} sobre a base consolidada inteira.

    Filho que ESTÁ na base: vale o pai que ele mesmo declara, invertido agora por
    `projecao.inverter_filhos` — depois de acrescentar processos, o registro de
    um pai não sabe dos filhos novos.

    Filho que NÃO está na base fica como veio no registro do pai. O banco que
    gerou o JSONL o conhecia e este arquivo não; não há como conferi-lo, e
    recalcular só sobre a base apagaria uma aresta verdadeira.
    """
    mapa = inverter_filhos(
        {"processo": l.processo, "grau": l.grau,
         "processo_pai": l.pai, "processo_pai_grau": l.pai_grau}
        for l in mantidas.values() if l.pai
    )
    for l in mantidas.values():
        externos = {f for f in l.filhos or () if f[0] not in mantidas}
        if externos:
            mapa.setdefault((l.processo, l.grau), set()).update(externos)
    return mapa


def filhos_divergentes(mantidas, filhos):
    """Quantos registros trazem `processos_filhos` diferente do recalculado."""
    return sum(
        1 for l in mantidas.values()
        if (l.filhos or frozenset()) != filhos.get((l.processo, l.grau), set())
    )


def orfaos(mantidas):
    """Pais citados sem registro na base. Casamento por NÚMERO, o mesmo critério
    de `SqliteStore.orfaos` — um pai que existe só no outro grau não é órfão."""
    return sorted({l.pai for l in mantidas.values() if l.pai and l.pai not in mantidas})


def _reescrever_filhos(bruto, filhos):
    doc = json.loads(bruto)
    doc["relacionamento"]["processos_filhos"] = [
        {"processo": p, "grau": g if g else None} for p, g in sorted(filhos)
    ]
    fim = b"\r\n" if bruto.endswith(b"\r\n") else b"\n"
    return json.dumps(doc, ensure_ascii=False).encode("utf-8") + fim


def _com_fim(bruto):
    """A última linha de um arquivo pode vir sem quebra; outra viria colada nela."""
    return bruto if bruto.endswith(b"\n") else bruto + os.linesep.encode()


def consolidar(fontes, mantidas, filhos, destino, removidos, ao_ler=None):
    """Regrava a base com as linhas mantidas, na ordem das fontes.

    `fontes[i]` é o caminho da fonte i (FONTE_BASE, FONTE_COLETA). Linha da BASE
    que perdeu vai para `removidos`; linha da coleta nova que perdeu é só
    ignorada — a base já tinha resposta igual ou melhor.

    Escrita atômica nos dois arquivos. `removidos` troca de nome primeiro: se a
    execução cair entre as duas trocas, sobra um registro das linhas removidas
    ao lado de uma base que ainda as tem — nunca o contrário.
    """
    vencedoras = {(l.fonte, l.posicao): l for l in mantidas.values()}
    destino, removidos = Path(destino), Path(removidos)
    tmp, tmp_removidos = Path(f"{destino}.tmp"), Path(f"{removidos}.tmp")
    removidos.parent.mkdir(parents=True, exist_ok=True)
    contadores = Counter()
    try:
        with open(tmp, "wb") as saida, open(tmp_removidos, "wb") as descarte:
            for fonte, caminho in enumerate(fontes):
                with open(caminho, "rb") as arquivo:
                    for posicao, bruto in enumerate(arquivo):
                        if ao_ler is not None:
                            ao_ler(len(bruto))
                        if not bruto.strip():
                            continue
                        linha = vencedoras.get((fonte, posicao))
                        if linha is None:
                            if fonte == FONTE_BASE:
                                descarte.write(_com_fim(bruto))
                                contadores["linhas_removidas"] += 1
                            continue
                        novos = filhos.get((linha.processo, linha.grau), set())
                        if novos != (linha.filhos or frozenset()):
                            bruto = _reescrever_filhos(bruto, novos)
                            contadores["filhos_corrigidos"] += 1
                        saida.write(_com_fim(bruto))
                        contadores["linhas_mantidas_da_base" if fonte == FONTE_BASE
                                   else "linhas_acrescentadas"] += 1
    except BaseException:
        tmp.unlink(missing_ok=True)
        tmp_removidos.unlink(missing_ok=True)
        raise
    os.replace(tmp_removidos, removidos)
    os.replace(tmp, destino)
    return contadores
