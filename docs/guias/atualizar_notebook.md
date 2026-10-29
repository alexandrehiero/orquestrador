# Atualizando um notebook que já coleta

Sequência para cada computador que tem uma coleta do [`menu`](../scripts/menu.md) em andamento ou terminada, depois de uma versão nova do código. A de 2026-10-29 traz duas correções de rota e duas opções novas:

- processos do **Colégio Recursal** (origem `9xxx`) eram gravados como `sem_dados` — resultado final, nunca mais tentado. Na base de 2025 eram 7.500, nenhum com dado;
- processos do **DEPRE** (origem `0500`) estouravam o teto de tentativas e paravam em `revisao_manual.txt`;
- a **opção 5** reabre e recoleta esses dois grupos; a **opção 6** recoleta a base inteira sem nunca piorar um registro;
- no precatório, a **sucessora do credor** passa a sair em `autores`. Não pede recoleta: a opção 4 corrige o que já está no banco.

Interromper o menu é seguro em qualquer ponto: cada processo é uma transação, e rodar a mesma opção de novo continua de onde parou.

## Comandos

No PowerShell, na pasta do projeto:

```powershell
# 1. Feche o menu (opção 0 ou Ctrl+C) e atualize o código e as dependências
git pull
uv sync

# 2. Só se o banco NÃO estiver em data/bancos: aponte a pasta, na mesma janela
$env:ORQUESTRADOR_DB_DIR = 'C:\dados_coleta'

# 3. Abra o menu do MESMO projeto de antes: o nome define banco e saída
uv run python scripts/menu.py <nome_do_projeto>
```

Sem Git, copie a pasta do projeto **sem** `data/`, `data_final/` e `.venv/`: os bancos e as listas do notebook ficam onde estão. Depois rode o `uv sync`.

## No menu, nesta ordem

| Passo | Opção | Quando | O que conferir |
|---|---|---|---|
| 1 | **5** | Sempre, uma vez | O cabeçalho lista quantos `9xxx` e `0500` foram reabertos; o resumo, quantos viraram `coletado` |
| 2 | **5** de novo | Se a 5 foi interrompida | "Nenhum processo do Colégio Recursal ou do DEPRE pendente" encerra |
| 3 | **2** | Se o resumo mostrar falhas pendentes | `falhas_pendentes.txt` esvazia |
| 4 | **1** | Se a lista ainda não terminou | Continua de onde parou, já pelas rotas novas |
| 5 | **4** | No fim | `base_final.jsonl` regenerado, já com a sucessora como autora nos precatórios |
| 6 | **3** e **4** | Se a 4 apontar órfãos | "Nenhum órfão" encerra o ciclo |

A reabertura da opção 5 acontece **uma vez por banco**: depois dela, um `sem_dados` dessas origens já veio da rota certa e é resultado legítimo. Rodar a 5 de novo só recoleta o que ficou pendente.

Enquanto um processo reaberto não é recoletado, ele fica fora do `base_final.jsonl` — `erro_transitorio` é fila, não resultado. Por isso a opção 4 vem depois da 5, não antes.

## Opção 6: renovar a base inteira (opcional)

Recoleta todos os números do banco para trazer movimentações e dados novos. Leva tanto quanto a coleta original, e pode ser interrompida e retomada pela própria 6.

| Passo | Opção | O que acontece |
|---|---|---|
| 1 | **6** | Pede confirmação, oferece backup do banco (`<projeto>_antes_atualizacao_<data>.db`) e começa a rodada |
| 2 | **6** de novo | Até aparecer "Rodada concluída"; cada execução tenta de novo as falhas |
| 3 | **4**, depois **3** e **4** | Leva os dados novos à base final |

Uma falha nunca toca o registro anterior, e uma resposta menos informativa (um `coletado` que volta como `sem_dados`) não o substitui. Os dois casos saem em `data/saida/<projeto>/atualizacao_nao_atualizados.txt`, com o motivo.

## Base final de um ano

Com a coleta terminada, copie `data/saida/<projeto>/base_final.jsonl` para `data_final/JSONL_final/base_final_<ano>.jsonl` e rode:

```powershell
uv run python scripts_final/preparar_base_final.py <ano>
```

O [`preparar_base_final`](../scripts_final/preparar_base_final.md) já manda para a coleta os `sem_dados` de `9xxx`/`0500` (lista em `data_final/auditoria/<ano>/rotas_novas.txt`), então também conserta uma base montada antes das rotas novas, sem passar pela opção 5.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| "parece ser uma pasta sincronizada" | O banco está no OneDrive/Drive. Defina `ORQUESTRADOR_DB_DIR` (passo 2) para uma pasta em disco local |
| "EXECUÇÃO INTERROMPIDA" | O e-SAJ caiu ou bloqueou. Nada foi perdido; espere e rode a mesma opção |
| A opção 5 não reabre nada | O banco já foi reaberto antes, ou não tem `9xxx`/`0500` sem dado. Confira o "por status" do resumo |
| Projeto "vazio" depois de atualizar | O nome passado ao `menu.py` difere do de antes: o nome define o banco |

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-29 | @alexandrehiero | Criação: sequência para as opções 5 e 6 e para o `preparar_base_final` com rotas novas |
| 2026-10-29 | @alexandrehiero | Sucessora no precatório corrigida pela opção 4 |
