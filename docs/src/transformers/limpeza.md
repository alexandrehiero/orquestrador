# Limpeza e normalização – `src/transformers/limpeza.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re`, `unicodedata`, `datetime` — sem imports do projeto |

## Contexto e Motivação

Os [parsers](../scrapers/parser_base.md) devolvem texto como o portal escreveu: a classe vem com o número entre parênteses, a data como `'09/01/2013 às 11:39 - Livre'`, o valor como `'R$ 3.724,16'`. Este módulo é onde esse texto vira dado.

**A pureza não é preferência estilística — é o que torna a arquitetura viável.** Se qualquer função daqui tocasse a rede ou o disco, corrigir uma regra de limpeza deixaria de ser operação local. Como todas recebem valor e devolvem valor, a opção 4 reprojeta a base inteira a partir do que já está no banco.

Há também consolidação: o módulo substitui as **quatro** implementações de data espalhadas pelo pipeline IAMSPE (`_chave_data`, `_iso_para_br`, `_br_para_iso` e a ausência dela no normalizador). Quatro implementações da mesma conversão — e a quarta era não converter —, resultando em datas em três formatos na mesma base.

## Decisões de Arquitetura

- **`None` em vez de string vazia ou sentinela** — sentinelas como `"NÃO INFORMADO"` parecem informativas até chegarem ao consumo: no Mongo quebram `$avg`/`$sum`; no pandas forçam `dtype=object` e desligam as operações vetorizadas da coluna. E o pipeline anterior as convertia para `None` no fim de qualquer forma — ela só existia para ser desfeita. A regra vale nas quatro funções: ausência tem uma representação só.
- **`limpar_classe` remove TODO conteúdo entre parênteses** — uma regra abrangente em vez de três específicas. Os três casos reais (número do próprio processo, sequenciais como `(06)`, referências legais como `(Lei nº 9.099/95)`) não têm nada em comum além dos parênteses. Três padrões podem falhar de três maneiras; um falha de uma — e é reversível, porque o texto original está no banco.
- **O laço trata aninhados e múltiplos** — `_PARENTESES` casa apenas parênteses sem aninhamento, então a substituição se repete até o texto parar de mudar. O `strip(" -–—:;,")` final remove a pontuação órfã típica de quando o parêntese vinha depois de um travessão.
- **ISO para datas** — em `AAAA-MM-DD` a ordem lexicográfica coincide com a cronológica, então ordenar, comparar e filtrar por intervalo funcionam sem converter para tipo de data: em SQL, no Mongo, no pandas ou numa planilha.
- **Nunca inventa data** — a função extrai do texto ou devolve `None`. Não infere, não completa ano de dois dígitos, não assume dia 1. Um `None` é filtrável; uma data inventada é indistinguível de uma observada.
- **A data é validada pelo calendário, não por faixa** — `1 <= mes <= 12` e `1 <= dia <= 31` passam isoladamente em `'31/02/2020'`, produzindo `'2020-02-31'`: ISO sintaticamente impecável que nenhum calendário resolve, gravada sem erro e falhando só na importação, longe da causa. `datetime.date` troca "parece uma data" por "**é** uma data" e ainda acerta bissexto de graça.
- **`finditer`, não `search`** — com uma tentativa só, uma data impossível encerrava a busca e a função devolvia `None` mesmo havendo data boa adiante: a validação teria trocado um erro (data falsa) por outro (dado perdido). O contrato é "a primeira data **válida** do texto".
- **Normalização serve para comparar, não para armazenar** — a forma sem acento e minúscula é usada **só** como chave de conjunto; o que vai para a base é a grafia da primeira aparição. Gravar a forma normalizada destruiria acentuação e caixa de nomes próprios para resolver um problema de comparação, sem possibilidade de reverter.
- **`dedup_nomes` preserva a ordem de aparição** — mantém lista com `set` auxiliar em vez de devolver o `set`. Numa lista de partes, a ordem em que o portal as apresenta carrega informação.
- **`dedup_movimentacoes` ordena DEPOIS de converter** — ordenar `'09/01/2013'` como string agrupa por dia, depois mês, depois ano: uma ordem que não significa nada. É por isso que dedup e ordenação moram na mesma função. A chave é o par `(data ISO, descrição normalizada)`.
- **Datas ilegíveis vão para o fim, nunca para o começo** — sem isso, uma movimentação sem data legível viraria "a mais antiga", que é exatamente a que o [`vinculo`](vinculo.md) usa para decidir a origem de um processo.
- **`valor_para_float` busca em dois passos, e a ordem dos passos é a decisão** — há duas correções empilhadas. A original apagava tudo que não fosse dígito ou vírgula: `'R$ 3.724,16 - atualizado em 2024'` virava **`3724.162024`**, plausível e errado por três ordens de grandeza. A segunda tentativa usou alternação única com os formatos do mais específico ao menos — e **não é assim que alternação funciona**: ela resolve pela posição **mais à esquerda** que casar com *qualquer* ramo, e a ordem só desempata candidatos que começam no mesmo ponto. Em `'em 2024: R$ 3.724,16'` o ano vencia pelo ramo `\d+`. Dois padrões separados convertem preferência de formato em preferência de **passo**: o primeiro varre a string inteira atrás de um valor com centavos, e o ano deixa de competir porque não está na mesma disputa.
- **`valor_para_float` aceita o que já é número** — torna a função idempotente: reprojetar uma base já projetada não quebra.

| Passo | Casa | Exemplos |
|---|---|---|
| `_VALOR_COM_CENTAVOS` | milhar com centavos, centavos sem milhar | `540.000,00`, `678,00` |
| `_VALOR_SEM_CENTAVOS` | milhar sem centavos, inteiro simples | `1.234`, `1234` |

Dentro de cada passo a alternação continua ordenada do mais específico para o menos: sem `\d{1,3}(?:\.\d{3})+,\d{2}` vindo primeiro, `'3.724,16'` casaria `\d+,\d{2}` a partir do `724` e devolveria `724.16`.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Sentinela textual (`"NÃO INFORMADO"`) para ausência | Quebra `$avg`/`$sum` no Mongo e força `dtype=object` no pandas. No pipeline anterior era convertida para `None` no fim de qualquer forma. |
| String vazia em vez de `None` | Duas representações de ausência na mesma base; `""` é um valor válido que passa em testes de existência. |
| Limpar a classe com padrões específicos por caso | Três padrões que podem falhar de três maneiras, contra um que falha de uma. E a decisão é reversível: o texto original está no banco. |
| Manter a data em `DD/MM/AAAA` | A ordem lexicográfica não coincide com a cronológica; ordenar e filtrar exigiria converter em todo ponto de consumo. |
| Converter para `datetime` em vez de string ISO | O destino é JSON e depois `mongoimport`. Um `datetime` exigiria serialização própria. |
| Inferir data faltante (ano de dois dígitos, dia 1 do mês) | Uma data inventada é indistinguível de uma observada depois de gravada. `None` é filtrável. |
| Validar a data por faixa (`mes<=12`, `dia<=31`) | `'31/02/2020'` passa nos dois testes e produz `'2020-02-31'` — ISO bem formada que não é data. Falharia só na importação. |
| Parar na primeira ocorrência do padrão de data | Uma data impossível encerraria a busca e mataria a data válida seguinte do mesmo texto. |
| Limpar a string inteira com `re.sub(r"[^\d,]", "", ...)` | Absorve qualquer outro número do campo: `'R$ 3.724,16 - atualizado em 2024'` vira `3724.162024`, sem erro e sem observação. |
| Um único padrão `\d[\d.]*,\d{2}` para o valor | Não casaria valores sem centavos (`'R$ 1.234'`), que o portal também exibe. |
| Uma alternação única, do formato mais específico ao menos | Foi a primeira tentativa e não resolve: a alternação escolhe a posição mais à esquerda que casar com qualquer ramo. |
| Ancorar o valor em `R$` | Perderia os campos que o portal exibe sem o símbolo — `'678,00'` é um deles. |
| Gravar o nome normalizado (sem acento, minúsculo) | Destruiria acentuação e caixa de nomes próprios para resolver um problema de comparação, sem reverter. |
| `dedup_nomes` devolvendo `set` | Perderia a ordem de aparição, que carrega informação sobre como o portal apresenta as partes. |
| Comparação difusa (`thefuzz`) para nomes | Uniria nomes distintos que se parecem. A dedup é conservadora de propósito. |
| Ordenar as movimentações antes de converter para ISO | Ordenaria por dia, depois mês, depois ano. |
| Ordenar com `None` no começo | Uma movimentação sem data legível viraria "a mais antiga" — e é a mais antiga que o `vinculo` usa para determinar a origem. |

## Limitações Conhecidas

- **A dedup não faz correspondência difusa, de propósito.** `'João da Silva'` e `'Joao da Silva'` colidem; `'João da Silva'` e `'J. da Silva'` não. Unir demais cria partes que não existem, e o efeito é irreversível na base final.
- **O nome do campo muda entre o bruto e a projeção.** O parser produz `{"data", "descricao"}`; `dedup_movimentacoes` devolve `{"data", "movimento"}`. Nada no código registra a correspondência.
- **`limpar_classe` remove parênteses legítimos.** Não há caso conhecido no TJSP, mas a regra é deliberadamente abrangente e não distingue.
- **Dentro de cada passo, quem decide ainda é a posição.** Os dois passos resolvem a competição entre *classes* de número, não dentro da mesma classe: `'Custas 12,50 - Valor R$ 3.724,16'` devolve `12.5`. O campo de origem (`#valorAcaoProcesso`) hoje traz só o valor, então o caso não ocorre na prática.
- **`_DATA_BR` exige dia e mês com dois dígitos.** Uma data escrita `9/1/2013` não é reconhecida.

## Exemplo de Uso

Todas as funções são puras e aplicadas pela [projeção](projecao.md) sobre o bruto guardado. Os valores abaixo foram conferidos à mão no interpretador; os três primeiros são de capas reais de `data/spike/`.

```python
from src.transformers.limpeza import data_para_iso, dedup_nomes, valor_para_float

valor_para_float('R$ 4.832,96')                      # 4832.96
valor_para_float('em 2024: R$ 3.724,16')             # 3724.16  <- o ano não compete
valor_para_float('R$ 1.234')                         # 1234.0   <- 2º passo, sem centavos
data_para_iso('09/01/2013 às 11:39 - Livre')         # '2013-01-09'
data_para_iso('31/02/2020')                          # None     <- data impossível
data_para_iso('31/02/2020 e 01/03/2020')             # '2020-03-01'  <- a 1ª VÁLIDA
data_para_iso('29/02/2024'), data_para_iso('30/02/2024')   # '2024-02-29', None
dedup_nomes(['MICHELE DIAS', 'Michele  Dias'])       # ['MICHELE DIAS']  <- grafia da 1ª
```

## Testes e Validação

Não há suíte automatizada — e **este é o módulo em que essa ausência é mais fácil de resolver**: funções puras, sem I/O, sem dependências do projeto, com os pares entrada/saída já nas docstrings. `scripts/checar_offline.py` **não** o exercita: para no parser e no vínculo, antes da projeção. A tabela acima é conferência manual; nada disso é reexecutado por ninguém. As 6 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os dois pontos em aberto viraram correção de código; registrados como decisões |
| 2026-08-11 | @alexandrehiero | Busca do valor em dois passos: a alternação única resolvia pelo padrão mais à esquerda, não pelo mais específico |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 8 decisões virou lista de tópicos; a tabela de conferência manual virou o Exemplo de Uso; invariantes migradas para o backlog de testes |
