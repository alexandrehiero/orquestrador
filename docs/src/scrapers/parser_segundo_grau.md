# Parser da capa de 2º grau – `src/scrapers/parser_segundo_grau.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `src.scrapers.parser_base`, `re` (biblioteca padrão) |

## Contexto e Motivação

A capa de `cposg` não é uma variação cosmética da capa de `cpopg`. Ela tem uma seção que
não existe no 1º grau — "Números de 1ª Instância" — e é justamente essa seção que carrega
a informação mais delicada do módulo.

A docstring enuncia as duas diferenças e a advertência:

> Diferenças frente ao 1º grau:
>
>   - Não existe 'Juiz'; por decisão do projeto, o RELATOR ocupa o campo juiz.
>   - O número de 1ª instância é capturado em `processo_1a_instancia` de forma
>     SEPARADA. Ele é o vínculo do RECURSO (relação lateral) e não pode ser
>     confundido com 'Processo principal' (incidente, relação hierárquica) — os
>     dois podem coexistir na mesma capa e cada um vai para seu campo.
>
> ATENÇÃO: os seletores de cposg variam mais que os de cpopg. Confirmar num agravo
> real antes da coleta em massa.

O ponto de fundo: um recurso e um incidente são vínculos de naturezas diferentes, e a
mesma capa pode exibir os dois. Se ambos fossem gravados no mesmo campo, o grafo de
relacionamento passaria a misturar "este processo subiu de instância" com "este processo
nasceu de outro". O parser não decide qual vale — ele apenas mantém os dois separados, e a
decisão fica com [`transformers/vinculo`](../transformers/vinculo.md), que é o único
escritor do tipo de relacionamento.

## Decisões de Arquitetura

### O relator ocupa o campo `juiz`

```python
def _extrair_juiz(self):
    val = self._por_id("#relatorProcesso")
    if val and self._juiz_valido(val):
        return val
    val = self._rotulo_estrito("Relator") or self._rotulo_estrito("Relator(a)")
    if val and self._juiz_valido(val):
        return val
    return None
```

A mesma cascata de três passos do [`parser_primeiro_grau`](parser_primeiro_grau.md), com
os rótulos do 2º grau — inclusive a forma `"Relator(a)"`, que o portal usa. E a mesma
desistência explícita no fim: campo ausente em vez de campo errado.

A decisão de reaproveitar o campo `juiz` em vez de criar `relator` mantém uma coluna só na
base final. Quem analisar "processos por magistrado" não precisa unir dois campos nem
saber de antemão o grau do registro; quem quiser separar tem o campo `grau` ao lado.

### `_extrair_foro` e `_extrair_vara` perdem o fallback por rótulo — de propósito

```python
def _extrair_foro(self):
    # No 2º grau não há foro/vara próprios. Só o id — SEM fallback por
    # rótulo, que pegaria os cabeçalhos da tabela 'Números de 1ª instância'.
    return self._por_id("#foroProcesso")
```

Esta é a decisão mais fácil de reverter por engano e a mais cara. A implementação da base
é `self._por_id("#foroProcesso") or self._rotulo_estrito("Foro")`, e o fallback é
perfeitamente sensato no 1º grau. No 2º, a tabela "Números de 1ª Instância" tem colunas
cujos cabeçalhos são exatamente `Foro`, `Vara` e `Juiz`. O `_rotulo_estrito` encontraria
esses cabeçalhos e devolveria o foro **do processo de origem** como se fosse o foro do
recurso.

O resultado não seria um campo vazio nem um erro: seria um dado plausível e errado,
atribuindo ao processo de 2º grau a localização do processo de 1º. Remover o fallback
troca esse risco por um `None` honesto.

### A seção de 1ª instância é varrida, não localizada por uma tabela

```python
def _celula_1a_instancia(self):
    """Texto da célula com o número de 1ª instância, ou None.

    O e-SAJ quebra a seção em DUAS tabelas: uma só com o cabeçalho
    ('Nº de 1ª instância | Foro | Vara | Juiz | Obs.') mais uma linha vazia
    de espaçamento, e OUTRA com os dados. Procurar 'a tabela cujo cabeçalho
    tem Foro e Vara' encontrava a primeira — que não tem dado nenhum.
    Por isso varremos as tabelas da SEÇÃO, não uma tabela só.
    """
```

A abordagem natural — "ache a tabela cujo cabeçalho contém Foro e Vara e leia a primeira
linha" — falha silenciosamente contra o HTML real, porque o cabeçalho e os dados estão em
tabelas **diferentes**. Daí a estratégia: localizar o **título** da seção e varrer as
tabelas que vêm depois dele.

O caminho rápido continua existindo, quando o portal fornece o `id`:

```python
el = self.soup.select_one("#numeroProcessoPrimeiraInstancia")
```

### A varredura para no próximo título — e é **só** isso que a delimita

```python
for elemento in cabecalho.find_all_next(["h2", "h3", "h4", "table"]):
    if elemento.name != "table":
        break  # começou outra seção
```

Sem o `break`, `find_all_next` continuaria até o fim do documento e alcançaria a tabela de
movimentações. Despachos citam números de outros processos em prosa corrida; um deles
viraria aresta no grafo de relacionamento — e uma aresta falsa é pior que uma aresta
ausente, porque nada a distingue de uma verdadeira depois de gravada.

A docstring registra o cenário concreto:

> Para no PRÓXIMO título: sem essa guarda a varredura invadiria as
> movimentações, onde despachos citam o número de origem no meio do texto
> ('Anote-se que os autos de origem possuem o nº ...') — e aí um número
> mencionado de passagem viraria vínculo de recurso.

A ênfase no "só isso" importa porque havia um segundo mecanismo aparentemente cumprindo a
mesma função, e ele custava caro — ver a decisão seguinte. A linha de resumo da docstring
acompanha o critério real:

> Primeira célula com QUALQUER número nas tabelas da seção de 1ª
> instância. Quem separa CNJ válido de formato antigo é o parse().

Ela dizia "com CNJ válido" enquanto o corpo já aceitava qualquer número — quem lesse só o
resumo concluía o oposto do que o método faz. A frase agora nomeia também o responsável pela
separação, que é o `parse()`, e não a varredura.

### Qualquer número acha a célula; o filtro de CNJ fica no `parse()`

```python
texto = celulas[0].get_text(" ", strip=True)
# Aceita QUALQUER número, não só CNJ válido: números anteriores
# ao padrão CNJ ('26747/2005') precisam chegar ao parse() para
# virar `processo_1a_instancia_bruto` e observação de vínculo.
# Exigir CNJ aqui tornava esse caminho inalcançável. Quem impede
# invadir as movimentações é a parada no próximo título, não
# este filtro.
if re.search(r"\d{4,}", texto):
    return texto
```

O filtro anterior era `_cnj_de_texto(texto)` — CNJ válido de 20 dígitos. Ele parecia uma
segunda linha de defesa contra a varredura pegar texto de passagem, mas na prática era
**redundante com a parada no próximo título e destrutivo para o caso que o módulo mais
queria preservar**.

O encadeamento do defeito era este. `_celula_1a_instancia()` só podia devolver `None` ou um
texto que já continha CNJ válido. Mas o `parse()` atribui:

```python
dados["processo_1a_instancia"] = cnj
dados["processo_1a_instancia_bruto"] = celula if (celula and not cnj) else None
```

A condição `celula and not cnj` exige uma célula não vazia **cujo texto não tenha CNJ**. Com
o filtro na varredura, sempre que `celula` era verdadeira `cnj` também era — e a condição
nunca podia ser satisfeita. O campo `processo_1a_instancia_bruto` era inalcançável por
construção, e com ele o ramo de `vinculo.derivar_vinculo` que registra a observação de
número em formato antigo.

O resultado prático: um número de origem como `'26747/2005'` — que existe nas capas de 2º
grau, porque processos anteriores ao padrão CNJ ainda tramitam — era **descartado em
silêncio**. Não virava aresta (correto, não há como) e também não virava observação
(incorreto, era exatamente o que o campo existia para fazer).

Afrouxar o filtro para `\d{4,}` devolve o texto ao `parse()`, que aí sim decide: com CNJ,
vínculo; sem CNJ, bruto preservado como observação. É a mesma divisão de trabalho do resto
do projeto — a varredura **localiza**, o `parse()` **classifica** — e a segurança contra
invadir as movimentações continua sendo a parada no próximo título, que nunca dependeu do
formato do número.

### O atalho por `id` usa o mesmo critério da varredura

Os dois caminhos que produzem a célula filtram igual — `\d{4,}`, não CNJ válido:

```python
el = self.soup.select_one("#numeroProcessoPrimeiraInstancia")
if el:
    txt = el.get_text(" ", strip=True)
    # Qualquer número serve, igual à varredura. Exigir CNJ aqui fazia o
    # atalho descartar em silêncio um formato antigo que ele mesmo havia
    # encontrado — e a varredura não o recuperava: numa página que só
    # tem o id, não existe tabela de seção para varrer.
    if re.search(r"\d{4,}", txt):
        return txt
return self._varrer_secao_1a_instancia()
```

Manter o filtro de CNJ só no atalho parecia inofensivo — afinal, um valor rejeitado ali cai
para a varredura, que hoje aceita qualquer número. Mas o fallback só funciona quando existe
o que varrer. Numa capa que exponha o número de origem **apenas** pelo `id`, sem a seção
"Números de 1ª Instância" em forma de tabela, `_varrer_secao_1a_instancia` não acha
cabeçalho, devolve `None`, e o número em formato antigo se perde — descartado pelo próprio
caminho que acabara de encontrá-lo.

O padrão é o mesmo que a decisão anterior corrigiu, e a lição se repete: **filtro de formato
em quem localiza produz descarte silencioso.** Localizar e classificar são responsabilidades
distintas, e o `parse()` é quem classifica. Com os dois caminhos usando o mesmo critério de
localização, `_celula_1a_instancia` passa a ter um contrato único — "devolve o texto da
célula que contém um número, ou `None`" — em vez de dois comportamentos conforme a rota.

### O cabeçalho é procurado com prioridade e com texto direto

```python
def _cabecalho_secao_1a(self):
    """O título 'Números de 1ª Instância'. Prioriza h2/h3/h4; só depois cai
    para outros elementos, e aí exigindo texto DIRETO — senão um <div>
    contêiner casaria e a varredura começaria no lugar errado."""
```

O mesmo cuidado de `_rotulo_estrito` na classe base: um `<div>` que envolve metade da
página "contém" o texto do título. Se ele fosse aceito como cabeçalho, `find_all_next`
começaria de um ponto arbitrário do documento e a guarda do parágrafo anterior perderia o
efeito.

O padrão do título tolera as variações de grafia que o portal usa:

```python
_PADRAO_SECAO_1A = re.compile(r"n[uú]meros?\s+de\s+1[ªaº]?\s*inst", re.I)
```

### O cabeçalho da tabela usa `<td class="label">`, não `<th>`

```python
if "label" in (tr.get("class") or []):
    continue  # cabeçalho usa <td class="label">, não <th>
```

Uma varredura que assumisse HTML semântico (`<th>` para cabeçalho) leria a linha de
cabeçalho como se fosse dado.

### Números em formato antigo não viram vínculo

```python
def _cnj_de_texto(texto):
    """Extrai 20 dígitos do texto, ou None. Número antigo ('26747/2005') não
    casa a máscara e vira None — vai para observação, não para vínculo."""
```

Processos anteriores ao padrão CNJ existem nas capas de 2º grau, e o desenho previsto é
preservá-los como observação em vez de descartá-los ou de forçá-los a virar aresta. O
campo destinado a isso é `processo_1a_instancia_bruto`:

```python
dados["processo_1a_instancia"] = cnj
dados["processo_1a_instancia_bruto"] = celula if (celula and not cnj) else None
```

A condição `celula and not cnj` é a que separa os dois destinos, e ela só é satisfazível
porque a varredura da seção entrega a célula sem filtrar por CNJ — ver a decisão acima.

### `parse()` estende, não substitui

```python
def parse(self):
    dados = super().parse()
```

Os doze campos da capa continuam vindo da classe base; esta subclasse acrescenta dois. O
dict bruto do 2º grau é, portanto, um superconjunto do de 1º grau — o que mantém a
[`projeção`](../transformers/projecao.md) uniforme, sem precisar saber o grau para ler os
campos comuns.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Gravar o número de 1ª instância no mesmo campo que `processo_principal` | Misturaria recurso (lateral) com incidente (hierárquico) num grafo em que a distinção é o dado principal. Os dois podem coexistir na mesma capa. |
| Criar um campo `relator` separado de `juiz` | Duplicaria a coluna na base final e obrigaria qualquer análise por magistrado a unir dois campos, sabendo o grau de antemão. |
| Herdar `_extrair_foro`/`_extrair_vara` da base, com o fallback por rótulo | O fallback encontraria os cabeçalhos `Foro` e `Vara` da tabela "Números de 1ª Instância" e atribuiria ao recurso a localização do processo de origem — dado plausível e errado. |
| Localizar a seção pela tabela cujo cabeçalho contém `Foro` e `Vara` | O e-SAJ quebra a seção em duas tabelas; essa busca encontra a que só tem o cabeçalho, sem dado nenhum. |
| Varrer o documento inteiro atrás de um CNJ de 1ª instância | As movimentações citam números de origem em prosa; um número mencionado de passagem viraria vínculo de recurso. |
| Aceitar qualquer elemento cujo texto contenha o título da seção | Um `<div>` contêiner casaria e a varredura começaria num ponto arbitrário, anulando a guarda do "próximo título". |
| Assumir `<th>` para o cabeçalho da tabela | O portal usa `<td class="label">`; a linha de cabeçalho seria lida como dado. |
| Descartar números em formato antigo | Perderia a informação de que existe um vínculo, ainda que não representável como aresta. O desenho previsto os preserva como observação. |
| Forçar o número antigo a virar aresta | Criaria uma aresta apontando para um processo que não existe sob aquele número no padrão CNJ. |
| Exigir CNJ válido na varredura da seção | Redundante com a parada no próximo título e destrutivo: `_celula_1a_instancia` só devolvia texto que já continha CNJ, então `celula and not cnj` nunca era verdadeiro e `processo_1a_instancia_bruto` era inalcançável. Números antigos eram descartados em silêncio. |
| Manter o filtro de CNJ só no atalho por `id`, confiando na varredura como fallback | O fallback só existe se houver seção a varrer. Numa capa que exponha o número apenas pelo `id`, o formato antigo era descartado pelo próprio caminho que o havia encontrado. |
| Deixar a docstring de `_varrer_secao_1a_instancia` dizendo "CNJ válido" | O resumo afirmava o oposto do critério implementado. Numa base de código sem testes, a docstring é o contrato que o próximo leitor assume — e este mandava de volta ao filtro que acabara de ser removido. |

## Limitações Conhecidas

- **Os seletores próprios de `cposg` não foram confirmados em HTML real.** É a advertência do
  próprio módulo: *"os seletores de cposg variam mais que os de cpopg. Confirmar num agravo
  real antes da coleta em massa."* O spike de 2026-08-10 já rodou contra HTML real de 2º
  grau — foi lá que `#situacaoProcesso` e `.unj-tag` foram confirmados para o campo
  `situacao` (ver [`parser_base`](parser_base.md)) —, mas os seletores que **só** existem
  aqui (`#relatorProcesso`, `#numeroProcessoPrimeiraInstancia`, `_PADRAO_SECAO_1A`) seguem
  sem observação registrada. Enquanto isso não for feito, `processo_1a_instancia` pode vir
  `None` sistematicamente sem que nada no pipeline acuse — `completude` não cobre esse
  campo. É o primeiro item a verificar com `scripts/spike_seletores.py`, que imprime
  justamente esse par:

  ```python
  if grau == 2:
      print(f"    1ª instância: {dados.get('processo_1a_instancia')!r} "
            f"(bruto: {dados.get('processo_1a_instancia_bruto')!r})")
  ```

- **Só o primeiro número de 1ª instância é capturado.** `_varrer_secao_1a_instancia`
  devolve na primeira célula que contenha um número, e `_cnj_de_texto` usa `search()`, que
  pega a primeira ocorrência do texto. Um recurso que abranja mais de um processo de
  origem — a seção chama-se "Números", no plural — terá apenas um vínculo registrado, e os
  demais serão perdidos sem observação. O afrouxamento do filtro não muda isso: ele altera
  *quais* células são aceitas, não *quantas*.

- **`foro` e `vara` ficam vazios sempre que o `id` não existir.** Removido o fallback, não
  há segundo caminho. É a troca deliberada descrita acima, mas significa que uma mudança de
  layout no portal zera os dois campos em toda a base de 2º grau silenciosamente.

- **A capa de 2º grau não expõe o grau do processo de origem como dado.** O
  [`vinculo`](../transformers/vinculo.md) assume `grau 1` por definição ao montar a aresta
  de recurso. É correto para o caso normal, mas é uma inferência do modelo, não um dado
  observado na página.

- **O dict bruto de 2º grau tem dois campos a mais que o de 1º.** Qualquer consumidor do
  bruto que assuma um conjunto fixo de chaves precisa usar `.get()`, como
  [`projecao`](../transformers/projecao.md) e [`vinculo`](../transformers/vinculo.md) fazem.

## Exemplo de Uso

Como todo parser do projeto, é instanciado pelo mapa de grau, nunca diretamente — e o mapa
é derivado do atributo `GRAU` de cada classe:

```python
PARSER_POR_GRAU = {P.GRAU: P for P in (ParserPrimeiroGrau, ParserSegundoGrau)}
```

```python
bruto = PARSER_POR_GRAU[grau](html).parse()
```

O consumidor dos dois campos extras é `derivar_vinculo`, em
`src/transformers/vinculo.py` — e é lá que a separação entre recurso e incidente vira
decisão:

```python
primeira = _digitos(bruto.get("processo_1a_instancia"))
if grau == 2 and primeira:
    candidatos.append((RECURSO, primeira, 1, "número de 1ª instância"))
```

```python
bruto_1a = bruto.get("processo_1a_instancia_bruto")
if bruto_1a:
    obs.append(f"Número de 1ª instância em formato antigo: {bruto_1a}")
```

## Testes e Validação

Não há testes automatizados neste repositório, e este é o módulo em que essa ausência mais
pesa: é o único cujo próprio código declara que os seletores ainda não foram confirmados
contra HTML real.

A validação prevista é `scripts/spike_seletores.py`, que consulta **sempre os dois graus**
para cada número — *"o spike consulta SEMPRE os dois, para comparar"* — salva o HTML em
`data/spike/<numero>_g2.html` e imprime `processo_1a_instancia` ao lado do bruto. Rodá-lo
sobre um agravo de instrumento real é o passo que a docstring pede antes da coleta em
massa.

As invariantes que valeria fixar, todas verificáveis sobre um fixture salvo:

- capa de 2º grau com seção "Números de 1ª Instância" devolve o CNJ correto em
  `processo_1a_instancia`;
- capa cujo despacho cita um número de origem no texto da movimentação **não** devolve esse
  número — a garantia do `break` no próximo título;
- `foro` e `vara` **não** recebem os valores das colunas homônimas da tabela de 1ª
  instância;
- capa que traz simultaneamente `Processo principal` no topo e número de 1ª instância
  preenche os **dois** campos, cada um no seu;
- um número de origem em formato antigo (`26747/2005`) resulta em
  `processo_1a_instancia: None` **e** `processo_1a_instancia_bruto` preenchido com o texto
  da célula — o par que a correção do filtro tornou alcançável, e o caso que mais interessa
  cobrir aqui. Vale exercitar os **dois** caminhos, porque foram corrigidos separadamente:
  o número antigo numa tabela da seção e o número antigo exposto só por
  `#numeroProcessoPrimeiraInstancia`, sem seção nenhuma na página.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | `_varrer_secao_1a_instancia` aceita qualquer número (`\d{4,}`) em vez de exigir CNJ válido, tornando `processo_1a_instancia_bruto` alcançável |
| 2026-08-10 | @alexandrehiero | Docstring de `_varrer_secao_1a_instancia` alinhada ao corpo; atalho por `#numeroProcessoPrimeiraInstancia` passa a usar o mesmo critério `\d{4,}` |

## Pontos em aberto

- **Os seletores próprios de `cposg` continuam não confirmados**, conforme a advertência no
  topo do módulo. O spike de 2026-08-10 rodou contra HTML real de 2º grau e confirmou os
  seletores de `situacao`, que vivem na classe base; os deste módulo —
  `#relatorProcesso`, `#numeroProcessoPrimeiraInstancia` e o padrão do título da seção —
  não têm observação registrada. Não é possível saber, apenas lendo o repositório, quais
  deles foram vistos funcionar e quais foram escritos a partir da inspeção visual das telas.

- **O texto original da célula é descartado quando o CNJ é extraído com sucesso.** Só o
  caso de falha teria o bruto preservado (se a condição acima fosse alcançável). É uma
  assimetria em relação à filosofia declarada em [`parser_base`](parser_base.md) — guardar
  o bruto e projetar depois —, ainda que defensável: quando o CNJ parseia, os 20 dígitos
  são a informação, e o resto da célula (foro, vara, juiz de origem) fica de fora do dict
  sem que nada registre que existia.

- **`_MASCARA_CNJ` está duplicada** em relação a `page_state.py`, com o mesmo padrão e
  comentário equivalente. Ver a anotação em [`numero_processo`](numero_processo.md).
