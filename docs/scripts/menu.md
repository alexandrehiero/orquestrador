# Orquestrador interativo – `scripts/menu.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `tqdm`, `concurrent.futures`, e todos os módulos de `src/` |

## Contexto e Motivação

Este é o único ponto de entrada do projeto. Tudo o que os módulos de `src/` sabem fazer só acontece quando este script os encadeia — e o encadeamento é pensado para quem vai operar uma coleta de dias sem ser quem escreveu o código.

**Um projeto = uma lista + um banco + uma pasta de saída**, todos derivados do nome passado na linha de comando. Um pesquisador pode ter uma coleta do IAMSPE em andamento e começar outra, da PGE, sem que a segunda toque na primeira — mesmo que as listas compartilhem processos.

**O banco é a fonte da verdade; os `.txt` são visões regeneradas a cada execução.** O modelo comum em scripts de coleta — "edite o arquivo de pendências e rode de novo" — transfere ao operador a responsabilidade de manter um estado consistente com milhares de linhas. Aqui os `.txt` são saída, nunca entrada de estado: apagar `falhas_pendentes.txt` não perde nada.

## Decisões de Pipeline

| Opção | O que faz | Usa rede? |
|---|---|---|
| 1 | Coleta os números de `data/entrada/<projeto>.txt`, pulando o que já tem desfecho | Sim |
| 2 | Recoleta apenas os `erro_transitorio` | Sim |
| 3 | Coleta os órfãos listados em `orfaos.txt` | Sim |
| 4 | Reprojeta vínculos, exporta o JSONL, recalcula os órfãos | **Não** |
| 0 | Sai, fechando o banco | — |

- **O fluxo é 1 → 4 → 3 → 4, e a instrução está dentro do próprio menu** — não num README que ninguém abre. A opção 4 aparece duas vezes porque faz duas coisas: exporta a base **e** recalcula os órfãos. A primeira execução descobre quais pais foram citados e nunca coletados; a 3 os coleta; a segunda 4 os incorpora ao grafo. O ciclo **converge** pelo critério de [`sqlite_store.orfaos`](../src/store/sqlite_store.md).
- **A reprojeção vem antes do export** — `orfaos()` e o mapa de filhos são calculados a partir das colunas de vínculo. Exportar antes produziria um JSONL coerente com a regra **antiga**, e só a execução seguinte o corrigiria, sem nada indicar a defasagem.
- **A reprojeção é guardada por versão de regra** — sem a guarda, toda opção 4 releria o `bruto` da base inteira, o grosso do banco, mesmo sem mudança nenhuma.
- **Workers fazem rede e parse; a thread principal grava** — como `coletar_um` é função pura que devolve um `ResultadoColeta`, os workers nunca tocam o banco, e o [`SqliteStore`](../src/store/sqlite_store.md) pode ser um objeto comum, sem lock nem thread escritora.
- **A submissão é limitada a `WORKERS * 2` em voo** — `ThreadPoolExecutor` aceita quantos `submit` você quiser e enfileira todos; com 250 mil números, a fila de futures estoura a memória antes de a primeira requisição sair. Não é otimização, é necessidade.
- **Workers não aceleram a coleta, e o código diz isso no ponto da tentação** — o `Pacer` e o `MonitorFalhas` são criados uma vez e compartilhados, então o teto continua 1 requisição a cada 1,7–2,5 s. Eles só evitam que um pico de latência deixe a fila ociosa. A fábrica só é construída quando uma opção precisa de rede: a opção 4 nunca cria cliente.
- **Duas formas de parar, ambas preservando o que foi pago** — o disjuntor (`EsajIndisponivelError`) e o `Ctrl+C` interrompem a submissão de trabalho novo, mas o laço continua consumindo o que está em execução. Cada resultado em voo custou uma requisição contra um portal público.
- **Sem bruto, o vínculo é `indefinido`, não `sem_vinculo`** — afirmar "não há pai" exige ter olhado, e em segredo de justiça a capa foi negada. Mesma disciplina que separa `sem_dados` de `erro_transitorio`.
- **Escrita atômica também nos `.txt`** — os arquivos são regeneráveis, mas um truncado é pior que um ausente: a opção 2 leria uma fila incompleta sem qualquer sinal.
- **`utf-8-sig` na leitura da entrada** — o Excel salva com BOM, e o primeiro número chegaria com três caracteres invisíveis na frente. Com `utf-8` puro o operador veria "1 número inválido" sem entender por quê. A validação de DV e tribunal acontece **antes** de qualquer requisição.

## Como Executar

```bash
# A partir da raiz do projeto, com o nome do projeto como argumento
uv run python scripts/menu.py iamspe_2026
uv run python scripts/menu.py            # sem argumento, o script pergunta
```

O nome é sanitizado (`re.sub(r"[^A-Za-z0-9_.-]", "_", nome)`) antes de virar caminho. Antes de rodar, coloque os números — um por linha — em `data/entrada/<nome>.txt`.

Se o projeto vive em pasta sincronizada (OneDrive, Drive), aponte o banco para disco local:

```bash
$env:ORQUESTRADOR_DB_DIR = 'C:\dados_coleta'      # PowerShell
export ORQUESTRADOR_DB_DIR=/home/voce/dados_coleta # bash
```

## Principais Parâmetros (constantes no código)

| Constante | Valor | Descrição |
|-----------|-------|-------------|
| `DIR_BANCOS` | `$ORQUESTRADOR_DB_DIR` ou `data/bancos` | Onde ficam os `.db`. A variável existe para tirar o banco de pasta sincronizada |
| `WORKERS` | `$ORQUESTRADOR_WORKERS` ou `3` | Threads de coleta. **Não** aumenta a taxa de requisições |
| `ENTRADA` | `data/entrada/<nome>.txt` | Lista de números (um por linha; `#` é comentário) |
| `SAIDA` | `data/saida/<nome>/` | Pasta de saída do projeto |
| `JSONL` | `<SAIDA>/base_final.jsonl` | Base final exportada |
| `ORFAOS` | `<SAIDA>/orfaos.txt` | Entrada da opção 3 (regenerado pela opção 4) |
| `FALHAS` | `<SAIDA>/falhas_pendentes.txt` | Visão da fila da opção 2 |
| `REVISAO` | `<SAIDA>/revisao_manual.txt` | Estouraram o teto de tentativas |
| `INVALIDOS` | `<SAIDA>/numeros_invalidos.txt` | Números rejeitados na leitura, com o motivo |
| `BANCO` | `<DIR_BANCOS>/<nome>.db` | Checkpoint SQLite |

Todos os caminhos derivados são definidos por `configurar_projeto(nome)`, chamada no início de `main()`.

## Logs e Monitoramento

O script usa `print()` e `tqdm.write()`, não o módulo `logging` — coerente com o [guia de logging](../guias/logging_padrao.md), que admite `print()` em scripts existentes. Há uma restrição própria: **dentro do laço de coleta, toda saída precisa passar por `tqdm.write`**, senão a linha da barra de progresso é corrompida. É por isso que a opção 4 injeta `log=tqdm.write` nas funções de `src/`, que têm `log=print` como padrão para não depender do `tqdm`.

Os prefixos entre colchetes usam o status como rótulo: `[coletado]`, `[segredo_justica]`, `[erro_transitorio]`, `[erro_persistente]`.

O monitoramento de estado não é feito por log, e sim pelos arquivos regenerados a cada execução mais o resumo impresso ao fim (`total()` e `contagem_por_status()`). A opção 2 grava um relatório com carimbo de tempo, marcado no cabeçalho como **auditoria**, para que ninguém tente editá-lo.

## Falhas Conhecidas e Workarounds

- **Banco em pasta sincronizada.** O script recusa abrir e imprime o comando exato para as duas shells.
- **O e-SAJ cai ou bloqueia no meio da coleta.** O disjuntor interrompe; os resultados em voo são gravados e a mesma opção retoma de onde parou.
- **O operador interrompe com `Ctrl+C`.** Parada graciosa: o que está em voo é drenado, os arquivos de falha são regenerados e o banco é fechado no `finally`.
- **A opção 3 é escolhida antes de a 4 ter rodado.** Mensagem explícita, em vez de erro de arquivo inexistente.
- **Entrada salva pelo Excel, com BOM.** Resolvido silenciosamente por `utf-8-sig`.
- **Números inválidos na lista.** Não interrompem: vão para `numeros_invalidos.txt` com o motivo (sem 20 dígitos, DV inválido, ou fora do TJSP) e a coleta segue com os válidos.
- **Metade das funções depende de globais preenchidos por `configurar_projeto()`.** `atualizar_arquivos_de_falha`, `escrever_relatorio` e `_mostrar` recebem `store` por parâmetro mas leem caminhos de globais. Não ocorre hoje (só `main()` chama), mas nenhuma é reutilizável fora desse fluxo. Ver [backlog §5](../backlog.md).
- **A opção 2 reclassifica a origem dos órfãos como `lista`,** e **a opção 3 descarta os números inválidos sem registrá-los.** Ambos em [backlog §5](../backlog.md).

## Decisões Futuras

- [ ] Migrar `print()`/`tqdm.write()` para `logging` com `FileHandler` — hoje não há registro em arquivo do que aconteceu numa execução longa.
- [ ] Expor `store.backup(destino)` como opção do menu; o método existe e usa `VACUUM INTO`.
- [ ] Permitir ajustar a cadência (`Pacer(minimo, maximo)`) por variável de ambiente.
- [ ] Opção para forçar a reprojeção (`forcar=True`) sem depender de a `VERSAO_REGRA` ter mudado.
- [ ] Testes do laço de coleta com um `client` dublê — ver [backlog de testes](../backlog_testes.md).

## Relação com Outros Artefatos

Este script é o único consumidor de quase todos os módulos de `src/`:

| Módulo | Usado para |
|---|---|
| [`numero_processo`](../src/scrapers/numero_processo.md) | Validar e desduplicar a entrada antes de gastar requisição |
| [`esaj_client`](../src/scrapers/esaj_client.md) | `Pacer` e `MonitorFalhas` compartilhados; um `EsajClient` por thread |
| [`coletor`](../src/scrapers/coletor.md) | `coletar_um` — a máquina de estados de um processo |
| [`exceptions`](../src/scrapers/exceptions.md) | `EsajIndisponivelError` como sinal de parada geral |
| [`status`](../src/status.md) | `ERRO_TRANSITORIO`, `ORIGEM_LISTA`, `ORIGEM_ORFAO` |
| [`sqlite_store`](../src/store/sqlite_store.md) | Checkpoint, filas, reprojeção de vínculos |
| [`vinculo`](../src/transformers/vinculo.md) | `derivar_vinculo`, `INDEFINIDO`, `VERSAO_REGRA` |
| [`exportador`](../src/aggregators/exportador.md) | `exportar_jsonl` e `escrever_lista_orfaos` |

O único módulo que **não** passa por aqui é o par de parsers, alcançado indiretamente pelo coletor. Antes de uma coleta em massa, [`spike_seletores`](spike_seletores.md) diagnostica os seletores contra HTML real — sem gravar no banco e sem compartilhar estado com este script.

## Lições Aprendidas

- **Fazer do banco a única fonte de verdade eliminou uma classe inteira de erro de operação.** Nenhum arquivo precisa ser editado à mão, e nenhum arquivo apagado por engano perde trabalho.
- **"Workers fazem rede, thread principal grava" foi mais barato que sincronizar o banco.** Sem lock, sem thread escritora, e o store continua um objeto comum.
- **Limitar a submissão a `WORKERS * 2` foi necessário, não otimização.**
- **A instrução de uso dentro do menu funciona melhor que documentada fora.** O fluxo está na tela que o operador vê a cada iteração.
- **Derivar tudo do nome do projeto tornou o isolamento automático.**
- **Uma coluna derivada precisa de um caminho de reprojeção,** senão mudar a regra exigiria recoletar — quebrando a promessa de que só o `bruto` é caro de obter.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-11 | @alexandrehiero | Criação |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 10 decisões virou lista de tópicos; código copiado removido; "Pontos em aberto" migrou para o backlog |
