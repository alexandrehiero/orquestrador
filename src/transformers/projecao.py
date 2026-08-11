"""Projeção: registro do banco -> estrutura JSON final (uma linha do JSONL).

Função pura: recebe a linha do SQLite (com o bruto) e devolve o documento final.
Como é pura e roda sobre o bruto guardado, mudar a estrutura de saída não custa
nenhuma requisição — basta reprojetar.
"""

from .limpeza import (
    data_para_iso,
    dedup_movimentacoes,
    dedup_nomes,
    limpar_classe,
    limpar_texto,
    valor_para_float,
)
from ..status import (
    COLETADO,
    ERRO_PERSISTENTE,
    GRAU_INDETERMINADO,
    SEGREDO_JUSTICA,
    SEM_DADOS,
)

FRASE_SEGREDO = "Processo em segredo de justiça: requer senha para acesso aos dados."
FRASE_SEM_DADOS = "Processo não localizado no e-SAJ."
FRASE_ERRO = "Não foi possível coletar após as tentativas previstas."


def _mascara(d20):
    if len(d20) != 20:
        return None
    return f"{d20[0:7]}-{d20[7:9]}.{d20[9:13]}.{d20[13:14]}.{d20[14:16]}.{d20[16:20]}"


def chave(processo, grau):
    """_id do Mongo. Explícito para que reimportar seja idempotente: sem ele, o
    Mongo gera ObjectId aleatório e cada reimportação DUPLICA a base."""
    return f"{processo}__{grau if grau else GRAU_INDETERMINADO}"


def _grupo(partes, polo):
    """Achata as partes de um polo em {pessoas, representantes}, com dedup.
    `tipo_parte` (Exeqte, Reqdo...) fica só no bruto, por decisão do projeto."""
    pessoas, reps = [], []
    for p in partes or []:
        if p.get("polo") != polo:
            continue
        if p.get("nome"):
            pessoas.append(p["nome"])
        reps.extend(p.get("representantes") or [])
    return {"pessoas": dedup_nomes(pessoas), "representantes": dedup_nomes(reps)}


def _ref(processo, grau):
    """Referência a outro processo: número e grau SEPARADOS."""
    if not processo:
        return None
    return {"processo": processo, "grau": grau if grau else None}


def esqueleto(processo, grau, status):
    """Molde canônico. Todo registro exportado tem os MESMOS campos, qualquer que
    seja o status — a contagem da base final sempre fecha com a lista de entrada."""
    return {
        "_id": chave(processo, grau),
        "processo": processo,
        "processo_mascara": _mascara(processo),
        "grau": grau if grau else None,
        "status": status,
        "situacao": None,
        "classe": None,
        "assunto_principal": None,
        "foro": None,
        "vara": None,
        "juiz": None,
        "valor_acao": None,
        "data_distribuicao": None,
        "partes": {
            "autores": {"pessoas": [], "representantes": []},
            "reus": {"pessoas": [], "representantes": []},
        },
        "movimentacoes": [],
        "relacionamento": {"tipo": None, "processo_pai": None, "processos_filhos": []},
        "observacoes": [],
    }


def projetar(reg, filhos=None):
    """`reg` é a linha vinda de SqliteStore.iter_exportaveis(); `filhos` é o
    conjunto de (processo, grau) que apontam para este registro."""
    processo = reg["processo"]
    grau = reg.get("grau") or GRAU_INDETERMINADO
    status = reg["status"]
    bruto = reg.get("bruto") or {}

    final = esqueleto(processo, grau, status)

    # Relacionamento vale para TODOS os status, inclusive segredo de justiça:
    # topologia não é dado sigiloso, e os filhos foram calculados a partir de
    # OUTROS registros. Zerar isso deixaria o grafo assimétrico.
    final["relacionamento"]["tipo"] = reg.get("tipo_vinculo")
    final["relacionamento"]["processo_pai"] = _ref(
        reg.get("processo_pai"), reg.get("processo_pai_grau")
    )
    final["relacionamento"]["processos_filhos"] = [
        _ref(p, g) for p, g in sorted(filhos or [])
    ]

    obs = list(bruto.get("observacoes") or [])

    if status == COLETADO:
        final["situacao"] = limpar_texto(bruto.get("situacao"))
        final["classe"] = limpar_classe(bruto.get("classe"))
        final["assunto_principal"] = limpar_texto(bruto.get("assunto"))
        final["foro"] = limpar_texto(bruto.get("foro"))
        final["vara"] = limpar_texto(bruto.get("vara"))
        final["juiz"] = limpar_texto(bruto.get("juiz"))
        final["valor_acao"] = valor_para_float(bruto.get("valor"))
        final["data_distribuicao"] = data_para_iso(bruto.get("data_distribuicao"))
        final["partes"] = {
            "autores": _grupo(bruto.get("partes"), "ATIVO"),
            "reus": _grupo(bruto.get("partes"), "PASSIVO"),
        }
        # Partes de polo OUTRO (Interessado, Terceiro...) não têm grupo na
        # estrutura final, por decisão de projeto — ficam no bruto. Quando TODAS
        # caem em OUTRO, porém, o documento sai com autores e réus vazios embora
        # a capa tenha sido aprovada por _capa_suspeita. Sem esta observação, o
        # registro é indistinguível de uma capa sem partes.
        if bruto.get("partes") and not (
            final["partes"]["autores"]["pessoas"]
            or final["partes"]["reus"]["pessoas"]
        ):
            obs.append(
                "Partes extraídas, mas nenhuma classificada como autor ou réu "
                "(todas em polo OUTRO). Os nomes ficam apenas no bruto."
            )
        final["movimentacoes"] = dedup_movimentacoes(bruto.get("movimentacoes"))
    elif status == SEGREDO_JUSTICA:
        obs.insert(0, FRASE_SEGREDO)  # estrutura intacta, conteúdo suprimido
    elif status == SEM_DADOS:
        obs.insert(0, FRASE_SEM_DADOS)
    elif status == ERRO_PERSISTENTE:
        obs.insert(0, FRASE_ERRO)
        if reg.get("ultimo_erro"):
            obs.append(f"Último erro: {reg['ultimo_erro']}")
    else:
        # Não deveria acontecer com o vocabulário unificado em src/status.py.
        # Antes, um `else` genérico rotulava QUALQUER valor desconhecido como
        # erro persistente — o dado saía plausível e errado. Aqui ele se
        # denuncia na própria base, que é onde alguém vai reparar.
        obs.insert(0, f"Status não reconhecido pela projeção: {status!r}")

    vistos = set()
    final["observacoes"] = [
        o for o in (limpar_texto(x) for x in obs)
        if o and not (o in vistos or vistos.add(o))
    ]
    return final


def inverter_filhos(vinculos):
    """{(pai, grau) -> {(filho, grau), ...}} a partir das arestas do banco.

    Os filhos são SEMPRE derivados da inversão dos pais, nunca gravados por um
    passo separado — era assim que o reconciliador antigo podia divergir do
    estado real. Set por decisão de projeto (dedup nativo).
    """
    mapa = {}
    for v in vinculos or []:
        pai, pai_grau = v.get("processo_pai"), v.get("processo_pai_grau")
        if not pai:
            continue
        mapa.setdefault((pai, pai_grau or GRAU_INDETERMINADO), set()).add(
            (v["processo"], v.get("grau") or GRAU_INDETERMINADO)
        )
    return mapa
