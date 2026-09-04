# Projeção do documento final – `src/transformers/projecao.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `src.transformers.limpeza`, `src.status` — sem dependências externas |

## Contexto e Motivação

Esta é a última transformação antes de o dado sair do projeto. Recebe uma linha do SQLite — com o dict bruto do parser dentro — e devolve o documento que vira uma linha do JSONL.

É aqui que a decisão registrada em [`parser_base`](../scrapers/parser_base.md) se paga. O parser guardou o texto como veio; este módulo é a **opinião** sobre aquele texto. Trocar a opinião — renomear um campo, mudar a estrutura de partes, aplicar outra regra de limpeza — é rodar a opção 4 de novo. Nenhuma requisição, nenhuma semana de recoleta.

O nome é literal no sentido de banco de dados: uma projeção é uma vista derivada de dados que continuam existindo em outro lugar. O SQLite é a fonte; o JSONL é a vista.

## Decisões de Arquitetura

- **`esqueleto`: todo registro tem os mesmos campos** — o documento nasce completo, com tudo em `None` ou vazio, e só depois é preenchido conforme o status permitir. Um sigiloso, um inexistente e um coletado têm a mesma forma; mudam os valores, não as chaves. Duas consequências: **a contagem fecha** (cada número da entrada produz uma linha, e `wc -l` é comparável com a lista original), e o consumo fica barato — no Mongo, conjuntos de chaves diferentes tornam qualquer agregação condicional; no pandas, colunas ausentes viram `NaN` com dtypes inconsistentes.
- **`_id` explícito torna a reimportação idempotente** — sem ele, cada `mongoimport` insere documentos com identificadores aleatórios, e reimportar depois de uma reprojeção **duplica a base inteira**, silenciosamente. O separador `__` codifica num escalar o par que no SQLite é chave composta.
- **Segredo de justiça suprime conteúdo, não topologia** — o bloco de relacionamento é preenchido **antes** do `if` que ramifica por status, e isso é deliberado. O sigilo protege partes, valor e movimentações; não protege o fato de que outro processo aponta para este. O argumento decisivo: **os filhos foram calculados a partir de outros registros**. Se A é sigiloso e B declara A como pai, essa informação está em B, que não é sigiloso. Zerar `processos_filhos` em A não esconderia nada e produziria um grafo assimétrico, em que quem percorre pelos filhos vê topologia diferente de quem percorre pelos pais.
- **Os filhos são sempre derivados, nunca gravados** — o banco guarda uma direção só. Não existe passo que "atualiza os filhos", logo não existe a possibilidade de eles divergirem dos pais — que é o defeito que o reconciliador anterior podia produzir. `set` dá dedup nativo, e `sorted(filhos)` garante que dois exports do mesmo banco produzam bytes idênticos.
- **`_ref` mantém número e grau separados, nunca concatenados** — gravar `"0000010-31.2013.8.26.0477 (grau 1)"` tornaria impossível consultar "todos os filhos de 1º grau" sem parsing. Como objeto, cada referência é filtrável e ligável ao `_id` correspondente.
- **O `else` se denuncia na própria base** — antes, o ramo final tratava qualquer status não reconhecido como `erro_persistente`: o registro saía com uma frase plausível e uma afirmação falsa. A escolha do canal importa: não há log a consultar num export que roda uma vez e produz milhões de linhas, mas há a base final, que é onde alguém vai olhar. Falhar alto, no lugar em que o problema será visto. Mesma lógica do `DESCONHECIDO` em [`page_state`](../scrapers/page_state.md).
- **Grau `0` volta a ser `null`** — o `0` é convenção interna do banco, necessária porque o SQLite aceita `NULL` em chave primária. Na base final não existe "grau zero" no Judiciário.
- **Só dois polos na base final** — `_grupo` descarta quem não está no polo pedido; não há grupo para `OUTRO`. A supressão é decisão de projeto (o recorte da pesquisa são os polos) e interage com uma escolha do parser: `'interessado'` foi **removido** do passivo por ser rótulo neutro e passou a cair em `OUTRO`. O parser preserva a categoria; a projeção a suprime.
- **Uma observação quando a supressão esvazia o documento** — no caso extremo em que **todas** as partes caem em `OUTRO`, o documento sai com autores e réus vazios, idêntico a uma capa sem partes, embora `completude["tem_partes"]` fosse verdadeiro e `_capa_suspeita` tenha aprovado a página justamente por haver partes. O registro passa por toda a rede de segurança e chega à base final aparentando o oposto do que foi observado. A observação não desfaz a supressão: impede que o documento **minta por omissão** e dá uma população recortável para auditar o classificador de polo.
- **Observações desduplicadas com ordem preservada** — vêm de duas origens (as de [`vinculo`](vinculo.md), anexadas ao bruto na coleta, e as que a projeção acrescenta por status) e podem repetir. O idioma aproveita que `set.add` devolve `None` para filtrar e registrar numa expressão só.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Omitir campos sem valor, produzindo documentos esparsos | Agregações no Mongo precisariam de condicional; no pandas, colunas ausentes viram `NaN` com dtypes inconsistentes. E a contagem deixaria de fechar por inspeção. |
| Deixar o Mongo gerar `_id` | Cada reimportação duplicaria a base inteira, sem erro. A reprojeção é operação frequente por design. |
| `_id` só com o número do processo | Colidiria os registros de 1º e 2º grau do mesmo número — a colisão que a chave composta existe para evitar. |
| Zerar o relacionamento em registros sigilosos | Não esconderia nada (a aresta está no registro do filho, que não é sigiloso) e produziria grafo assimétrico conforme a direção percorrida. |
| Gravar os filhos no banco, atualizando a cada coleta | Duas fontes de verdade para a mesma aresta. Era assim que o reconciliador anterior podia divergir do estado real. |
| Referência a outro processo como string concatenada | Impossibilitaria filtrar por grau sem parsing e quebraria a ligação com o `_id`. |
| `else` genérico rotulando status desconhecido como `erro_persistente` | Era o comportamento anterior: o dado saía plausível e errado, sem sinal em lugar nenhum. |
| Levantar exceção no `else` | Abortaria o export inteiro por causa de um registro. A observação preserva o restante da base e ainda denuncia o caso. |
| Manter `grau: 0` na base final | Expõe uma convenção interna do SQLite como se fosse dado do domínio. |
| Projetar `tipo_parte` (Exeqte, Reqdo…) na base final | Decisão do projeto: o polo é o que interessa para análise; o rótulo original permanece recuperável no bruto. |
| Criar um terceiro grupo `outros` nas partes | Mudaria o recorte da pesquisa para acomodar um caso que a observação já denuncia. |
| Suprimir o polo `OUTRO` sem observação nenhuma | O documento sai com autores e réus vazios, indistinguível de capa sem partes — apesar de ter sido aprovado por haver partes. |

## Limitações Conhecidas

- **Vários campos são renomeados entre o bruto e a base final,** sem que nada registre a correspondência:

  | Bruto (parser) | Base final (JSONL) |
  |---|---|
  | `assunto` | `assunto_principal` |
  | `valor` | `valor_acao` |
  | `movimentacoes[].descricao` | `movimentacoes[].movimento` |

- **`completude` não é projetado.** As três bandeiras ficam no bruto: a qualidade da extração não é auditável a partir do JSONL, só consultando o SQLite.
- **`origem` e `atualizado_em` são lidos do banco e descartados.** A base final não registra se o processo veio da lista de entrada ou foi descoberto como órfão, nem quando foi coletado.
- **`movimentacoes` só é preenchido para `coletado`.** Para os demais a lista fica vazia — correto, mas torna `movimentacoes: []` ambíguo entre "não há o que listar" e "capa sem movimentações".
- **`tipo_vinculo` é copiado sem validação.** `projetar` faz `reg.get("tipo_vinculo")` direto: um valor fora dos quatro do vocabulário sairia na base final sem sinal — ao contrário do `status`, que tem o ramo `else` para se denunciar. Ver [backlog §2](../../backlog.md).

## Exemplo de Uso

Função pura: não precisa de banco. Os casos são construídos escrevendo à mão o dicionário que `iter_exportaveis` devolveria.

```python
from src.transformers.projecao import inverter_filhos, projetar

mapa = inverter_filhos(store.vinculos())          # {(pai, grau) -> {(filho, grau), ...}}
doc = projetar(reg, mapa.get((reg["processo"], reg["grau"]), set()))

# {'_id': '10110499020188260066__1', 'processo': '10110499020188260066',
#  'grau': 1, 'status': 'segredo_justica',
#  'classe': None, 'partes': {'autores': {...}, 'reus': {...}},   <- conteúdo suprimido
#  'relacionamento': {'tipo': 'indefinido', 'processo_pai': None,
#                     'processos_filhos': [{'processo': '30000042520198260000',
#                                           'grau': 2}]},          <- topologia preservada
#  'observacoes': ['Processo em segredo de justiça: requer senha ...']}
```

O caso acima é real: está em `data/saida/teste1/base_final.jsonl`.

## Testes e Validação

Não há suíte automatizada. O módulo é puro e não precisa de banco, e `scripts/checar_offline.py` **não** o alcança: para no parser e no vínculo. A invariante de maior valor — um `segredo_justica` com filhos preserva `processos_filhos` — é observável em dado real no JSONL do projeto `teste1`. As 8 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os dois pontos em aberto resolvidos: polo `OUTRO` virou decisão documentada, `ultimo_erro` corrigido no store |
| 2026-08-11 | @alexandrehiero | Limitação do `tipo` não reprojetável reescrita: `reprojetar_vinculos` roda antes do export |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 9 decisões virou lista de tópicos; código copiado removido; invariantes migradas para o backlog de testes |
