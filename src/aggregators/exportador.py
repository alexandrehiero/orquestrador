"""Export da base final: SQLite -> JSONL (um documento por linha).

STREAMING é obrigatório. O consolidador antigo montava uma lista com todos os
registros e chamava json.dumps sobre ela: a 500 mil processos isso são dezenas
de GB de objetos em RAM mais a string inteira materializada antes de escrever.
Aqui a memória é constante — só o mapa de filhos fica residente.

JSONL e não array JSON: `mongoimport` consome JSONL nativamente em streaming, e
um array de 15 GB seria ilegível por qualquer ferramenta.

Escrita atômica: grava em .tmp e só então troca. Interromper no meio nunca deixa
uma base final truncada por cima da anterior.
"""

import json
import os
from collections import Counter
from pathlib import Path

from ..transformers.projecao import inverter_filhos, projetar


def exportar_jsonl(store, caminho, log=print):
    """Projeta todos os registros exportáveis e grava o JSONL. Devolve o resumo.

    `erro_transitorio` fica de fora por construção (não está entre os status
    exportáveis do store): é fila de trabalho, não resultado.
    """
    # Filhos são DERIVADOS da inversão dos pais, calculada agora — nunca um
    # campo gravado por um passo anterior que pudesse divergir do estado real.
    mapa_filhos = inverter_filhos(store.vinculos())

    caminho = str(caminho)
    tmp = caminho + ".tmp"
    total = 0
    por_status = Counter()
    por_grau = Counter()
    com_pai = 0
    com_filhos = 0

    try:
        with open(tmp, "w", encoding="utf-8") as arq:
            for reg in store.iter_exportaveis():
                filhos = mapa_filhos.get((reg["processo"], reg["grau"]), set())
                doc = projetar(reg, filhos)
                arq.write(json.dumps(doc, ensure_ascii=False) + "\n")

                total += 1
                por_status[doc["status"]] += 1
                por_grau[doc["grau"]] += 1
                if doc["relacionamento"]["processo_pai"]:
                    com_pai += 1
                if doc["relacionamento"]["processos_filhos"]:
                    com_filhos += 1
                if total % 5000 == 0:
                    log(f"  {total} registros exportados...")
    except BaseException:
        # A base anterior fica intacta (a troca só acontece no os.replace), mas
        # sem isto um .tmp de vários GB fica esquecido no disco após uma queda.
        Path(tmp).unlink(missing_ok=True)
        raise

    os.replace(tmp, caminho)

    return {
        "arquivo": caminho,
        "total": total,
        "por_status": dict(por_status),
        "por_grau": dict(por_grau),
        "com_pai": com_pai,
        # Documentos EXPORTADOS que têm filhos — comparável com `total` e
        # `com_pai`. `len(mapa_filhos)` contava também pais órfãos (citados mas
        # não coletados), então não era comparável com nada nesta mesma linha.
        "com_filhos": com_filhos,
        # Pares (pai, grau) citados que não casam com nenhum documento exportado.
        # NÃO é o mesmo que o total de órfãos: orfaos() casa por NÚMERO, este
        # conta PARES. A diferença entre os dois é exatamente o caso "o pai
        # existe, mas só no outro grau" — referência pendente, não coleta a
        # fazer. Nomeado por pares para não ser lido como o tamanho de orfaos.txt.
        "pares_pai_sem_documento": len(mapa_filhos) - com_filhos,
    }


def escrever_lista_orfaos(store, caminho):
    """Números citados como pai que NÃO têm registro — entrada da opção 3.

    Critério: 'não tem REGISTRO', não 'não tem dados'. Um processo gravado como
    sem_dados já foi visitado e sai da lista para sempre — é isso que faz o
    ciclo 4 -> 3 -> 4 convergir.
    """
    orfaos = store.orfaos()
    caminho = Path(caminho)
    tmp = Path(str(caminho) + ".tmp")
    # Diagnóstico em arquivo SEPARADO: preserva os graus em que cada órfão foi
    # citado. Sem ele, `graus_citados` seria calculado pelo SQL e descartado.
    diag = caminho.with_name(caminho.stem + "_diagnostico.txt")
    tmp_diag = Path(str(diag) + ".tmp")
    try:
        # Uma coluna só em orfaos.txt: este arquivo é LIDO de volta pela opção 3,
        # e ler_numeros extrai dígitos da linha inteira — um grau na mesma linha
        # viraria um número de 21 dígitos e seria descartado como inválido.
        tmp.write_text(
            "".join(f"{o['processo']}\n" for o in orfaos), encoding="utf-8"
        )
        tmp_diag.write_text(
            "# Órfãos e os graus em que foram citados como pai.\n"
            "# Arquivo de LEITURA HUMANA — a opção 3 lê apenas "
            f"{caminho.name}.\n"
            "# processo\tgraus_citados\n"
            + "".join(
                f"{o['processo']}\t{o.get('graus_citados') or ''}\n" for o in orfaos
            ),
            encoding="utf-8",
        )
        # Os dois temporários ficam prontos ANTES de qualquer troca. Não é
        # transação — os.replace não é atômico entre arquivos — mas a janela em
        # que a lista e o diagnóstico podem discordar cai de "toda a escrita do
        # segundo arquivo" para o intervalo entre dois os.replace.
        os.replace(tmp, caminho)
        os.replace(tmp_diag, diag)
    except BaseException:
        tmp.unlink(missing_ok=True)
        tmp_diag.unlink(missing_ok=True)
        raise

    return orfaos
