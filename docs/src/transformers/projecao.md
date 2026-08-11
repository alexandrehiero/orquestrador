# Projeção do documento final – `src/transformers/projecao.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `src.transformers.limpeza`, `src.status` |

## Contexto e Motivação

Esta é a última transformação antes do dado sair do projeto. Recebe uma linha do SQLite —
com o dict bruto do parser dentro — e devolve o documento que vira uma linha do JSONL.

> Função pura: recebe a linha do SQLite (com o bruto) e devolve o documento final.
> Como é pura e roda sobre o bruto guardado, mudar a estrutura de saída não custa
> nenhuma requisição — basta reprojetar.

É aqui que a decisão registrada em [`parser_base`](../scrapers/parser_base.md) se paga. O
parser guardou o texto como veio; este módulo é a **opinião** sobre aquele texto. Trocar a
opinião — renomear um campo, mudar a estrutura de partes, aplicar uma regra de limpeza
diferente — é rodar a opção 4 do [`menu`](../../scripts/menu.md) de novo. Nenhuma
requisição, nenhuma semana de recoleta.

O nome do módulo é literal no sentido de banco de dados: uma projeção é uma vista derivada
de dados que continuam existindo em outro lugar. O SQLite é a fonte; o JSONL é a vista.

## Decisões de Arquitetura

### `esqueleto`: todo registro tem os mesmos campos

```python
def esqueleto(processo, grau, status):
    """Molde canônico. Todo registro exportado tem os MESMOS campos, qualquer que
    seja o status — a contagem da base final sempre fecha com a lista de entrada."""
```

O documento nasce completo, com todos os campos em `None` ou vazio, e só depois é
preenchido conforme o status permitir. Um processo sigiloso, um inexistente e um coletado
têm exatamente a mesma forma no JSONL — mudam os valores, não as chaves.

Duas consequências práticas. A primeira é a que a docstring destaca: **a contagem fecha**.
Cada número da lista de entrada produz exatamente uma linha, e um `wc -l` no JSONL é
comparável com a lista original. A segunda é sobre o consumo: em MongoDB, documentos com
conjuntos de chaves diferentes tornam qualquer agregação condicional; no pandas, colunas
ausentes viram `NaN` em umas linhas e não em outras, com dtypes inconsistentes. Emitir
`null` explícito é mais barato para todo mundo do que omitir a chave.

### `_id` explícito torna a reimportação idempotente

```python
def chave(processo, grau):
    """_id do Mongo. Explícito para que reimportar seja idempotente: sem ele, o
    Mongo gera ObjectId aleatório e cada reimportação DUPLICA a base."""
    return f"{processo}__{grau if grau else GRAU_INDETERMINADO}"
```

Sem `_id`, cada `mongoimport` insere documentos novos com identificadores aleatórios:
reimportar depois de uma reprojeção duplica a base inteira, silenciosamente. Com `_id`
derivado da chave `(processo, grau)`, a mesma linha sempre ocupa o mesmo documento — a
importação vira uma operação repetível.

O separador `__` existe porque o `_id` precisa ser um escalar; ele codifica o par que no
SQLite é chave composta. É a mesma chave de [`sqlite_store`](../store/sqlite_store.md),
serializada.

### Segredo de justiça suprime conteúdo, não topologia

```python
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
```

O bloco de relacionamento é preenchido **antes** do `if` que ramifica por status, e isso é
deliberado. O sigilo protege o conteúdo do processo — partes, valor, movimentações. Não
protege o fato de que outro processo aponta para ele.

O segundo argumento do comentário é o decisivo: **os filhos foram calculados a partir de
outros registros**. Se o processo A é sigiloso e o processo B declara A como pai, essa
informação está em B, que não é sigiloso. Zerar `processos_filhos` em A não esconderia
nada — B continuaria apontando para A — e produziria um grafo assimétrico, em que a aresta
existe numa direção e não na outra. Quem percorresse o grafo pelos filhos veria uma
topologia diferente de quem percorresse pelos pais.

### Os filhos são sempre derivados, nunca gravados

```python
def inverter_filhos(vinculos):
    """{(pai, grau) -> {(filho, grau), ...}} a partir das arestas do banco.

    Os filhos são SEMPRE derivados da inversão dos pais, nunca gravados por um
    passo separado — era assim que o reconciliador antigo podia divergir do
    estado real. Set por decisão de projeto (dedup nativo).
    """
```

O banco guarda uma direção só (filho → pai). A lista de filhos é calculada no momento do
export, invertendo todas as arestas. Não existe passo que "atualiza os filhos", e portanto
não existe a possibilidade de os filhos gravados divergirem dos pais gravados — que é o
defeito que o reconciliador do pipeline anterior podia produzir.

A escolha de `set` como valor do mapa dá dedup nativo: se duas arestas apontarem para o
mesmo par, ele entra uma vez. E `sorted(filhos)` na projeção garante ordem estável na saída,
para que dois exports do mesmo banco produzam bytes idênticos.

### `_ref`: número e grau separados, nunca concatenados

```python
def _ref(processo, grau):
    """Referência a outro processo: número e grau SEPARADOS."""
    if not processo:
        return None
    return {"processo": processo, "grau": grau if grau else None}
```

A alternativa — gravar `"0000010-31.2013.8.26.0477 (grau 1)"` como string — tornaria
impossível consultar "todos os filhos de 1º grau" sem parsing. Como objeto, cada referência
é filtrável (`relacionamento.processo_pai.grau: 1`) e ligável ao `_id` correspondente.

### O `else` que se denuncia na própria base

```python
else:
    # Não deveria acontecer com o vocabulário unificado em src/status.py.
    # Antes, um `else` genérico rotulava QUALQUER valor desconhecido como
    # erro persistente — o dado saía plausível e errado. Aqui ele se
    # denuncia na própria base, que é onde alguém vai reparar.
    obs.insert(0, f"Status não reconhecido pela projeção: {status!r}")
```

Antes, o ramo final tratava qualquer status não reconhecido como `erro_persistente`: o
registro saía com uma frase plausível e uma afirmação falsa. Agora os quatro status
esperados têm ramos explícitos e o `else` escreve, no próprio documento, que não soube o que
fazer.

A escolha do canal importa. Não há log a consultar num export que roda uma vez e produz
milhões de linhas — mas há a base final, que é justamente onde alguém vai olhar. Falhar
alto, no lugar em que o problema será visto, em vez de falhar silenciosamente num lugar
plausível. É a mesma lógica do `DESCONHECIDO` em
[`page_state`](../scrapers/page_state.md): tornar o "não sei" visível em vez de convertê-lo
num palpite.

### Grau `0` volta a ser `null`

```python
"grau": grau if grau else None,
```

O `0` é convenção interna do banco, necessária porque o SQLite aceita `NULL` em chave
primária (ver [`status`](../status.md)). Na base final ele não tem sentido — não existe
"grau zero" no Judiciário — e vira `null`, que qualquer ferramenta entende como ausência.

### Só dois polos na base final — e uma observação quando isso esvazia o documento

O esqueleto tem dois grupos de partes, e a projeção preenche exatamente esses dois:

```python
final["partes"] = {
    "autores": _grupo(bruto.get("partes"), "ATIVO"),
    "reus": _grupo(bruto.get("partes"), "PASSIVO"),
}
```

`_grupo` descarta quem não está no polo pedido; não há grupo para `OUTRO`. A supressão é
decisão de projeto — o recorte da pesquisa são os polos —, e ela interage com uma decisão
deliberada do [`parser_base`](../scrapers/parser_base.md): `'interessado'` e
`'interessada'` foram **removidos** do polo passivo por serem rótulo neutro, e passaram a
cair em `OUTRO`. O parser preserva a categoria; a projeção a suprime. Um "Terceiro
Interessado" é coletado, fica guardado no bruto e não aparece no JSONL.

Isso vale também para rótulos novos ou com grafia inesperada, que caem em `OUTRO` por não
terem sido reconhecidos — e é aí que a supressão deixa de ser recorte e vira buraco:

```python
if bruto.get("partes") and not (
    final["partes"]["autores"]["pessoas"]
    or final["partes"]["reus"]["pessoas"]
):
    obs.append(
        "Partes extraídas, mas nenhuma classificada como autor ou réu "
        "(todas em polo OUTRO). Os nomes ficam apenas no bruto."
    )
```

No caso extremo em que **todas** as partes caem em `OUTRO`, o documento sai com `autores` e
`reus` vazios — idêntico a uma capa sem partes — embora `completude["tem_partes"]` fosse
verdadeiro e `_capa_suspeita` tenha aprovado a página justamente por haver partes. O registro
passa por toda a rede de segurança da coleta e chega à base final aparentando o oposto do que
foi observado. A observação não desfaz a supressão: ela impede que o documento minta por
omissão, e dá uma população recortável no JSONL (`observacoes` contendo a frase) para quem
quiser auditar o classificador de polo.

A condição olha só `pessoas`, e não `representantes`, porque o parser descarta parte sem
nome (`if not nome: continue`): toda parte da lista tem nome, então `pessoas` vazio com
`partes` não vazio implica que nenhuma caiu nos dois polos. E ela só existe no ramo de
`coletado` — nos demais status não há partes para classificar.

### Observações desduplicadas com ordem preservada

```python
vistos = set()
final["observacoes"] = [
    o for o in (limpar_texto(x) for x in obs)
    if o and not (o in vistos or vistos.add(o))
]
```

As observações vêm de duas origens — as de [`vinculo`](vinculo.md), anexadas ao bruto na
coleta, e as que a projeção acrescenta por status — e podem repetir. O idioma
`not (o in vistos or vistos.add(o))` aproveita que `set.add` devolve `None` (falso) para
filtrar e registrar numa expressão só, preservando a ordem de primeira aparição. É a mesma
disciplina de [`limpeza.dedup_nomes`](limpeza.md).

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Omitir campos sem valor, produzindo documentos esparsos | Agregações no Mongo passariam a precisar de condicional; no pandas, colunas ausentes viram `NaN` com dtypes inconsistentes. E a contagem da base deixaria de fechar por inspeção. |
| Deixar o Mongo gerar `_id` | Cada reimportação duplicaria a base inteira, sem erro. A reprojeção é uma operação frequente por design. |
| `_id` só com o número do processo | Colidiria os registros de 1º e 2º grau do mesmo número — a mesma colisão que a chave composta do banco existe para evitar. |
| Zerar o relacionamento em registros sigilosos | Não esconderia nada (a aresta está no registro do filho, que não é sigiloso) e produziria um grafo assimétrico conforme a direção percorrida. |
| Gravar os filhos no banco, atualizando a cada coleta | Duas fontes de verdade para a mesma aresta. Era assim que o reconciliador anterior podia divergir do estado real. |
| Referência a outro processo como string concatenada | Impossibilitaria filtrar por grau sem parsing e quebraria a ligação com o `_id`. |
| `else` genérico rotulando status desconhecido como `erro_persistente` | Era o comportamento anterior: o dado saía plausível e errado, sem sinal em lugar nenhum. |
| Levantar exceção no `else` | Abortaria o export inteiro por causa de um registro. A observação no documento preserva o restante da base e ainda assim denuncia o caso. |
| Manter `grau: 0` na base final | Expõe uma convenção interna do SQLite como se fosse dado do domínio. |
| Projetar `tipo_parte` (Exeqte, Reqdo…) na base final | Decisão do projeto: o polo é o que interessa para análise; o rótulo original permanece recuperável no bruto. |
| Criar um terceiro grupo `outros` nas partes | Mudaria o recorte da pesquisa para acomodar um caso que a observação já denuncia. Os nomes continuam no bruto, recuperáveis por reprojeção. |
| Suprimir o polo `OUTRO` sem observação nenhuma | O documento sai com autores e réus vazios, indistinguível de capa sem partes — apesar de `_capa_suspeita` tê-la aprovado por haver partes. |

## Limitações Conhecidas

- **Vários campos são renomeados entre o bruto e a base final**, sem que nada registre a
  correspondência:

  | Bruto (parser) | Base final (JSONL) |
  |---|---|
  | `assunto` | `assunto_principal` |
  | `valor` | `valor_acao` |
  | `movimentacoes[].descricao` | `movimentacoes[].movimento` |

  Quem for auditar o JSONL contra o banco precisa desta tabela, que hoje só existe lendo os
  dois módulos lado a lado.

- **`completude` não é projetado.** As três bandeiras que o parser produz
  (`tem_classe`, `tem_partes`, `tem_movimentacoes`) ficam no bruto e não chegam à base
  final. É coerente — são metadados de diagnóstico, não dado do processo —, mas significa
  que a qualidade da extração não é auditável a partir do JSONL: só consultando o SQLite.

- **`origem` e `atualizado_em` são lidos do banco e descartados.**
  `SqliteStore.iter_exportaveis` inclui as duas colunas no `SELECT`, e `projetar` não usa
  nenhuma. A base final não registra se o processo veio da lista de entrada ou foi
  descoberto como órfão, nem quando foi coletado.

- **`movimentacoes` só é preenchido para `coletado`.** Para os demais status a lista fica
  vazia, o que é correto (não há o que listar), mas torna `movimentacoes: []` ambíguo entre
  "processo sem movimentações" e "processo cujo conteúdo não foi obtido". O campo `status`
  ao lado desfaz a ambiguidade.

- **O `tipo` do relacionamento é copiado sem validação.** `reg.get("tipo_vinculo")` vai
  direto para o documento. Se um valor fora do vocabulário de [`vinculo`](vinculo.md)
  entrasse na coluna, sairia na base final sem qualquer sinal — ao contrário do `status`,
  que tem o ramo `else` para se denunciar.

- **Partes em polo `OUTRO` continuam fora da base final.** A observação registra o caso
  extremo (todas em `OUTRO`), mas o caso comum — um interessado ao lado de autor e réu —
  some sem qualquer sinal, porque os dois grupos estão preenchidos. Os nomes ficam no bruto;
  recuperá-los é decidir criar o grupo e reprojetar.

- **O relacionamento é reprojetado por outro passo, não por este.** As colunas
  `tipo_vinculo`, `processo_pai` e `processo_pai_grau` são apenas **copiadas** aqui. Quem as
  recalcula a partir do bruto é
  [`SqliteStore.reprojetar_vinculos`](../store/sqlite_store.md), que a opção 4 chama antes do
  export. O resultado prático é o mesmo — uma opção 4 basta para a regra nova valer na base
  inteira —, mas por um caminho diferente, e que precisa rodar primeiro. Chamar `projetar`
  isoladamente sobre um banco não reprojetado devolve o vínculo antigo.

- **As observações de vínculo guardadas no `bruto` não são recalculadas.** `obs` começa em
  `list(bruto.get("observacoes") or [])`, e essa lista foi escrita pelo `menu` no momento da
  coleta. A reprojeção de vínculo atualiza as colunas, não o bruto: um documento pode sair
  com `relacionamento.tipo` novo e uma observação de vínculo antiga ao lado. As observações
  que **esta** página acrescenta (status, polo `OUTRO`) são recalculadas normalmente.

## Exemplo de Uso

O único consumidor é o [`exportador`](../aggregators/exportador.md), que chama as duas
funções públicas em momentos diferentes. Primeiro a inversão, uma vez para a base inteira:

```python
# Filhos são DERIVADOS da inversão dos pais, calculada agora — nunca um
# campo gravado por um passo anterior que pudesse divergir do estado real.
mapa_filhos = inverter_filhos(store.vinculos())
```

Depois a projeção, registro a registro, em streaming:

```python
for reg in store.iter_exportaveis():
    filhos = mapa_filhos.get((reg["processo"], reg["grau"]), set())
    doc = projetar(reg, filhos)
    arq.write(json.dumps(doc, ensure_ascii=False) + "\n")
```

O `mapa_filhos` é a única estrutura que fica residente em memória durante o export — os
documentos são escritos e descartados um a um.

## Testes e Validação

Não há testes automatizados neste repositório. O módulo é puro e não precisa de banco: os
casos são construídos escrevendo à mão o dicionário que `iter_exportaveis` devolveria.

As invariantes que valeria fixar, em ordem de gravidade:

- **um registro `segredo_justica` com filhos preserva `processos_filhos` preenchido** — a
  garantia de que o sigilo não corta a topologia. Acontece em dado real: no
  `data/saida/teste1/base_final.jsonl`, o registro `10110499020188260066__1` é
  `segredo_justica` e tem `30000042520198260000` (grau 2) como filho;
- os quatro status esperados produzem documentos com **o mesmo conjunto de chaves**; um
  status fora do vocabulário produz a observação `"Status não reconhecido pela projeção"` e
  **não** a frase de erro persistente;
- um registro `erro_persistente` com `ultimo_erro` preenchido produz **duas** observações: a
  frase genérica e `"Último erro: ..."` — a segunda depende de o `SELECT` de
  `iter_exportaveis` trazer a coluna;
- `chave(processo, 1)` e `chave(processo, 2)` são diferentes, e `chave(processo, 0)` é igual
  a `chave(processo, None)`;
- `grau = 0` no banco vira `grau: null` no documento;
- `inverter_filhos` de uma aresta `(N, 2) → (N, 1)` mapeia `(N, 1)` para `{(N, 2)}` — o caso
  do recurso cujo número é o mesmo da origem;
- observações repetidas nas duas origens (vínculo e status) aparecem uma vez só, na ordem
  de primeira aparição;
- partes com polo `ATIVO` e `PASSIVO` caem em `autores` e `reus` respectivamente, com dedup
  aplicado; um bruto cujas partes estejam **todas** em `OUTRO` produz autores e réus vazios
  **com** a observação correspondente.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os dois pontos em aberto resolvidos: polo `OUTRO` virou decisão documentada, `ultimo_erro` corrigido no store |
| 2026-08-11 | @alexandrehiero | Limitação do `tipo` não reprojetável reescrita: `reprojetar_vinculos` roda antes do export |

## Pontos em aberto

Nenhum. Os dois itens registrados em 2026-08-10 saíram desta seção por caminhos diferentes:

| Ponto de 2026-08-10 | Desfecho |
|---|---|
| Partes com polo `OUTRO` desaparecem da base final | Continua sendo decisão de projeto, agora registrada em "Só dois polos na base final"; o caso extremo passou a gerar observação no JSONL |
| `ultimo_erro` é consumido aqui mas nunca chega | Corrigido no [`sqlite_store`](../store/sqlite_store.md): a coluna entrou no `SELECT` de `iter_exportaveis` |

A supressão do polo `OUTRO` no caso comum permanece em **Limitações Conhecidas** — é
consequência assumida do recorte, não pendência.
