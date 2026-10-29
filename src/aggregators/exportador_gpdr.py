"""Export da estrutura do GPDR: JSONL consolidado -> array JSON.

Array JSON (`[{...},{...}]`), e não JSONL, porque é o formato de entrega da base
do GPDR: as duas se carregam pelo mesmo `mongoimport --jsonArray`.

STREAMING e escrita atômica, como `exportador`: um documento por vez num .tmp, e
só no fim a troca de nome. Interromper nunca deixa uma base pela metade com nome
de base boa. A memória fica no tamanho do mapa de filhos; os blocos da PGE são
lidos do índice em disco, um por documento.
"""

import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path

from ..status import GRAU_INDETERMINADO
from ..transformers import estrutura_gpdr


def _json_default(valor):
    """Decimal -> int quando inteiro, float quando não.

    O cálculo monetário é feito em Decimal. `default=str` gravaria 620000 como o
    TEXTO "620000.0", e a base chegaria ao Mongo com números virados string —
    erro que já custou uma regeração completa no GPDR. Qualquer outro tipo é
    defeito nosso, e se denuncia em vez de virar texto.
    """
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    raise TypeError(f"Tipo não serializável: {type(valor).__name__}")


class EscritorArrayJson:
    """Grava um array JSON documento a documento, finalizando de forma atômica.

    Enquanto o `with` está aberto o conteúdo vive num .tmp; só ao sair sem erro
    o arquivo assume o nome definitivo.
    """

    def __init__(self, destino):
        self.destino = Path(destino)
        self.temporario = Path(f"{self.destino}.tmp")
        self._arquivo = None
        self._primeiro = True

    def __enter__(self):
        self.destino.parent.mkdir(parents=True, exist_ok=True)
        self._arquivo = self.temporario.open("w", encoding="utf-8")
        self._arquivo.write("[\n")
        return self

    def escrever(self, documento):
        if not self._primeiro:
            self._arquivo.write(",\n")
        self._arquivo.write(json.dumps(documento, ensure_ascii=False, default=_json_default))
        self._primeiro = False

    def __exit__(self, tipo_excecao, *_):
        self._arquivo.write("\n]\n")
        self._arquivo.close()
        if tipo_excecao is None:
            os.replace(self.temporario, self.destino)
        else:
            self.temporario.unlink(missing_ok=True)
        return False


def exportar_estrutura_gpdr(origem, destino, foros, ipca, filhos, indice_pge,
                            posicoes=None, limite=None, ao_ler=None):
    """Projeta cada linha do JSONL na estrutura do GPDR e grava o array.

    `filhos` é o mapa recalculado sobre a base inteira (`consolidacao.mapa_filhos`).
    `posicoes` restringe às linhas mantidas — só a amostra precisa, porque ela
    lê a base sem consolidá-la. `limite` para após N documentos.
    """
    contadores = Counter()
    with EscritorArrayJson(destino) as escritor, open(origem, "rb") as arquivo:
        for posicao, bruto in enumerate(arquivo):
            if ao_ler is not None:
                ao_ler(len(bruto))
            if limite is not None and contadores["documentos_escritos"] >= limite:
                break
            if not bruto.strip() or (posicoes is not None and posicao not in posicoes):
                continue
            reg = json.loads(bruto)
            chave = (reg["processo"], reg.get("grau") or GRAU_INDETERMINADO)
            escritor.escrever(estrutura_gpdr.projetar(
                reg, foros, ipca, filhos.get(chave), indice_pge.obter(reg["processo"]),
                contadores,
            ))
            contadores["documentos_escritos"] += 1
    return contadores
