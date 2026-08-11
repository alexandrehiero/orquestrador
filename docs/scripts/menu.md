# Orquestrador interativo – `scripts/menu.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `tqdm`, `concurrent.futures` (biblioteca padrão), e todos os módulos de `src/` |

## Contexto e Motivação

Este é o único ponto de entrada do projeto. Tudo o que os módulos de `src/` sabem fazer só
acontece quando este script os encadeia — e o encadeamento tem uma forma específica, pensada
para quem vai operar uma coleta que dura dias sem ser quem escreveu o código.

> Um PROJETO = uma lista + um banco + uma pasta de saída, todos derivados do nome
> passado na linha de comando. Bases diferentes com processos em comum não
> interferem uma na outra.

Essa é a decisão que organiza o script inteiro. Um pesquisador pode ter uma coleta da base
do IAMSPE em andamento e começar outra, da PGE, sem que a segunda toque na primeira — mesmo
que as duas listas compartilhem processos. O isolamento é por **nome**, e vem de graça:
`configurar_projeto` deriva todos os caminhos de um argumento só.

A segunda decisão estruturante é sobre onde mora a verdade:

> O BANCO é a fonte da verdade; os .txt são VISÕES regeneradas a cada execução.
> Isso evita pedir que alguém edite à mão um arquivo com milhares de linhas — e
> evita que um erro nessa edição destrua a lista de falhas, que representa semanas
> de coleta.

O modelo comum em scripts de coleta — "edite o arquivo de pendências e rode de novo" —
transfere para o operador a responsabilidade de manter um estado consistente com milhares
de linhas. Aqui os `.txt` são saída, nunca entrada de estado: apagar
`falhas_pendentes.txt` não perde nada, porque ele é reescrito a partir do banco na execução
seguinte.

## Decisões de Pipeline

### O fluxo é 1 → 4 → 3 → 4, e o menu diz isso

```
 1 → 4 → 3 (se houver) → 4 de novo. 
 A opção 2 só faz sentido se a 1 reportar falhas.
```

A instrução está dentro do próprio `MENU`, não num README que ninguém abre. O motivo de a
opção 4 aparecer duas vezes é que ela faz duas coisas: exporta a base **e** recalcula a
lista de órfãos. A primeira execução descobre quais pais foram citados e nunca coletados; a
opção 3 os coleta; a segunda execução da 4 incorpora esses processos ao grafo e recalcula.
O ciclo termina quando a lista de órfãos sai vazia — e ele **converge** por causa do
critério documentado em [`sqlite_store.orfaos`](../src/store/sqlite_store.md).

| Opção | O que faz | Usa rede? |
|---|---|---|
| 1 | Coleta os números de `data/entrada/<projeto>.txt`, pulando o que já tem desfecho | Sim |
| 2 | Recoleta apenas os `erro_transitorio` | Sim |
| 3 | Coleta os órfãos listados em `orfaos.txt` | Sim |
| 4 | Reprojeta vínculos, exporta o JSONL, recalcula os órfãos | **Não** |
| 0 | Sai, fechando o banco | — |

### A reprojeção vem antes do export

```python
def opcao_4(store):
    """Local, sem rede. Reprojeta vínculos, exporta o JSONL e recalcula órfãos.

    A reprojeção vem PRIMEIRO porque orfaos() e o mapa de filhos são calculados
    a partir das colunas de vínculo: exportar antes de reprojetar produziria uma
    base final coerente com a regra ANTIGA de derivação.
    """
```

A ordem não é arbitrária. `tipo_vinculo` e `processo_pai` são valores derivados que vivem em
**coluna**, não na projeção — porque `orfaos()` e `vinculos()` precisam deles em SQL. Isso
cria uma exceção à regra geral do projeto (o bruto é a verdade, todo o resto é recalculado
no export), e `reprojetar_vinculos` é o que fecha essa brecha: mudar a regra de derivação
volta a ser uma operação local.

Se o export rodasse primeiro, o JSONL sairia coerente com a regra antiga e só a execução
seguinte da opção 4 o corrigiria — sem que nada indicasse a defasagem.

O custo é controlado por versão de regra:

```python
rep = store.reprojetar_vinculos(
    derivar_vinculo, INDEFINIDO, VERSAO_REGRA, log=tqdm.write
)
if rep["pulado"]:
    print(f"Vínculos já na regra v{VERSAO_REGRA} — reprojeção dispensada.")
```

Sem essa guarda, toda execução da opção 4 releria o `bruto` da base inteira — o grosso do
banco — mesmo sem nenhuma mudança de regra.

### Workers fazem rede; a thread principal grava

```python
def executar_coleta(store, fabrica, numeros, origem, descricao):
    """Laço de coleta com pool de workers.

    Os workers fazem SÓ rede e parse; quem grava no banco é a thread principal.
    Assim o SqliteStore não precisa ser thread-safe — menos código e menos risco
    do que um lock de escrita ou uma thread escritora dedicada.

    A submissão é LIMITADA a WORKERS*2 em voo: enfileirar 250 mil futures de uma
    vez estouraria a memória antes da primeira requisição sair.

    Nenhuma falha de um processo derruba o laço; só o circuit breaker (e-SAJ
    fora do ar / bloqueio) interrompe, de propósito.
    """
```

Três decisões numa docstring. A primeira é a que evita um problema inteiro: como
`coletar_um` é uma função pura que devolve um `ResultadoColeta` (ver
[`coletor`](../src/scrapers/coletor.md)), os workers nunca tocam o banco. O
[`SqliteStore`](../src/store/sqlite_store.md) pode então ser um objeto comum, sem lock e sem
fila de escrita.

A segunda é o controle de submissão. `ThreadPoolExecutor` aceita quantos `submit` você
quiser e enfileira todos — com 250 mil números, a fila de futures estoura a memória antes de
a primeira requisição sair. O laço mantém no máximo `WORKERS * 2` em voo:

```python
while parada is None and len(pendentes) < WORKERS * 2:
    try:
        pendentes.add(pool.submit(tarefa, next(fila)))
    except StopIteration:
        break
```

### Workers não aceleram a coleta — e o código diz isso

```python
# Workers NÃO aumentam a taxa vista pelo e-SAJ: o Pacer é global e o teto
# continua 1 requisição a cada 1,7-2,5s. Eles evitam que um pico de latência
# numa página deixe a fila ociosa e perca slots.
WORKERS = max(1, int(os.environ.get("ORQUESTRADOR_WORKERS") or 3))
```

O comentário está no ponto em que alguém seria tentado a aumentar o número. O `Pacer` e o
`MonitorFalhas` são criados **uma vez** e compartilhados por todos os clientes; a explicação
completa está em [`esaj_client`](../src/scrapers/esaj_client.md).

```python
if fabrica is None:
    # Pacer e monitor criados UMA vez e compartilhados por todos os
    # workers — é isso que mantém a cadência e o circuito globais.
    fabrica = fabrica_cliente(Pacer(), MonitorFalhas())
```

A fábrica só é construída quando uma opção precisa de rede — a opção 4 nunca cria cliente
nenhum.

### Duas formas de parar, ambas preservando o que foi pago

```python
except EsajIndisponivelError as erro:
    # Para de submeter, mas drena o que já está em voo:
    # esses resultados foram pagos e não podem ser perdidos.
    parada = str(erro)
    continue
```

```python
except KeyboardInterrupt:
    parada = "interrompido pelo usuário (Ctrl+C)"
```

Nos dois casos a variável `parada` interrompe a submissão de trabalho novo, mas o laço
continua consumindo o que já está em execução. Cada resultado em voo custou uma requisição
contra um portal público; descartá-los seria jogar fora o recurso mais caro do pipeline.

A mensagem final fecha o contrato com o operador:

```python
if parada:
    print(f"\n!! EXECUÇÃO INTERROMPIDA: {parada}")
    print("   Nada foi perdido. Rode a mesma opção para retomar de onde parou.")
```

### Sem bruto, o vínculo é `indefinido` — não `sem_vinculo`

```python
# `tipo` do relacionamento tem UM único escritor: derivar_vinculo.
# Sem bruto (segredo de justiça, sem dados) o tipo é INDEFINIDO, não
# sem_vinculo: nunca chegamos a olhar a capa, então "não há sinal de
# pai" seria afirmação sobre algo que a coleta não observou.
vinc = {"tipo": INDEFINIDO, "processo_pai": None,
        "processo_pai_grau": None, "observacoes": []}
```

A mesma disciplina epistêmica que separa `sem_dados` de `erro_transitorio` em
[`status`](../src/status.md), aplicada ao relacionamento: afirmar "não há pai" exige ter
olhado. Ver [`vinculo`](../src/transformers/vinculo.md).

### Escrita atômica também nos `.txt`

```python
def _escrever_atomico(caminho, linhas):
    """tmp + os.replace: interromper nunca deixa um arquivo pela metade — e a
    lista de falhas é o dado mais caro de reconstruir do pipeline."""
```

O mesmo padrão do [`exportador`](../src/aggregators/exportador.md). Os `.txt` são
regeneráveis a partir do banco, mas um arquivo truncado é pior que um ausente: a opção 2
leria uma fila incompleta sem qualquer sinal.

### `utf-8-sig` na leitura da entrada

```python
def ler_numeros(caminho):
    """Lê o .txt (um número por linha) e devolve (válidos, inválidos).

    utf-8-sig remove o BOM que o Excel insere e que quebraria o primeiro número
    em silêncio. Dedup com set(). Valida o DV antes de gastar requisição.
    """
```

O detalhe do BOM é o tipo de coisa que só aparece em produção: o Excel salva CSV/TXT com
marca de ordem de byte, e o primeiro número do arquivo chega com três caracteres invisíveis
na frente. Com `utf-8` puro ele falharia na validação e o operador veria "1 número inválido"
sem entender por quê.

A validação de DV e de tribunal acontece **antes** de qualquer requisição — a
justificativa está em [`numero_processo`](../src/scrapers/numero_processo.md).

## Como Executar

```bash
# A partir da raiz do projeto, com o nome do projeto como argumento
uv run python scripts/menu.py iamspe_2026

# Sem argumento, o script pergunta
uv run python scripts/menu.py
```

O nome é sanitizado antes de virar caminho:

```python
nome = re.sub(r"[^A-Za-z0-9_.-]", "_", nome)
```

Antes de rodar, coloque os números — um por linha — em `data/entrada/<nome>.txt`.

Se o projeto vive em pasta sincronizada (OneDrive, Drive), aponte o banco para disco local:

```bash
# PowerShell
$env:ORQUESTRADOR_DB_DIR = 'C:\dados_coleta'

# bash
export ORQUESTRADOR_DB_DIR=/home/voce/dados_coleta
```

## Principais Parâmetros (constantes no código)

| Constante | Valor | Descrição |
|-----------|-------|-------------|
| `RAIZ` | `Path(__file__).resolve().parents[1]` | Raiz do repositório; também é inserida em `sys.path` para os imports de `src/` |
| `DIR_DADOS` | `RAIZ / "data"` | Pasta base de entrada e saída |
| `DIR_BANCOS` | `$ORQUESTRADOR_DB_DIR` ou `data/bancos` | Onde ficam os `.db`. Variável de ambiente para tirar o banco de pasta sincronizada |
| `WORKERS` | `$ORQUESTRADOR_WORKERS` ou `3` | Threads de coleta. **Não** aumenta a taxa de requisições |
| `ENTRADA` | `data/entrada/<nome>.txt` | Lista de números (um por linha; `#` é comentário) |
| `SAIDA` | `data/saida/<nome>/` | Pasta de saída do projeto |
| `JSONL` | `<SAIDA>/base_final.jsonl` | Base final exportada |
| `ORFAOS` | `<SAIDA>/orfaos.txt` | Entrada da opção 3 (regenerado pela opção 4) |
| `FALHAS` | `<SAIDA>/falhas_pendentes.txt` | Visão da fila da opção 2 |
| `REVISAO` | `<SAIDA>/revisao_manual.txt` | Estouraram o teto de tentativas |
| `INVALIDOS` | `<SAIDA>/numeros_invalidos.txt` | Números rejeitados na leitura, com o motivo |
| `BANCO` | `<DIR_BANCOS>/<nome>.db` | Checkpoint SQLite |

Todos os caminhos derivados são definidos por `configurar_projeto(nome)`, chamada no início
de `main()`.

## Logs e Monitoramento

O script usa `print()` e `tqdm.write()`, não o módulo `logging`. Isso é coerente com o
[guia de logging](../guias/logging_padrao.md), que registra que scripts existentes podem
ainda usar `print()` — mas há uma restrição própria deste script:

**dentro do laço de coleta, toda saída precisa passar por `tqdm.write`.** Um `print()`
comum durante a barra de progresso corrompe a linha da barra:

```python
tqdm.write(f"[{r.status}] {numero} (grau {r.grau})")
```

```python
tqdm.write(f"[{st}] {numero}: {r.motivo}")
```

É por isso que a opção 4 injeta `log=tqdm.write` nas funções de `src/` que reportam
progresso — elas têm `log=print` como padrão justamente para não depender do `tqdm`.

Os prefixos entre colchetes seguem a convenção do guia, com o status como rótulo:
`[coletado]`, `[segredo_justica]`, `[erro_transitorio]`, `[erro_persistente]`.

O monitoramento de estado não é feito por log, e sim pelos arquivos regenerados a cada
execução, mais o resumo impresso por `_mostrar`:

```python
pend, persist = atualizar_arquivos_de_falha(store)
print(f"\nFalhas pendentes (opção 2): {pend}  -> {FALHAS.name}")
print(f"Revisão manual:             {persist}  -> {REVISAO.name}")
print(f"Total no banco: {store.total()} | por status: {store.contagem_por_status()}")
```

A opção 2 ainda grava um relatório com carimbo de tempo, explicitamente marcado como
auditoria para que ninguém tente editá-lo:

```python
"# Este arquivo é AUDITORIA: não precisa editar, apagar linhas nem",
f"# renomear. A fila da opção 2 é regenerada em {FALHAS.name}.",
```

## Falhas Conhecidas e Workarounds

- **Problema:** o banco está em pasta sincronizada (OneDrive, Drive, Dropbox).
  **Workaround:** o script recusa abrir e imprime o comando exato para as duas shells:

  ```python
  except PastaSincronizadaError as erro:
      print(f"\n{erro}\n")
      print("Defina ORQUESTRADOR_DB_DIR apontando para uma PASTA em disco local:")
  ```

- **Problema:** o e-SAJ cai ou bloqueia o acesso no meio da coleta.
  **Workaround:** o circuit breaker interrompe a execução (ver
  [`esaj_client`](../src/scrapers/esaj_client.md)); os resultados em voo são gravados e a
  mesma opção retoma de onde parou.

- **Problema:** o operador precisa interromper (`Ctrl+C`).
  **Workaround:** tratado como parada graciosa — o que está em voo é drenado, os arquivos
  de falha são regenerados e o banco é fechado no `finally`.

- **Problema:** a opção 3 é escolhida antes de a 4 ter rodado.
  **Workaround:** mensagem explícita, em vez de erro de arquivo inexistente:

  ```python
  if not ORFAOS.exists():
      print(f"\n{ORFAOS.name} não existe. Rode a opção 4 primeiro para gerá-lo.")
  ```

- **Problema:** o arquivo de entrada foi salvo pelo Excel e tem BOM.
  **Workaround:** resolvido silenciosamente com `encoding="utf-8-sig"` na leitura.

- **Problema:** números inválidos na lista de entrada.
  **Workaround:** não interrompem a execução; vão para `numeros_invalidos.txt` com o motivo
  (sem 20 dígitos, DV inválido, ou fora do TJSP) e a coleta segue com os válidos.

## Decisões Futuras

- [ ] Migrar `print()`/`tqdm.write()` para `logging` com `FileHandler`, conforme o
      [padrão de logging](../guias/logging_padrao.md) — hoje não há registro em arquivo do
      que aconteceu numa execução longa, só o que ficou no terminal.
- [ ] Expor `store.backup(destino)` como opção do menu. O método existe e usa
      `VACUUM INTO`, mas não há caminho pela interface.
- [ ] Permitir ajustar a cadência (`Pacer(minimo, maximo)`) por variável de ambiente, como
      já acontece com `ORQUESTRADOR_WORKERS`.
- [ ] Opção para forçar a reprojeção de vínculos (`forcar=True`) sem depender de a
      `VERSAO_REGRA` ter mudado.
- [ ] Testes automatizados do laço de coleta com um `client` dublê, conforme as invariantes
      listadas em [`coletor`](../src/scrapers/coletor.md).

## Relação com Outros Artefatos

Este script é o único consumidor de quase todos os módulos de `src/`:

| Módulo | Usado para |
|---|---|
| [`src/scrapers/numero_processo`](../src/scrapers/numero_processo.md) | Validar e desduplicar a entrada antes de gastar requisição |
| [`src/scrapers/esaj_client`](../src/scrapers/esaj_client.md) | `Pacer` e `MonitorFalhas` compartilhados; um `EsajClient` por thread |
| [`src/scrapers/coletor`](../src/scrapers/coletor.md) | `coletar_um` — a máquina de estados de um processo |
| [`src/scrapers/exceptions`](../src/scrapers/exceptions.md) | `EsajIndisponivelError` como sinal de parada geral |
| [`src/status`](../src/status.md) | `ERRO_TRANSITORIO`, `ORIGEM_LISTA`, `ORIGEM_ORFAO` |
| [`src/store/sqlite_store`](../src/store/sqlite_store.md) | Checkpoint, filas, reprojeção de vínculos |
| [`src/transformers/vinculo`](../src/transformers/vinculo.md) | `derivar_vinculo`, `INDEFINIDO`, `VERSAO_REGRA` |
| [`src/aggregators/exportador`](../src/aggregators/exportador.md) | `exportar_jsonl` e `escrever_lista_orfaos` |

O único módulo de `src/` que **não** passa por aqui é o par de parsers, alcançado
indiretamente pelo `coletor`.

Antes de uma coleta em massa, [`spike_seletores`](spike_seletores.md) diagnostica os
seletores contra HTML real — ele não grava no banco e não compartilha estado com este
script.

A saída `base_final.jsonl` é o artefato final do projeto, pronto para `mongoimport`.

## Lições Aprendidas

- **Fazer do banco a única fonte de verdade eliminou uma classe inteira de erro de
  operação.** Nenhum arquivo precisa ser editado à mão, e nenhum arquivo apagado por engano
  perde trabalho.

- **A separação "workers fazem rede, thread principal grava" foi mais barata que
  sincronizar o banco.** Não há lock, não há thread escritora, e o `SqliteStore` continua um
  objeto comum.

- **Limitar a submissão a `WORKERS * 2` foi necessário, não uma otimização.** Enfileirar
  todos os futures de uma vez estoura a memória antes da primeira requisição.

- **Deixar a instrução de uso dentro do menu funciona melhor que documentá-la fora.** O
  fluxo `1 → 4 → 3 → 4` está na tela que o operador vê a cada iteração.

- **Derivar tudo do nome do projeto tornou o isolamento automático.** Não há como
  contaminar uma coleta com outra por esquecer de trocar um caminho.

- **Uma coluna derivada precisa de um caminho de reprojeção.** `tipo_vinculo` mora em coluna
  porque as consultas de grafo são SQL; sem `reprojetar_vinculos`, mudar a regra de
  derivação exigiria recoletar — quebrando a promessa de que só o `bruto` é caro de obter.

## Pontos em aberto

- **Metade das funções depende de globais que só existem depois de `configurar_projeto()`.**
  `ENTRADA`, `SAIDA`, `JSONL`, `ORFAOS`, `FALHAS`, `REVISAO`, `INVALIDOS` e `BANCO` nascem
  como `None` no nível do módulo e são preenchidos por efeito colateral:

  ```python
  ENTRADA = SAIDA = JSONL = ORFAOS = FALHAS = REVISAO = INVALIDOS = BANCO = None
  ```

  `atualizar_arquivos_de_falha`, `escrever_relatorio` e `_mostrar` recebem `store` como
  parâmetro mas leem os caminhos dos globais. Chamar qualquer uma antes de
  `configurar_projeto` levanta `AttributeError` num ponto distante da causa (`None.name`).
  Como o único ponto de entrada é `main()`, que sempre configura primeiro, o problema não
  ocorre hoje — mas nenhuma dessas funções é reutilizável fora desse fluxo, e nada no código
  declara a pré-condição.

- **A opção 2 reclassifica a origem dos órfãos como `lista`.** A chamada é fixa:

  ```python
  resumo, parada = executar_coleta(
      store, fabrica, pendentes, ORIGEM_LISTA, "Recoletando"
  )
  ```

  A fila da opção 2 vem de `numeros_com_erro_transitorio()`, que não distingue procedência —
  ela inclui números que falharam durante a opção 3, gravados com `ORIGEM_ORFAO`. Quando um
  deles é recoletado com sucesso, o resultado entra numa **linha nova** (grau 1 ou 2, contra
  a linha de erro em grau 0), e essa linha recebe `origem = "lista"`. O processo passa a
  constar como se tivesse vindo do arquivo de entrada.

  O efeito fica restrito a consultas sobre a coluna `origem` — nada no fluxo do menu a
  utiliza. Registro porque a coluna existe justamente para separar "a base que pedi" da
  "base que descobri", e essa distinção se perde no caminho da recoleta.

- **A opção 3 descarta os números inválidos sem registrá-los.**

  ```python
  numeros, _ = ler_numeros(ORFAOS)
  ```

  A opção 1 grava os rejeitados em `numeros_invalidos.txt` com o motivo; aqui o segundo
  retorno é ignorado. Como `vinculo._dv_ok` já filtra o dígito verificador antes de criar a
  aresta, o caso restante é o de um pai **fora do TJSP** (`np.do_tjsp` falso) — um número de
  outro tribunal citado como processo principal. Ele sumiria da fila sem aparecer em lugar
  nenhum, e continuaria sendo listado como órfão em toda execução da opção 4.

- **A docstring do módulo descreve a opção 4 sem mencionar a reprojeção.** O cabeçalho diz
  apenas *"4 - transforma os dados coletados na estrutura JSON final (local, sem rede)"*,
  enquanto a docstring de `opcao_4` já registra os três passos. Não é incorreto — a
  reprojeção é parte de "transformar" —, mas quem ler só o topo do arquivo não descobre que
  a opção 4 escreve no banco.
