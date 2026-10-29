# Nomes das partes – `src/transformers/nomes.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-23                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re`, `unicodedata` — sem dependências externas |

## Contexto e Motivação

Uma consulta por `Fazenda Pública do Estado de São Paulo (FESP)` precisa achar os processos das duas bases. O GPDR formatou os nomes na v1 e unificou grafias na v7; este módulo aplica as mesmas regras, copiadas de `normalize.py` e `unificacao.py`. Não é detalhe: na lista de 2025, **276 mil nomes do polo passivo** caem numa das grafias que a v7 unificou, e só a Fazenda aparece em cinco formas (`FAZENDA DO ESTADO DE SÃO PAULO`, `Estado de São Paulo`, `Fazenda Publica do Estado de Sao Paulo`…).

## Decisões de Arquitetura

- **Duas etapas, na ordem do GPDR: forma, depois unificação** — a unificação compara contra nomes já formatados, e o alvo (`… (FESP)`) nunca passa pela formatação, que o deixaria `(fesp)`.
- **Forma: palavras capitalizadas, partículas em minúsculo, siglas preservadas** — `Maria da Silva`, `IAMSPE`. Acentuação diferencia (`José` ≠ `Jose`). `NÃO HÁ REGISTRO` é sentinela do e-SAJ e fica intacto.
- **Só as regras da v7 que são tabelas fechadas** — as grafias de advogado conferidas na OAB e os entes do polo passivo. A regra das sociedades individuais de advocacia fica de fora: ela troca o nome quando o titular sem sufixo existe **na própria base**, uma decisão medida e tomada para o GPDR.
- **Entes só em pessoas do polo passivo** — `Estado de São Paulo` no polo ativo é outro papel processual. Ali a comparação ignora acento, caixa e pontuação, exceção que vale só para essa lista fechada de instituições.
- **Desduplicação depois das trocas, com `dict.fromkeys`** — duas grafias que viram a mesma pessoa deixam de contar duas vezes, e a ordem de primeira aparição se mantém entre execuções.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Manter os nomes como o e-SAJ entrega | A mesma instituição em cinco grafias; consultas entre as bases não casariam. |
| Aplicar também a regra das sociedades | Depende do vocabulário da base inteira e foi decidida para o GPDR. |
| Unificar por semelhança de texto | Nenhuma regra do GPDR é inferida; toda troca é decisão humana declarada. |

## Limitações Conhecidas

- **Variantes fora da lista ficam intactas**, como na v7: `CBPM - CAIXA BENEFICENTE DA POLÍCIA MILITAR` (832 em 2025) começa pela sigla e não casa nenhuma das 9 grafias; `São Paulo Previdência` sem a sigla também não.
- **`capitalize()` achata nomes compostos por apóstrofo** (`D'Angelo` → `D'angelo`), igual ao GPDR.

## Exemplo de Uso

```python
from src.transformers import nomes

nomes.normalizar_nomes(["FAZENDA DO ESTADO DE SÃO PAULO", "Estado de São Paulo"], True, Counter())
# ['Fazenda Pública do Estado de São Paulo (FESP)']
```

## Testes e Validação

5.003 nomes da v7 do GPDR reformatados por `formatar_nome`: **nenhum mudou** (a formatação é idempotente sobre a saída do GPDR).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação, portado do GPDR |
