# Export da base final – `src/aggregators/exportador.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `json`, `os`, `pathlib`, `collections.Counter` (biblioteca padrão); `src.transformers.projecao` |

## Contexto e Motivação

Este módulo produz o artefato que sai do projeto: o arquivo que outro pesquisador vai
importar no MongoDB ou abrir no pandas. Tem 126 linhas e três decisões que só fazem sentido
na escala em que ele opera.

A docstring abre com a que é obrigatória:

> STREAMING é obrigatório. O consolidador antigo montava uma lista com todos os
> registros e chamava json.dumps sobre ela: a 500 mil processos isso são dezenas
> de GB de objetos em RAM mais a string inteira materializada antes de escrever.
> Aqui a memória é constante — só o mapa de filhos fica residente.

O custo do modelo antigo é duplo, e o segundo é o que mata: além dos objetos Python em
memória, `json.dumps` sobre uma lista monta **a string inteira** antes de escrever o
primeiro byte. O processo precisa segurar simultaneamente a estrutura de dados e sua
serialização. É uma operação que não fica lenta — ela simplesmente não termina.

A segunda decisão é sobre o formato:

> JSONL e não array JSON: `mongoimport` consome JSONL nativamente em streaming, e
> um array de 15 GB seria ilegível por qualquer ferramenta.

E a terceira, sobre a gravação:

> Escrita atômica: grava em .tmp e só então troca. Interromper no meio nunca deixa
> uma base final truncada por cima da anterior.

## Decisões de Arquitetura

### JSONL, não array JSON

Um documento por linha, sem vírgula no fim e sem colchetes ao redor. A diferença é
estrutural: um array JSON só é válido depois do `]`, o que obriga qualquer leitor a
processar o arquivo inteiro antes de entregar o primeiro registro. Cada linha de um JSONL é
um documento completo e independente.

As três consequências que importam aqui:

- **`mongoimport` consome JSONL nativamente**, em streaming — sem carregar o arquivo;
- **o arquivo é processável linha a linha** por qualquer ferramenta, inclusive `head`,
  `grep` e `wc -l`, que num array de gigabytes não servem para nada;
- **a escrita é incremental**: a linha é serializada, escrita e descartada.

```python
arq.write(json.dumps(doc, ensure_ascii=False) + "\n")
```

`ensure_ascii=False` mantém os acentos como caracteres UTF-8 em vez de escapes `\uXXXX` —
o arquivo fica menor e legível a olho nu, e o encoding é declarado na abertura
(`encoding="utf-8"`).

### Memória constante, com uma exceção declarada

O laço central não acumula nada:

```python
with open(tmp, "w", encoding="utf-8") as arq:
    for reg in store.iter_exportaveis():
        filhos = mapa_filhos.get((reg["processo"], reg["grau"]), set())
        doc = projetar(reg, filhos)
        arq.write(json.dumps(doc, ensure_ascii=False) + "\n")
```

`iter_exportaveis` é um gerador (ver [`sqlite_store`](../store/sqlite_store.md)), `projetar`
é uma função pura, e o `doc` é descartado logo após ser escrito. O que fica residente é o
`mapa_filhos` — e a docstring diz isso explicitamente, em vez de fingir que a memória é
constante de forma absoluta.

Essa exceção é inevitável: para saber os filhos de um processo é preciso ter visto **todas**
as arestas, e elas estão espalhadas por toda a base. Não dá para calcular em streaming.

### Os filhos são calculados agora, nunca lidos de um campo

```python
# Filhos são DERIVADOS da inversão dos pais, calculada agora — nunca um
# campo gravado por um passo anterior que pudesse divergir do estado real.
mapa_filhos = inverter_filhos(store.vinculos())
```

O banco guarda uma direção (filho → pai) e a outra é derivada no momento do export. Como o
mapa é reconstruído a cada execução da opção 4, ele não pode estar desatualizado em relação
às arestas — não existe janela entre "gravar o pai" e "atualizar o filho". A justificativa
completa está em [`projecao.inverter_filhos`](../transformers/projecao.md).

### Escrita atômica: `.tmp` e `os.replace`

```python
tmp = caminho + ".tmp"
```

```python
os.replace(tmp, caminho)
```

`os.replace` é atômico dentro do mesmo sistema de arquivos: ou o nome aponta para o arquivo
novo, ou para o antigo, nunca para um estado intermediário. Como o `.tmp` fica no mesmo
diretório do destino, a condição é satisfeita.

O que isso protege é específico. A opção 4 pode levar minutos numa base grande, e um
`Ctrl+C` no meio da escrita — sem o `.tmp` — deixaria um `base_final.jsonl` truncado **por
cima** do anterior, que estava íntegro. O pesquisador perderia a base boa para ficar com uma
pela metade, e o arquivo truncado nem sequer parece quebrado: as linhas que existem são
JSON válido. O mesmo padrão aparece em `menu._escrever_atomico`, pelo mesmo motivo.

### O temporário é removido quando o export falha

```python
except BaseException:
    # A base anterior fica intacta (a troca só acontece no os.replace), mas
    # sem isto um .tmp de vários GB fica esquecido no disco após uma queda.
    Path(tmp).unlink(missing_ok=True)
    raise
```

Note o que este bloco **não** resolve: a base anterior já estava protegida, e continua
protegida, pelo `os.replace` — ele só é alcançado no fim, então uma falha no meio nunca
chegou a tocar o arquivo bom. O problema era outro, e puramente operacional: um
`base_final.jsonl.tmp` de vários gigabytes ficava no diretório de saída depois de uma queda,
sem aviso e sem ninguém para removê-lo. Na próxima tentativa ele é sobrescrito, mas até lá
ocupa disco de um projeto que pode estar rodando num notebook.

Duas escolhas dentro do bloco:

- **`BaseException`, não `Exception`.** O caso real é `KeyboardInterrupt`, que herda de
  `BaseException` e escaparia de um `except Exception`. Interromper o export com `Ctrl+C` é
  exatamente o cenário em que o `.tmp` sobra;
- **`raise` nu.** Re-levanta a exceção original com o traceback intacto. A limpeza é um
  efeito colateral no caminho de erro, não um tratamento: quem chamou continua vendo a falha
  que aconteceu.

`missing_ok=True` cobre a falha que ocorre antes de o arquivo existir — por exemplo, no
`open` — sem precisar de um segundo `try`.

### `erro_transitorio` fica de fora por construção, não por filtro

```python
def exportar_jsonl(store, caminho, log=print):
    """Projeta todos os registros exportáveis e grava o JSONL. Devolve o resumo.

    `erro_transitorio` fica de fora por construção (não está entre os status
    exportáveis do store): é fila de trabalho, não resultado.
    """
```

Não há `if status != ERRO_TRANSITORIO` neste módulo. A exclusão vem de `STATUS_EXPORTAVEIS`,
declarado em [`status`](../status.md) e aplicado no `SELECT` de `iter_exportaveis`. A
distinção é relevante para quem for estender: mudar o que entra na base final é mudar o
vocabulário, num lugar só, e não acrescentar condições aqui.

O motivo de fundo é conceitual — `erro_transitorio` não é um resultado, é um item de fila.
Exportá-lo significaria publicar como dado algo que ainda vai ser tentado de novo.

### O resumo é devolvido, não impresso

```python
return {
    "arquivo": caminho,
    "total": total,
    "por_status": dict(por_status),
    "por_grau": dict(por_grau),
    "com_pai": com_pai,
    # Documentos EXPORTADOS que têm filhos — comparável com `total` e
    # `com_pai`. `len(mapa_filhos)` contava também pais órfãos (citados mas
    # não coletados), então não era comparável com nada nesta mesma linha.
    "com_filhos": com_filhos,
    # Pares (pai, grau) citados que não casam com nenhum documento exportado.
    # NÃO é o mesmo que o total de órfãos: orfaos() casa por NÚMERO, este
    # conta PARES. A diferença entre os dois é exatamente o caso "o pai
    # existe, mas só no outro grau" — referência pendente, não coleta a
    # fazer. Nomeado por pares para não ser lido como o tamanho de orfaos.txt.
    "pares_pai_sem_documento": len(mapa_filhos) - com_filhos,
}
```

O módulo calcula os números e quem apresenta é o [`menu`](../../scripts/menu.md). Os
contadores são acumulados no mesmo laço da escrita, sem segunda passada pelo arquivo.

### Duas populações, e o cuidado de não misturá-las na mesma linha

A chave `com_filhos` substituiu `pais_com_filhos`, que era `len(mapa_filhos)` — e a diferença
não é de nome, é de **população contada**:

| Métrica | Conta | Unidade |
|---|---|---|
| `total`, `com_pai`, `com_filhos` | documentos escritos no JSONL | registro exportado |
| `pares_pai_sem_documento` | chaves do `mapa_filhos` que nenhum documento reivindicou | par `(pai, grau)` citado |

`com_filhos` é incrementado dentro do laço, quando o documento que está sendo escrito tem
`processos_filhos` não vazio. É por isso que ele é comparável com `total` e `com_pai`: as
três respostas são sobre a mesma coisa, um documento da base final. `len(mapa_filhos)` não
era — incluía pais **citados e não coletados**, que por definição não estão na base final —,
e o `menu` imprimia esse número ao lado de `com_pai`, convidando a uma subtração que não
significava nada.

Hoje as duas comparáveis ficam juntas e a terceira, sozinha:

```python
print(f"  com pai: {resumo['com_pai']} | com filhos: {resumo['com_filhos']}")
print(f"  pares (pai, grau) sem documento: {resumo['pares_pai_sem_documento']}")
```

**O nome carrega a unidade de propósito.** A chave chamava-se `pais_citados_sem_registro`, e
esse nome descreve com precisão outra coisa: os órfãos de `orfaos()`, que são **números** sem
registro nenhum. Quem lesse o resumo esperaria que o número batesse com a contagem de linhas
de `orfaos.txt` — e ele não bate, por construção. `orfaos()` casa pelo **número**; este
contador conta **pares**. Um pai coletado no grau 2 e citado no grau 1 entra aqui e não entra
lá, porque ele **tem** registro: o que não existe é o par citado.

Trocar o nome não muda nenhum cálculo; muda a pergunta que o leitor acha que está sendo
respondida. `pares_pai_sem_documento` diz a unidade — pares — e diz o critério — sem
documento exportado —, e com isso a divergência em relação a `orfaos.txt` deixa de parecer
erro e volta a ser o que é: o diagnóstico de "o pai existe, mas só no outro grau", a
limitação assumida em [`sqlite_store.orfaos`](../store/sqlite_store.md).

O progresso segue a mesma lógica, com o `log` injetável:

```python
if total % 5000 == 0:
    log(f"  {total} registros exportados...")
```

O padrão `log=print` mantém o módulo utilizável isoladamente, e o `menu` passa
`tqdm.write` — necessário para que a mensagem não corrompa a barra de progresso.

### `escrever_lista_orfaos`: o critério que faz o ciclo convergir

```python
def escrever_lista_orfaos(store, caminho):
    """Números citados como pai que NÃO têm registro — entrada da opção 3.

    Critério: 'não tem REGISTRO', não 'não tem dados'. Um processo gravado como
    sem_dados já foi visitado e sai da lista para sempre — é isso que faz o
    ciclo 4 -> 3 -> 4 convergir.
    """
```

A segunda função do módulo fecha o laço do fluxo de trabalho. A opção 4 exporta a base **e**
recalcula quais pais citados ainda não têm registro próprio; a opção 3 coleta esses; a
opção 4 roda de novo. O ciclo termina quando a lista sai vazia — e só termina porque o
critério é "não tem registro", não "não tem dados". Um processo que o e-SAJ afirma não
existir foi visitado e sai da lista definitivamente. A consulta que sustenta isso está em
[`sqlite_store.orfaos`](../store/sqlite_store.md).

A mesma escrita atômica é aplicada — hoje nas duas funções do módulo, com o mesmo
`try/except BaseException` que limpa o `.tmp` do JSONL:

```python
try:
    tmp.write_text(
        "".join(f"{o['processo']}\n" for o in orfaos), encoding="utf-8"
    )
    os.replace(tmp, caminho)
except BaseException:
    tmp.unlink(missing_ok=True)
    raise
```

A lista de órfãos também é insumo, e um arquivo truncado faria a opção 3 coletar menos do que
deveria, silenciosamente.

### Uma coluna de números, e o diagnóstico num arquivo separado

```python
# Uma coluna só: este arquivo é LIDO de volta pela opção 3, e ler_numeros
# extrai dígitos da linha inteira — um grau na mesma linha viraria um
# número de 21 dígitos e seria descartado como inválido.
```

Este ponto já foi registrado como pendência em duas direções opostas — "a lista perde o
grau" e depois "`graus_citados` não chega a lugar nenhum" —, e as duas se resolvem pela mesma
observação: são **dois consumidores diferentes**, e um arquivo não serve aos dois.

`orfaos.txt` é lido **de volta** pela opção 3, pelo mesmo `menu.ler_numeros` da lista de
entrada. E `ler_numeros` chama `NumeroProcesso.tentar(linha)`, que aplica `so_digitos` à
**linha inteira**:

```python
def so_digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))
```

Uma linha `00012345678901234567\t1` vira 21 dígitos, e o construtor a rejeita por não ter 20.
O órfão sairia da fila em silêncio — o arquivo pareceria correto e a opção 3 coletaria menos
do que deveria. Não é uma preferência de formato: acrescentar qualquer coisa àquela linha
**quebra** o consumidor.

O diagnóstico, então, vai para um arquivo próprio:

```python
# Diagnóstico em arquivo SEPARADO: preserva os graus em que cada órfão foi
# citado. Sem ele, `graus_citados` seria calculado pelo SQL e descartado.
diag = caminho.with_name(caminho.stem + "_diagnostico.txt")
```

`orfaos_diagnostico.txt` tem `processo\tgraus_citados`, cabeçalho comentado e um aviso de que
é leitura humana — a opção 3 lê apenas `orfaos.txt`. É o que faz o `GROUP_CONCAT` de
[`orfaos()`](../store/sqlite_store.md) chegar ao disco em vez de ser calculado e descartado,
e é o insumo para reconhecer o caso "o pai existe, mas só no outro grau": comparar o grau
citado com o grau efetivamente gravado no banco.

Quanto à lista em si, escrever só o número é a granularidade **correta**, não uma perda.
`menu.opcao_3` filtra com `numeros_finalizados()` (que é `SELECT DISTINCT processo`) e entrega
cada número a `coletar_um`, que **escolhe o grau sozinho** pela origem do CNJ. Não há a quem
entregar um grau: as quatro etapas do ciclo falam de números. O raciocínio completo está em
[`sqlite_store`](../store/sqlite_store.md), na seção sobre o casamento do órfão.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Montar uma lista e chamar `json.dumps` sobre ela | Modelo do consolidador anterior: dezenas de GB de objetos em RAM **mais** a string inteira materializada antes do primeiro byte escrito. Não fica lento, não termina. |
| Array JSON (`[{...}, {...}]`) | Só é válido depois do `]`: obriga o leitor a processar tudo antes de entregar o primeiro registro, e um arquivo de 15 GB fica ilegível por qualquer ferramenta. |
| CSV | A estrutura tem aninhamento (partes por polo, listas de movimentações, referências com número e grau). Achatá-la para CSV perderia a forma ou exigiria colunas serializadas — que é JSON dentro de CSV. |
| `ensure_ascii=True` (padrão do `json`) | Acentos viram `\uXXXX`: arquivo maior e ilegível a olho nu, sem ganho — o encoding já está declarado como UTF-8. |
| Escrever direto no arquivo final | Uma interrupção deixa a base truncada por cima da anterior, que estava íntegra. E o truncado não parece quebrado: as linhas existentes são JSON válido. |
| Gravar os filhos no banco e apenas ler aqui | Duas fontes de verdade para a mesma aresta, com janela de divergência entre gravar o pai e atualizar o filho. |
| Filtrar `erro_transitorio` neste módulo | Espalharia a definição do que entra na base final. Ela vive em `STATUS_EXPORTAVEIS`, num lugar só. |
| Imprimir o resumo aqui | Amarraria o módulo ao console. Devolvendo o dicionário, quem chama decide o formato — e é o que permite ao `menu` usar `tqdm.write`. |
| Calcular as contagens numa segunda passada | Exigiria reler o arquivo escrito. Os contadores custam nada acumulados no mesmo laço. |
| Reportar `len(mapa_filhos)` como "pais com filhos" | Conta pais citados e não coletados, que não estão na base final. Impresso ao lado de `com_pai`, convidava a uma comparação sem significado. |
| `except Exception` na limpeza do `.tmp` | Não pega `KeyboardInterrupt`, que é justamente o caso real: `Ctrl+C` no meio de um export longo. |
| Deixar o `.tmp` no disco para inspeção pós-falha | Vários GB esquecidos sem aviso, num projeto que roda em notebook. O traceback já diz o que falhou. |
| Gravar o grau na lista de órfãos | Além de não haver a quem entregá-lo (`coletar_um` decide o grau pela origem do CNJ), `ler_numeros` extrai dígitos da linha inteira: o grau viraria um 21º dígito e o órfão sairia da fila em silêncio. |
| Descartar `graus_citados` de vez | Perderia o único insumo para diagnosticar "o pai existe, mas só no outro grau" — a limitação assumida de `orfaos()` casar por número. |
| Uma coluna extra no próprio `orfaos.txt` | Quebra o consumidor: veja acima. O arquivo é lido de volta pela opção 3. |
| Deixar o diagnóstico só no console | Some com a rolagem do terminal. O arquivo fica ao lado da base final e pode ser conferido depois. |

## Limitações Conhecidas

- **`mapa_filhos` cresce com o número de arestas, não com o número de processos.** É a única
  estrutura residente, e a docstring é honesta quanto a isso. Numa base em que a maioria dos
  processos tem vínculo, o mapa se aproxima do tamanho da base.

- **`pares_pai_sem_documento` e `orfaos.txt` continuam medindo populações diferentes.** O
  nome novo torna a diferença legível, mas não a elimina: um conta pares `(pai, grau)` sem
  documento, o outro conta números sem registro. Quem comparar os dois precisa saber que a
  divergência é informativa, não erro.

- **`escrever_lista_orfaos` faz três escritas de arquivo e nenhuma é transação.** São dois
  arquivos (`orfaos.txt` e `orfaos_diagnostico.txt`), cada um com seu `.tmp` e seu
  `os.replace`, em blocos `try/except` independentes. Uma falha entre os dois deixa a lista
  atualizada e o diagnóstico velho — inconsistência entre arquivos que nenhum dos dois
  denuncia. Como o diagnóstico é leitura humana e a lista é o insumo real, o risco é baixo,
  mas não é zero.

- **O diagnóstico é regravado inteiro a cada opção 4.** `orfaos_diagnostico.txt` não guarda
  histórico: os graus citados na execução anterior somem. Comparar duas rodadas exige ter
  copiado o arquivo antes.

- **`por_grau` usa a chave `None` para grau indeterminado.** O contador acumula
  `doc["grau"]`, que a projeção já converteu de `0` para `None`. O resumo impresso sai como
  `{None: 12, 1: 340, 2: 88}`.

- **O export não registra quando foi feito.** O JSONL não tem cabeçalho nem metadados de
  execução, e `atualizado_em` não é projetado (ver
  [`projecao`](../transformers/projecao.md)). Duas bases exportadas em momentos diferentes
  são indistinguíveis pelo conteúdo.

- **`escrever_lista_orfaos` não usa o `log` injetável.** Diferente de `exportar_jsonl`, ela
  não reporta progresso — irrelevante hoje, já que a consulta é única e a escrita é curta.

## Exemplo de Uso

As duas funções são chamadas em sequência pela opção 4 do `scripts/menu.py`, que é
inteiramente local — sem rede:

```python
def opcao_4(store):
    """Local, sem rede. Reprojeta vínculos, exporta o JSONL e recalcula órfãos.

    A reprojeção vem PRIMEIRO porque orfaos() e o mapa de filhos são calculados
    a partir das colunas de vínculo: exportar antes de reprojetar produziria uma
    base final coerente com a regra ANTIGA de derivação.
    """
```

A ordem é parte do contrato deste módulo: as duas funções aqui **leem** as colunas de
vínculo (`store.vinculos()` e `store.orfaos()`), e quem as regrava é
[`reprojetar_vinculos`](../store/sqlite_store.md). Exportar antes produziria um JSONL e uma
lista de órfãos calculados sobre a regra anterior — desatualizados por exatamente uma
execução, sem nenhum sinal.

```python
resumo = exportar_jsonl(store, JSONL, log=tqdm.write)
orfaos = escrever_lista_orfaos(store, ORFAOS)
```

O resumo devolvido é apresentado pelo chamador:

```python
print(f"  registros:  {resumo['total']}")
print(f"  por status: {resumo['por_status']}")
print(f"  por grau:   {resumo['por_grau']}")
print(f"  com pai: {resumo['com_pai']} | com filhos: {resumo['com_filhos']}")
print(f"  pares (pai, grau) sem documento: {resumo['pares_pai_sem_documento']}")
```

E a lista de órfãos decide a mensagem que fecha o ciclo:

```python
if orfaos:
    print(f"registro -> {ORFAOS.name}. Rode a opção 3 para coletá-los.")
else:
    print("\nNenhum órfão: todo processo citado no relacionamento tem registro.")
```

## Testes e Validação

Não há testes automatizados neste repositório, e `scripts/v_checar_offline.py` — o mais
próximo que existe de regressão — **não alcança este módulo**: ele para no parser e no
vínculo, sem tocar em banco nem em export.

A validação em uso é o próprio resumo impresso pela opção 4: `total` deve bater com a soma
de `por_status`, e ambos com a contagem de linhas do arquivo (`wc -l base_final.jsonl`) — o
que é possível **porque** a saída é JSONL e todo registro produz exatamente uma linha.

O módulo é testável contra um `SqliteStore(":memory:")` populado à mão, sem rede e sem
projeto real. As invariantes que valeria fixar:

- o número de linhas do arquivo é igual a `resumo["total"]` e à soma de `por_status`;
- **nenhuma linha tem `status: "erro_transitorio"`** — a garantia que vem de
  `STATUS_EXPORTAVEIS`;
- cada linha é JSON válido isoladamente, e todas têm o mesmo conjunto de chaves;
- os `_id` são únicos no arquivo — o que confirma que a chave `(processo, grau)` está sendo
  respeitada de ponta a ponta;
- `com_filhos` é menor ou igual a `total` — a garantia de que as duas contagens falam de
  documentos exportados — e `com_filhos + pares_pai_sem_documento == len(mapa_filhos)`;
- uma exceção no meio do laço deixa o arquivo final **anterior** intacto e **não** deixa
  `.tmp` no diretório (a garantia do `try/except` + `os.replace`) — vale para o JSONL e para
  os dois arquivos de órfãos;
- um `KeyboardInterrupt` no meio do laço produz o mesmo resultado — é o motivo de o `except`
  ser `BaseException`;
- um pai citado por um registro e sem registro próprio aparece em `orfaos.txt`; o mesmo pai,
  depois de gravado como `sem_dados`, **não** aparece mais — a condição de convergência do
  ciclo 4 → 3 → 4;
- **toda linha de `orfaos.txt` sobrevive a `menu.ler_numeros`** — nenhuma tem 21 dígitos. É
  a invariante que justifica o arquivo de diagnóstico separado, e a que quebraria se alguém
  acrescentasse uma coluna;
- `orfaos_diagnostico.txt` tem uma linha de dados por linha de `orfaos.txt`, na mesma ordem;
- um pai citado no grau 1 que existe gravado no grau 2 **não** aparece em `orfaos.txt`, mas
  **conta** em `pares_pai_sem_documento` — a diferença entre as duas medidas.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Ponto em aberto resolvido pela mudança de critério em `orfaos()`; `com_filhos` e limpeza do `.tmp` documentados |
| 2026-08-11 | @alexandrehiero | `pares_pai_sem_documento`; `orfaos_diagnostico.txt`; `.tmp` protegido também em `escrever_lista_orfaos` |

## Pontos em aberto

Nenhum. Os três itens que passaram por esta página estão fechados:

| Ponto | Desfecho |
|---|---|
| A lista de órfãos perde o grau (2026-08-10) | `orfaos()` passou a casar por número: escrever só o número virou a granularidade **correta** |
| `graus_citados` não chega a lugar nenhum (2026-08-11) | Gravado em `orfaos_diagnostico.txt`, arquivo separado porque `orfaos.txt` é lido de volta pela opção 3 |
| As contagens do resumo confundem populações (2026-08-11) | `pais_citados_sem_registro` → `pares_pai_sem_documento`: o nome passou a dizer a unidade |

O que resta está em **Limitações Conhecidas**, e nenhum item é pendência de correção: a
diferença entre as duas medidas de órfão é real e informativa, e as escritas de arquivo não
são atômicas **entre si**.
