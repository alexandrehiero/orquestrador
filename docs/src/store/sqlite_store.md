# Checkpoint em SQLite – `src/store/sqlite_store.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `sqlite3`, `json`, `pathlib` (biblioteca padrão) |

## Contexto e Motivação

Uma coleta de centenas de milhares de processos a uma requisição a cada 1,7–2,5 s não é uma execução: é uma **campanha**, que atravessa dias, quedas de energia, suspensões do notebook e `Ctrl+C`. O que decide se ela termina não é a velocidade — é a qualidade do checkpoint.

Este módulo é a **fonte de verdade** do orquestrador. Os `.txt` que o [`menu`](../../scripts/menu.md) produz são views regeneradas a cada execução; apagar um deles não perde nada.

Três motivos sustentam SQLite em vez de arquivos soltos: transação (interrupção no meio de uma gravação faz rollback); retomada por chave indexada, sem varrer um diretório de centenas de milhares de entradas; e consultas de grafo — "quais pais citados não têm registro?" — que viram `LEFT JOIN` em vez de algoritmo em memória.

## Decisões de Arquitetura

- **Chave primária `(processo, grau)`** — o mesmo número existe nos dois graus. Chaveando só pelo número, o segundo registro sobrescreve o primeiro e o que se perde é uma **aresta**: origem e recurso ocupam a mesma chave. Foi essa colisão que embaralhou o relacionamento no pipeline anterior.
- **Grau `0` para o indeterminado, nunca `NULL`** — o SQLite aceita `NULL` em chave primária e `NULL != NULL`, então a chave deixaria de barrar duplicatas nos registros sem observação, que são os mais reprocessados. A [projeção](../transformers/projecao.md) devolve `null` no JSONL.
- **O vocabulário de status vem de fora** — [`src/status.py`](../status.md) diz quais são os estados; este módulo diz o que cada um autoriza a fazer com o banco.
- **`registrar_resultado` é o único ponto que valida o status** — gravar `erro_transitorio` por ele é erro de programação, não condição de execução, e levanta `ValueError`.
- **A linha de grau 0 é removida na MESMA transação** — a tentativa que falhou grava `(N, 0, erro)`; a recoleta acerta e grava `(N, 1, coletado)`. Sem o `DELETE`, as duas coexistem e ambas viram linha no JSONL quando a de grau 0 chega a `erro_persistente`.
- **Erro sempre em grau 0: tentativa não é observação** — o coletor sabe em que grau falhou e o store descarta isso de propósito; gravar `(N, 1, erro)` afirmaria uma existência de 1º grau não observada. O grau tentado fica só no texto de `ultimo_erro`.
- **A promoção a `erro_persistente` é o que esvazia a fila** — sem teto, uma falha permanente volta à fila indefinidamente e o arquivo de falhas nunca chega a zero, que é a única métrica de conclusão.
- **`reprojetar_vinculos` devolve a coluna derivada ao domínio do reprocessável** — `tipo_vinculo` e `processo_pai` vivem em coluna porque `orfaos()` e `vinculos()` são SQL sobre eles; sem esta função, corrigir uma regra exigiria **recoletar**. Não é hipótese: após a mudança do padrão sem bruto para `INDEFINIDO`, os `segredo_justica` já gravados continuavam saindo com `sem_vinculo`, e recoletá-los não traria conteúdo nenhum.
    - **Sem bruto, o tipo é o que o chamador disser** — `derivar` e `tipo_sem_bruto` são parâmetros: a persistência não importa `transformers.vinculo`, pela disciplina que mantém `status.py` neutro.
    - **Guarda por versão da regra** — se `versao_regra_vinculo` em `meta` já for o da regra atual e `forcar` for falso, retorna `{"pulado": True}` sem ler nada; senão toda opção 4 releria o `bruto` da base inteira à toa.
    - **Paginação por chave, não `OFFSET`** — `OFFSET n` produz e descarta `n` linhas por lote, tornando a varredura quadrática; `(processo, grau) > (último lido)` usa o índice. O cursor começa em `("", -1)`.
    - **Ler o lote antes de escrever** — `UPDATE` na tabela que um `SELECT` itera tem comportamento indefinido no SQLite; o `.fetchall()` de 500 linhas elimina a questão.
    - **Só grava o que mudou** — preserva o sentido de `atualizado_em`. Quando grava, reescreve também `bruto["observacoes"]`, senão o tipo novo conviveria com as observações da regra antiga.
    - **A reprojeção vem antes do export** — `orfaos()` e o mapa de filhos leem as colunas; exportar antes produziria uma base coerente com a regra **antiga**.
- **WAL e `synchronous = FULL`** — inverte o trade-off usual porque não há o que ganhar: o gargalo é a rede e o `fsync` cai numa espera de segundos, enquanto cada commit perdido é uma requisição a refazer. `isolation_level=None` deixa os `with self.con:` como as únicas transações.
- **A ausência de `FOREIGN KEY` é a decisão, não um esquecimento** — uma FK rejeitaria todo filho cujo pai ainda não foi coletado, que é a definição de órfão; o ciclo 4 → 3 → 4 não teria como começar. A referência pendente é o **insumo** da etapa seguinte.
- **Recusa a abrir banco em pasta sincronizada** — OneDrive e similares copiam `.db` e `-wal` em momentos diferentes e produzem banco incoerente **sem erro**. A checagem é heurística, com escape via `permitir_pasta_sincronizada=True`.
- **`iter_exportaveis` é gerador, não lista** — materializar 500 mil registros foi o que inviabilizou o consolidador anterior. O `SELECT` inclui `ultimo_erro` porque a projeção o consome; sem a coluna, a causa da falha nunca chegava ao JSONL apesar de estar no banco.
- **`orfaos()` casa por "não tem REGISTRO", não "não tem dados"** — `sem_dados` é visita concluída e sai da lista para sempre. É o que faz o ciclo 4 → 3 → 4 **convergir**.
- **O casamento do órfão é pelo NÚMERO, não pelo par** — `coletar_um` recebe um número e decide o grau sozinho, então "colete `N` no grau 1" é instrução que ele não sabe obedecer. As três granularidades do ciclo concordam.
- **`vinculos()` devolve uma direção só (filho → pai)** — os filhos são a inversão disto, calculada no export. Gravar as duas criaria duas fontes de verdade para a mesma aresta, que era como o reconciliador antigo divergia.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Um arquivo JSON por processo, ou shards | A retomada exige listar centenas de milhares de arquivos a cada execução; sem transação, uma interrupção deixa arquivo truncado. |
| CSV incremental com append | Sem chave, sem índice e sem transação. Descobrir o que já foi feito exige ler o arquivo inteiro; uma linha parcial no fim corrompe o parsing. |
| Postgres ou outro banco servidor | Exigiria instalação e serviço rodando para um projeto que precisa ser reproduzível num notebook. O SQLite é arquivo. |
| Chave primária só no número do processo | O mesmo número existe em 1º e 2º grau; o segundo sobrescreve o primeiro e a aresta entre origem e recurso passa a apontar para o lugar errado. |
| `NULL` para grau desconhecido | O SQLite aceita `NULL` em PRIMARY KEY, e `NULL != NULL` — a chave pararia de barrar duplicatas nos registros mais reprocessados. |
| `synchronous = NORMAL` ou `OFF` | Trocaria durabilidade por velocidade que não se converte em nada: o gargalo é a rede, e cada commit perdido é uma requisição a refazer. |
| Gravar o erro no grau em que a tentativa falhou | Afirmaria uma existência que não foi observada. Falhar ao consultar um grau não é observar aquele grau. |
| Sem teto de tentativas | A fila da opção 2 nunca esvazia: falhas permanentes giram indefinidamente e o pesquisador perde a métrica de conclusão. |
| Gravar também a aresta pai → filho | Duas fontes de verdade para a mesma relação, que precisariam ser reconciliadas. A inversão no export é derivada e não pode divergir. |
| Casar órfãos pelo par `(processo, grau)` | Reportaria como órfão permanente todo número coletado num grau e citado como pai no outro: a opção 3 o descartaria e a 4 voltaria a listá-lo. |
| Uniformizar as três etapas no **par** | Não resolveria: `coletar_um` recebe um número e decide o grau sozinho. A granularidade pedida não existe na coleta. |
| Declarar `FOREIGN KEY (processo_pai)` | Rejeitaria a gravação de todo filho cujo pai ainda não foi coletado — a definição de órfão. O ciclo 4 → 3 → 4 não teria como começar. |
| Manter o `PRAGMA foreign_keys = ON` | Sem FK no esquema, o pragma não fazia nada além de sugerir uma garantia inexistente a quem lesse o código. |
| `iter_exportaveis` devolvendo lista | Materializar todos os registros em memória foi o que inviabilizou o consolidador anterior. |
| Omitir `ultimo_erro` do `SELECT` de export | A projeção consome a chave. Sem ela, todo `erro_persistente` sai da base final com a frase genérica e sem a causa, que está no banco. |
| Deixar o vínculo só na coleta e recoletar quando a regra mudar | Gastaria requisições para reprocessar dado que já está no banco — e para `segredo_justica` a recoleta nem traria conteúdo novo. |
| Derivar o vínculo na projeção, sem coluna | `orfaos()` e `vinculos()` deixariam de ser SQL: descobrir órfãos exigiria carregar e derivar a base inteira em memória. |
| Reprojetar em toda opção 4, sem guarda de versão | Pagaria a leitura do `bruto` da base inteira mesmo sem mudança de regra, dobrando o tempo do export local. |
| `LIMIT/OFFSET` para paginar a reprojeção | O SQLite produz e descarta as `n` linhas anteriores a cada lote; a varredura completa vira quadrática. |
| `UPDATE` dentro do laço que itera o `SELECT` da mesma tabela | Comportamento indefinido: a linha alterada pode reaparecer, sumir ou ser visitada duas vezes conforme o plano de consulta. |
| Atualizar só as colunas de vínculo na reprojeção | Deixaria o tipo novo convivendo com as observações da regra antiga, gravadas dentro do `bruto` pela coleta. |
| Regravar todas as linhas na reprojeção | Reescreveria a base inteira para mudar poucos registros e destruiria o significado de `atualizado_em`. |
| `SqliteStore` importar `derivar_vinculo` | Faria a persistência depender das regras de derivação. `derivar` e `tipo_sem_bruto` entram como parâmetros. |
| Store thread-safe, com lock de escrita | Mais código e mais risco. Workers fazem rede, a thread principal grava — mesmo resultado sem sincronização. |
| Apenas avisar sobre pasta sincronizada, sem bloquear | O modo de falha é silencioso e o custo é a coleta inteira. O bloqueio com escape força a decisão consciente. |

## Limitações Conhecidas

- **Não é thread-safe, por decisão.** A conexão é criada numa thread e usada por ela; o [`menu`](../../scripts/menu.md) garante que só a thread principal grava.
- **`bruto` é JSON numa coluna TEXT.** Consultar por conteúdo exige `json_extract` — o preço de guardar um dict de estrutura variável sem impor esquema.
- **`ultimo_erro` é truncado em 500 caracteres.** Tracebacks encadeados e listas de CNJs perdem o final.
- **`contagem_por_grau` não fecha com `total()`.** Conta só `coletado` e `segredo_justica`, os únicos com grau observado; a docstring do método declara isso.
- **`numeros_finalizados()` devolve números, não pares.** É a granularidade escolhida para o ciclo, não uma inconsistência: a coleta não sabe operar por par.
- **Um pai que existe só no OUTRO grau vira referência a um nó ausente.** O JSONL fica com um `processo_pai` que nenhum `_id` resolve; o diagnóstico sai em `orfaos_diagnostico.txt`, com `graus_citados`.
- **A primeira reprojeção altera registros de erro já publicados.** Linhas com `bruto` nulo recebem `tipo_sem_bruto`, então `tipo_vinculo` passa de `NULL` a `indefinido` — e `erro_persistente` é exportável.
- **`backup()` existe mas nenhum script o chama.** Usa `VACUUM INTO`; depende de o pesquisador chamá-lo manualmente.
- **O esquema não tem versionamento nem migração.** `CREATE TABLE IF NOT EXISTS` cria o que falta mas não altera o que existe.

## Exemplo de Uso

```python
from src.store.sqlite_store import SqliteStore
from src.transformers.vinculo import INDEFINIDO, VERSAO_REGRA, derivar_vinculo

with SqliteStore("C:/dados_coleta/projeto.db") as store:   # levanta PastaSincronizadaError
    fila = [n for n in validos if n not in store.numeros_finalizados()]   # retomada
    store.registrar_erro(numero, motivo)                   # -> erro_transitorio | erro_persistente
    store.registrar_resultado(numero, grau, status, bruto=bruto, tipo_vinculo=v["tipo"])

    rep = store.reprojetar_vinculos(derivar_vinculo, INDEFINIDO, VERSAO_REGRA)
    print(rep)                          # {'vistos': 9, 'alterados': 0, 'pulado': False}
    for reg in store.iter_exportaveis():                   # streaming, memória constante
        ...
```

## Testes e Validação

Não há suíte automatizada. A validação em uso é operacional: o `menu` imprime `total()` e `contagem_por_status()` ao fim de cada execução. O módulo é testável sem rede e sem arquivo com `SqliteStore(":memory:")`. As 15 invariantes que valeria fixar estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os quatro pontos em aberto viraram correção de código; registrados como decisões |
| 2026-08-11 | @alexandrehiero | `reprojetar_vinculos`: a coluna de vínculo deixa de exigir recoleta para ser corrigida |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas). Corrigidas três afirmações que o código já contradizia: a reprojeção **tem** guarda por versão, **reescreve** `bruto["observacoes"]`, e sua assinatura inclui `versao` e `forcar` |
