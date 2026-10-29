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

O `<nome_do_projeto>` determina **todos** os caminhos de entrada e saída — um projeto é uma lista, um banco e uma pasta de saída. Bases diferentes com processos em comum não interferem uma na outra. Ver [`scripts/menu`](../scripts/menu.md). Num computador que já coleta, depois de uma versão nova do código, siga a [sequência de comandos](atualizar_notebook.md).

## Dados locais

Coloque os dados em `data/`. Nem tudo ali é ignorado pelo Git: a **lista de entrada é versionada**, e apenas as saídas, os bancos e os temporários ficam de fora
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
| `data/saida/<projeto>/relatorio_rotas_novas_<data>.txt` | Desfecho de cada número recoletado pela opção 5 | Não |
| `data/saida/<projeto>/atualizacao_nao_atualizados.txt` | Opção 6: registros mantidos ou desistidos, com o motivo | Não |
| `data/spike/<numero>_g<grau>.html` | HTML salvo pelo diagnóstico de seletores | Não |

Os arquivos de `data/saida/` são **visões regeneradas** a cada execução — o banco é a fonte da verdade. Apagar qualquer um deles não perde trabalho.

A base final de um ano ([`preparar_base_final`](../scripts_final/preparar_base_final.md)) usa mais estas fontes, todas fora do Git (`data/` e `data_final/` estão no `.gitignore`):

| Caminho | Uso | De onde vem |
|---------|-----|-------------|
| `data/por_ano/processos_tjsp_<ano>.txt` | O que a coleta do ano devia ter respondido | Lista da PGE, dividida por ano |
| `data/processos_PGE.json` | Movimentações do Atos da PGE (9 GB) | O `processos.json` do GPDR |
| `data/ipca_mensal.csv` | IPCA número-índice, tabela 1737 do SIDRA | O mesmo arquivo do GPDR |
| `data/unidades_foro_tjsp.md` | Código `OOOO` do CNJ → foro (Resolução TJSP nº 65/2008) | Copiado de `Codigos_dados_GPDR/data/` |
| `data_final/JSONL_final/base_final_<ano>.jsonl` | Base do ano, entrada do script | Copiado à mão de `data/saida/<projeto>/` |
| `data_final/JSON_final/base_final_<ano>.json` | Base final na estrutura do GPDR, + `.meta.json` | Gerado |
| `data_final/auditoria/<ano>/` | Faltantes, duplicados, órfãos, `sem_dados` de rota nova e linhas removidas | Gerado |

## Variáveis de ambiente

| Variável | Padrão | Para que serve |
|----------|--------|----------------|
| `ORQUESTRADOR_DB_DIR` | `data/bancos` | Diretório dos bancos SQLite |
| `ORQUESTRADOR_WORKERS` | `3` | Threads de coleta |

**O banco não pode ficar em pasta sincronizada.** Clientes de sincronização (OneDrive, Google Drive, Dropbox) copiam o `.db` e o `-wal` em momentos diferentes e produzem um banco incoerente **sem emitir erro** — semanas de coleta perdidas em silêncio. O projeto detecta isso e se recusa a abrir:

```bash
# PowerShell
$env:ORQUESTRADOR_DB_DIR = 'C:\dados_coleta'

# bash
export ORQUESTRADOR_DB_DIR=/home/voce/dados_coleta
```

Aumentar `ORQUESTRADOR_WORKERS` **não** acelera a coleta: a cadência é global (uma requisição a cada 1,1–1,6 s, com ou sem workers; só os "Mais" das movimentações ficam fora dela). Os workers só evitam que um pico de latência numa página deixe a fila ociosa. Ver
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

Sempre use `uv add` em vez de `pip install` direto — isso mantém `pyproject.toml` e `uv.lock` sincronizados.

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

A documentação fica em `docs/`. Veja a [página inicial](../index.md) para a visão geral do projeto e o mapa dos módulos.

## Documentando seu trabalho

Copie o template ADR correspondente ao artefato, registre a página no `nav` do `mkdocs.yml` e abra PR com código e documentação juntos. **Toda página cabe em 150 linhas** — as regras que tornam isso viável estão em [Como documentar](../index.md#como-documentar).

Pontos ambíguos ou que pareçam defeito vão direto para o [backlog](../backlog.md); invariantes que valeria testar, para o [backlog de testes](../backlog_testes.md).

## Referências

- [Documentação do uv](https://docs.astral.sh/uv/)
- [Página inicial da documentação](../index.md) — visão geral e mapa dos módulos
- [Padrão de logging](logging_padrao.md) — convenções para scripts de pipeline
