# Padrão de Logging

Guia normativo para logging em scripts de pipeline do projeto. Scripts existentes podem ainda usar `print()` — ao criar ou refatorar scripts, adote este padrão.

Hoje os dois scripts do repositório usam `print()`: [`menu.py`](../scripts/menu.md) (com `tqdm.write` dentro do laço de coleta — ver a seção sobre barra de progresso) e [`spike_seletores.py`](../scripts/spike_seletores.md), cuja saída **é** o produto do diagnóstico.

## Objetivos

- Registrar progresso, falhas recuperáveis e erros de forma consistente.
- Persistir logs em arquivo para auditoria de coletas longas.
- Manter compatibilidade visual com os prefixos já usados no projeto: `[OK]`, `[FALHA]`, `[ERRO]`, `[AVISO]`.

## Estrutura recomendada

```python
import logging
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "coleta.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
```

## Convenção de níveis

| Nível | Quando usar | Exemplo |
|-------|-------------|---------|
| `INFO` | Progresso normal, sucesso | `logger.info("[OK] Processo coletado: %s", num)` |
| `WARNING` | Falha recuperável, formato inesperado | `logger.warning("[FALHA] HTML vazio: %s", num)` |
| `ERROR` | Exceção capturada, item ignorado | `logger.error("[ERRO] Processo %s: %s", num, e)` |
| `DEBUG` | Detalhes de parsing (opcional) | URLs, tamanho de HTML |

## Prefixos no mensagem

Mantenha os prefixos entre colchetes no texto da mensagem para facilitar `grep` em arquivos de log:

```python
logger.info("[OK] Processo coletado: %s", numero)
logger.warning("[AVISO] Arquivo CSV com formato antigo detectado")
logger.warning("[FALHA] HTML vazio ou erro de parsing: %s", numero)
logger.error("[ERRO] Processo %s: %s", numero, exc)
```

## Interrupção graciosa

Em scripts com checkpoint (ex.: append em CSV), trate `KeyboardInterrupt`:

```python
try:
    executar_coleta()
except KeyboardInterrupt:
    logger.warning("[AVISO] Coleta interrompida pelo usuário. Dados já salvos permanecem no arquivo de saída.")
```

## Barra de progresso: use `tqdm.write`

Dentro de um laço com barra de progresso, `print()` corrompe a linha da barra. Toda saída
precisa passar por `tqdm.write`:

```python
tqdm.write(f"[{r.status}] {numero} (grau {r.grau})")
```

É por isso que as funções de `src/` que reportam progresso recebem o logger por parâmetro,
com `log=print` como padrão — assim elas não dependem do `tqdm`, e quem chama de dentro de
uma barra injeta o escritor correto:

```python
resumo = exportar_jsonl(store, JSONL, log=tqdm.write)
```

Ao migrar para `logging`, o mesmo cuidado vale: um `StreamHandler` comum escreve direto no
stderr e quebra a barra. A solução é um handler que delegue a `tqdm.write`.

## Diretório `logs/`

- Logs ficam em `logs/<nome-do-script>.log` na raiz do projeto.
- Acrescente `logs/` ao `.gitignore` — não versionar arquivos de log.
- Crie `logs/` automaticamente no script (`mkdir(exist_ok=True)`).

## Migração de `print()` para `logging`

| Antes (`print`) | Depois (`logging`) |
|-----------------|-------------------|
| `print(f"[OK] ...")` | `logger.info("[OK] ...")` |
| `print(f"[FALHA] ...")` | `logger.warning("[FALHA] ...")` |
| `print(f"[ERRO] ...")` | `logger.error("[ERRO] ...")` |
| `print(f"[AVISO] ...")` | `logger.warning("[AVISO] ...")` |

## Referências

- [Documentação logging — Python](https://docs.python.org/3/library/logging.html)
- [Template de script](../scripts/template_script.md) — seção "Logs e Monitoramento"
