# Derivação do vínculo – `src/transformers/vinculo.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re` (biblioteca padrão) — sem imports do projeto |

## Contexto e Motivação

Este módulo responde a uma pergunta só: **de onde este processo nasceu?** E a resposta vira
duas colunas no SQLite (`processo_pai`, `processo_pai_grau`) mais um rótulo (`tipo_vinculo`)
que é a base de todo o grafo de relacionamento da pesquisa.

A primeira linha da docstring é uma afirmação de propriedade:

> Deriva o vínculo (tipo + processo pai) — ÚNICO ESCRITOR de `tipo`.

E o parágrafo seguinte diz o que isso corrige:

> Chamado NA COLETA, com o bruto do parser em mãos. Grava direto nas colunas do
> SQLite. Nenhum passo posterior reescreve o tipo — no pipeline IAMSPE ele tinha
> dois donos (normalizador e vincular_pais), e o segundo desfazia o primeiro.

Dois escritores para o mesmo campo é uma condição de corrida sem concorrência: basta
executar as etapas na ordem errada — ou executar a segunda duas vezes — para que o valor
final dependa do histórico de execução em vez do dado. Pior: como ambos gravavam valores
plausíveis, a divergência não aparecia como erro. Um único escritor, chamado no momento em
que a evidência está em mãos, elimina a classe inteira de problemas.

## Decisões de Arquitetura

### Vocabulário fechado, atribuído só com evidência

> Vocabulário fechado, atribuído SÓ com evidência:
>
>   incidente   -> link 'Processo principal' no topo, ou a movimentação de origem.
>                  O pai é do MESMO grau (incidente corre na mesma instância).
>   recurso     -> capa de 2º grau declarando o número de 1ª instância.
>                  O pai é, por definição, do grau 1.
>   indefinido  -> há indício de vínculo, mas o número é inválido/antigo.
>   sem_vinculo -> nenhum sinal de pai.

Quatro valores, cada um amarrado a uma evidência específica na página. Note que **o grau do
pai é derivado do tipo**, não observado: incidente corre na mesma instância, logo
`pai_grau = grau`; recurso vem de 1ª instância por definição, logo `pai_grau = 1`. São
inferências do domínio jurídico, não leituras do HTML — e por isso ficam explícitas no
código, num lugar só.

### O rótulo que foi removido, e por quê

> Note o que NÃO existe mais: 'Ação de Conhecimento (Pai)'. Ele afirmava duas
> coisas não verificadas — que o processo é ação de conhecimento (a Classe
> responde isso) e que ele é pai (só é verdade se tiver filhos, o que se sabe
> invertendo os vínculos, não na coleta).

Vale destrinchar, porque é o melhor exemplo do critério do módulo. O rótulo antigo
misturava três informações num campo só:

| Afirmação embutida | Problema |
|---|---|
| "é ação de conhecimento" | Duplica a `classe`, que já responde isso — e podia divergir dela |
| "é pai" | Só se sabe **depois**, invertendo as arestas de todos os registros |
| (o tipo de vínculo em si) | A única coisa que o campo deveria dizer |

A segunda é a mais grave: "ser pai" não é observável na capa do próprio processo. Um
processo é pai quando **outro** aponta para ele. Essa informação só existe depois que a
coleta inteira terminou, e é exatamente o que
[`projecao.inverter_filhos`](projecao.md) calcula no export. Afirmá-la durante a coleta é
adivinhar.

### Prioridade entre candidatos, e nada é descartado

```python
def derivar_vinculo(bruto, grau, processo):
    """Devolve {tipo, processo_pai, processo_pai_grau, observacoes}.

    Prioridade: link do topo > movimentação de origem > número de 1ª instância.
    Quando há mais de um vínculo válido, o HIERÁRQUICO (incidente) vence — é o
    pai direto — e o outro é registrado em observacoes, nunca descartado.
    """
```

A ordem em que os candidatos entram na lista **é** a prioridade — não há sorteio nem
heurística:

```python
pai_link = _digitos(bruto.get("processo_principal"))
if pai_link:
    candidatos.append((INCIDENTE, pai_link, grau, "link do topo"))

pai_mov = _pai_da_movimentacao(bruto.get("movimentacoes"), proprio)
if pai_mov and pai_mov != pai_link:
    candidatos.append((INCIDENTE, pai_mov, grau, "movimentação de origem"))

primeira = _digitos(bruto.get("processo_1a_instancia"))
if grau == 2 and primeira:
    candidatos.append((RECURSO, primeira, 1, "número de 1ª instância"))
```

O incidente vence o recurso porque é o pai **direto**: um agravo que também é incidente de
outro processo nasceu do incidente, e só depois subiu. Mas o vínculo perdedor não some —
vira observação:

```python
obs.append(f"Outro vínculo detectado ({origem}): {pai} (grau {pai_grau}).")
```

O modelo guarda um pai por processo; a informação sobre os demais fica registrada em texto,
onde pode ser recuperada por quem precisar.

### A movimentação mais antiga vence

```python
def _pai_da_movimentacao(movimentacoes, proprio):
    """Quando há mais de uma citação, vence a da DATA MAIS ANTIGA — a
    movimentação de ORIGEM, que declara de onde o processo nasceu."""
```

Movimentações citam "processo principal" mais de uma vez ao longo da vida do processo. A
que interessa é a **primeira**: é a que registra a origem. As posteriores são referências
de tramitação.

E a proteção que torna esse critério confiável:

```python
def _chave_data(data_br):
    """Chave ordenável. Data ilegível vai para o fim — nunca vira 'mais antiga'."""
```

Uma data que não casa o padrão devolve `(9999, 99, 99)` — vai para o fim da ordenação. Sem
isso, uma data ilegível ordenaria como a menor e uma movimentação qualquer viraria a de
origem. É a mesma disciplina de [`limpeza.dedup_movimentacoes`](limpeza.md), aplicada a uma
decisão que cria aresta no grafo.

### O padrão é ancorado no rótulo

```python
# Ancorado no rótulo — nunca captura um CNJ solto que apareça no meio do texto.
_PADRAO_PAI_MOV = re.compile(
    r"processo principal:?\s*(\d{7}[-.]?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4})", re.I
)
```

Despachos citam números de processos o tempo todo, em prosa corrida. Buscar "um CNJ nas
movimentações" transformaria qualquer menção de passagem em aresta de paternidade. O padrão
exige a expressão `processo principal` imediatamente antes do número — é a diferença entre
ler uma declaração e colher uma coincidência. A mesma preocupação aparece no
[`parser_segundo_grau`](../scrapers/parser_segundo_grau.md), onde a varredura para no
próximo título para não invadir as movimentações.

### Validação de DV antes de criar a aresta

```python
def _dv_ok(d20):
    """DV do CNJ (ISO 7064 MOD 97-10). Filtrar aqui é de graça e evita criar
    aresta no grafo apontando para um número que não existe."""
```

"De graça" é literal: é aritmética sobre 20 dígitos, contra o custo de uma aresta falsa que
geraria um órfão permanente. O número inválido vira `orfaos.txt`, a opção 3 tentaria
coletá-lo, o e-SAJ responderia que não existe, e o ciclo consumiria requisições para
descobrir o que a conta já sabia.

Quando o DV não fecha, o vínculo é ignorado **com registro**:

```python
obs.append(f"Vínculo ignorado ({origem}): número {pai} com DV inválido.")
```

### Guarda de auto-referência em todos os caminhos

```python
# Guarda de auto-referência em TODOS os caminhos. No pipeline antigo ela
# existia só para o número de 1ª instância; o link do topo podia criar
# um processo filho de si mesmo.
if pai == proprio and pai_grau == grau:
```

A guarda está no laço que percorre os candidatos, e não em cada extração — é o que garante
cobertura sem depender de lembrar. Repare que ela compara **o par**: `pai == proprio` não
basta. Um recurso de 2º grau cujo número de 1ª instância é o próprio número é um vínculo
legítimo `(N, 2) → (N, 1)`, e é exatamente para isso que a chave do banco é composta (ver
[`sqlite_store`](../store/sqlite_store.md)). Comparar só o número mataria essa aresta.

### `indefinido` ≠ `sem_vinculo`

```python
if bruto_1a or descartados:
    return {"tipo": INDEFINIDO, "processo_pai": None,
            "processo_pai_grau": None, "observacoes": obs}

return {"tipo": SEM_VINCULO, "processo_pai": None,
        "processo_pai_grau": None, "observacoes": obs}
```

A distinção é a mesma que atravessa o projeto inteiro, aplicada ao relacionamento:
`sem_vinculo` é "olhei e não há sinal de pai"; `indefinido` é "há sinal, mas não consegui
transformá-lo em aresta". São afirmações epistemicamente diferentes, e colapsá-las esconderia
justamente os casos que merecem revisão manual — o mesmo raciocínio que separa `sem_dados`
de `erro_transitorio` em [`status`](../status.md).

### O tipo é decidido por um contador, não pelo texto das observações

A condição acima era, até esta revisão, `any("ignorado" in o for o in obs)`: o tipo devolvido
saía de uma busca pela palavra `"ignorado"` dentro das mensagens que **este mesmo módulo**
acabara de escrever. Hoje o laço conta:

```python
# Contador explícito. Antes o tipo era decidido procurando a palavra
# "ignorado" nas observações que este mesmo módulo escreve — controle de
# fluxo passando por texto de log. Reescrever a mensagem para "Vínculo
# descartado" mudaria o TIPO em silêncio, sem quebrar nada visivelmente.
descartados = 0
```

Vale nomear a fragilidade, porque ela não é sobre estilo. Uma mensagem de log é texto para
humano: quem a reescreve — para deixá-la mais clara, para padronizar o vocabulário, para
traduzir — não espera estar mexendo no valor de um campo da base. Trocar `"Vínculo ignorado"`
por `"Vínculo descartado"` faria todos esses registros migrarem de `indefinido` para
`sem_vinculo`, sem exceção, sem teste vermelho e sem nada de errado à vista: as observações
continuariam corretas, o tipo continuaria sendo um dos quatro do vocabulário, e a base sairia
afirmando "olhei e não há sinal de pai" sobre processos em que havia sinal. O contador
separa as duas coisas — o que aconteceu no laço e o que se escreveu sobre isso.

Repare que a distinção entre os dois motivos de descarte (auto-referência e DV inválido)
permanece só nas observações. Para o **tipo**, os dois são equivalentes: houve sinal, não
virou aresta.

### A capa de 2º grau sem número de 1ª instância deixa rastro

```python
elif grau == 2 and not bruto.get("processo_1a_instancia_bruto"):
    # Registrado porque este é o caminho pelo qual uma FALHA DE SELETOR do
    # cposg chegaria à base final: em silêncio, indistinguível de um processo
    # de competência originária que genuinamente não tem 1ª instância.
    obs.append("Capa de 2º grau sem número de 1ª instância localizado.")
```

Antes, esse caso não produzia nada: nenhum candidato, nenhuma observação, tipo
`sem_vinculo`, documento idêntico ao de um processo que de fato não tem origem em 1ª
instância. E é exatamente por aí que uma quebra de seletor do `cposg` chegaria à base final
— sem erro, sem falha, sem número na fila de revisão. Uma coleta inteira poderia sair com
`processo_1a_instancia: null` em todos os recursos, e a única pista seria alguém achar
estranho que a base não tenha nenhum vínculo de recurso.

Três precisões sobre o ramo:

- ele é um `elif` de `if grau == 2 and primeira`, e testa `processo_1a_instancia_bruto`.
  Só dispara quando **não há nenhum dos dois** — nem o CNJ válido, nem o número em formato
  antigo. O formato antigo já tem observação própria (`"Número de 1ª instância em formato
  antigo"`) e já leva o registro a `indefinido`; escrever as duas seria ruído;
- o **tipo continua `sem_vinculo`**. A correção torna o caso visível e contável, não o
  reclassifica: não houve sinal de pai nenhum, e afirmar `indefinido` aqui seria inventar um
  indício que a capa não trouxe;
- a observação **não distingue** competência originária de seletor quebrado — nada na página
  permite essa distinção. O que ela dá é uma população recortável: se a fração de capas de
  2º grau com essa observação saltar de uma coleta para outra, é sinal de seletor, não de
  mudança na natureza dos processos.

### Sem bruto, o padrão é `indefinido`

A regra tem um complemento fora deste módulo, em `scripts/menu.py`, para os registros que
nunca chegam a passar por aqui:

```python
# `tipo` do relacionamento tem UM único escritor: derivar_vinculo.
# Sem bruto (segredo de justiça, sem dados) o tipo é INDEFINIDO, não
# sem_vinculo: nunca chegamos a olhar a capa, então "não há sinal de
# pai" seria afirmação sobre algo que a coleta não observou.
vinc = {"tipo": INDEFINIDO, "processo_pai": None,
        "processo_pai_grau": None, "observacoes": []}
```

`segredo_justica` e `sem_dados` chegam ao banco com `bruto=None`, e o padrão anterior os
rotulava `sem_vinculo` — que, pelo critério deste módulo, é uma afirmação: "olhei e não há
sinal de pai". Em segredo de justiça não houve o que olhar; o conteúdo foi negado. O rótulo
descrevia uma verificação que não aconteceu, e uma consulta que filtrasse
`relacionamento.tipo == "sem_vinculo"` para contar processos sem pai incluiria os sigilosos
como se tivessem sido conferidos.

`indefinido` diz a coisa certa com o vocabulário que já existe: pode haver pai, não dá para
saber. É a mesma escolha que `status` faz ao separar `sem_dados` de `erro_transitorio` —
ausência observada não é ausência de observação.

A regra vale nos **dois** caminhos que escrevem a coluna. O segundo é a reprojeção:

```python
rep = store.reprojetar_vinculos(derivar_vinculo, INDEFINIDO, log=tqdm.write)
```

`INDEFINIDO` entra ali pelo mesmo motivo, como `tipo_sem_bruto` — e é isso que finalmente
corrigiu a base já produzida (ver abaixo).

### O vínculo voltou a ser reprojetável

Esta página registrava, até esta revisão, uma assimetria incômoda: [`limpeza`](limpeza.md) e
[`projecao`](projecao.md) rodam sobre o bruto guardado e mudam com uma opção 4, enquanto
`derivar_vinculo` rodava **só na coleta** e o resultado virava coluna. Corrigir uma regra
daqui valia apenas para o que fosse coletado dali em diante.

Não era teoria: depois da correção que trocou o padrão sem bruto para `INDEFINIDO`, os
registros `segredo_justica` do `data/saida/teste1/base_final.jsonl` continuavam com
`"tipo": "sem_vinculo"`. O código certo, a base errada, e nenhum caminho local para
reconciliar os dois — recoletar um processo sigiloso gasta requisição e não traz conteúdo.

[`SqliteStore.reprojetar_vinculos`](../store/sqlite_store.md) fechou isso: a opção 4 relê o
bruto de cada registro, chama esta função de novo e regrava as colunas quando o resultado
muda. A coluna continua existindo — `orfaos()` e `vinculos()` são SQL sobre ela —, mas deixou
de ser a **origem** do valor.

O que isso significa para quem mexe neste módulo: mudar uma regra de derivação passou a ser
uma alteração local, verificável rodando a opção 4 sobre um banco existente e olhando quantos
vínculos foram atualizados. A ressalva está em Limitações — as `observacoes` não são
reescritas.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Derivar o vínculo num passo posterior, sobre o banco | Foi o modelo anterior: dois donos do campo `tipo`, e o segundo desfazia o primeiro. O valor final passava a depender da ordem de execução. |
| Manter o rótulo `'Ação de Conhecimento (Pai)'` | Afirmava duas coisas não verificadas: a classe (que já existe em campo próprio) e a paternidade (que só se sabe invertendo as arestas, depois da coleta). |
| Vocabulário aberto, aceitando qualquer string descritiva | Impossibilita agregação. Um vocabulário fechado de quatro valores é consultável; texto livre não. |
| Deixar o recurso vencer o incidente | O incidente é o pai direto — o processo nasceu dele e só depois subiu de instância. |
| Descartar o vínculo perdedor | Perderia informação real sobre a topologia. Registrado em `observacoes`, ele continua recuperável. |
| Aceitar vários pais por processo | Complicaria o modelo (o grafo deixaria de ser floresta) para representar um caso que a observação de `observacoes` já cobre. |
| Buscar qualquer CNJ nas movimentações | Despachos citam números em prosa; toda menção de passagem viraria aresta de paternidade. |
| Usar a movimentação mais recente que cita o processo principal | As citações posteriores são referências de tramitação; a de origem é a primeira. |
| Ordenar datas sem tratar as ilegíveis | Uma data que não casa o padrão viraria a "mais antiga" e determinaria a origem do processo. |
| Não validar o DV do pai | Cria aresta apontando para número inexistente, que vira órfão permanente e consome requisições da opção 3 para descobrir o que a aritmética já sabia. |
| Guarda de auto-referência só comparando o número | Mataria a aresta legítima `(N, 2) → (N, 1)`, que é a razão de a chave do banco ser `(processo, grau)`. |
| Um único valor para "sem pai" | Colapsaria "não há sinal" e "há sinal que não resolvi", escondendo os casos que merecem revisão. |
| Decidir o tipo procurando `"ignorado"` nas observações | Fluxo de controle passando por texto de log: reescrever a mensagem mudaria o tipo de todos esses registros em silêncio, sem quebrar nada visivelmente. |
| Deixar a capa de 2º grau sem 1ª instância passar sem observação | É o caminho pelo qual uma quebra de seletor do `cposg` chegaria à base final indistinguível de um processo de competência originária. |
| Classificar essa capa como `indefinido` em vez de `sem_vinculo` | Inventaria um indício que a página não trouxe. A observação registra o caso sem afirmar o que não se viu. |
| `sem_vinculo` como padrão para registro sem bruto | Afirma "olhei e não há sinal de pai" sobre uma capa cujo conteúdo a coleta não chegou a ver — em segredo de justiça, a capa foi negada. |
| Recoletar para aplicar uma regra de vínculo nova | Gasta requisições para reprocessar dado que já está no banco. O bruto guardado tem tudo de que esta função precisa. |
| Derivar o vínculo na projeção, abandonando as colunas | `orfaos()` e `vinculos()` deixariam de ser SQL. A reprojeção mantém a coluna e recalcula seu conteúdo. |

## Limitações Conhecidas

- **Um processo tem no máximo um pai.** O modelo é uma floresta, não um grafo geral. Quando
  há mais de um vínculo válido, o segundo vira texto em `observacoes` — recuperável por
  leitura, não por consulta.

- **O grau do pai é inferido, nunca observado.** `incidente` assume mesmo grau; `recurso`
  assume grau 1. As duas inferências são corretas para o caso normal, mas nenhuma é lida da
  página. Um incidente que tramite em instância diferente da do processo principal seria
  registrado com o grau errado.

- **O tipo não é validado por ninguém depois daqui.** A [`projeção`](projecao.md) copia
  `reg.get("tipo_vinculo")` direto para o JSONL, sem conferir contra o vocabulário. Se um
  valor estranho entrasse na coluna por outro caminho, sairia na base final sem sinal.

- **`_dv_ok` reimplementa o cálculo que `NumeroProcesso.dv_esperado` já faz.** O módulo é
  puro e não importa o value object, o que mantém a independência ao custo de duas cópias
  da regra mais delicada do projeto. Registrado no
  [backlog](../../backlog.md#1-duplicacao-de-utilitarios).

- **`_PADRAO_PAI_MOV` embute a máscara CNJ em vez de reaproveitá-la.** Um ajuste na máscara
  (novo separador, sufixo) precisaria ser replicado aqui, e esta é a cópia mais fácil de
  esquecer porque está escondida dentro de outro padrão.

- **O rótulo `'processo principal'` no padrão é uma lista de uma frase só.** Se o e-SAJ
  escrever a origem de outra forma ("autos principais", "processo de origem"), a
  movimentação deixa de ser reconhecida — sem erro, sem observação: o processo simplesmente
  sai como `sem_vinculo`.

- **O ramo da capa de 2º grau sem 1ª instância não tem cobertura.** As duas capas de `cposg`
  em `data/spike/` — `00037068020208260554_g2` e `30000042520198260000_g2` — têm
  `processo_1a_instancia` preenchido (verificado com `scripts/v_checar_offline.py`), então o
  `elif` nunca é exercitado pelas fixtures atuais. A observação existe no código e ninguém a
  viu ser escrita.

- **A reprojeção corrige o tipo e o pai, mas não as observações.**
  [`SqliteStore.reprojetar_vinculos`](../store/sqlite_store.md) rechama esta função sobre o
  bruto guardado e regrava `tipo_vinculo`, `processo_pai` e `processo_pai_grau` — as três
  colunas. A quarta saída, `observacoes`, não: ela foi anexada ao `bruto` pelo `menu` no
  momento da coleta (`bruto["observacoes"] = vinc["observacoes"]`) e é dali que a
  [`projeção`](projecao.md) a lê.

    Na prática: mude uma regra que altere o **tipo** e a base inteira se corrige na próxima
    opção 4; mude a **mensagem** de uma observação, ou acrescente uma nova — como a de capa
    de 2º grau sem 1ª instância —, e os registros antigos continuam saindo com o texto do dia
    em que foram coletados, ao lado de um tipo já atualizado.

## Exemplo de Uso

A chamada única, em `scripts/menu.py`, no momento da gravação:

```python
# `tipo` do relacionamento tem UM único escritor: derivar_vinculo.
# Sem bruto (segredo de justiça, sem dados) o tipo é INDEFINIDO, não
# sem_vinculo: nunca chegamos a olhar a capa, então "não há sinal de
# pai" seria afirmação sobre algo que a coleta não observou.
vinc = {"tipo": INDEFINIDO, "processo_pai": None,
        "processo_pai_grau": None, "observacoes": []}
bruto = r.bruto
if bruto:
    vinc = derivar_vinculo(bruto, r.grau, numero)
    bruto = dict(bruto)
    bruto["observacoes"] = vinc["observacoes"]
```

As três chaves do retorno vão direto para colunas do banco; a quarta é anexada ao bruto e
chega à base final como `observacoes`:

```python
store.registrar_resultado(
    numero, r.grau, r.status, bruto=bruto,
    processo_pai=vinc["processo_pai"],
    processo_pai_grau=vinc["processo_pai_grau"],
    tipo_vinculo=vinc["tipo"], origem=origem,
)
```

O segundo chamador é a reprojeção, que passa a função em vez de importá-la — o store não
depende da camada de transformação:

```python
if bruto:
    v = derivar(bruto, linha["grau"], linha["processo"])
else:
    v = {"tipo": tipo_sem_bruto,
         "processo_pai": None, "processo_pai_grau": None}
```

Repare que a reprojeção consome só as **três** primeiras chaves. `observacoes` fica de fora,
e é a razão da limitação registrada acima.

## Testes e Validação

Não há testes automatizados neste repositório. O módulo é puro — recebe um dict, um inteiro
e uma string, devolve um dict — e não precisa de HTML nem de rede para ser exercitado: os
casos são construídos escrevendo o `bruto` à mão.

O que existe é `scripts/v_checar_offline.py`, que reprocessa os HTMLs de `data/spike/` sem
nenhuma requisição e **imprime** o vínculo derivado de cada capa. Não é teste — não há
asserção nem runner —, mas é a única execução do módulo sobre dado real. A saída de hoje,
para as capas que o classificador reconhece:

| Capa | Identidade | Tipo | Pai |
|---|---|---|---|
| `00002171920238260396` g1 | `CONFERE` | `incidente` | `10008582420228260396` |
| `00037068020208260554` g1 | `CONFERE` | `incidente` | `30132863020138260554` |
| `10008582420228260396` g1 | `CONFERE` | `sem_vinculo` | — |
| `30000042520198260000` g2 | `CONFERE` | `recurso` | `10110499020188260066` |
| `00037068020208260554` g2 | `DIVERGE` | `recurso` | `00037068020208260554` |

A última linha precisa de ressalva. O script analisa a capa **mesmo quando a identidade
diverge**, de propósito, para permitir inspeção — e a coleta real não faz isso: `coletar_um`
barra a página antes de chamar o parser, e o registro viraria `erro_transitorio`. Aquele
`recurso` é artefato do diagnóstico, não comportamento do pipeline. O que ele mostra, ainda
assim, é a forma da aresta `(N, 2) → (N, 1)` — a que a guarda de auto-referência tem de
deixar passar, e que só é representável porque a chave do banco é composta.

As quatro primeiras linhas são pipeline de verdade, e nenhuma delas exercita o `elif` novo:
as duas capas de 2º grau têm `processo_1a_instancia` preenchido.

As invariantes que valeria fixar, em ordem de gravidade:

- **auto-referência no link do topo** (`processo_principal` igual ao próprio número, mesmo
  grau) devolve `indefinido` e a observação correspondente — era o caminho que, no pipeline
  anterior, criava um processo filho de si mesmo;
- **a aresta `(N, 2) → (N, 1)`** é preservada: um bruto de 2º grau cujo
  `processo_1a_instancia` é o próprio número devolve `recurso` com
  `processo_pai_grau = 1`, **não** `indefinido`;
- link do topo e número de 1ª instância presentes juntos devolvem `incidente`, e o recurso
  aparece em `observacoes` — a regra de prioridade;
- entre duas movimentações citando processos principais diferentes, vence a de data mais
  antiga; se uma delas tiver data ilegível, ela **não** vence;
- uma movimentação que cita um CNJ sem a expressão `processo principal` antes **não** gera
  vínculo;
- pai com DV inválido devolve `indefinido` com observação, e `processo_pai` fica `None` —
  e continua devolvendo `indefinido` se a **mensagem** da observação for reescrita, que é o
  que o contador `descartados` garante;
- um bruto de **grau 1** sem nenhum sinal devolve `sem_vinculo` com `observacoes` vazia;
- um bruto de **grau 2** sem `processo_1a_instancia` nem `processo_1a_instancia_bruto`
  devolve `sem_vinculo` com **uma** observação — o único `sem_vinculo` que sai daqui com
  `observacoes` não vazia;
- **um banco gravado com a regra antiga converge para a nova** depois de uma
  `reprojetar_vinculos`: um `segredo_justica` com `tipo_vinculo = 'sem_vinculo'` passa a
  `indefinido` sem nenhuma requisição — e a segunda passada não altera mais nada.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os três pontos em aberto viraram correção de código; registrados aqui como decisões |
| 2026-08-11 | @alexandrehiero | `reprojetar_vinculos` no store: a limitação "corrigir vínculo exige recoleta" deixou de existir |

## Pontos em aberto

Nenhum. Os três itens registrados em 2026-08-10 viraram código, e a decisão de cada um está
acima:

| Ponto de 2026-08-10 | Onde ficou a decisão |
|---|---|
| Tipo decidido pelo texto de uma mensagem | "O tipo é decidido por um contador, não pelo texto das observações" |
| Registro sem `bruto` recebia `sem_vinculo` | "Sem bruto, o padrão é `indefinido`" (corrigido em `scripts/menu.py`) |
| Ausência de 1ª instância no 2º grau não gerava observação | "A capa de 2º grau sem número de 1ª instância deixa rastro" |

A limitação registrada em 2026-08-11 — "corrigir uma regra deste módulo não é uma
reprojeção" — foi resolvida por `reprojetar_vinculos` e virou a decisão "O vínculo voltou a
ser reprojetável". Restam em **Limitações Conhecidas** o ramo sem cobertura nas fixtures e o
fato de a reprojeção não reescrever as `observacoes`.
