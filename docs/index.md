# Orquestrador de Coleta TJSP / e-SAJ

Coleta de processos judiciais do Tribunal de Justiça de São Paulo pelo portal [e-SAJ](https://esaj.tjsp.jus.br), com montagem de um Data Lake em JSONL pronto para `mongoimport`.

Projeto de Iniciação Científica (FAPESP) do **CeMEPI-PGE / FEA-RP-USP**.

Esta documentação é escrita para quem vai **reproduzir ou estender** o trabalho. Ela segue o formato de **ADRs** (*Architecture Decision Records*): cada página registra por que uma decisão foi tomada, qual alternativa foi descartada e o que ainda não está resolvido.

## O problema

Coletar centenas de milhares de processos de um portal público não é difícil por causa do volume — é difícil porque **os erros são silenciosos**. Um processo aberto por engano produz um registro completo, com dados verdadeiros, sob o número errado. Uma falha de rede interpretada como "não encontrei" grava o processo no grau errado. Um seletor quebrado grava capas sem partes. Nenhum desses casos levanta exceção, e todos são invisíveis numa base grande.

O orquestrador é construído em torno dessa constatação. A regra que atravessa o projeto inteiro é epistemológica:

> **"Não consegui perguntar" nunca pode ser confundido com "perguntei e não existe".**

Ela aparece na taxonomia de status, na decisão de avançar de grau, na conferência de identidade, na classificação de página e na derivação de vínculo — sempre com o mesmo efeito: quando o pipeline não sabe, ele **diz que não sabe** em vez de produzir um dado plausível.

## Como funciona

Um menu interativo com quatro operações. O fluxo recomendado é **1 → 4 → 3 → 4**.

```
data/entrada/<projeto>.txt
        │
        │  ┌─────────────── opções 1, 2 e 3 (usam rede) ───────────────┐
        ▼  │                                                            │
  NumeroProcesso ─→ EsajClient ─→ ClassificadorPagina ─→ Parser ─→ derivar_vinculo
   valida CNJ       cadência       que página é esta?     capa       tipo + pai
   antes da rede    global                                bruta
        │                                                            │
        └────────────────────────────→ SqliteStore ←─────────────────┘
                                       checkpoint ACID
                                       chave (processo, grau)
                                             │
        ┌──────────── opção 4 (local, sem rede) ────────────┐
        ▼                                                    ▼
  reprojetar_vinculos ─→ projetar (limpeza) ─→ base_final.jsonl
                                             └→ orfaos.txt ──→ volta para a opção 3
```

| Opção | O que faz | Rede? |
|---|---|---|
| 1 | Coleta os números da lista, pulando o que já tem desfecho | Sim |
| 2 | Recoleta apenas os que falharam por motivo transitório | Sim |
| 3 | Coleta processos citados como pai que ainda não têm registro | Sim |
| 4 | Reprojeta vínculos, exporta o JSONL e recalcula os órfãos | **Não** |

O ciclo 4 → 3 → 4 fecha o grafo de relacionamento e **converge**: um processo que o e-SAJ afirma não existir sai da lista de órfãos para sempre. Detalhes de operação em [`menu`](scripts/menu.md).

## As decisões que sustentam o projeto

| Decisão | Por quê | Página |
|---|---|---|
| **Checkpoint em SQLite**, não em shards JSON | ACID numa coleta de semanas; retomada indexada em vez de varrer centenas de milhares de arquivos | [`sqlite_store`](src/store/sqlite_store.md) |
| **Chave `(processo, grau)`** | O mesmo número existe em 1º e 2º grau; chavear só pelo número embaralha o relacionamento | [`sqlite_store`](src/store/sqlite_store.md) |
| **Só um `NAO_ENCONTRADO` explícito avança de grau** | Erro de rede que faz descer para o 2º grau grava o processo com o grau errado, em silêncio | [`coletor`](src/scrapers/coletor.md) |
| **Invariante de identidade** | Entrar no processo errado grava dados de um sob o número de outro, e nada detecta | [`page_state`](src/scrapers/page_state.md) |
| **Taxonomia de status** | Distinguir "sei que não existe" de "não consegui perguntar" é o que faz a fila de falhas esvaziar | [`status`](src/status.md) |
| **O bruto é gravado; o JSONL é uma projeção dele** | Corrigir uma regra de limpeza é reprojetar localmente, sem recoletar nada | [`parser_base`](src/scrapers/parser_base.md) |
| **Pacer global** | A cadência é o intervalo *entre* requisições; workers não aumentam a taxa vista pelo e-SAJ | [`esaj_client`](src/scrapers/esaj_client.md) |
| **`tipo` do vínculo tem um único escritor** | Vocabulário fechado, atribuído só com evidência; dois donos faziam o segundo desfazer o primeiro | [`vinculo`](src/transformers/vinculo.md) |
| **Segredo de justiça suprime conteúdo, não topologia** | A aresta está no registro do outro processo, que não é sigiloso | [`projecao`](src/transformers/projecao.md) |
| **Saída em JSONL, com `_id` explícito** | Streaming, memória constante, `mongoimport` nativo — e reimportação idempotente | [`exportador`](src/aggregators/exportador.md) |
| **Um projeto = um banco = uma saída** | Bases diferentes com processos em comum não interferem uma na outra | [`menu`](scripts/menu.md) |

## Por onde começar

1. **[Configuração do ambiente](guias/configuracao_ambiente.md)** — `uv`, dependências e onde colocar os dados.
2. **[`spike_seletores`](scripts/spike_seletores.md)** — antes de qualquer coleta em massa, diagnostique os seletores contra HTML real.
3. **[`menu`](scripts/menu.md)** — o orquestrador propriamente dito.

Para entender o pipeline lendo código, comece por [`status`](src/status.md) e [`numero_processo`](src/scrapers/numero_processo.md), que não dependem de nada.

## Mapa da documentação

| Camada | Módulo | Responsabilidade |
|---|---|---|
| — | [`status`](src/status.md) | Vocabulário de status — fonte única, sem imports |
| `scrapers` | [`exceptions`](src/scrapers/exceptions.md) | Hierarquia de erros; o disjuntor fica fora dela de propósito |
| `scrapers` | [`numero_processo`](src/scrapers/numero_processo.md) | Value object do CNJ; roteamento de grau |
| `scrapers` | [`esaj_client`](src/scrapers/esaj_client.md) | Único ponto que toca a rede; cadência e circuito |
| `scrapers` | [`page_state`](src/scrapers/page_state.md) | Que página é esta? E é do processo pedido? |
| `scrapers` | [`parser_base`](src/scrapers/parser_base.md) | Extração da capa em dict **bruto** |
| `scrapers` | [`parser_primeiro_grau`](src/scrapers/parser_primeiro_grau.md) | Especialização de `cpopg` (juiz) |
| `scrapers` | [`parser_segundo_grau`](src/scrapers/parser_segundo_grau.md) | Especialização de `cposg` (relator, 1ª instância) |
| `scrapers` | [`coletor`](src/scrapers/coletor.md) | Máquina de estados de **um** processo |
| `store` | [`sqlite_store`](src/store/sqlite_store.md) | Checkpoint, filas e consultas de grafo |
| `transformers` | [`limpeza`](src/transformers/limpeza.md) | Texto bruto → dado utilizável (módulo puro) |
| `transformers` | [`vinculo`](src/transformers/vinculo.md) | Derivação do relacionamento |
| `transformers` | [`projecao`](src/transformers/projecao.md) | Registro do banco → documento final |
| `aggregators` | [`exportador`](src/aggregators/exportador.md) | SQLite → JSONL, em streaming |

**Scripts:** [`menu`](scripts/menu.md) (ponto de entrada) e [`spike_seletores`](scripts/spike_seletores.md) (diagnóstico, sem gravar nada).

**Guias:** [configuração do ambiente](guias/configuracao_ambiente.md) e [padrão de logging](guias/logging_padrao.md).

**Backlog:** [dívidas em aberto](backlog.md) · [invariantes de teste](backlog_testes.md) · [itens encerrados](backlog_encerrado.md).

## Como documentar

**Toda página cabe em 150 linhas.** É o teto do projeto, e ele existe porque documentação que ninguém termina de ler não documenta nada. O que o mantém viável:

- **Não copie código para a página.** Referencie o arquivo e o símbolo. O código está no repositório, e uma segunda cópia diverge em silêncio — a mesma falha que [`status`](src/status.md) existe para impedir.
- **"Decisões de Arquitetura" é lista de tópicos,** um por decisão, no padrão `- **Afirmação** — por quê; consequência.`
- **A tabela "Alternativas Consideradas" é a forma densa do porquê.** Preserve-a: é ali que a decisão fica defensável.
- **Um bloco de código só,** em "Exemplo de Uso", mostrando o caminho de entrada real.

Ao criar um artefato novo, copie o template e preencha **todas** as seções:

| Tipo | Template | Destino |
|------|----------|---------|
| Módulo `src/` | [template_src.md](src/template_src.md) | `docs/src/<caminho>/<nome>.md` |
| Script | [template_script.md](scripts/template_script.md) | `docs/scripts/<nome>.md` |
| Notebook | [template_notebook.md](notebooks/template_notebook.md) | `docs/notebooks/<nome>.md` |

A estrutura de `docs/src/` e `docs/scripts/` **espelha** a de `src/` e `scripts/`. `__init__.py` vazios não são documentados.

Quando algo no código estiver ambíguo ou parecer defeito, registre direto no [backlog](backlog.md), com a evidência, em vez de adivinhar a intenção — as páginas não têm mais seção "Pontos em aberto", para que a dívida tenha um lugar só. Invariantes que valeria testar vão para o [backlog de testes](backlog_testes.md).

Registre a nova página no `nav` do `mkdocs.yml` e abra PR com código e documentação juntos.

## Visualizar localmente

```bash
uv run mkdocs serve                 # servidor com live-reload
uv run mkdocs build --strict        # falha em qualquer link quebrado
```

## Estado atual

Não há suíte de testes automatizados. O [backlog de testes](backlog_testes.md) lista as 92 invariantes que valeria fixar, com a ordem sugerida por risco/custo, e [`spike_seletores`](scripts/spike_seletores.md) já produz os fixtures — os HTMLs de `data/spike/` são páginas reais do e-SAJ, e a maior parte da camada de scraping é composta de funções puras sobre string.
