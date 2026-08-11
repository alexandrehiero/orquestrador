> **Modelo ADR** — Copie este arquivo, renomeie para o script (ex.: `docs/scripts/coleta_PGE_GPDR_tjsp_fase_capa.md`) e preencha todas as seções. Registre decisões de pipeline, parâmetros e lições aprendidas.

# [Nome do Script] – `scripts/nome_do_script.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | YYYY-MM-DD                                 |
| Data de atualização | YYYY-MM-DD                                 |
| Responsável(is)     | @username_github                           |
| Dependências principais | `pandas`, `curl_cffi` (via módulo em src) |

## Contexto e Motivação

*Qual pipeline esse script executa? Por que ele é necessário?*  
*Exemplo: Coleta em lote de todos os processos listados no arquivo `PGE.GPDR.json`, enriquecendo a base com dados de movimentação do TJSP.*

## Decisões de Pipeline

- **Fonte de dados:** `data/PGE.GPDR.json` (gerado pelo time da PGE)
- **Destino:** `data/coleta_tjsp_resultados.csv` (incremental, com checkpoint)
- **Controle de repetição:** carrega processos já salvos a partir do CSV de saída – evita refazer coletas.
- **Delay entre requisições:** `random.uniform(3.5, 7.2)` para não sobrecarregar o TJSP.
- **Tratamento de múltiplos resultados:** utiliza método `resolve_multiple_results` do scraper.

## Como Executar

```bash
# A partir da raiz do projeto
python scripts/coleta_PGE_GPDR_tjsp_fase_capa.py
```

## Principais Parâmetros (constantes no código)

| Constante | Valor | Descrição |
|-----------|-------|-------------|
| `INPUT_FILE` | `data/PGE.GPDR.json` | Arquivo com a lista de processos |
| `OUTPUT_FILE` | `data/coleta_tjsp_resultados.csv` | Resultados incrementais |
| `SLEEP_RANGE` | `3.5, 7.2` | Intervalo aleatório entre chamadas |

## Logs e Monitoramento

- Logs são escritos no console e em `logs/coleta.log` (configurar `logging.basicConfig`).
- Em caso de interrupção (`Ctrl+C`), o script finaliza graciosamente e os processos já coletados permanecem no CSV.

## Falhas Conhecidas e Workarounds

- **Problema:** Processos com número muito antigo retornam página vazia.  
  **Workaround:** O script registra `[FALHA]` e continua.
- **Problema:** O TJSP pode devolver captcha após muitas requisições.  
  **Workaround:** Não implementado – é necessário reiniciar manualmente após pausa.

## Decisões Futuras

- [ ] Implementar retry com backoff exponencial (biblioteca `tenacity`).
- [ ] Enviar notificação ao Telegram ao final da coleta.
- [ ] Paralelizar com `asyncio` para ganho de performance (cuidado com bloqueio).

## Relação com Outros Artefatos

- Depende do módulo `src/scrapers/scraper_tjsp_capa_request.py`.
- Alimenta a base normalizada (issue #33).

## Lições Aprendidas

- O checkpoint por CSV é simples e eficaz; evita reprocessar centenas de itens após falha.
- O uso de `pathlib` tornou o script portável entre Windows e Linux.
