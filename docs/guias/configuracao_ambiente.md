# Configuração do Ambiente

Guia para pesquisadores configurarem o ambiente local do projeto `orquestrador`.

## Pré-requisitos

- **Python 3.11+** (versão declarada em `requires-python`, no `pyproject.toml`)
- **uv** — gerenciador de pacotes e ambientes virtuais

### Instalando o uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ou via pip
pip install uv
```

## Configuração inicial

```bash
git clone <url-do-repositorio>
cd orquestrador
uv sync
```

O `uv sync` cria o ambiente virtual (`.venv/`) e instala as dependências de `pyproject.toml`.

## Executando código

```bash
# Orquestrador de coleta (ponto de entrada do projeto)
uv run python scripts/menu.py <nome_do_projeto>

# Diagnóstico de seletores, antes de qualquer coleta em massa
uv run python scripts/spike_seletores.py <nome_do_projeto>
uv run python scripts/spike_seletores.py 0000001-58.2013.8.26.0477

# Python interativo
uv run python

# Módulos
uv run python -m src.scrapers.numero_processo
```

O `<nome_do_projeto>` determina **todos** os caminhos de entrada e saída — um projeto é uma
lista, um banco e uma pasta de saída. Bases diferentes com processos em comum não
interferem uma na outra. Ver [`scripts/menu`](../scripts/menu.md).

## Dados locais

Coloque os dados em `data/`. Nem tudo ali é ignorado pelo Git: a **lista de entrada é
versionada**, e apenas as saídas, os bancos e os temporários ficam de fora
(`data/saida/`, `data/spike/`, `*.db`, `*.tmp`).

| Caminho | Uso | Versionado? |
|---------|-----|-------------|
| `data/entrada/<projeto>.txt` | Lista de números CNJ, um por linha (`#` é comentário) | Sim |
| `data/bancos/<projeto>.db` | Checkpoint SQLite da coleta | Não (`*.db`) |
| `data/saida/<projeto>/base_final.jsonl` | Base final, pronta para `mongoimport` | Não |
| `data/saida/<projeto>/orfaos.txt` | Pais citados sem registro — entrada da opção 3 | Não |
| `data/saida/<projeto>/orfaos_diagnostico.txt` | Os mesmos órfãos, com os graus em que foram citados | Não |
| `data/saida/<projeto>/falhas_pendentes.txt` | Fila da opção 2 | Não |
| `data/saida/<projeto>/revisao_manual.txt` | Estouraram o teto de tentativas | Não |
| `data/saida/<projeto>/numeros_invalidos.txt` | Números rejeitados na leitura, com o motivo | Não |
| `data/spike/<numero>_g<grau>.html` | HTML salvo pelo diagnóstico de seletores | Não |

Os arquivos de `data/saida/` são **visões regeneradas** a cada execução — o banco é a fonte
da verdade. Apagar qualquer um deles não perde trabalho.

## Variáveis de ambiente

| Variável | Padrão | Para que serve |
|----------|--------|----------------|
| `ORQUESTRADOR_DB_DIR` | `data/bancos` | Diretório dos bancos SQLite |
| `ORQUESTRADOR_WORKERS` | `3` | Threads de coleta |

**O banco não pode ficar em pasta sincronizada.** Clientes de sincronização (OneDrive,
Google Drive, Dropbox) copiam o `.db` e o `-wal` em momentos diferentes e produzem um banco
incoerente **sem emitir erro** — semanas de coleta perdidas em silêncio. O projeto detecta
isso e se recusa a abrir:

```bash
# PowerShell
$env:ORQUESTRADOR_DB_DIR = 'C:\dados_coleta'

# bash
export ORQUESTRADOR_DB_DIR=/home/voce/dados_coleta
```

Aumentar `ORQUESTRADOR_WORKERS` **não** acelera a coleta: a cadência é global (uma
requisição a cada 1,7–2,5s, com ou sem workers). Os workers só evitam que um pico de
latência numa página deixe a fila ociosa. Ver
[`src/scrapers/esaj_client`](../src/scrapers/esaj_client.md).

## Adicionando dependências

```bash
# Dependência principal
uv add pandas

# Dependência de desenvolvimento
uv add --dev pytest

# Com versão específica
uv add "beautifulsoup4>=4.12"
```

Sempre use `uv add` em vez de `pip install` direto — isso mantém `pyproject.toml` e
`uv.lock` sincronizados.

As dependências de execução do projeto são poucas e cada uma tem um motivo registrado:

| Pacote | Onde é usado | Por quê |
|--------|--------------|---------|
| `curl_cffi` | [`esaj_client`](../src/scrapers/esaj_client.md) | Imita a impressão digital TLS de um navegador real; `requests` é bloqueado |
| `beautifulsoup4` | `page_state`, parsers, `spike_seletores` | Parsing do HTML das capas |
| `tqdm` | [`menu`](../scripts/menu.md) | Barra de progresso em coletas longas |

## Documentação (MkDocs)

```bash
# Servidor local com live-reload
uv run mkdocs serve

# Build estático (pasta site/), falhando em qualquer link quebrado
uv run mkdocs build --strict
```

Use sempre `--strict` antes de abrir PR: ele promove link quebrado a erro, em vez de
aviso.

A documentação fica em `docs/`. Veja a [página inicial](../index.md) para a visão geral do
projeto e o mapa dos módulos.

## Documentando seu trabalho

Ao criar um novo artefato, copie o template ADR correspondente:

| Tipo | Template | Destino |
|------|----------|---------|
| Módulo `src/` | [`docs/src/template_src.md`](../src/template_src.md) | `docs/src/<caminho>/<nome>.md` |
| Script | [`docs/scripts/template_script.md`](../scripts/template_script.md) | `docs/scripts/<nome>.md` |
| Notebook | [`docs/notebooks/template_notebook.md`](../notebooks/template_notebook.md) | `docs/notebooks/<nome>.md` |

A estrutura de `docs/src/` e `docs/scripts/` **espelha** a de `src/` e `scripts/`: cada
`.py` tem um `.md` de mesmo nome no caminho equivalente. `__init__.py` vazios não são
documentados.

Registre a nova página no `nav` do `mkdocs.yml` (raiz do repositório) e abra PR com código +
ADR juntos. Pontos ambíguos ou que pareçam defeito vão para a seção **Pontos em aberto** da
página e depois para o [backlog](../backlog.md).

## Referências

- [Documentação do uv](https://docs.astral.sh/uv/)
- [Página inicial da documentação](../index.md) — visão geral e mapa dos módulos
- [Padrão de logging](logging_padrao.md) — convenções para scripts de pipeline
