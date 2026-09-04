# Parser de 2º grau – `src/scrapers/parser_segundo_grau.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re`; herda de `src/scrapers/parser_base.py` |

## Contexto e Motivação

A capa de `cposg` não é variação cosmética da de `cpopg`. Ela tem uma seção que não existe no 1º grau — "Números de 1ª Instância" — e é justamente essa seção que carrega a informação mais delicada do módulo.

**Um recurso e um incidente são vínculos de naturezas diferentes, e a mesma capa pode exibir os dois.** Se fossem gravados no mesmo campo, o grafo passaria a misturar "este processo subiu de instância" com "este processo nasceu de outro". O parser não decide qual vale — mantém os dois separados, e a decisão fica com [`vinculo`](../transformers/vinculo.md), único escritor do tipo de relacionamento.

A advertência do próprio código: *"os seletores de cposg variam mais que os de cpopg. Confirmar num agravo real antes da coleta em massa."*

## Decisões de Arquitetura

- **O relator ocupa o campo `juiz`** — mesma cascata de três passos do [1º grau](parser_primeiro_grau.md), com os rótulos daqui (inclusive `"Relator(a)"`, que o portal usa) e a mesma desistência explícita no fim. Reaproveitar o campo mantém **uma coluna só** na base final: quem analisar "processos por magistrado" não precisa unir dois campos nem saber o grau de antemão, e quem quiser separar tem o campo `grau` ao lado.
- **`_extrair_foro` e `_extrair_vara` perdem o fallback por rótulo, de propósito** — é a decisão mais fácil de reverter por engano e a mais cara. A tabela "Números de 1ª Instância" tem colunas cujos cabeçalhos são exatamente `Foro`, `Vara` e `Juiz`; o `_rotulo_estrito` da base os encontraria e devolveria o foro **do processo de origem** como se fosse o do recurso. Não seria campo vazio nem erro: seria dado plausível e errado.
- **A seção é varrida a partir do título, não localizada por uma tabela** — a abordagem natural ("ache a tabela cujo cabeçalho contém Foro e Vara") falha em silêncio contra o HTML real, porque o e-SAJ quebra a seção em **duas** tabelas: uma só com o cabeçalho e uma linha vazia, outra com os dados. A busca natural encontra a primeira.
- **A varredura para no próximo título — e é SÓ isso que a delimita** — sem o `break`, `find_all_next` alcançaria a tabela de movimentações, onde despachos citam números de origem em prosa (*"Anote-se que os autos de origem possuem o nº…"*). Um número mencionado de passagem viraria vínculo de recurso, e **uma aresta falsa é pior que uma ausente**, porque nada a distingue de uma verdadeira depois de gravada.
- **Qualquer número localiza a célula; o filtro de CNJ fica no `parse()`** — o filtro anterior (`_cnj_de_texto`) parecia segunda linha de defesa, mas era redundante com a parada no próximo título **e destrutivo**. `_celula_1a_instancia` só devolvia texto que já continha CNJ, então a condição `celula and not cnj` nunca podia ser satisfeita: `processo_1a_instancia_bruto` era inalcançável por construção, e com ele o ramo de observação. Um número como `'26747/2005'` — que existe, porque processos anteriores ao padrão CNJ ainda tramitam — era **descartado em silêncio**.
- **O atalho por `id` usa o mesmo critério da varredura** — manter o filtro de CNJ só no atalho parecia inofensivo, porque um valor rejeitado cairia para a varredura. Mas o fallback só funciona quando existe o que varrer: numa capa que exponha o número **apenas** pelo `id`, sem a seção em forma de tabela, o número antigo se perde — descartado pelo próprio caminho que acabara de encontrá-lo. A lição se repete: **filtro de formato em quem localiza produz descarte silencioso.**
- **O cabeçalho é procurado com prioridade e por texto direto** — prioriza `h2`/`h3`/`h4` e só depois cai para outros elementos, exigindo texto direto. Um `<div>` que envolve meia página "contém" o título; aceito como cabeçalho, faria `find_all_next` começar de um ponto arbitrário e anularia a guarda do próximo título.
- **O cabeçalho da tabela usa `<td class="label">`, não `<th>`** — uma varredura que assumisse HTML semântico leria a linha de cabeçalho como dado.
- **Números em formato antigo viram observação, não vínculo** — preservá-los é o desenho previsto: não há como representá-los como aresta, e descartá-los perderia a informação de que existe um vínculo.
- **`parse()` estende, não substitui** — os doze campos vêm da base e esta subclasse acrescenta dois. O dict bruto do 2º grau é um **superconjunto** do de 1º, o que mantém a [projeção](../transformers/projecao.md) uniforme, sem precisar saber o grau para ler os campos comuns.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Gravar o número de 1ª instância no mesmo campo que `processo_principal` | Misturaria recurso (lateral) com incidente (hierárquico) num grafo em que a distinção é o dado principal. Os dois podem coexistir na mesma capa. |
| Criar um campo `relator` separado de `juiz` | Duplicaria a coluna e obrigaria qualquer análise por magistrado a unir dois campos, sabendo o grau de antemão. |
| Herdar `_extrair_foro`/`_extrair_vara` com o fallback por rótulo | O fallback encontraria os cabeçalhos `Foro` e `Vara` da tabela de 1ª instância e atribuiria ao recurso a localização do processo de origem. |
| Localizar a seção pela tabela cujo cabeçalho contém `Foro` e `Vara` | O e-SAJ quebra a seção em duas tabelas; essa busca encontra a que só tem o cabeçalho. |
| Varrer o documento inteiro atrás de um CNJ de 1ª instância | As movimentações citam números de origem em prosa; um número de passagem viraria vínculo de recurso. |
| Aceitar qualquer elemento cujo texto contenha o título da seção | Um `<div>` contêiner casaria e a varredura começaria num ponto arbitrário, anulando a guarda do "próximo título". |
| Assumir `<th>` para o cabeçalho da tabela | O portal usa `<td class="label">`; a linha de cabeçalho seria lida como dado. |
| Descartar números em formato antigo | Perderia a informação de que existe um vínculo, ainda que não representável como aresta. |
| Forçar o número antigo a virar aresta | Criaria aresta apontando para um processo que não existe sob aquele número no padrão CNJ. |
| Exigir CNJ válido na varredura da seção | Redundante com a parada no próximo título e destrutivo: `celula and not cnj` nunca era verdadeiro e `processo_1a_instancia_bruto` era inalcançável. |
| Manter o filtro de CNJ só no atalho por `id` | O fallback só existe se houver seção a varrer. Numa capa que exponha o número apenas pelo `id`, o formato antigo era descartado pelo caminho que o encontrou. |
| Deixar a docstring dizendo "CNJ válido" | O resumo afirmava o oposto do critério implementado. Sem testes, a docstring é o contrato que o próximo leitor assume. |

## Limitações Conhecidas

- **Só o primeiro número de 1ª instância é capturado.** A varredura devolve na primeira célula com número e `_cnj_de_texto` usa `search()`. A seção chama-se "Números", no plural — um recurso com mais de um processo de origem registra só um vínculo, e os demais se perdem sem observação.
- **O texto original da célula é descartado quando o CNJ é extraído.** Foro, vara e juiz de origem, que estão na mesma célula, ficam fora do dict — assimetria frente à filosofia de [`parser_base`](parser_base.md) de guardar o bruto e projetar depois.
- **O fallback `_PADRAO_SECAO_1A` nunca foi exercitado.** O risco foi **reduzido em 2026-08-11**: `scripts/checar_offline.py` mostra `juiz` e `processo_1a_instancia` preenchidos nas **duas** capas reais de 2º grau de `data/spike/`, o que confirma `#relatorProcesso` e `#numeroProcessoPrimeiraInstancia`. Mas a saída não distingue qual caminho produziu o número, então a varredura de seção pode nunca ter rodado. Se o atalho por `id` sair da página, o fallback assume sem nunca ter sido testado — e `completude` não cobre o campo, então `processo_1a_instancia: null` sistemático não dispara nada.

## Exemplo de Uso

O parser é escolhido pelo mapa derivado do atributo `GRAU`, nunca instanciado direto.

```python
from src.scrapers.coletor import PARSER_POR_GRAU

bruto = PARSER_POR_GRAU[2](html).parse()      # ParserSegundoGrau

bruto["juiz"]                      # 'JARBAS GOMES'          <- o relator ocupa o campo
bruto["processo_1a_instancia"]     # '10110499020188260066'  <- CNJ válido -> vira vínculo
bruto["processo_1a_instancia_bruto"]  # None
bruto["processo_principal"]        # None  <- se houvesse, seria INCIDENTE, campo distinto

# Numa capa com número anterior ao padrão CNJ, os dois trocam de papel:
#   processo_1a_instancia       -> None
#   processo_1a_instancia_bruto -> '26747/2005'   <- vira observação, nunca aresta
```

## Testes e Validação

Não há suíte automatizada, e este é o módulo em que a ausência mais pesa: o próprio código declara que os seletores variam mais que os de `cpopg`. A validação prevista é `scripts/spike_seletores.py`, que consulta **sempre os dois graus** para cada número, salva o HTML em `data/spike/<numero>_g2.html` e imprime `processo_1a_instancia` ao lado do bruto. Rodá-lo sobre um agravo de instrumento real é o passo que a docstring pede antes da coleta em massa. As 5 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | `_varrer_secao_1a_instancia` aceita qualquer número (`\d{4,}`) em vez de exigir CNJ válido, tornando `processo_1a_instancia_bruto` alcançável |
| 2026-08-10 | @alexandrehiero | Docstring alinhada ao corpo; atalho por `#numeroProcessoPrimeiraInstancia` passa a usar o mesmo critério `\d{4,}` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 10 decisões virou lista de tópicos; código copiado removido. A limitação "seletores nunca confirmados" foi atualizada para o estado de 2026-08-11, em que `checar_offline.py` os observou preenchidos nas duas capas reais |
