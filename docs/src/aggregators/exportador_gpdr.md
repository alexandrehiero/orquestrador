# Export da estrutura do GPDR – `src/aggregators/exportador_gpdr.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-23                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `json`, `decimal`, `os`; `src.transformers.estrutura_gpdr` |

## Contexto e Motivação

O último passo da base final: ler o JSONL consolidado, projetar cada linha com [`estrutura_gpdr`](../transformers/estrutura_gpdr.md) e gravar o resultado. É o par de [`exportador`](exportador.md) para a forma do GPDR: o mesmo streaming, a mesma escrita atômica, outro formato de saída.

## Decisões de Arquitetura

- **Array JSON, não JSONL** — é o formato de entrega da base do GPDR, e as duas se carregam pelo mesmo `mongoimport --jsonArray`. O [`exportador`](exportador.md) escolheu JSONL pelo motivo oposto; aqui a régua é a compatibilidade com a base vizinha, e o JSONL continua existindo ao lado.
- **Streaming e escrita atômica** — um documento por vez num `.tmp`, e só ao fim a troca de nome (`EscritorArrayJson`, portado do `io_stream` do GPDR). Um `Ctrl+C` nunca deixa uma base pela metade com nome de base boa.
- **`Decimal` vira `int` ou `float`, e qualquer outro tipo é erro** — `default=str` gravaria `620000` como o texto `"620000.0"`, erro que já custou uma regeração inteira no GPDR. O GPDR ainda convertia tipos desconhecidos em texto; aqui eles se denunciam.
- **`json.dumps` + uma escrita por documento** — `json.dump` direto no arquivo faz dezenas de escritas pequenas por documento.
- **`posicoes` só para a amostra** — a amostra lê o JSONL sem consolidá-lo, e precisa pular as linhas que perderam na desduplicação. Depois de consolidado, todas as linhas valem.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| JSONL também na saída final | Quebraria o comando de carga comum com o GPDR. |
| `default=str` | Números virariam texto no Mongo, em silêncio. |
| Capturar erro por documento e seguir | A contagem final deixaria de fechar com a base; um defeito de projeção deve parar o export, e a escrita atômica protege a saída anterior. |

## Limitações Conhecidas

- **O array só é válido depois do `]`.** Um leitor precisa ir até o fim, ou ler em streaming (como `atos_pge.ler_array_json`).
- **Os blocos da PGE dependem do índice aberto.** Exportar exige ter montado o `IndicePge` na mesma execução.

## Exemplo de Uso

```python
from src.aggregators import exportador_gpdr

with atos_pge.IndicePge(caminho_indice) as indice:
    indice.montar(ATOS_PGE, set(mantidas))
    contagens = exportador_gpdr.exportar_estrutura_gpdr(
        jsonl, destino, foros, ipca, filhos, indice)
```

## Testes e Validação

Execução completa sobre 2025 e smoke test de 2.000 documentos. O script confere que os documentos escritos são exatamente os processos distintos da base consolidada.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação |
