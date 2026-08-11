# Limpeza e normalização – `src/transformers/limpeza.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re`, `unicodedata`, `datetime.date` (biblioteca padrão) — sem imports do projeto |

## Contexto e Motivação

Os [parsers](../scrapers/parser_base.md) devolvem texto como o portal escreveu: a classe
vem com o número do processo entre parênteses, a data vem como
`'09/01/2013 às 11:39 - Livre'`, o valor da causa vem como `'R$ 3.724,16'`. Este módulo é
onde esse texto vira dado.

A docstring liga a natureza do módulo à decisão central do projeto:

> Limpeza e normalização — módulo PURO (sem rede, sem I/O, testável isolado).
>
> É aqui que o texto bruto do parser vira dado utilizável. Rodar sobre o bruto
> guardado no SQLite significa que corrigir qualquer regra abaixo é uma
> REPROJEÇÃO local — nenhuma requisição nova.

A pureza não é preferência estilística — é o que torna a arquitetura viável. Se qualquer
função daqui tocasse a rede ou o disco, corrigir uma regra de limpeza deixaria de ser uma
operação local. Como todas recebem valor e devolvem valor, a opção 4 do
[`menu`](../../scripts/menu.md) reprojeta a base inteira a partir do que já está no banco.

Há também um objetivo de consolidação declarado:

> Substitui as QUATRO implementações de data espalhadas pelo pipeline IAMSPE
> (_chave_data, _iso_para_br, _br_para_iso e nenhuma no normalizador).

Quatro implementações da mesma conversão, e a quarta era a ausência dela — o normalizador
simplesmente não convertia. O resultado eram datas em três formatos na mesma base.

## Decisões de Arquitetura

### `None` em vez de string vazia ou sentinela

```python
def limpar_texto(valor):
    """Colapsa espaços e devolve None (não string vazia) quando não há conteúdo.

    None em vez de sentinela: a sentinela era convertida para None no fim do
    pipeline de qualquer forma, e strings em campos numéricos quebram $avg/$sum
    no Mongo e forçam dtype=object no pandas.
    """
```

A justificativa é operacional e vale para todo o módulo. Sentinelas do tipo
`"NÃO INFORMADO"` parecem informativas até chegarem ao consumo: no Mongo, um campo que
mistura número e string quebra `$avg` e `$sum`; no pandas, força `dtype=object` e desliga
todas as operações vetorizadas da coluna. E como o pipeline anterior convertia a sentinela
para `None` no fim de qualquer forma, ela só existia para ser desfeita.

A regra atravessa as quatro funções de conversão: `limpar_texto`, `limpar_classe`,
`data_para_iso` e `valor_para_float` devolvem `None` quando não há o que devolver. Ausência
é representada de um jeito só.

### `limpar_classe` remove **todo** conteúdo entre parênteses

```python
def limpar_classe(valor):
    """Remove TODO conteúdo entre parênteses da classe.

    Cobre os três casos reais: o número do próprio processo
    ('Cumprimento de Sentença contra a Fazenda Pública (0000010-31...)'),
    sequenciais ('(06)') e referências legais ('(Lei nº 9.099/95)').
    O laço trata parênteses aninhados/múltiplos.
    """
```

Uma regra abrangente em vez de três regras específicas. Os três casos listados são reais e
não têm nada em comum a não ser estarem entre parênteses — tentar reconhecer "número de
processo", "sequencial" e "referência legal" separadamente exigiria três padrões que
poderiam falhar de três maneiras. Remover tudo entre parênteses falha de uma maneira só, e
é uma decisão reversível: o texto original continua no banco.

O laço existe porque `_PARENTESES` casa apenas parênteses sem aninhamento
(`\([^()]*\)`); repetir a substituição até o texto parar de mudar resolve aninhados e
múltiplos:

```python
anterior = None
while anterior != texto:  # múltiplos/aninhados
    anterior = texto
    texto = _PARENTESES.sub(" ", texto)
```

A limpeza final remove pontuação órfã das pontas (`strip(" -–—:;,")`) — o resíduo típico de
quando o parêntese removido estava depois de um travessão.

### ISO para datas, e nunca inventar uma

```python
def data_para_iso(valor):
    """'09/01/2013 às 11:39 - Livre' -> '2013-01-09'. None se não houver data.

    ISO porque é ordenável como string, filtrável por intervalo no Mongo e
    interpretável por qualquer ferramenta. Nunca 'inventa' data.
    """
```

O formato `AAAA-MM-DD` tem uma propriedade que `DD/MM/AAAA` não tem: a ordem lexicográfica
coincide com a ordem cronológica. Isso significa que ordenar, comparar e filtrar por
intervalo funcionam sem converter para tipo de data — em SQL, no Mongo, no pandas ou numa
planilha.

O "nunca inventa" é o complemento necessário: a função extrai a data do texto ou devolve
`None`. Ela não infere, não completa ano de dois dígitos, não assume o dia 1 quando só há
mês. Um `None` é filtrável; uma data inventada é indistinguível de uma observada.

### A data é validada pelo calendário, não por faixa

```python
# Validar por faixa (mes<=12, dia<=31) aceitava 31/02/2020 e devolvia
# '2020-02-31' — string ISO que não corresponde a data nenhuma, gravada no
# JSONL e quebrando só na importação. date() rejeita na origem e ainda
# acerta ano bissexto (29/02/2024 passa, 30/02/2024 não).
for m in _DATA_BR.finditer(str(valor)):
    dia, mes, ano = m.groups()
    try:
        return date(int(ano), int(mes), int(dia)).isoformat()
    except ValueError:
        continue  # data impossível: tenta a próxima ocorrência do texto
```

A validação anterior era campo a campo — `1 <= mes <= 12` e `1 <= dia <= 31` — e cada campo
passava isoladamente em `'31/02/2020'`. O que saía era `'2020-02-31'`: uma string ISO
sintaticamente impecável, que nenhum calendário resolve. Ela ia para o JSONL sem erro e sem
observação, e só falharia lá na frente, na importação, longe do lugar onde a causa está.
Delegar a `datetime.date` troca "parece uma data" por "**é** uma data", e ainda resolve de
graça o caso que qualquer validação artesanal erra: `29/02/2024` passa (bissexto),
`30/02/2024` não.

A segunda metade da correção é o `finditer` no lugar do `search`. Com uma única tentativa,
encontrar uma data impossível encerrava a busca e a função devolvia `None` mesmo havendo uma
data boa adiante no mesmo texto — a validação teria trocado um erro (data falsa) por outro
(dado perdido). Iterando, `'31/02/2020 e 01/03/2020'` devolve `'2020-03-01'`. O contrato
segue sendo "a primeira data **válida** do texto".

### Normalização serve para **comparar**, não para armazenar

Esta é a decisão mais sutil do módulo e a que mais protege o dado.

```python
def _chave_dedup(texto):
    """Chave de comparação: minúsculas, sem acento, espaços colapsados.
    Faz 'MICHELE DIAS' e 'Michele  Dias' colidirem como o mesmo nome."""
```

```python
def dedup_nomes(itens):
    """Remove duplicatas e vazios preservando a ordem. A GRAFIA guardada é a da
    primeira aparição — nada é reescrito."""
```

A forma normalizada — sem acento, minúscula — é usada **só** como chave de conjunto. O que
vai para a base é a grafia original. Um pipeline que gravasse a forma normalizada
destruiria informação (acentuação de nomes próprios, caixa correta) para resolver um
problema de comparação, e o dado não teria como voltar.

A ordem de aparição também é preservada: `dedup_nomes` mantém uma lista com `set` auxiliar
em vez de devolver o próprio `set`. Numa lista de partes, a ordem em que o portal as
apresenta carrega informação.

### `dedup_movimentacoes` ordena **depois** de converter

```python
def dedup_movimentacoes(movs):
    """Dedup por (data ISO, descrição normalizada) e ordena da mais antiga para
    a mais recente. O e-SAJ entrega em ordem decrescente; a ordenação só é
    correta DEPOIS da conversão para ISO."""
```

Ordenar `'09/01/2013'` como string agrupa por dia, depois mês, depois ano — uma ordem que
não significa nada. A conversão precisa vir primeiro, e é por isso que dedup e ordenação
moram na mesma função em vez de serem duas etapas independentes.

A chave de dedup é o par `(data ISO, descrição normalizada)`: a mesma movimentação repetida
com grafias diferentes colide; movimentações com o mesmo texto em datas diferentes, não.

E as datas ilegíveis vão para o fim, nunca para o começo:

```python
saida.sort(key=lambda m: (m["data"] is None, m["data"] or ""))
```

O primeiro elemento da tupla é `False` (0) para datas conhecidas e `True` (1) para `None`,
o que joga os desconhecidos para o fim. Sem isso, `None` ou string vazia ordenaria antes de
qualquer data e uma movimentação sem data legível viraria "a mais antiga" — que é
exatamente a que o [`vinculo`](vinculo.md) usa para decidir a origem de um processo. A
mesma proteção aparece lá, em `_chave_data`.

### `valor_para_float` busca em dois passos, e a ordem dos passos é a decisão

```python
# Dois passos, e a ordem é o ponto. Alternação num regex só resolve pelo padrão
# MAIS À ESQUERDA, não pelo mais específico: em 'em 2024: R$ 3.724,16' o '2024'
# vencia e produzia 2024.0. Procurando primeiro QUALQUER valor com centavos em
# toda a string, o ano deixa de competir com o valor.
_VALOR_COM_CENTAVOS = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}")
_VALOR_SEM_CENTAVOS = re.compile(r"\d{1,3}(?:\.\d{3})+|\d+")
```

```python
texto = str(valor)
m = _VALOR_COM_CENTAVOS.search(texto) or _VALOR_SEM_CENTAVOS.search(texto)
```

Há duas correções empilhadas aqui, e vale separá-las porque a segunda é uma armadilha
clássica de expressão regular.

**A primeira**: a versão original não tinha padrão nenhum — apagava da string tudo que não
fosse dígito ou vírgula e convertia o que sobrasse. `'R$ 3.724,16 - atualizado em 2024'`
produzia **`3724.162024`**: um número plausível, errado por três ordens de grandeza, sem
erro e sem observação.

**A segunda**: a correção seguinte usou uma alternação única, com os formatos ordenados do
mais específico para o menos, na expectativa de que o mais específico vencesse. Não é assim
que funciona. Uma alternação resolve pela posição **mais à esquerda** que casar com
*qualquer* ramo; a ordem dos ramos só desempata entre candidatos que começam no **mesmo
ponto**. Em `'em 2024: R$ 3.724,16'`, o `2024` aparece antes, casa o último ramo (`\d+`) e
vence — a função devolvia `2024.0`.

Separar em dois padrões converte a preferência de formato numa preferência de **passo**: o
primeiro `search` varre a string inteira atrás de um valor com centavos, e só se não houver
nenhum o segundo aceita um inteiro solto. O ano deixa de competir com o valor porque não
está na mesma disputa.

| Passo | Casa | Exemplos |
|---|---|---|
| `_VALOR_COM_CENTAVOS` | milhar com centavos, centavos sem milhar | `540.000,00`, `678,00` |
| `_VALOR_SEM_CENTAVOS` | milhar sem centavos, inteiro simples | `1.234`, `1234` |

Dentro de cada passo a alternação continua ordenada do mais específico para o menos, pelo
mesmo motivo de antes: sem `\d{1,3}(?:\.\d{3})+,\d{2}` vindo primeiro, `'3.724,16'` casaria
o ramo `\d+,\d{2}` a partir do `724` e devolveria `724.16`.

A conversão que segue é a mesma — ponto fora, vírgula vira ponto —, mas opera sobre o trecho
casado, não sobre a string inteira.

### `valor_para_float` aceita o que já é número

```python
if isinstance(valor, (int, float)):
    return float(valor)
```

Torna a função idempotente: reprojetar uma base já projetada não quebra. É coerente com o
papel do módulo — as funções são aplicadas sobre o bruto, mas nada impede que sejam
reaproveitadas sobre dado já convertido.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Sentinela textual (`"NÃO INFORMADO"`) para ausência | Quebra `$avg`/`$sum` no Mongo e força `dtype=object` no pandas. No pipeline anterior ela era convertida para `None` no fim de qualquer forma. |
| String vazia em vez de `None` | Duas representações de ausência na mesma base; `""` é um valor válido que passa em testes de existência. |
| Limpar a classe com padrões específicos por caso (número, sequencial, lei) | Três padrões que podem falhar de três maneiras, contra um que falha de uma. E a decisão é reversível: o texto original está no banco. |
| Manter a data em `DD/MM/AAAA` | A ordem lexicográfica não coincide com a cronológica; ordenar e filtrar por intervalo exigiria converter em todo ponto de consumo. |
| Converter para `datetime` em vez de string ISO | O destino é JSON e depois `mongoimport`. Um `datetime` exigiria serialização própria; a string ISO atravessa o pipeline sem tratamento especial. |
| Inferir data faltante (ano de dois dígitos, dia 1 do mês) | Uma data inventada é indistinguível de uma observada depois de gravada. `None` é filtrável. |
| Validar a data por faixa (`mes<=12`, `dia<=31`) | `'31/02/2020'` passa nos dois testes e produz `'2020-02-31'` — ISO bem formada que não é data. Falharia só na importação. |
| Parar na primeira ocorrência do padrão de data | Uma data impossível encerraria a busca e mataria a data válida seguinte do mesmo texto: trocaria dado errado por dado perdido. |
| Limpar a string inteira com `re.sub(r"[^\d,]", "", ...)` | Absorve qualquer outro número do campo: `'R$ 3.724,16 - atualizado em 2024'` vira `3724.162024`, sem erro e sem observação. |
| Um único padrão `\d[\d.]*,\d{2}` para o valor | Não casaria valores sem centavos (`'R$ 1.234'`), que o portal também exibe. |
| Uma alternação única, com os formatos do mais específico para o menos | Foi a primeira tentativa e não resolve: a alternação escolhe a posição mais à esquerda que casar com qualquer ramo. Em `'em 2024: R$ 3.724,16'` o ano vencia pelo ramo `\d+`. |
| Ancorar o valor em `R$` | Perderia os campos que o portal exibe sem o símbolo — `'678,00'` é um deles. Os dois passos filtram por formato, não por prefixo. |
| Gravar o nome normalizado (sem acento, minúsculo) | Destruiria acentuação e caixa de nomes próprios para resolver um problema de comparação, sem possibilidade de reverter. |
| `dedup_nomes` devolvendo `set` | Perderia a ordem de aparição, que carrega informação sobre como o portal apresenta as partes. |
| Comparação difusa (`thefuzz`) para nomes | Uniria nomes distintos que se parecem. A dedup aqui é conservadora de propósito: só colide o que é o mesmo texto a menos de acento, caixa e espaço. |
| Ordenar as movimentações antes de converter para ISO | Ordenaria por dia, depois mês, depois ano. |
| Ordenar com `None` no começo | Uma movimentação sem data legível viraria "a mais antiga" — e é a mais antiga que o `vinculo` usa para determinar a origem do processo. |

## Limitações Conhecidas

- **A dedup não faz correspondência difusa, de propósito.** `'João da Silva'` e
  `'Joao da Silva'` colidem (o acento some na chave); `'João da Silva'` e `'J. da Silva'`
  não. É a escolha conservadora: unir demais cria partes que não existem, e o efeito é
  irreversível na base final.

- **O nome do campo muda entre o bruto e a projeção.** O parser produz
  `{"data", "descricao"}`; `dedup_movimentacoes` devolve `{"data", "movimento"}`. Quem
  comparar o bruto guardado no SQLite com o JSONL final precisa saber disso — não há nada
  no código que registre a correspondência.

- **`limpar_classe` remove parênteses legítimos.** Uma classe cujo nome oficial contenha
  parênteses informativos perde essa parte. Não há caso conhecido no TJSP, mas a regra é
  deliberadamente abrangente e não distingue.

- **Dentro de cada passo, quem decide ainda é a posição.** Os dois passos resolvem a
  competição entre *classes* de número — nenhum ano vence um valor com centavos —, mas não a
  competição dentro da mesma classe. Verificado:

  | Entrada | Saída | Leitura |
  |---|---|---|
  | `'R$ 3.724,16 - atualizado em 2024'` | `3724.16` | texto depois do valor: correto |
  | `'em 2024: R$ 3.724,16'` | `3724.16` | ano antes do valor: correto |
  | `'Custas 12,50 - Valor R$ 3.724,16'` | `12.5` | **dois** valores com centavos: vence o primeiro |
  | `'2024: 1.234'` | `2024.0` | nenhum valor com centavos: vence o primeiro inteiro |

  O campo de origem é `#valorAcaoProcesso`, que hoje traz só o valor, então nenhuma das duas
  últimas linhas ocorre na prática. A fragilidade que resta é sobre o que aconteceria se o
  portal passasse a anexar outro número **do mesmo formato** no mesmo campo.

- **`_DATA_BR` exige dia e mês com dois dígitos** (`\b(\d{2})/(\d{2})/(\d{4})\b`):
  `'9/1/2013'` devolve `None`. O e-SAJ preenche com zero à esquerda em todas as capas
  observadas em `data/spike/`, então a restrição não perde dado hoje — mas ela é do padrão,
  não do calendário, e nada avisaria se uma redação nova aparecesse.

- **`_chave_dedup` usa `casefold()` enquanto `_norm` (em `page_state.py` e
  `parser_base.py`) usa `lower()`.** As três funções fazem a mesma normalização com uma
  diferença de semântica Unicode. Está registrado no
  [backlog](../../backlog.md#1-duplicacao-de-utilitarios).

- **`_chave_dedup` levanta `TypeError` se receber `None`.** Os dois chamadores garantem
  string não vazia antes de chamar, mas a função é pública o bastante (sem prefixo de
  módulo privado no uso interno) para ser reaproveitada sem essa garantia.

## Exemplo de Uso

Todas as funções são consumidas por [`projecao.projetar`](projecao.md), no ramo de
`coletado`:

```python
final["situacao"] = limpar_texto(bruto.get("situacao"))
final["classe"] = limpar_classe(bruto.get("classe"))
final["assunto_principal"] = limpar_texto(bruto.get("assunto"))
final["foro"] = limpar_texto(bruto.get("foro"))
final["vara"] = limpar_texto(bruto.get("vara"))
final["juiz"] = limpar_texto(bruto.get("juiz"))
final["valor_acao"] = valor_para_float(bruto.get("valor"))
final["data_distribuicao"] = data_para_iso(bruto.get("data_distribuicao"))
```

A dedup de partes, aplicada por polo:

```python
return {"pessoas": dedup_nomes(pessoas), "representantes": dedup_nomes(reps)}
```

E as movimentações:

```python
final["movimentacoes"] = dedup_movimentacoes(bruto.get("movimentacoes"))
```

`limpar_texto` também é usada na desduplicação final das observações, o que mostra que ela
não é só para campos de capa:

```python
final["observacoes"] = [
    o for o in (limpar_texto(x) for x in obs)
    if o and not (o in vistos or vistos.add(o))
]
```

## Testes e Validação

Não há testes automatizados neste repositório — e este é o módulo em que essa ausência é
mais fácil de resolver. Todas as funções são puras, sem I/O, sem dependências do projeto, e
as próprias docstrings já trazem os pares entrada/saída.

O que existe de mais próximo de regressão no repositório é
[`scripts/v_checar_offline.py`](../../backlog.md#6-ausencia-de-testes), que reprocessa os
HTMLs de `data/spike/` sem nenhuma requisição — e ele **não exercita este módulo**: para no
parser e no vínculo, antes da projeção. Nada aqui é verificado automaticamente.

A tabela abaixo é o resultado de conferência **manual**, chamando as funções no
interpretador. Os três primeiros valores são os que aparecem nas capas reais do spike:

| Função | Entrada | Saída |
|---|---|---|
| `valor_para_float` | `'R$ 4.832,96'` | `4832.96` |
| `valor_para_float` | `'R$ 540.000,00'` | `540000.0` |
| `valor_para_float` | `'678,00'` | `678.0` |
| `valor_para_float` | `'R$ 3.724,16 - atualizado em 2024'` | `3724.16` |
| `valor_para_float` | `'em 2024: R$ 3.724,16'` | `3724.16` |
| `valor_para_float` | `'R$ 1.234'` | `1234.0` (sem centavos, segundo passo) |
| `valor_para_float` | `'Custas 12,50 - Valor R$ 3.724,16'` | `12.5` (limitação: dois valores da mesma classe) |
| `data_para_iso` | `'09/01/2013 às 11:39 - Livre'` | `'2013-01-09'` |
| `data_para_iso` | `'29/02/2024'` / `'30/02/2024'` | `'2024-02-29'` / `None` |
| `data_para_iso` | `'31/02/2020'` | `None` |
| `data_para_iso` | `'31/02/2020 e 01/03/2020'` | `'2020-03-01'` |
| `limpar_classe` | `'Cumprimento de Sentença contra a Fazenda Pública (0000010-31...)'` | sem os parênteses |
| `_chave_dedup` | `'MICHELE DIAS'` e `'Michele  Dias'` | mesma chave |

As invariantes que valeria fixar, além dos exemplos acima:

- toda função devolve `None` — nunca `''` — para entrada vazia ou não convertível;
- `limpar_classe` resolve parênteses aninhados e múltiplos numa passada;
- `dedup_nomes` preserva a **grafia da primeira aparição**, não a normalizada, e mantém a
  ordem;
- `dedup_movimentacoes` devolve em ordem crescente de data, com as datas `None` **no fim**;
- `valor_para_float(3724.16)` devolve `3724.16` — idempotência sobre valor já convertido;
- **um valor com centavos vence um ano que apareça antes dele** — o caso que a alternação
  única errava, e a razão de a busca ter dois passos.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os dois pontos em aberto viraram correção de código; registrados aqui como decisões |
| 2026-08-11 | @alexandrehiero | Busca do valor em dois passos: a alternação única resolvia pelo padrão mais à esquerda, não pelo mais específico |

## Pontos em aberto

Nenhum. Os dois itens registrados em 2026-08-10 viraram código, e a decisão de cada um está
acima:

| Ponto de 2026-08-10 | Onde ficou a decisão |
|---|---|
| `data_para_iso` aceitava datas inexistentes | "A data é validada pelo calendário, não por faixa" |
| `valor_para_float` era ganancioso sobre a string inteira | "`valor_para_float` busca em dois passos" |

A pendência que a primeira correção do valor tinha deixado — a âncora resolver por posição e
não por formato — foi fechada pelos dois passos. O que resta é mais estreito e está em
**Limitações Conhecidas**: dentro da **mesma** classe de número, o primeiro do texto ainda
vence.
