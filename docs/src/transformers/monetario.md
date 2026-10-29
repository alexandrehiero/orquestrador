# Correção monetária – `src/transformers/monetario.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-23                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `csv`, `decimal` — sem dependências externas |

## Contexto e Motivação

`processo.valorCorrigido` da base do GPDR leva o valor da ação ao Real e ao poder de compra de junho de 2026. Para que um valor corrigido signifique o mesmo nas duas bases, este módulo é uma **cópia deliberada** de `Codigos_dados_GPDR/src/monetary.py` (a v2 daquela base). Os dois projetos não compartilham pacote, e os dois se chamam `src`.

São duas operações, e as duas são necessárias. A conversão de moeda muda a unidade de conta (Cr$ de 1981 e R$ de hoje são unidades diferentes). A correção pelo IPCA repõe o poder de compra. Só a primeira produz números absurdos; só a segunda mistura unidades.

## Decisões de Arquitetura

- **Mesma referência do GPDR: `COMPETENCIA_REFERENCIA = "2026-06"`** — mudá-la muda todos os valores e quebra a comparação entre as bases.
- **Moeda pelo símbolo E pelo ano** — `Cr$` existiu em três períodos, e nos anos de troca convivem duas moedas. `Cr$` e `CR$` são moedas diferentes (fator 1.000), e a comparação nunca normaliza a caixa.
- **Competência: mês da distribuição se for do ano do CNJ; senão, ano do CNJ + junho** — a distribuição de outro ano marca outro evento (redistribuição). O vocabulário de `fonteCompetencia` é o do GPDR (`ultimaDistribuicao`, `ano_cnj`).
- **Sem a competência conferida à mão** — `competencias_conferidas.csv` é trabalho humano sobre processos do GPDR. Aqui só a regra automática vale.
- **`Decimal` com 40 dígitos, num contexto local** — a precisão do GPDR, sem alterar o contexto global do processo (o GPDR fazia `getcontext().prec = 40` na importação).
- **Os dois números-índice ficam no documento** — a conta se refaz sem a tabela nem este código.
- **O status diz por que uma etapa falhou** — `convertido`, `fora_da_serie_ipca` (antes de dez/1979 ou competência não publicada), `moeda_nao_identificada` (símbolo e ano sem era, como o `$` isolado que aparece 10 vezes em 2025).

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Importar o módulo do GPDR por caminho relativo | Os dois pacotes se chamam `src`; o segundo sombrearia o primeiro. |
| Referência no mês mais recente do IPCA | Os valores deixariam de ser comparáveis com o GPDR, que fixou 2026-06. |
| `float` em vez de `Decimal` | O fator de 1981 até hoje passa de 10¹¹; o arredondamento divergiria do GPDR. |

## Limitações Conhecidas

- **A cópia pode divergir do GPDR.** Se o GPDR mudar a regra, esta cópia não acompanha sozinha. A conferência abaixo é o que denuncia a diferença.
- **Valor sem símbolo chega como `R$`** (ver [`estrutura_gpdr`](estrutura_gpdr.md)).

## Exemplo de Uso

```python
from src.transformers import monetario

ipca = monetario.carregar_ipca(Path("data/ipca_mensal.csv"))
bloco = monetario.valor_corrigido(22635.82, "R$", "00000073620258260383", "2025-01-08", ipca)
# {'moedaOriginal': 'R$', 'brlNominal': Decimal('22635.82'), 'brlAtualizado': Decimal('24356.17'),
#  'competencia': '2025-01', 'fonteCompetencia': 'ultimaDistribuicao', ...}
```

## Testes e Validação

Conferido contra a v7 do GPDR: 3.003 documentos (inclusive Cr$ e CR$) recalculados a partir de `valorAcao`, moeda e data, **zero diferenças** em todas as chaves do bloco.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação, portado do GPDR |
