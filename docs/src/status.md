# Vocabulário de status – `src/status.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | nenhuma — módulo sem imports, por decisão |

## Contexto e Motivação

Este é o menor módulo do projeto e não executa nada: são doze constantes e a docstring que
explica por que elas precisam morar num lugar só. A primeira linha:

> Vocabulário de status da coleta — FONTE ÚNICA.

O que ele corrige está no parágrafo seguinte:

> Antes existiam três declarações independentes das mesmas strings (coletor,
> sqlite_store e projecao). Nada impedia que divergissem, e a divergência seria
> silenciosa: um registro gravado com um valor que a projeção não reconhece cai
> no ramo `else` e vira 'erro persistente' sem erro nenhum.

Vale seguir esse modo de falha até o fim, porque ele é característico do projeto inteiro. As
três cópias não quebram nada quando concordam — e concordavam. O problema é o que acontece
no dia em que uma delas muda: nenhum import falha, nenhuma exceção sobe, nenhum teste
acusaria (não há testes). O [`coletor`](scrapers/coletor.md) grava `"segredo_justica"`, o
[`SqliteStore`](store/sqlite_store.md) aceita porque a string está na sua própria lista, e a
projeção — que tem a terceira cópia, agora divergente — não reconhece o valor, cai no `else`
e escreve no JSONL que o processo deu **erro persistente**.

O resultado é um registro plausível, internamente consistente e factualmente errado. É
exatamente a mesma classe de falha que a [regra central do coletor](scrapers/coletor.md)
existe para impedir, só que na camada de vocabulário em vez da de roteamento.

## Decisões de Arquitetura

### O módulo é propositalmente neutro: zero imports do projeto

```python
Este módulo é PROPOSITALMENTE neutro — sem imports do projeto. Se o vocabulário
morasse no `sqlite_store`, o `scrapers/coletor` passaria a depender da camada de
persistência, que ele não deve conhecer.
```

Este é o motivo de o módulo existir em `src/` e não dentro de `store/`. O lugar óbvio para
o vocabulário seria o `sqlite_store`, que é quem valida e grava os status — mas isso
inverteria a direção da dependência. O `coletar_um` é uma função pura que **não conhece o
banco** (ver [`coletor`](scrapers/coletor.md)); fazê-lo importar de `store/` para saber
escrever `"coletado"` amarraria o scraper à persistência sem nenhum ganho.

Um módulo folha resolve isso: todos importam dele, ele não importa de ninguém. Não há como
introduzir ciclo. É a mesma razão pela qual as exceções vivem em um módulo próprio, e não
em quem as levanta — ver [`exceptions`](scrapers/exceptions.md).

### Os cinco status, e o que cada um autoriza

```python
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
```

Os comentários não são glossário: cada um descreve uma **consequência operacional**. A
distinção que carrega mais peso é a entre `SEM_DADOS` e `ERRO_TRANSITORIO`, que é a versão
em vocabulário da diferença entre "perguntei e não existe" e "não consegui perguntar".
`SEM_DADOS` é final — o processo nunca mais será tentado; `ERRO_TRANSITORIO` volta à fila.
Trocar um pelo outro por engano é gravar uma afirmação falsa e permanente, e é por isso que
o [`page_state`](scrapers/page_state.md) exige uma frase explícita do portal antes de
autorizar `sem_dados`.

`SEGREDO_JUSTICA` é terminal mas **não** é ausência de dado: o grau observado acompanha o
registro, porque em qual instância o processo tramita não é informação sigilosa.

### `STATUS_TERMINAIS` e `STATUS_EXPORTAVEIS`

```python
#: Não voltam para a fila de recoleta.
STATUS_TERMINAIS = (COLETADO, SEGREDO_JUSTICA, SEM_DADOS, ERRO_PERSISTENTE)

#: Geram registro no JSONL. `erro_transitorio` é fila de trabalho, não resultado,
#: e por isso nunca chega ao export.
STATUS_EXPORTAVEIS = STATUS_TERMINAIS
```

Os dois conjuntos coincidem hoje, mas respondem a perguntas diferentes — "isto sai da fila?"
e "isto vira linha do JSONL?" — e por isso têm nomes diferentes. O comentário explica a
coincidência: `erro_transitorio` é o único status que não é resultado de nada, é fila de
trabalho, e um processo em fila não tem o que exportar.

Na prática o `SqliteStore` usa os dois em consultas distintas: `STATUS_TERMINAIS` para saber
o que já foi resolvido e `STATUS_EXPORTAVEIS` para montar o `SELECT` do export.

### `TETO_TENTATIVAS_PADRAO` mora aqui, não no `sqlite_store`

```python
#: Tentativas antes de promover erro_transitorio -> erro_persistente. Mora aqui,
#: e não no sqlite_store, porque é a REGRA DE TRANSIÇÃO entre dois status — não
#: um detalhe de persistência. É ela que faz a fila de falhas esvaziar em vez de
#: girar para sempre.
TETO_TENTATIVAS_PADRAO = 5
```

É a única constante do módulo que não é uma string de status, e a justificativa da exceção
está no próprio comentário: o número **define** quando `erro_transitorio` vira
`erro_persistente`. Sem ele o vocabulário estaria incompleto — teria os dois estados e não
a aresta entre eles. Que a transição seja implementada por um `UPDATE` no SQLite é
coincidência de implementação; a regra é de domínio.

É também o que fecha o ciclo aberto pelas decisões conservadoras do resto do pipeline. O
[`_capa_suspeita`](scrapers/coletor.md) reprova capas legítimas sem partes de propósito, e
essa escolha só é sustentável porque o falso positivo tem saída: cinco tentativas e o
processo sai da fila automática para revisão manual, em vez de girar para sempre.

### `GRAU_INDETERMINADO = 0`, nunca `NULL`

```python
#: Grau indeterminado. Nunca NULL: o SQLite não impede NULL em PRIMARY KEY, e
#: como NULL != NULL a chave deixaria de barrar duplicatas.
GRAU_INDETERMINADO = 0
```

O SQLite tem uma peculiaridade frente a outros bancos: ele **aceita** `NULL` numa coluna de
PRIMARY KEY. E como `NULL != NULL` na semântica SQL, duas linhas com grau nulo não colidem —
a chave `(processo, grau)` deixaria de barrar duplicatas exatamente nos registros em que
nada foi observado, que são os mais propensos a serem reprocessados.

O sentinela `0` é um valor real: compara, indexa e colide como qualquer outro. É o grau com
que `coletar_um` devolve `sem_dados` e com que os erros são gravados.

### As duas origens

```python
#: De onde veio o número.
ORIGEM_LISTA = "lista"
ORIGEM_ORFAO = "orfao"
```

`lista` é um número que veio do arquivo de entrada; `orfao` é um número descoberto durante a
coleta, como alvo de um vínculo cujo processo não estava na lista. A distinção é o que
permite ao export separar a base pedida da base descoberta.

### Quem consome o quê

Verificado nos imports de cada módulo:

| Módulo | Constantes importadas |
|---|---|
| `src/scrapers/coletor.py` | `COLETADO`, `ERRO_TRANSITORIO`, `GRAU_INDETERMINADO`, `SEGREDO_JUSTICA`, `SEM_DADOS` |
| `src/store/sqlite_store.py` | `COLETADO`, `ERRO_PERSISTENTE`, `ERRO_TRANSITORIO`, `GRAU_INDETERMINADO`, `ORIGEM_LISTA`, `SEGREDO_JUSTICA`, `STATUS_EXPORTAVEIS`, `STATUS_TERMINAIS`, `TETO_TENTATIVAS_PADRAO` |
| `src/transformers/projecao.py` | `COLETADO`, `ERRO_PERSISTENTE`, `GRAU_INDETERMINADO`, `SEGREDO_JUSTICA`, `SEM_DADOS` |
| `scripts/menu.py` | `ERRO_TRANSITORIO`, `ORIGEM_LISTA`, `ORIGEM_ORFAO` |

São exatamente os três módulos que antes mantinham cópias, mais o script que orquestra os
três. Nenhum deles declara mais as strings por conta própria.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Manter as três declarações independentes | Nada as amarrava. A divergência não levanta erro em lugar nenhum: o valor não reconhecido cai no `else` da projeção e vira "erro persistente" silenciosamente. |
| Colocar o vocabulário no `store/sqlite_store.py` | É onde os status são validados e gravados, mas faria `scrapers/coletor` importar da camada de persistência — que ele não deve conhecer, justamente por ser uma função pura que não grava nada. |
| Colocar o vocabulário no `scrapers/coletor.py` | Inverteria o problema: `store` e `transformers` passariam a depender do scraper para saber ler o próprio banco. |
| Usar `enum.Enum` em vez de constantes de string | Os valores vão direto para colunas TEXT do SQLite e para o JSONL. Um `Enum` exigiria `.value` em cada ponto de gravação e comparação, sem ganhar validação onde ela importa — que é na leitura do banco, onde a string já chegou solta. |
| Deixar `TETO_TENTATIVAS_PADRAO` no `sqlite_store` | O número é a regra de transição entre dois status, não um detalhe de armazenamento. Separá-lo do vocabulário deixaria os dois estados documentados e a aresta entre eles não. |
| `NULL` para grau desconhecido, em vez de `0` | O SQLite aceita `NULL` em PRIMARY KEY e `NULL != NULL`: a chave `(processo, grau)` pararia de barrar duplicatas exatamente nos registros sem observação. |
| Manter uma constante `TODOS` com o vocabulário completo, como documentação executável | Nenhum módulo a importava. Num arquivo recém-criado, uma constante sem consumidor não é dívida antiga a tolerar — é dívida nova a não contrair; e a lista de status já está na íntegra logo acima, no próprio módulo. |
| `scripts/menu.py` obter `ERRO_TRANSITORIO` pelo reexport do `coletor` | Funciona (o import não copia nada), mas o mesmo arquivo passava a mostrar duas procedências para o mesmo vocabulário, sugerindo dois donos onde há um. |

## Limitações Conhecidas

- **`STATUS_EXPORTAVEIS` é o mesmo objeto que `STATUS_TERMINAIS`, não uma cópia.** A linha é
  `STATUS_EXPORTAVEIS = STATUS_TERMINAIS`. São tuplas, então não há risco de mutação
  compartilhada, mas os dois nomes não podem divergir por acidente **nem** por intenção sem
  alterar essa linha. Qualquer código que assuma que um dia poderão diferir está assumindo
  algo que hoje não é verdade.

- **Nada valida que o status gravado pertença ao vocabulário, exceto num ponto.**
  `SqliteStore.registrar_resultado` levanta `ValueError` quando o status não está em
  `STATUS_TERMINAIS`. Fora dele — em `registrar_erro`, na projeção, em consultas ad hoc —
  uma string arbitrária entraria sem reclamação. A fonte única elimina a divergência entre
  módulos; ela não introduz checagem de tipo.

    Não há tupla com o vocabulário **completo**: `STATUS_TERMINAIS` cobre quatro dos cinco,
    e `ERRO_TRANSITORIO` fica de fora. Uma validação abrangente precisaria montar o conjunto
    no ponto de uso ou reintroduzir a constante que existia para isso.

- **O módulo não documenta a transição entre status, só os nomes.** Que
  `erro_transitorio → erro_persistente` aconteça em `registrar_erro`, e que
  `sem_dados` seja irreversível, são fatos que vivem no `sqlite_store` e no `coletor`. Quem
  ler só este arquivo conhece o vocabulário e não a máquina.

- **`GRAU_INDETERMINADO` é usado como grau e como sentinela de "sem observação".** As duas
  leituras coincidem hoje, mas um grau 0 legítimo (que o e-SAJ não usa) tornaria o valor
  ambíguo. É uma aposta sobre o domínio, não uma garantia estrutural.

## Exemplo de Uso

No [`coletor`](scrapers/coletor.md), que importa só o que usa:

```python
from ..status import (
    COLETADO,
    ERRO_TRANSITORIO,
    GRAU_INDETERMINADO,
    SEGREDO_JUSTICA,
    SEM_DADOS,
)
```

```python
# Todos os graus responderam NAO_ENCONTRADO explicitamente.
return ResultadoColeta(SEM_DADOS, GRAU_INDETERMINADO, None, None)
```

No [`SqliteStore`](store/sqlite_store.md), onde o vocabulário vira validação e regra de
transição:

```python
if status not in STATUS_TERMINAIS:
    raise ValueError(f"Status não terminal em registrar_resultado: {status!r}")
```

```python
def registrar_erro(self, processo, erro, teto_tentativas=TETO_TENTATIVAS_PADRAO,
```

```python
status = ERRO_PERSISTENTE if tentativas >= teto_tentativas else ERRO_TRANSITORIO
```

E o comentário que o próprio `sqlite_store` deixou no lugar da cópia que tinha:

```python
# Vocabulário de status: FONTE ÚNICA em src/status.py. Este módulo declarava as
# mesmas strings que o coletor e a projeção — três cópias que nada impedia de
# divergir, e cuja divergência seria silenciosa.
```

## Testes e Validação

Não há testes automatizados neste repositório. Este módulo não tem comportamento a exercitar
— são atribuições de constantes — e sua correção é verificável por leitura: se nenhum outro
arquivo declara as mesmas strings, a fonte é única.

A conferência que substitui um teste é uma busca:

```bash
grep -rn '"coletado"\|"segredo_justica"\|"sem_dados"\|"erro_transitorio"\|"erro_persistente"' src/ scripts/
```

Hoje ela devolve apenas as linhas de `src/status.py`. Qualquer ocorrência nova fora daqui é
uma quarta cópia nascendo, e é o sinal que este módulo existe para tornar visível.

As invariantes que valeria fixar, se um dia houver suíte:

- todo status do módulo é aceito por `SqliteStore` sem `ValueError` no caminho apropriado —
  `STATUS_TERMINAIS` em `registrar_resultado`, `ERRO_TRANSITORIO` em `registrar_erro`;
- todo status que a `projecao` ramifica é um dos declarados aqui — hoje a projeção trata
  `COLETADO`, `SEGREDO_JUSTICA`, `SEM_DADOS` e `ERRO_PERSISTENTE`, e o `else` é o ramo de
  erro;
- `registrar_erro` promove a `erro_persistente` exatamente na `TETO_TENTATIVAS_PADRAO`-ésima
  tentativa, não antes.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação: extração do vocabulário antes duplicado em `coletor`, `sqlite_store` e `projecao` |
| 2026-08-10 | @alexandrehiero | `TODOS` removido (constante sem consumidor); `scripts/menu.py` passa a importar `ERRO_TRANSITORIO` daqui, não reexportado pelo `coletor` |

## Pontos em aberto

Nenhum item em aberto.
