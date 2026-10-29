"""Vocabulário de status da coleta — FONTE ÚNICA.

Antes existiam três declarações independentes das mesmas strings (coletor,
sqlite_store e projecao). Nada impedia que divergissem, e a divergência seria
silenciosa: um registro gravado com um valor que a projeção não reconhece cai
no ramo `else` e vira 'erro persistente' sem erro nenhum.

Este módulo é PROPOSITALMENTE neutro — sem imports do projeto. Se o vocabulário
morasse no `sqlite_store`, o `scrapers/coletor` passaria a depender da camada de
persistência, que ele não deve conhecer.
"""

#: Resultado observado com sucesso: a capa foi lida e analisada.
COLETADO = "coletado"
#: O e-SAJ exigiu senha. O GRAU é conhecido; o conteúdo, não.
SEGREDO_JUSTICA = "segredo_justica"
#: O e-SAJ afirmou explicitamente que o processo não existe. Resultado FINAL.
SEM_DADOS = "sem_dados"
#: Não foi possível perguntar (rede, layout, seleção irresolvível). Volta à fila.
ERRO_TRANSITORIO = "erro_transitorio"
#: Estourou o teto de tentativas: sai da fila automática, vai para revisão.
ERRO_PERSISTENTE = "erro_persistente"

#: Não voltam para a fila de recoleta.
STATUS_TERMINAIS = (COLETADO, SEGREDO_JUSTICA, SEM_DADOS, ERRO_PERSISTENTE)

#: Geram registro no JSONL. `erro_transitorio` é fila de trabalho, não resultado,
#: e por isso nunca chega ao export.
STATUS_EXPORTAVEIS = STATUS_TERMINAIS

#: Tentativas antes de promover erro_transitorio -> erro_persistente. Mora aqui,
#: e não no sqlite_store, porque é a REGRA DE TRANSIÇÃO entre dois status — não
#: um detalhe de persistência. É ela que faz a fila de falhas esvaziar em vez de
#: girar para sempre.
TETO_TENTATIVAS_PADRAO = 5

#: Grau indeterminado. Nunca NULL: o SQLite não impede NULL em PRIMARY KEY, e
#: como NULL != NULL a chave deixaria de barrar duplicatas.
GRAU_INDETERMINADO = 0

#: De onde veio o número.
ORIGEM_LISTA = "lista"
ORIGEM_ORFAO = "orfao"

#: Quanto cada status diz sobre o processo. A atualização da base nunca troca um
#: resultado por outro MENOS informativo: um coletado que volta como sem_dados é
#: mais provavelmente tropeço do e-SAJ do que processo que deixou de existir, e
#: substituí-lo apagaria a capa já coletada. Mora aqui pelo mesmo motivo do teto:
#: é regra de transição entre status, não detalhe de persistência.
INFORMATIVIDADE = {
    COLETADO: 3,
    SEGREDO_JUSTICA: 2,
    SEM_DADOS: 1,
    ERRO_PERSISTENTE: 0,
    ERRO_TRANSITORIO: 0,
}

#: Situação de um número na fila da atualização da base (opção 6 do menu).
#: Vocabulário à parte: a falha de uma atualização não vira status em `registro`,
#: porque ali ela apagaria ou duplicaria o dado que a atualização veio renovar.
ATUALIZACAO_PENDENTE = "pendente"
ATUALIZACAO_FEITA = "atualizado"
#: O e-SAJ respondeu algo menos informativo; o registro anterior foi mantido.
ATUALIZACAO_MANTIDA = "mantido"
#: Estourou o teto de tentativas; o registro anterior foi mantido.
ATUALIZACAO_DESISTIDA = "desistido"
