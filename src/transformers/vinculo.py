"""Deriva o vínculo (tipo + processo pai) — ÚNICO ESCRITOR de `tipo`.

Chamado NA COLETA, com o bruto do parser em mãos. Grava direto nas colunas do
SQLite. Nenhum passo posterior reescreve o tipo — no pipeline IAMSPE ele tinha
dois donos (normalizador e vincular_pais), e o segundo desfazia o primeiro.

Vocabulário fechado, atribuído SÓ com evidência:
  incidente   -> link 'Processo principal' no topo, ou a movimentação de origem.
                 O pai é do MESMO grau (incidente corre na mesma instância).
  recurso     -> capa de 2º grau declarando o número de 1ª instância.
                 O pai é, por definição, do grau 1.
  indefinido  -> há indício de vínculo, mas o número é inválido/antigo.
  sem_vinculo -> nenhum sinal de pai.

Note o que NÃO existe mais: 'Ação de Conhecimento (Pai)'. Ele afirmava duas
coisas não verificadas — que o processo é ação de conhecimento (a Classe
responde isso) e que ele é pai (só é verdade se tiver filhos, o que se sabe
invertendo os vínculos, não na coleta).
"""

import re

INCIDENTE = "incidente"
RECURSO = "recurso"
SEM_VINCULO = "sem_vinculo"
INDEFINIDO = "indefinido"

VERSAO_REGRA = "1"

# Ancorado no rótulo — nunca captura um CNJ solto que apareça no meio do texto.
_PADRAO_PAI_MOV = re.compile(
    r"processo principal:?\s*(\d{7}[-.]?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4})", re.I
)
_DATA_BR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def _digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def _dv_ok(d20):
    """DV do CNJ (ISO 7064 MOD 97-10). Filtrar aqui é de graça e evita criar
    aresta no grafo apontando para um número que não existe."""
    if len(d20) != 20:
        return False
    base = int(d20[0:7] + d20[9:13] + d20[13:14] + d20[14:16] + d20[16:20] + "00")
    return d20[7:9] == f"{98 - (base % 97):02d}"


def _chave_data(data_br):
    """Chave ordenável. Data ilegível vai para o fim — nunca vira 'mais antiga'."""
    m = _DATA_BR.search(str(data_br or ""))
    if not m:
        return (9999, 99, 99)
    dia, mes, ano = m.groups()
    return (int(ano), int(mes), int(dia))


def _pai_da_movimentacao(movimentacoes, proprio):
    """Quando há mais de uma citação, vence a da DATA MAIS ANTIGA — a
    movimentação de ORIGEM, que declara de onde o processo nasceu."""
    melhor = None
    for mov in movimentacoes or []:
        m = _PADRAO_PAI_MOV.search(mov.get("descricao") or "")
        if not m:
            continue
        pai = _digitos(m.group(1))
        if len(pai) != 20 or pai == proprio:
            continue
        chave = _chave_data(mov.get("data"))
        if melhor is None or chave < melhor[0]:
            melhor = (chave, pai)
    return melhor[1] if melhor else None


def derivar_vinculo(bruto, grau, processo):
    """Devolve {tipo, processo_pai, processo_pai_grau, observacoes}.

    Prioridade: link do topo > movimentação de origem > número de 1ª instância.
    Quando há mais de um vínculo válido, o HIERÁRQUICO (incidente) vence — é o
    pai direto — e o outro é registrado em observacoes, nunca descartado.
    """
    proprio = _digitos(processo)
    obs = []
    bruto = bruto or {}

    candidatos = []

    pai_link = _digitos(bruto.get("processo_principal"))
    if pai_link:
        candidatos.append((INCIDENTE, pai_link, grau, "link do topo"))

    pai_mov = _pai_da_movimentacao(bruto.get("movimentacoes"), proprio)
    if pai_mov and pai_mov != pai_link:
        candidatos.append((INCIDENTE, pai_mov, grau, "movimentação de origem"))

    primeira = _digitos(bruto.get("processo_1a_instancia"))
    if grau == 2 and primeira:
        candidatos.append((RECURSO, primeira, 1, "número de 1ª instância"))
    elif grau == 2 and not bruto.get("processo_1a_instancia_bruto"):
        # Registrado porque este é o caminho pelo qual uma FALHA DE SELETOR do
        # cposg chegaria à base final: em silêncio, indistinguível de um processo
        # de competência originária que genuinamente não tem 1ª instância.
        obs.append("Capa de 2º grau sem número de 1ª instância localizado.")

    escolhido = None
    # Contador explícito. Antes o tipo era decidido procurando a palavra
    # "ignorado" nas observações que este mesmo módulo escreve — controle de
    # fluxo passando por texto de log. Reescrever a mensagem para "Vínculo
    # descartado" mudaria o TIPO em silêncio, sem quebrar nada visivelmente.
    descartados = 0
    for tipo, pai, pai_grau, origem in candidatos:
        # Guarda de auto-referência em TODOS os caminhos. No pipeline antigo ela
        # existia só para o número de 1ª instância; o link do topo podia criar
        # um processo filho de si mesmo.
        if pai == proprio and pai_grau == grau:
            obs.append(f"Vínculo ignorado ({origem}): aponta para o próprio processo.")
            descartados += 1
            continue
        if not _dv_ok(pai):
            obs.append(f"Vínculo ignorado ({origem}): número {pai} com DV inválido.")
            descartados += 1
            continue
        if escolhido is None:
            escolhido = (tipo, pai, pai_grau)
        else:
            obs.append(f"Outro vínculo detectado ({origem}): {pai} (grau {pai_grau}).")

    bruto_1a = bruto.get("processo_1a_instancia_bruto")
    if bruto_1a:
        obs.append(f"Número de 1ª instância em formato antigo: {bruto_1a}")

    if escolhido:
        tipo, pai, pai_grau = escolhido
        return {"tipo": tipo, "processo_pai": pai,
                "processo_pai_grau": pai_grau, "observacoes": obs}

    if bruto_1a or descartados:
        return {"tipo": INDEFINIDO, "processo_pai": None,
                "processo_pai_grau": None, "observacoes": obs}

    return {"tipo": SEM_VINCULO, "processo_pai": None,
            "processo_pai_grau": None, "observacoes": obs}
