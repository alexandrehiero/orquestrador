# Checkpoint em SQLite – `src/store/sqlite_store.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `sqlite3`, `json`, `pathlib`, `datetime` (biblioteca padrão); `src.status` |

## Contexto e Motivação

Uma coleta de centenas de milhares de processos a uma requisição a cada 1,7–2,5s não é uma
execução: é uma **campanha**, que atravessa dias, quedas de energia, suspensões do
notebook e `Ctrl+C`. O que decide se ela termina não é a velocidade — é a qualidade do
checkpoint.

A docstring enuncia os três motivos da escolha:

> Por que SQLite e não shards em disco:
>
>   - ACID: interrupção no meio de uma gravação faz rollback; nunca há estado
>     corrompido. Numa coleta de semanas isso deixa de ser conforto.
>   - Retomada O(1) por chave indexada, sem varrer diretório com centenas de
>     milhares de arquivos.
>   - As consultas de grafo (órfãos, filhos) viram SQL em vez de carregar a base
>     inteira em memória.

Vale desdobrar o segundo. A alternativa natural — um arquivo JSON por processo, ou shards
de alguns milhares — parece mais simples até a primeira retomada. Para saber o que já foi
feito, é preciso listar o diretório inteiro: centenas de milhares de entradas, num sistema
de arquivos, a cada execução. Com índice, a mesma pergunta é uma consulta que não depende
do tamanho da base. E o terceiro motivo só existe porque o primeiro e o segundo existem:
uma vez que os dados estão num banco relacional, "quais pais citados não têm registro
próprio" vira um `LEFT JOIN` em vez de um algoritmo.

Este módulo é a **fonte de verdade** do orquestrador. Os arquivos `.txt` que o
[`menu`](../../scripts/menu.md) produz são views regeneradas a cada execução; se um deles
for apagado, nada se perde.

## Decisões de Arquitetura

### Chave primária `(processo, grau)`

```sql
PRIMARY KEY (processo, grau)
```

> Chave: (processo, grau). O MESMO número pode existir em 1º e 2º grau — foi a
> colisão dessa chave que embaralhou o relacionamento no pipeline anterior.

Um processo que sobe em recurso pode aparecer nas duas instâncias do e-SAJ. Chaveando só
pelo número, o segundo registro sobrescreve o primeiro — e o que se perde não é uma linha,
é uma **aresta**: o vínculo entre a origem e o recurso passa a apontar para o lugar
errado, porque origem e recurso ocupam a mesma chave. Foi essa colisão que embaralhou o
relacionamento no pipeline anterior.

Com a chave composta, `(N, 1)` e `(N, 2)` são registros distintos e o
[`vinculo`](../transformers/vinculo.md) pode criar uma aresta de um para o outro.

### Grau `0` para o indeterminado, nunca `NULL`

> 1 / 2  -> grau OBSERVADO (a página respondeu em cpopg / cposg)
> 0      -> indeterminado (sem_dados, erro) — projetado como null no JSONL.
>           Nunca NULL: SQLite não impede NULL em PRIMARY KEY, e como
>           NULL != NULL a chave deixaria de barrar duplicatas.

O SQLite difere de outros bancos aqui: ele **aceita** `NULL` numa coluna de chave
primária. Como `NULL != NULL` na semântica SQL, duas linhas com grau nulo não colidem — e
a chave deixaria de barrar duplicatas exatamente nos registros em que nada foi observado,
que são os mais reprocessados. O detalhamento está em [`status`](../status.md), onde
`GRAU_INDETERMINADO` é declarado.

O `0` é convenção interna: a [`projeção`](../transformers/projecao.md) o converte de volta
em `null` no JSONL, para que a base final não exponha um grau que não existe.

### O vocabulário de status vem de fora

```python
# Vocabulário de status: FONTE ÚNICA em src/status.py. Este módulo declarava as
# mesmas strings que o coletor e a projeção — três cópias que nada impedia de
# divergir, e cuja divergência seria silenciosa.
from ..status import (
    COLETADO,
    ERRO_PERSISTENTE,
    ...
)
```

Este módulo **usa** o vocabulário; quem o define é [`src/status.py`](../status.md). A
divisão importa: o `status.py` diz quais são os estados, o `sqlite_store` diz o que cada
um autoriza a fazer com o banco.

### O único ponto que valida o status gravado

```python
if status not in STATUS_TERMINAIS:
    raise ValueError(f"Status não terminal em registrar_resultado: {status!r}")
```

`registrar_resultado` é para desfechos definitivos. Tentar gravar `erro_transitorio` por
ele é erro de programação, não condição de execução — daí a exceção, que sobe em vez de
virar mais uma linha no banco.

### A limpeza da linha de grau 0, na mesma transação

```python
if grau != GRAU_INDETERMINADO:
    self.con.execute(
        "DELETE FROM registro WHERE processo = ? AND grau = ?",
        (processo, GRAU_INDETERMINADO),
    )
```

> Remove, na MESMA transação, a linha de grau indeterminado que o mesmo
> número possa ter deixado numa tentativa anterior que falhou — senão o
> processo apareceria duas vezes na base final.

Este é o detalhe que faz a recoleta funcionar sem duplicar. O ciclo é: a primeira tentativa
falha e grava `(N, 0, erro_transitorio)`; a opção 2 tenta de novo e agora dá certo,
gravando `(N, 1, coletado)`. Sem o `DELETE`, as duas linhas coexistem e **as duas** são
exportáveis quando a de grau 0 já tiver virado `erro_persistente` — o mesmo processo
apareceria duas vezes no JSONL, uma como coletado e outra como falha.

Estar na mesma transação (`with self.con:`) é o que garante que não exista um instante em
que o `INSERT` valeu e o `DELETE` não.

### Erro sempre em grau 0: tentativa não é observação

```python
self.con.execute(
    """INSERT INTO registro ...
       VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
       ...""",
    (processo, GRAU_INDETERMINADO, status, tentativas,
     str(erro)[:500], origem, _agora()),
)
```

O [`coletor`](../scrapers/coletor.md) sabe em qual grau a falha ocorreu e transporta essa
informação no `ResultadoColeta`. O store a descarta de propósito: **falhar ao consultar um
grau não é observar aquele grau**. Gravar `(N, 1, erro)` afirmaria que o processo tem uma
existência de 1º grau, que é justamente o que não se sabe. O grau da tentativa sobrevive
apenas dentro do texto de `ultimo_erro`, como contexto para leitura humana.

É a mesma disciplina da regra central do coletor, aplicada à persistência: só se grava
grau quando houve resposta.

### A promoção a `erro_persistente` é o que esvazia a fila

```python
tentativas = (linha["tentativas"] if linha else 0) + 1
status = ERRO_PERSISTENTE if tentativas >= teto_tentativas else ERRO_TRANSITORIO
```

> Incrementa tentativas; ao estourar o teto vira erro_persistente e
> sai da fila automática, indo para revisão manual — é isso que faz o
> arquivo de falhas ESVAZIAR em vez de girar para sempre.

Sem o teto, um processo que falha por motivo permanente (capa realmente sem partes, layout
que nunca será reconhecido) volta à fila da opção 2 indefinidamente, e o arquivo de falhas
nunca chega a zero — o pesquisador perde a única métrica que diz se a coleta terminou.

`registrar_erro` devolve o status resultante, e é isso que o `menu` contabiliza no resumo
da execução.

### `reprojetar_vinculos`: a coluna derivada volta a ser reprocessável

Esta é a correção que restaura a promessa central do projeto, e o motivo dela é
arquitetural — não é uma conveniência.

```python
def reprojetar_vinculos(self, derivar, tipo_sem_bruto, log=None):
    """Recalcula tipo_vinculo/processo_pai a partir do BRUTO já gravado.

    Por que existe: `tipo_vinculo` e `processo_pai` são os únicos valores
    derivados que vivem em COLUNA, não na projeção. A coluna é necessária —
    orfaos() e vinculos() são SQL sobre ela — mas sem esta reprojeção mudar
    a regra de derivação exigiria RECOLETAR, quebrando a promessa de que o
    bruto é a verdade e todo o resto é reprocessável localmente.
    """
```

O projeto inteiro se apoia numa separação: o `bruto` é o que foi **observado**, e tudo o
mais é **opinião** sobre ele. Trocar uma opinião custa uma opção 4; o que exige rede é
observar de novo. [`limpeza`](../transformers/limpeza.md) e
[`projecao`](../transformers/projecao.md) respeitam isso por construção, porque rodam no
export a partir do bruto guardado.

O vínculo era a exceção — e não por descuido. `orfaos()` e `vinculos()` são consultas SQL
sobre `processo_pai`: para o grafo ser consultável no banco, o resultado da derivação
**precisa** estar em coluna. Só que colunas são gravadas, e o que gravava era a coleta.
Corrigir uma regra de `derivar_vinculo` valia apenas para o que fosse coletado dali em
diante; o já coletado ficava com a regra do dia em que passou pela rede.

Isso deixou de ser hipótese: depois da correção que trocou o padrão sem bruto para
`INDEFINIDO`, os registros `segredo_justica` do `data/saida/teste1/base_final.jsonl`
continuavam saindo com `"tipo": "sem_vinculo"`. O código estava certo e a base, errada — e
não havia como consertá-la sem gastar requisições contra o portal por processos cujo
conteúdo é sigiloso.

`reprojetar_vinculos` fecha o buraco sem abrir mão da coluna: relê o bruto, chama a mesma
função de derivação e regrava as três colunas. A coluna continua sendo coluna; ela só deixa
de ser a **origem** do valor para voltar a ser um **cache consultável** dele.

#### Sem bruto, o tipo é o que o chamador disser

```python
if bruto:
    v = derivar(bruto, linha["grau"], linha["processo"])
else:
    v = {"tipo": tipo_sem_bruto,
         "processo_pai": None, "processo_pai_grau": None}
```

> Registros sem bruto (segredo, sem_dados) recebem `tipo_sem_bruto`: a
> coleta nunca viu a capa, então afirmar 'sem vínculo' seria afirmar sobre
> o que não foi observado.

É a mesma regra que o `menu` aplica na coleta, agora nos dois caminhos que escrevem a
coluna. Repare que `derivar` e `tipo_sem_bruto` são **parâmetros**: o store não importa
`src.transformers.vinculo`. É a mesma disciplina de camadas que mantém
[`status`](../status.md) neutro — a persistência não precisa conhecer as regras de
derivação, só precisa saber reaplicá-las.

#### Paginação por chave, não por `OFFSET`

```sql
WHERE (processo, grau) > (?, ?)
ORDER BY processo, grau
LIMIT 500
```

`LIMIT 500 OFFSET n` parece o jeito óbvio de percorrer a base em lotes, e é o jeito caro: o
SQLite precisa **produzir e descartar** as `n` linhas anteriores a cada lote, o que torna a
varredura completa quadrática. Com a comparação de tupla `(processo, grau) > (último lido)`,
cada lote começa exatamente onde o anterior parou, usando o índice da chave primária — custo
constante por lote, independentemente de quantas linhas já passaram.

O par `("", -1)` inicia o cursor: qualquer processo real é maior que a string vazia.

#### Ler o lote inteiro antes de escrever

O `.fetchall()` não é acidental:

> Paginação por CHAVE (não OFFSET, que é O(n) a cada lote) e leitura antes
> da escrita: alterar linhas enquanto um SELECT da mesma tabela é iterado
> tem comportamento indefinido no SQLite.

Iterar um cursor e fazer `UPDATE` na mesma tabela dentro do laço é justamente o caso em que a
documentação do SQLite não garante nada: a linha alterada pode reaparecer, sumir ou ser
visitada duas vezes, dependendo de como o plano de consulta percorre o índice. Materializar
500 linhas primeiro e só então escrever elimina a questão — e 500 linhas é um lote pequeno o
bastante para a memória não ser argumento.

#### Só grava o que mudou

```python
if novo != atual:
```

Numa base de centenas de milhares de registros em que a regra mudou para poucos, isto é a
diferença entre reescrever tudo e reescrever o necessário. E preserva o significado de
`atualizado_em`: a coluna continua marcando quando aquele registro **mudou**, não quando o
último export passou por ele. O retorno `{"vistos", "alterados"}` deixa a diferença visível
no console.

Cada lote é uma transação (`with self.con:`). Interromper no meio deixa a base
metade-reprojetada, e isso é seguro: a derivação é função pura do bruto, então rodar de novo
termina o serviço e produz o mesmo resultado.

#### A ordem no `menu` faz parte da correção

```python
def opcao_4(store):
    """Local, sem rede. Reprojeta vínculos, exporta o JSONL e recalcula órfãos.

    A reprojeção vem PRIMEIRO porque orfaos() e o mapa de filhos são calculados
    a partir das colunas de vínculo: exportar antes de reprojetar produziria uma
    base final coerente com a regra ANTIGA de derivação.
    """
```

`inverter_filhos(store.vinculos())` e `orfaos()` leem as colunas. Reprojetar depois do
export produziria um JSONL e uma lista de órfãos calculados sobre o estado anterior —
silenciosamente desatualizados por exatamente uma execução.

### WAL e `synchronous = FULL`

```python
# WAL: tolera bem suspensão do notebook e é mais rápido em escrita
# sequencial. FULL: fsync a cada commit — a ~3,5s por processo o custo é
# irrelevante e protege contra queda de energia/bateria.
self.con.execute("PRAGMA journal_mode = WAL")
self.con.execute("PRAGMA synchronous = FULL")
self.con.execute("PRAGMA busy_timeout = 30000")
```

A escolha de `FULL` inverte o trade-off usual. Normalmente troca-se durabilidade por
velocidade; aqui não há o que ganhar, porque o gargalo é a rede — o `fsync` acontece uma
vez a cada vários segundos de espera. E o que se protege é caro: cada commit perdido é uma
requisição que terá de ser refeita contra um portal público.

`isolation_level=None` desliga o gerenciamento implícito de transação do módulo `sqlite3`,
deixando os blocos `with self.con:` como as únicas transações — explícitas e do tamanho
exato de uma gravação.

### A ausência de `FOREIGN KEY` é a decisão, não um esquecimento

O que fecha o método `_configurar` não é mais um pragma, e sim a explicação de um pragma que
saiu:

```python
# Sem PRAGMA foreign_keys: o schema NÃO declara FK de propósito.
# processo_pai aponta para um processo que legitimamente pode ainda não
# ter sido coletado — é exatamente essa a definição de órfão. Uma FK
# rejeitaria a gravação do filho e quebraria o ciclo 4 -> 3 -> 4.
```

Havia antes um `PRAGMA foreign_keys = ON` que não tinha efeito nenhum: o esquema não declara
nenhuma `FOREIGN KEY`, e o pragma só liga a checagem das que existem. Ele era inofensivo em
execução e enganoso na leitura — prometia uma garantia de integridade referencial que o banco
não dá.

O ponto é que a garantia **não deve** ser dada. Uma FK de `processo_pai` para `processo`
rejeitaria a gravação de todo filho cujo pai ainda não foi coletado — que é a situação normal
e frequente: o filho é justamente por onde se descobre a existência do pai. Com FK, o ciclo
4 → 3 → 4 não teria como começar, porque a aresta que produz a lista de órfãos nunca chegaria
a ser gravada. A referência pendente não é uma inconsistência a impedir; é o **insumo** da
etapa seguinte, e `orfaos()` existe para consultá-la.

O que sobra é convenção mantida por índice (`idx_registro_pai`) e por um único escritor
(`derivar_vinculo`), que valida o DV antes de criar a aresta — a checagem que faz sentido
aqui, e que uma FK não faria.

### A recusa a rodar em pasta sincronizada

```python
class PastaSincronizadaError(RuntimeError):
    """O .db está dentro de pasta de sincronização — risco de corrupção."""
```

```python
def _detectar_pasta_sincronizada(caminho):
    """Devolve o nome da pasta suspeita, ou None. Clientes de sync copiam o .db
    e o -wal em momentos diferentes, produzindo um banco incoerente SEM erro."""
```

Esta é uma decisão de produto, não de engenharia: o projeto vive numa pasta do OneDrive, e
o modo de falha é silencioso. O cliente de sincronização copia `.db` e `-wal` em momentos
diferentes; o resultado é um banco internamente incoerente que **não emite erro** — semanas
de coleta perdidas sem aviso.

A mensagem é escrita para quem vai ler no meio de um problema, e oferece a saída:

> Mova o banco para um disco local (ex.: C:/dados_coleta/) ou, se tiver certeza, use
> permitir_pasta_sincronizada=True.

A checagem é heurística (nome de pasta contra uma lista de serviços conhecidos) e tem
escape explícito, para não bloquear quem sabe o que está fazendo.

### Streaming obrigatório na leitura para export

```python
def iter_exportaveis(self):
    """Itera em STREAMING os registros que vão para o JSONL.

    Streaming é obrigatório: materializar 500 mil registros numa lista foi
    exatamente o que inviabilizou o consolidador anterior.
    """
```

O método é um gerador: o cursor do SQLite entrega linha a linha e o `bruto` é
desserializado uma de cada vez. É a metade do par que mantém a memória constante no export
— a outra está no [`exportador`](../aggregators/exportador.md).

O `SELECT` traz dez colunas, e a décima foi acrescentada depois:

```sql
SELECT processo, grau, status, bruto, ultimo_erro, processo_pai,
       processo_pai_grau, tipo_vinculo, origem, atualizado_em
```

`ultimo_erro` está aí porque a [`projeção`](../transformers/projecao.md) o consome no ramo
de `erro_persistente` (`if reg.get("ultimo_erro")`). Sem a coluna no `SELECT`, a chave
simplesmente não existia no dicionário devolvido, o `.get` respondia `None` e a observação
**nunca** era escrita: todo registro `erro_persistente` saía no JSONL com a frase genérica
`"Não foi possível coletar após as tentativas previstas."` e nenhuma informação sobre a
causa — que estava no banco o tempo todo, e chegava a `revisao_manual.txt` por outro caminho
(`numeros_com_erro_persistente`, que sempre incluiu a coluna). O dado existia, o consumidor
existia, e faltava a linha que ligava os dois.

A coluna vem para **todos** os status, não só para os de falha, e isso não polui os demais:
`registrar_resultado` zera `ultimo_erro` no `ON CONFLICT DO UPDATE`, de modo que um processo
que falhou algumas vezes e depois foi coletado não carrega o erro antigo para a base final.

### As duas consultas de grafo

```python
def orfaos(self):
    """Pais citados por algum registro que NÃO têm registro NENHUM.

    Critério 1 — 'não tem REGISTRO', não 'não tem dados'. Um processo
    gravado como sem_dados JÁ foi visitado e sai da lista para sempre.
    """
```

O primeiro critério é a diferença entre um ciclo que converge e um que não converge. Se
órfão fosse "pai sem dados", um processo que o e-SAJ afirma não existir seria reportado para
sempre: a opção 3 o coletaria, o resultado seria `sem_dados` de novo, e a opção 4 voltaria a
listá-lo. Como o critério é "não tem **registro**", `sem_dados` é uma visita concluída e o
número sai da lista definitivamente.

### O casamento do órfão é pelo NÚMERO, não pelo par `(processo, grau)`

Este é o segundo critério, e ele parece contradizer a chave composta que o resto do módulo
defende. Não contradiz: são perguntas diferentes.

```sql
LEFT JOIN registro p
       ON p.processo = f.processo_pai
```

> Critério 2 — casamento pelo NÚMERO, não pelo par (processo, grau).
> Parece uma perda de precisão e é o contrário: a coleta opera por NÚMERO
> (o coletor decide o grau sozinho, pela origem do CNJ), e
> `numeros_finalizados()` também.

O argumento que decide é o que a etapa seguinte sabe fazer. A saída desta consulta vira
`orfaos.txt`, que vira a fila da opção 3, que chama `coletar_um` — e `coletar_um` recebe um
número e **escolhe o grau sozinho**, por `np.graus_a_tentar`, derivado da origem do CNJ.
"Colete `N` no grau 1" é uma instrução que o coletor não sabe obedecer. Uma lista de órfãos
com grau seria, portanto, precisão que ninguém consegue consumir.

E casar pelo par produzia o oposto do que a docstring promete. Um número coletado no grau 2 e
citado como pai no grau 1 seria reportado como órfão; a opção 3 o descartaria por
`numeros_finalizados()` já o dar como finalizado; a opção 4 voltaria a listá-lo — para
sempre, em toda execução. Uniformizar tudo no **par** não resolveria, porque o problema não
está na consulta: está em pedir à coleta uma granularidade que ela não tem.

Com a mudança, as três granularidades do ciclo concordam:

| Etapa | Granularidade |
|---|---|
| `orfaos()` | número (`ON p.processo = f.processo_pai`, `GROUP BY f.processo_pai`) |
| `escrever_lista_orfaos` | número (grava `f"{o['processo']}\n"`) |
| `numeros_finalizados()` | número (`SELECT DISTINCT processo`) |

A limitação que vem junto está assumida em voz alta na própria docstring:

> Limitação assumida: quando o pai existe só no OUTRO grau, a referência
> aponta para um nó ausente da base. Isso é inconsistência de dado a
> relatar, não trabalho de coleta — recoletar devolveria a mesma resposta.
> `graus_citados` fica na saída para permitir esse diagnóstico.

É uma reclassificação honesta do problema, não uma varredura para baixo do tapete. Se `(N, 1)`
é citado como pai e só existe `(N, 2)`, mandar a opção 3 coletar `N` não muda nada — o
coletor voltaria a resolver para o grau 2, que já está lá. O que resta é um relatório: a
aresta aponta para um nó que a base não tem. Por isso a consulta mantém

```sql
GROUP_CONCAT(DISTINCT f.processo_pai_grau) AS graus_citados
```

— a coluna existe para permitir esse diagnóstico (em que grau aquele pai foi citado),
comparando-a com o grau efetivamente presente no banco.

### `vinculos()`: uma direção só

```python
def vinculos(self):
    """Arestas filho -> pai. Os FILHOS da base final são a inversão disto —
    derivados, nunca gravados por um passo separado (que era como o
    reconciliador antigo podia divergir do estado real)."""
```

O banco guarda **só** a aresta filho → pai. A lista de filhos de cada processo é calculada
na hora do export, invertendo estas arestas. Guardar as duas direções criaria duas fontes
de verdade que precisariam ser reconciliadas — e era exatamente o reconciliador que podia
divergir do estado real.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Um arquivo JSON por processo, ou shards | A retomada exige listar centenas de milhares de arquivos a cada execução; sem transação, uma interrupção no meio da escrita deixa arquivo truncado. |
| CSV incremental com append | Sem chave, sem índice e sem transação. Descobrir o que já foi feito exige ler o arquivo inteiro; uma linha parcial no fim corrompe o parsing. |
| Postgres ou outro banco servidor | Exigiria instalação e serviço rodando para um projeto que precisa ser reproduzível por um pesquisador num notebook. O SQLite é arquivo. |
| Chave primária só no número do processo | O mesmo número existe em 1º e 2º grau; o segundo registro sobrescreve o primeiro e a aresta entre origem e recurso passa a apontar para o lugar errado. |
| `NULL` para grau desconhecido | O SQLite aceita `NULL` em PRIMARY KEY, e `NULL != NULL` — a chave pararia de barrar duplicatas justamente nos registros mais reprocessados. |
| `synchronous = NORMAL` ou `OFF` | Trocaria durabilidade por uma velocidade que não se converte em nada: o gargalo é a rede, e cada commit perdido é uma requisição a refazer. |
| Gravar o erro no grau em que a tentativa falhou | Afirmaria uma existência que não foi observada. Falhar ao consultar um grau não é observar aquele grau. |
| Sem teto de tentativas | A fila da opção 2 nunca esvazia: falhas permanentes giram indefinidamente e o pesquisador perde a métrica de conclusão. |
| Gravar também a aresta pai → filho | Duas fontes de verdade para a mesma relação, que precisariam ser reconciliadas. A inversão no export é derivada e não pode divergir. |
| Casar órfãos pelo par `(processo, grau)` | Reportaria como órfão permanente todo número coletado num grau e citado como pai no outro: a opção 3 o descartaria por já estar finalizado e a opção 4 voltaria a listá-lo em toda execução. |
| Uniformizar as três etapas no **par**, em vez de no número | Não resolveria: `coletar_um` recebe um número e decide o grau sozinho, pela origem do CNJ. "Colete `N` no grau 1" é instrução que o coletor não sabe obedecer. |
| Declarar `FOREIGN KEY (processo_pai) REFERENCES registro (processo)` | Rejeitaria a gravação de todo filho cujo pai ainda não foi coletado — que é a definição de órfão. O ciclo 4 → 3 → 4 não teria como começar. |
| Manter o `PRAGMA foreign_keys = ON` | Sem FK no esquema, o pragma não fazia nada além de sugerir uma garantia inexistente a quem lesse o código. |
| `iter_exportaveis` devolvendo lista | Materializar todos os registros em memória foi o que inviabilizou o consolidador anterior. |
| Omitir `ultimo_erro` do `SELECT` de export | A projeção consome a chave. Sem ela, todo `erro_persistente` sai da base final com a frase genérica e sem a causa, que está gravada no banco. |
| Deixar o vínculo só na coleta e recoletar quando a regra mudar | Gastaria requisições contra o portal para reprocessar dado que já está no banco — e para `segredo_justica` a recoleta nem traria conteúdo novo. O bruto já contém tudo o que a derivação precisa. |
| Derivar o vínculo na projeção, sem coluna | `orfaos()` e `vinculos()` deixariam de ser SQL: descobrir órfãos exigiria carregar e derivar a base inteira em memória, que é o modelo do consolidador antigo. |
| `LIMIT/OFFSET` para paginar a reprojeção | O SQLite produz e descarta as `n` linhas anteriores a cada lote; a varredura completa vira quadrática. A comparação de tupla usa o índice da chave primária. |
| `UPDATE` dentro do laço que itera o `SELECT` da mesma tabela | Comportamento indefinido: a linha alterada pode reaparecer, sumir ou ser visitada duas vezes conforme o plano de consulta. |
| `SqliteStore` importar `derivar_vinculo` | Faria a camada de persistência depender das regras de derivação. `derivar` e `tipo_sem_bruto` entram como parâmetros, como `status.py` permanece neutro. |
| Regravar todas as linhas na reprojeção | Reescreveria a base inteira para mudar poucos registros e destruiria o significado de `atualizado_em`, que passaria a marcar o último export. |
| Deixar o store ser thread-safe, com lock de escrita | Mais código e mais risco. A separação adotada — workers fazem rede, a thread principal grava — obtém o mesmo resultado sem sincronização. |
| Apenas avisar sobre pasta sincronizada, sem bloquear | O modo de falha é silencioso e o custo é a coleta inteira. O bloqueio com escape explícito força a decisão consciente. |

## Limitações Conhecidas

- **O store não é thread-safe, por decisão.** A conexão é criada numa thread e usada por
  ela. O desenho do [`menu`](../../scripts/menu.md) garante isso: só a thread principal
  grava. Reutilizar o `SqliteStore` em outro contexto concorrente exige repensar essa
  premissa.

- **`bruto` é JSON dentro de uma coluna TEXT.** Consultar por conteúdo do bruto exige
  `json_extract` ou desserialização no Python. É o preço de guardar um dict de estrutura
  variável (o de 2º grau tem dois campos a mais) sem impor esquema.

- **`ultimo_erro` é truncado em 500 caracteres** (`str(erro)[:500]`). Mensagens longas —
  tracebacks encadeados, listas de CNJs encontrados numa divergência de identidade —
  perdem o final.

- **`contagem_por_grau` só conta `coletado` e `segredo_justica`, e por isso não fecha com
  `total()`.** São os únicos status com grau observado — `sem_dados` e os erros não têm grau
  para contar. O fato aritmético continua valendo; o que mudou é que ele deixou de depender
  de alguém ler o SQL, porque a docstring do método agora o declara.

- **`numeros_finalizados()` devolve números, não pares `(processo, grau)`.** É a consulta
  que sustenta a retomada, e ela responde "este número já tem algum desfecho?", não "este
  número já tem desfecho neste grau?". Hoje isso é a granularidade **escolhida** para o
  ciclo inteiro (ver a seção sobre o casamento do órfão), e não uma inconsistência: a coleta
  não sabe operar por par.

- **Um pai que existe só no OUTRO grau vira referência a um nó ausente da base.** É a
  contrapartida assumida da decisão acima. `(N, 1)` citado como pai com apenas `(N, 2)`
  gravado não aparece em `orfaos()` — corretamente, porque recoletar `N` devolveria o grau 2
  outra vez — mas o JSONL fica com um `processo_pai` que nenhum `_id` da base resolve. É
  inconsistência a **relatar**, e o relato depende de quem consulta.

  O diagnóstico que `graus_citados` permite chega ao disco: o
  [`exportador`](../aggregators/exportador.md) grava `orfaos_diagnostico.txt` com
  `processo\tgraus_citados` ao lado da lista de coleta.

- **A reprojeção não reescreve as observações guardadas no `bruto`.**
  `reprojetar_vinculos` atualiza `tipo_vinculo`, `processo_pai` e `processo_pai_grau` — não
  o `bruto["observacoes"]`, que a coleta preencheu com o retorno de `derivar_vinculo`. Se
  uma regra nova passar a escrever uma observação diferente (como a de capa de 2º grau sem
  1ª instância), o tipo e o pai do registro antigo são corrigidos, mas as observações que
  saem no JSONL continuam sendo as do dia da coleta.

- **A reprojeção percorre `erro_transitorio` e `erro_persistente` também.** Não há filtro de
  status: essas linhas têm `bruto` nulo e recebem `tipo_sem_bruto`. O efeito visível é que a
  coluna `tipo_vinculo` desses registros passa de `NULL` (como `registrar_erro` a grava) para
  `indefinido` na primeira opção 4 — e, como `erro_persistente` é exportável, o
  `relacionamento.tipo` dele na base final deixa de ser `null`. É coerente com o critério
  (não se olhou a capa), mas é mudança de valor numa base já publicada.

- **A reprojeção lê a base inteira a cada opção 4.** É uma varredura completa, em lotes de
  500, mesmo quando nada mudou. A cada execução ela paga a leitura de todos os `bruto`
  gravados — o custo dominante do export local numa base grande.

- **`backup()` existe mas nenhum script o chama.** O método está disponível e a docstring
  explica o cuidado (`VACUUM INTO` em vez de copiar o `.db` com `-wal` pendente), mas o
  menu não oferece a opção. Fazer backup depende de o pesquisador chamar o método
  manualmente.

- **O esquema não tem versionamento nem migração.** `CREATE TABLE IF NOT EXISTS` cria o
  que falta, mas não altera o que existe: um banco criado com esquema antigo continua com
  ele, e a divergência só apareceria como erro de coluna inexistente.

## Exemplo de Uso

Abertura com tratamento do caso da pasta sincronizada, em `scripts/menu.py`:

```python
try:
    store = SqliteStore(BANCO)
except PastaSincronizadaError as erro:
    print(f"\n{erro}\n")
    print("Defina ORQUESTRADOR_DB_DIR apontando para uma PASTA em disco local:")
```

A docstring da classe documenta o uso como context manager, que garante o fechamento:

```python
with SqliteStore("C:/dados/coleta.db") as store:
    feitos = store.numeros_finalizados()
```

Retomada — a consulta que faz a opção 1 pular o que já tem desfecho:

```python
feitos = store.numeros_finalizados()  # retomada: pula o que já tem resultado
fila = [n for n in validos if n not in feitos]
```

As duas gravações, no consumidor:

```python
st = store.registrar_erro(numero, r.motivo, origem=origem)
```

```python
store.registrar_resultado(
    numero, r.grau, r.status, bruto=bruto,
    processo_pai=vinc["processo_pai"],
    processo_pai_grau=vinc["processo_pai_grau"],
    tipo_vinculo=vinc["tipo"], origem=origem,
)
```

A reprojeção, primeira coisa que a opção 4 faz:

```python
rep = store.reprojetar_vinculos(derivar_vinculo, INDEFINIDO, log=tqdm.write)
print(f"  {rep['vistos']} registros lidos | {rep['alterados']} vínculos atualizados")
```

E as consultas que alimentam o export, em `src/aggregators/exportador.py`:

```python
mapa_filhos = inverter_filhos(store.vinculos())
```

```python
for reg in store.iter_exportaveis():
```

## Testes e Validação

Não há testes automatizados neste repositório. A validação em uso é operacional: o `menu`
imprime `store.total()` e `store.contagem_por_status()` ao fim de cada execução, e os
arquivos `falhas_pendentes.txt` e `revisao_manual.txt` são regenerados a partir do banco a
cada rodada.

Este módulo é testável sem rede e sem arquivo: `SqliteStore(":memory:")` cria o esquema num
banco em memória — e, como o caminho não passa por nenhuma pasta suspeita, a checagem de
sincronização não interfere. As invariantes que valeria fixar, em ordem de risco:

- gravar `(N, 0, erro_transitorio)` e depois `(N, 1, coletado)` deixa **uma** linha para
  `N` — a garantia do `DELETE` na mesma transação, e a que evita duplicata no JSONL;
- `registrar_erro` chamado `TETO_TENTATIVAS_PADRAO` vezes devolve `erro_persistente`
  exatamente na última, e `erro_transitorio` em todas as anteriores;
- `registrar_resultado` com `erro_transitorio` levanta `ValueError`;
- `(N, 1)` e `(N, 2)` coexistem como registros distintos — a razão de ser da chave
  composta;
- `orfaos()` **não** devolve um pai gravado como `sem_dados` (visitado é visitado), mas
  devolve um pai que nunca foi gravado;
- `orfaos()` **não** devolve um pai citado no grau 1 que existe gravado no grau 2 — o
  casamento é pelo número — e `graus_citados` daquele pai traz o grau em que ele foi citado;
- `iter_exportaveis()` devolve a chave `ultimo_erro` preenchida num registro
  `erro_persistente`, e `None` num `coletado` que antes havia falhado (o `ON CONFLICT` zera
  a coluna);
- `iter_exportaveis()` não devolve nenhum registro com `erro_transitorio`;
- um caminho contendo `OneDrive` levanta `PastaSincronizadaError`, e o mesmo caminho com
  `permitir_pasta_sincronizada=True` abre normalmente.

E as da reprojeção, que é o método com mais superfície de erro do módulo:

- **é idempotente**: rodar `reprojetar_vinculos` duas vezes seguidas devolve `alterados = 0`
  na segunda — a garantia de que a derivação é função pura do bruto;
- um registro gravado com uma regra antiga (por exemplo, `sem_vinculo` num
  `segredo_justica`) sai com o valor novo depois de uma passada, **sem** nenhuma requisição;
- `vistos` é igual a `total()` — nenhum registro escapa da paginação por chave, inclusive o
  primeiro em ordem alfabética (o cursor começa em `("", -1)`);
- com mais de 500 registros — o tamanho do lote —, `vistos` continua igual a `total()` e
  nenhuma linha é visitada duas vezes;
- o `bruto` não é modificado por ela: só as três colunas de vínculo e `atualizado_em`;
- interromper no meio e rodar de novo termina o serviço, com o mesmo resultado final.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os quatro pontos em aberto viraram correção de código; registrados aqui como decisões |
| 2026-08-11 | @alexandrehiero | `reprojetar_vinculos`: a coluna de vínculo deixa de exigir recoleta para ser corrigida |

## Pontos em aberto

Nenhum. Os quatro itens registrados em 2026-08-10 viraram código, e a decisão de cada um
está acima:

| Ponto de 2026-08-10 | Onde ficou a decisão |
|---|---|
| `iter_exportaveis` não selecionava `ultimo_erro` | "Streaming obrigatório na leitura para export" |
| Convergência do ciclo 4 → 3 → 4 | "O casamento do órfão é pelo NÚMERO, não pelo par" |
| `import os` órfão | Import removido; não há decisão a registrar |
| `PRAGMA foreign_keys = ON` sem efeito | "A ausência de `FOREIGN KEY` é a decisão" |

O que sobrou dos dois primeiros — a referência a um pai que existe só no outro grau, e a
coluna `graus_citados` sem consumidor — está em **Limitações Conhecidas**, que é onde
pertence: são consequências assumidas de decisões tomadas, não pendências.
