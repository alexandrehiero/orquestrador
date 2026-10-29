"""Projeção: documento do JSONL do orquestrador -> estrutura JSON do GPDR.

A referência de schema é a v7 de `Codigos_dados_GPDR` (`PGE_GPDR_e_Dados_Capa_v7`):
mesmos nomes de campo, mesmo aninhamento, mesma ordem de chaves e as mesmas
convenções de valor — datas em Extended JSON, foro lido do CNJ, valor corrigido
pelo IPCA, nomes formatados. Fica de fora só `metadados`, que é o cadastro
administrativo da PGE e não existe para um processo coletado pelo orquestrador.

O que o orquestrador sabe e o GPDR não tem onde guardar entra nos objetos a que
pertence, em chaves novas no FIM de cada um, para que a ordem das chaves comuns
continue a da v7: `status` e `situacao` em `processo`, `juiz` em `orgaoJulgador`,
e `relacionamento` e `observacoes` no nível de `processo`, fechando o documento.

Função pura, como `projecao`: mudar a estrutura de saída é rodar de novo sobre o
JSONL, sem nenhuma requisição. Os campos de conteúdo já chegam vazios fora do
status `coletado` (`projecao.esqueleto`), então nenhum ramo por status é preciso.

Duas diferenças assumidas frente ao GPDR:

- **Campos sem dado saem como null, nunca ausentes.** No GPDR `valorCorrigido`
  some quando não há valor; aqui todo documento tem os mesmos campos, qualquer
  que seja o status (o mesmo princípio de `projecao.esqueleto`). No Mongo,
  `{campo: null}` casa com as duas formas.
- **`tiposParte` sai sempre como lista vazia.** O tipo de parte (Reqte, Exeqte…)
  fica no bruto do SQLite e não chega ao JSONL, que é a entrada deste módulo.
"""

import re

from . import monetario, nomes
from ..status import GRAU_INDETERMINADO

CAMPO_MOVIMENTOS_TJSP = "movimentos_tjsp"
CAMPO_MOVIMENTOS_PGE = "movimentos_pge"
CAMPO_ORIGEM_PGE = "origem_pge"

TRIBUNAL = {
    "sigla": "TJSP",
    "nome": "Tribunal de Justiça de São Paulo",
    "segmento": "JUSTICA_ESTADUAL",
    "jtr": 826,
}
# '°' é o sinal de grau (U+00B0), como na base do GPDR — não o ordinal 'º'.
GRAUS = {
    1: {"sigla": "G1", "nome": "1° Grau", "numero": 1},
    2: {"sigla": "G2", "nome": "2° Grau", "numero": 2},
}
POLOS = (("autores", "ATIVO"), ("reus", "PASSIVO"))

_LINHA_TABELA_FOROS = re.compile(r"^\|\s*(\d{4})\s*\|\s*(.+?)\s*\|$")
_TOTAL_DECLARADO = re.compile(r"Total de registros:\s*(\d+)")


def carregar_foros(caminho):
    """Lê `unidades_foro_tjsp.md` (Resolução TJSP nº 65/2008) -> {código: descrição}.

    O arquivo declara o próprio total, e a leitura confere contra ele: uma linha
    perdida por formatação deixaria processos sem descrição sem que nada
    acusasse o motivo.
    """
    texto = caminho.read_text(encoding="utf-8")
    tabela = {}
    for linha in texto.splitlines():
        achado = _LINHA_TABELA_FOROS.match(linha.strip())
        if achado is None:
            continue
        codigo, descricao = achado.groups()
        if codigo in tabela:
            raise ValueError(f"Código {codigo} repetido em {caminho}.")
        tabela[codigo] = descricao
    if not tabela:
        raise ValueError(f"Nenhuma linha de tabela reconhecida em {caminho}.")
    declarado = _TOTAL_DECLARADO.search(texto)
    if declarado is not None and int(declarado.group(1)) != len(tabela):
        raise ValueError(f"{caminho} declara {declarado.group(1)} registros, mas "
                         f"foram lidos {len(tabela)}.")
    return tabela


def _data(iso):
    """'2024-12-19' -> {"$date": "2024-12-19T00:00:00.000Z"}, como o GPDR.

    Extended JSON, e não a string ISO: o `mongoimport` cria Date nativo, que
    ordena e filtra por intervalo.
    """
    return {"$date": f"{iso}T00:00:00.000Z"} if iso else None


def _numero(valor):
    """620000.0 -> 620000: o GPDR grava inteiro quando o valor é inteiro."""
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    return valor


def _ref(processo, grau):
    return {"processo": processo, "grau": grau if grau else None}


def _partes(partes, contadores):
    """{autores, reus} -> lista com um item por polo, como o GPDR.

    O polo só entra se tiver alguém: o GPDR não cria item para polo ausente.
    """
    saida = []
    for chave, polo in POLOS:
        grupo = (partes or {}).get(chave) or {}
        pessoas = nomes.normalizar_nomes(grupo.get("pessoas"), polo == "PASSIVO", contadores)
        representantes = nomes.normalizar_nomes(grupo.get("representantes"), False, contadores)
        if pessoas or representantes:
            saida.append({"polo": polo, "tiposParte": [], "pessoas": pessoas,
                          "representantes": representantes})
    return saida


def projetar(reg, foros, ipca, filhos, bloco_pge, contadores):
    """`reg` é uma linha do JSONL; `filhos` é o conjunto de (processo, grau) que
    apontam para ele; `bloco_pge` é o bloco do Atos ou None (sem par).

    Os filhos chegam de fora (`consolidacao.mapa_filhos`), e não são lidos do
    próprio `reg`: depois de acrescentar processos, o registro de um pai não
    sabe dos filhos novos — a mesma razão pela qual `exportador` deriva os
    filhos em vez de gravá-los.
    """
    numero = reg["processo"]
    status = reg["status"]
    contadores[f"status_{status}"] += 1

    codigo = numero[16:20] if len(numero) == 20 else None
    descricao_foro = foros.get(codigo) if codigo else None
    contadores["foro_atribuido" if descricao_foro else "foro_fora_da_tabela"] += 1

    valor = reg.get("valor_acao")
    bloco_valor = None
    if valor is not None:
        bloco_valor = monetario.valor_corrigido(
            valor, reg.get("valor_acao_moeda"), numero, reg.get("data_distribuicao"), ipca
        )
        contadores[f"valor_{bloco_valor['status']}"] += 1

    movimentos = [
        {"descricao": m.get("movimento"), "dataHora": _data(m.get("data"))}
        for m in (reg.get("movimentacoes") or ())
    ]

    rel = reg.get("relacionamento") or {}
    filhos = sorted(filhos or ())
    if filhos:
        contadores["com_filhos"] += 1

    if bloco_pge is None:
        contadores["sem_par_pge"] += 1
    else:
        contadores["com_bloco_pge"] += 1
        contadores["movimentos_pge"] += len(bloco_pge[CAMPO_MOVIMENTOS_PGE])

    grau = reg.get("grau") or GRAU_INDETERMINADO
    return {
        "processo": {
            "numero": numero,
            "classe": {"descricao": reg.get("classe")},
            "assunto": {"descricao": reg.get("assunto_principal")},
            "valorAcao": _numero(valor),
            "valorCorrigido": bloco_valor,
            "foro": {"codigo": codigo, "descricao": descricao_foro} if codigo else None,
            # Sem `status`, um segredo de justiça e um processo inexistente seriam
            # o mesmo documento vazio.
            "status": status,
            "situacao": reg.get("situacao"),
        },
        "tribunal": dict(TRIBUNAL),
        "grau": dict(GRAUS[grau]) if grau in GRAUS else None,
        # No 2º grau, o `juiz` do orquestrador é o relator (`parser_segundo_grau`).
        "orgaoJulgador": {"nome": reg.get("vara"), "juiz": reg.get("juiz")},
        "datas": {
            "ultimaDistribuicao": _data(reg.get("data_distribuicao")),
            # Primeiro item: a lista vem do e-SAJ com o mais recente primeiro.
            "ultimoMovimento": dict(movimentos[0]) if movimentos else None,
        },
        "partes": _partes(reg.get("partes"), contadores),
        CAMPO_MOVIMENTOS_TJSP: movimentos,
        "_id": reg["_id"],
        CAMPO_MOVIMENTOS_PGE: bloco_pge[CAMPO_MOVIMENTOS_PGE] if bloco_pge else None,
        CAMPO_ORIGEM_PGE: bloco_pge[CAMPO_ORIGEM_PGE] if bloco_pge else None,
        "relacionamento": {
            "tipo": rel.get("tipo"),
            "processo_pai": rel.get("processo_pai"),
            "processos_filhos": [_ref(p, g) for p, g in filhos],
        },
        "observacoes": list(reg.get("observacoes") or ()),
    }
