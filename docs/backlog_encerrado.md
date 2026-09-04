# Backlog — itens encerrados

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-09-04                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Origem              | seção "Itens encerrados" de [backlog.md](backlog.md) |

Registro do que já foi resolvido, para não voltar como "descoberta nova". O contexto
completo — com a alternativa descartada — está na página de origem de cada item.

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

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-09-04 | @alexandrehiero | Criação: os 37 itens encerrados saíram de `backlog.md` para esta página; o nome do script de conferência offline foi acertado para `checar_offline.py`, que é o arquivo existente |
