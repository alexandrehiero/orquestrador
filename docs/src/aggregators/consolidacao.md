# Auditoria e consolidação do JSONL – `src/aggregators/consolidacao.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-29                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `json`, `os`; `src.status`, `src.transformers.projecao` |

## Contexto e Motivação

A base de uma coleta chega como JSONL, copiada à mão para `data_final/JSONL_final/`, e pode ter passado por mais de uma máquina ou execução. Antes de virar a estrutura do GPDR, ela é confrontada com a lista do ano: falta algum processo? algum aparece duas vezes? E, depois de acrescentar os que faltavam, o grafo de relacionamento continua fechando?

Este módulo responde às três perguntas e reescreve o JSONL quando é preciso. Quem chama é [`preparar_base_final`](../../scripts_final/preparar_base_final.md).

## Decisões de Arquitetura

- **Duplicado é número repetido, não `_id` repetido** — o orquestrador decide o grau sozinho, então um número tem um único registro, a premissa de `SqliteStore.numeros_finalizados`. Duas linhas do mesmo número são duas respostas à mesma pergunta.
- **Fica a resposta mais informativa** — `coletado` > `segredo_justica` > `sem_dados` > `erro_persistente`. "Perguntei e não existe" vale mais que "não consegui perguntar".
- **Empate entre base e coleta nova fica com a base; empate dentro da mesma fonte, com a última linha** — só um desfecho melhor justifica reescrever gigabytes, e é isso que torna a segunda execução idempotente. Dentro de um arquivo, a linha acrescentada por último é a mais recente.
- **Só o mínimo de cada registro fica em memória** — `Linha` guarda número, grau, status, pai e filhos; o documento é descartado logo após a leitura. Em 2025, 368 mil tuplas.
- **Filho que está na base: vale o pai que ele declara; filho fora da base: fica como veio** — o registro de um pai não sabe dos filhos acrescentados agora, então os filhos internos são a inversão dos pais (`projecao.inverter_filhos`). Mas um filho que o banco original conhecia e este JSONL não tem não pode ser conferido. Recalcular só sobre a base o apagaria, e no teste com um recorte isso aconteceu com 6 de 7 "correções".
- **Leitura e escrita em binário** — as linhas mantidas são copiadas sem `json.loads`/`dumps` e chegam idênticas, inclusive o `\r\n`. Só o registro cujos filhos mudaram é decodificado e reescrito.
- **Nada é destruído** — linha da base que perdeu vai, byte a byte, para `removidos_<carimbo>.jsonl`. A base consolidada mais esse arquivo reconstituem a original. Linha da coleta nova que perdeu é só ignorada, porque a base já tinha resposta igual ou melhor.
- **Escrita atômica nos dois arquivos, `removidos` primeiro** — se a execução cair entre as duas trocas de nome, sobra o registro das linhas removidas ao lado de uma base que ainda as tem. Nunca o contrário.
- **Órfão por número**, o critério de `SqliteStore.orfaos`: um pai que existe só no outro grau não é órfão.

- **`preferir_coleta` inverte o empate entre as fontes, por número** — para a recoleta pedida (`--recoletar` do [`preparar_base_final`](../../scripts_final/preparar_base_final.md)), quando uma regra de extração mudou e a linha da base ficou velha. Só o empate: uma coleta com status pior continua perdendo, então uma falha nunca troca a capa da base.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Desduplicar por `_id` | `X__0` (erro) e `X__1` (coletado) do mesmo número passariam como distintos. |
| Ficar sempre com a última linha | Uma tentativa nova que falhou apagaria uma coleta boa. |
| Recalcular os filhos só sobre a base | Apaga arestas verdadeiras para processos fora da base. |
| Reescrever o JSONL a cada execução | 6 GB regravados sem mudança; o checksum deixaria de provar que nada mudou. |
| Backup integral antes de reescrever | Dobra o disco. As linhas removidas são poucas e bastam para reconstituir a original. |
| Decodificar e recodificar todas as linhas | Mudaria bytes (ordem, espaçamento, fim de linha) de registros que não mudaram. |

## Limitações Conhecidas

- **O `removidos_*.jsonl` acumula um arquivo por consolidação.** É auditoria; nada o apaga.
- **Os órfãos de outro ano são a maioria** numa base por ano, e não indicam falha (ver o script).
- **Duas linhas `coletado` do mesmo número em graus diferentes** se resolvem pela última linha, e o descarte vai para `duplicados.txt`. O orquestrador não as produz, mas uma junção manual de bases poderia.

## Exemplo de Uso

```python
from src.aggregators import consolidacao as c

linhas = list(c.ler_linhas(jsonl, c.FONTE_BASE))
linhas += c.ler_linhas(export_faltantes, c.FONTE_COLETA, apenas=set(a_coletar))
mantidas, descartadas = c.escolher(linhas)
filhos = c.mapa_filhos(mantidas)
c.consolidar([jsonl, export_faltantes], mantidas, filhos, jsonl, removidos)
```

## Testes e Validação

Base sintética de 301 linhas reais de 2025, com 2 faltantes (um deles filho de um processo da base, que teve os filhos apagados), 1 `erro_persistente`, 1 duplicata exata e 1 cópia rebaixada a `sem_dados`. Resultado: 3 coletados no e-SAJ, +3 acrescentados, −3 removidos, exatamente 1 filho corrigido, e todos os `processos_filhos` iguais aos do JSONL original de 2025. A segunda execução não usou a rede e deixou o JSONL com o mesmo checksum.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação |
| 2026-10-29 | @alexandrehiero | `escolher(..., preferir_coleta)` para a recoleta pedida |
