"""Coleta de UM processo: máquina de estados.

REGRA CENTRAL — só um NAO_ENCONTRADO explícito autoriza avançar de grau.
Queda de rede, página não reconhecida ou seleção irresolvível devolvem
erro_transitorio SEM tocar no grau seguinte. Se erro de rede fizesse avançar,
um processo de 1º grau cuja consulta caiu por Wi-Fi seria buscado no 2º grau,
encontrado lá e gravado com o GRAU ERRADO — contaminando em silêncio o
relacionamento que este orquestrador existe para consertar.

Esta função NÃO grava nada e NÃO conhece o banco. Ela devolve um resultado; quem
persiste é o orquestrador. EsajIndisponivelError (circuit breaker) atravessa
sem ser capturada: é parada geral, não falha deste processo.
"""

from collections import namedtuple

from .exceptions import EsajRequisicaoError
from .page_state import (
    ClassificadorPagina,
    EstadoPagina,
    Identidade,
    escolher_na_selecao,
    verificar_identidade,
)
from .parser_primeiro_grau import ParserPrimeiroGrau
from .parser_segundo_grau import ParserSegundoGrau
from ..status import (
    COLETADO,
    ERRO_TRANSITORIO,
    GRAU_INDETERMINADO,
    SEGREDO_JUSTICA,
    SEM_DADOS,
)

#: Derivado do atributo GRAU de cada parser — que assim deixa de ser decorativo.
#: Um dicionário escrito à mão aceitaria {1: ParserSegundoGrau} sem reclamar e
#: rodaria o parser errado em silêncio. Público de propósito: o spike importa
#: DESTE dicionário em vez de manter o seu.
PARSER_POR_GRAU = {P.GRAU: P for P in (ParserPrimeiroGrau, ParserSegundoGrau)}

#: grau 0 = indeterminado (não houve observação bem-sucedida).
ResultadoColeta = namedtuple("ResultadoColeta", "status grau bruto motivo")


def _erro(motivo, grau):
    """`grau` é o grau TENTADO, não observado — vai só para a mensagem.

    Obrigatório de propósito: o default nunca era usado, e um default aqui
    convidaria a esquecer o grau justamente no diagnóstico. A gravação continua
    em GRAU_INDETERMINADO: uma tentativa que falhou não é observação, e criar
    coluna para ela convidaria a tratá-la como se fosse.
    """
    return ResultadoColeta(ERRO_TRANSITORIO, grau, None, motivo)


def _capa_suspeita(completude):
    """Capa com classe/movimentações mas SEM partes é seletor quebrado, não
    processo sem partes. A validação antiga exigia que os QUATRO blocos
    estivessem vazios, então uma quebra só no seletor de partes passava e
    gravava o processo sem autores nem réus — invisível numa base de 500 mil.

    Falso positivo é tratado pelo contador de tentativas: após o teto, vira
    erro_persistente e vai para revisão manual em vez de girar para sempre.
    """
    if not completude.get("tem_partes"):
        if completude.get("tem_classe") or completude.get("tem_movimentacoes"):
            return "capa sem partes (possível seletor quebrado)"
        return "capa sem nenhum bloco extraído"
    return None


def coletar_um(np, client):
    """`np` é um NumeroProcesso. Devolve ResultadoColeta — nunca levanta
    exceção de rede comum (só EsajIndisponivelError, que é parada geral)."""
    for grau in np.graus_a_tentar:
        try:
            html = client.buscar(np, grau)
        except EsajRequisicaoError as erro:
            # NÃO tenta o próximo grau: não sabemos se o processo está aqui.
            return _erro(f"falha de rede no grau {grau}: {erro}", grau)

        estado = ClassificadorPagina(html).classificar()
        verificada = True  # busca direta: o próprio e-SAJ resolveu o número
        veio_de_selecao = False

        if estado == EstadoPagina.LISTA_SELECAO:
            escolha = escolher_na_selecao(html, np)
            if escolha.destino is None:
                # Antes isto virava registro vazio e, no orquestrador novo,
                # viraria 'sem_dados' PERMANENTE: "existe, mas não soube
                # escolher" gravado como "não existe".
                return _erro(f"seleção sem opção resolvível (grau {grau})", grau)
            verificada = escolha.verificada
            veio_de_selecao = True
            try:
                html = client.abrir_detalhe(escolha.destino, grau)
            except EsajRequisicaoError as erro:
                return _erro(f"falha ao abrir detalhe (grau {grau}): {erro}", grau)
            estado = ClassificadorPagina(html).classificar()

            if estado == EstadoPagina.LISTA_SELECAO:
                # Segunda tela de seleção. O tratamento seria o mesmo do ramo
                # final, mas o MOTIVO gravado diria "página não reconhecida" —
                # e esta página é reconhecida. Diagnóstico honesto importa: o
                # relatório de revisão manual é lido por humanos.
                return _erro(
                    f"segunda tela de seleção após abrir o detalhe (grau {grau})",
                    grau,
                )

        if estado == EstadoPagina.SENHA_SEGREDO:
            # Grau OBSERVADO é conhecido e não é sigiloso — vai junto.
            return ResultadoColeta(SEGREDO_JUSTICA, grau, None, None)

        if estado == EstadoPagina.DADOS_CAPA:
            identidade, achados = verificar_identidade(html, np)
            if identidade == Identidade.DIVERGE:
                return _erro(
                    f"identidade divergente (grau {grau}): a página traz "
                    f"{sorted(achados)}",
                    grau,
                )
            if identidade == Identidade.INDETERMINADO and not verificada:
                # Palpite na modal + página sem número conferível = risco de
                # gravar os dados de um processo sob o número de outro.
                return _erro(
                    f"escolha não verificada e identidade indeterminada "
                    f"(grau {grau})",
                    grau,
                )

            bruto = PARSER_POR_GRAU[grau](html).parse()
            suspeita = _capa_suspeita(bruto.get("completude") or {})
            if suspeita:
                return _erro(f"{suspeita} (grau {grau})", grau)
            return ResultadoColeta(COLETADO, grau, bruto, None)

        if estado == EstadoPagina.NAO_ENCONTRADO:
            if veio_de_selecao:
                # A tela de seleção já PROVOU que o processo existe neste grau.
                # Se a página aberta agora diz que não existe, o problema é do
                # destino (código de sessão expirado, link inválido) — não é
                # prova de ausência, e descer de grau produziria um registro com
                # o grau errado. Volta para a fila.
                return _erro(
                    f"a seleção resolveu um destino, mas a página aberta responde "
                    f"'não encontrado' (grau {grau}) — destino provavelmente expirado",
                    grau,
                )
            continue  # ÚNICO caminho que autoriza tentar o próximo grau

        # DESCONHECIDO: layout novo, bloqueio, captcha, manutenção.
        return _erro(f"página não reconhecida (grau {grau})", grau)

    # Todos os graus responderam NAO_ENCONTRADO explicitamente.
    return ResultadoColeta(SEM_DADOS, GRAU_INDETERMINADO, None, None)
