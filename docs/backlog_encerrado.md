# Backlog — itens encerrados

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-09-04                                 |
| Data de atualização | 2026-10-29                                 |
| Responsável(is)     | @alexandrehiero                            |
| Origem              | seção "Itens encerrados" de [backlog.md](backlog.md) |

Registro do que já foi resolvido, para não voltar como "descoberta nova". O contexto completo — com a alternativa descartada — está na página de origem de cada item.

Um item chega aqui quando o código muda e a página de origem passa a registrar a decisão.

| Item | Página | Como foi resolvido |
|---|---|---|
| `_registrar_falha` lia `falhas_seguidas` fora do lock | `esaj_client` | `falha()` devolve `(abrir, falhas_seguidas)` |
| Contrato "sempre levanta" só num comentário | `esaj_client` | Renomeado para `_levantar_falha` |
| `_USER_AGENT` podia divergir do `impersonate` | `esaj_client` | UA manual removido |
| `estatisticas()` subnotificava requisições | `esaj_client` | `requisicoes` (HTTP real) separado de `operacoes` |
| Detector e resolvedor de seleção com listas diferentes | `page_state` | Seletores compartilhados em constantes |
| Vocabulário de status em três declarações | `coletor` | Extraído para `src/status.py` |
| Segunda tela de seleção caía no motivo errado | `coletor` | Motivo próprio |
| `NAO_ENCONTRADO` após seleção resolvida avançava de grau | `coletor` | Vira `erro_transitorio` |
| Grau do erro descartado na gravação | `coletor` | Decisão documentada: tentativa não é observação |
| `_juiz_valido` comparava por subcadeia | `parser_base` | Comparação por palavra inteira |
| `SELETORES_SITUACAO` nunca confirmado | `parser_base` | Confirmado no spike de 2026-08-10 |
| `GRAU` declarado e nunca lido | `parser_primeiro_grau` | Alimenta `PARSER_POR_GRAU` |
| `processo_1a_instancia_bruto` inalcançável | `parser_segundo_grau` | Filtro CNJ saiu da varredura |
| Docstring de `_varrer_secao_1a_instancia` contradizia o corpo | `parser_segundo_grau` | Docstring alinhada |
| Atalho por `id` mantinha filtro de CNJ | `parser_segundo_grau` | Mesmo critério `\d{4,}` |
| `TODOS` definido e nunca importado | `status` | Constante removida |
| `menu.py` com duas procedências do vocabulário | `status`, `coletor` | `ERRO_TRANSITORIO` vem de `src.status` |
| `exceptions.md` documentava `falha()` como booleano | `exceptions` | Bloco substituído pelo código real |
| `iter_exportaveis` não selecionava `ultimo_erro` | `sqlite_store` | Coluna no `SELECT`: `erro_persistente` deixou de sair no JSONL sem a causa |
| Ciclo 4 → 3 → 4 podia não convergir | `sqlite_store` | `orfaos()` casa pelo NÚMERO; as três granularidades concordam |
| `import os` sem uso | `sqlite_store` | Import removido |
| `PRAGMA foreign_keys = ON` sem efeito | `sqlite_store` | Pragma removido; a ausência de FK virou decisão explicada no código |
| `contagem_por_grau` não fecha com `total()` sem aviso | `sqlite_store` | Docstring declara que só conta status com grau observado |
| `data_para_iso` aceitava datas inexistentes | `limpeza` | `datetime.date` dentro de `try`, iterando todas as ocorrências |
| `valor_para_float` era ganancioso sobre a string | `limpeza` | Passou a casar um padrão monetário e ignorar o resto (refinado no item abaixo) |
| Tipo do vínculo decidido pelo texto de log | `vinculo` | Contador `descartados` |
| Registro sem `bruto` recebia `sem_vinculo` | `vinculo`, `coletor` | `INDEFINIDO` em `scripts/menu.py` |
| Capa de 2º grau sem 1ª instância não gerava observação | `vinculo` | `elif` registra o caso (sem cobertura de fixture — ver [backlog §2](backlog.md)) |
| Partes todas em polo `OUTRO` saíam sem sinal | `projecao` | Observação explícita no JSONL |
| `.tmp` sobrava quando o export falhava | `exportador` | `try/except BaseException` remove e re-levanta |
| `pais_com_filhos` não era comparável com nada | `exportador` | `com_filhos` (documentos exportados) + um contador de pares |
| Corrigir uma regra de vínculo exigia RECOLETA | `sqlite_store`, `vinculo`, `projecao` | `reprojetar_vinculos`: a opção 4 recalcula as colunas a partir do bruto, antes do export |
| Alternação única resolvia pelo padrão mais à esquerda | `limpeza` | Busca em dois passos: valor com centavos em toda a string antes de aceitar inteiro solto |
| `pais_citados_sem_registro` era lido como tamanho de `orfaos.txt` | `exportador` | Renomeado para `pares_pai_sem_documento` — o nome passou a dizer a unidade |
| `graus_citados` não chegava a lugar nenhum | `exportador`, `sqlite_store` | Gravado em `orfaos_diagnostico.txt`, separado porque `orfaos.txt` é lido de volta pela opção 3 |
| `.tmp` sem proteção em `escrever_lista_orfaos` | `exportador` | Mesmo `try/except BaseException` das demais escritas |
| Docstring do script de conferência offline com o nome errado do arquivo | `backlog` §5 | Corrigida para `python scripts/checar_offline.py` |
| Movimentações vazias no layout novo do e-SAJ (set/2026), gravadas como `coletado` sem alarme | `coletor`, `parser_base`, `esaj_client` | Clique em "Exibir" e nos "Mais" até não haver cursor; recusa ou resposta estranha vira `erro_transitorio` |
| Valor da ação sem o símbolo da moeda | `limpeza`, `projecao` | Campo `valor_acao_moeda`, com `R$` como padrão; `valor_acao` segue número |
| Movimentações do JSON em duas direções (dias crescentes, mesmo dia decrescente) | `limpeza` | `dedup_movimentacoes` deixou de ordenar: a lista sai na ordem do e-SAJ |
| Cadência alterada no `EsajClient` não chegava ao menu, que cria o `Pacer` à parte | `esaj_client`, `menu` | Padrão 1,1–1,6 s também no `Pacer`; o cabeçalho do menu lê o valor dele |
| A opção 2 reclassificava a origem dos órfãos como `lista` | `menu`, `sqlite_store` | `registrar_resultado` reaproveita a origem de uma linha anterior do número |
| `with self.con:` não abria transação: com `isolation_level=None`, cada comando era gravado sozinho | `sqlite_store` | `_transacao()` com `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` |
| Precatório sem autor quando o credor vinha como `Sucessora` (polo `OUTRO`) | `parser_base`, `projecao` | `projecao._polo`: em capa com `Ent. Devedora`, sucessor(a) vai para `autores`; a base de 2025 foi recoletada com `--recoletar` |

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-09-04 | @alexandrehiero | Criação: os 37 itens encerrados saíram de `backlog.md` para esta página; o nome do script de conferência offline foi acertado para `checar_offline.py`, que é o arquivo existente |
| 2026-09-21 | @alexandrehiero | 4 itens do layout novo do e-SAJ: movimentações, moeda do valor, ordem das movimentações e cadência do menu |
| 2026-10-29 | @alexandrehiero | 2 itens do `sqlite_store`: origem dos órfãos na recoleta e transações que não existiam |
| 2026-10-29 | @alexandrehiero | Sucessora do credor no precatório |
