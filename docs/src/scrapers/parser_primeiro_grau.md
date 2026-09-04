# Parser de 1º grau – `src/scrapers/parser_primeiro_grau.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | herda de `src/scrapers/parser_base.py` |

## Contexto e Motivação

Com 19 linhas, este é o menor módulo do projeto — e o tamanho é a informação.

As capas de `cpopg` e `cposg` são parecidas o suficiente para compartilhar quase tudo, mas divergem num ponto que não tem como ser abstraído: **no 1º grau existe juiz; no 2º existe relator**. O [`ParserCapaBase`](parser_base.md) declara essa divergência como método abstrato e deixa cada subclasse resolvê-la. Esta classe é a implementação para `cpopg`; todo o resto vem herdado sem alteração.

Há uma leitura estrutural que só aparece comparando as duas subclasses. O [`parser_segundo_grau`](parser_segundo_grau.md) sobrescreve quatro métodos e acrescenta três; este sobrescreve um. Isso diz algo concreto sobre a herança: **o `ParserCapaBase` foi escrito contra o HTML de 1º grau.** Ele não é um denominador comum neutro entre as instâncias — é o parser de `cpopg` com o juiz extraído para fora. Quem for estender o projeto para outro tribunal precisa saber disso antes de assumir que a base é genérica.

## Decisões de Arquitetura

- **Cascata de três passos, com desistência explícita** — degradação ordenada, do mais confiável ao menos, terminando em desistência e não em chute: (1) `#juizProcesso`, o identificador estável do layout tradicional, resposta direta e sem ambiguidade; (2) `_rotulo_estrito("Juiz")`, para o layout `unj`, em que o campo pode não ter `id` — a busca é por texto **direto exatamente igual** ao rótulo, o que impede `'Juizado Especial Cível'` de casar com `'Juiz'`; (3) `None`. Não há terceiro palpite.
- **`_juiz_valido` é aplicado nos dois caminhos, inclusive no canônico** — o passo 1 não confia no `id`: um `id` estável poderia, em tese, conter o texto certo no lugar errado, e a lista de bloqueio custa uma comparação de string. Validar os dois caminhos com o mesmo critério também garante que exista **uma** definição de "isto parece nome de juiz" no projeto, em vez de uma por caminho de extração.
- **Campo ausente em vez de campo errado** — sem a lista de bloqueio, o passo 2 é perfeitamente capaz de devolver `"1ª Vara da Fazenda Pública"` como nome de juiz: é um texto que aparece perto do rótulo, num layout onde a estrutura mudou. Uma vez no JSONL, esse valor é indistinguível de um nome real, e um agrupamento por juiz passaria a contar varas como se fossem pessoas. **A assimetria de custo decide:** um juiz que existe e não foi extraído produz um `null` a mais numa base que já tem muitos; um juiz extraído errado contamina uma agregação inteira.
- **`GRAU = 1` deixou de ser decorativo** — o atributo sempre esteve aqui, mas ninguém o lia: o pareamento grau → parser era feito por dicionários escritos à mão, um no coletor e outro no spike, ambos repetindo o que estas classes já declaravam. Eram **três** afirmações sobre a mesma coisa, e nada obrigava as três a concordarem. `{1: ParserSegundoGrau}` seria aceito sem reclamação: nenhum import falha, nenhuma exceção sobe, e o parser de 2º grau rodaria sobre uma capa de 1º devolvendo classe, partes e movimentações corretas (vêm da base) com `juiz: None` — o mesmo modo de falha silenciosa que a lista de bloqueio existe para evitar no valor extraído. Derivado, **o erro deixa de ser expressável**: a chave *é* o `GRAU` da classe.
- **O roteamento passou a ter uma fonte só** — o spike importa `PARSER_POR_GRAU` do coletor. Um spike que rodasse por um caminho diferente do da coleta poderia confirmar seletores que a coleta nunca usaria: pior que não diagnosticar, porque produz confiança infundada.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Devolver a vara, o foro ou o órgão quando o juiz não for encontrado | Dado errado é pior que dado ausente. Uma agregação por juiz consumiria nomes de órgãos como se fossem pessoas, sem qualquer sinal. |
| Só o passo 1 (`#juizProcesso`) | Perderia todas as capas servidas no layout `unj`, em que o campo pode não ter `id`. |
| Só o passo 2 (busca por rótulo) | Descartaria o caminho mais confiável e barato em favor de uma varredura de todos os `span`/`td`/`div` da página. |
| Inverter a ordem, tentando o rótulo primeiro | Mesma perda: a busca textual é mais cara e mais frágil que um `id` estável. |
| Confiar no `id` sem passar por `_juiz_valido` | Criaria dois critérios diferentes de "é nome de juiz" no mesmo método, e o caminho canônico ficaria sem rede de proteção. |
| Usar `if self.GRAU == 1` dentro do `ParserCapaBase`, sem subclasse | Espalharia condicionais de instância pela classe base. O ponto do Template Method é que a divergência fique declarada num lugar só. |
| Tratar juiz e relator como campos separados no dict bruto | O projeto decidiu que o relator ocupa o campo `juiz` no 2º grau. Um campo só simplifica a projeção e a análise. |
| `PARSER_POR_GRAU` escrito à mão | Três afirmações independentes sobre o mesmo fato. `{1: ParserSegundoGrau}` roda o parser errado em silêncio. |

## Limitações Conhecidas

- **`juiz` não entra em `completude`.** As três bandeiras são `tem_classe`, `tem_partes` e `tem_movimentacoes`. Se `#juizProcesso` sumir do portal e o rótulo mudar de texto, **toda** a base passa a ter `juiz: null` sem que nada acuse: `_capa_suspeita` continuará aprovando, porque partes e movimentações seguem chegando. A detecção depende de alguém olhar a distribuição do campo depois da coleta. Ver [backlog §2](../../backlog.md).
- **Um juiz cujo sobrenome seja exatamente uma palavra da lista de bloqueio é descartado.** `'Câmara'` é o caso nomeado no código. Nenhum critério de vocabulário resolve isso; o que salva é o texto original preservado no bruto, que torna a correção futura uma reprojeção.
- **O módulo não tem lógica própria para testar isoladamente.** Toda a mecânica (`_por_id`, `_rotulo_estrito`, `_juiz_valido`) vive na classe base; esta subclasse é a composição de três chamadas.

## Exemplo de Uso

Nunca instanciado diretamente — quem escolhe é o mapa derivado do atributo `GRAU`.

```python
from src.scrapers.coletor import PARSER_POR_GRAU

bruto = PARSER_POR_GRAU[1](html).parse()     # ParserPrimeiroGrau
bruto["juiz"]      # 'ALEXANDRE FRANCISCO SANTOS'   <- passo 1, via #juizProcesso
                   # None                            <- se o único candidato for uma vara
```

## Testes e Validação

Não há suíte automatizada. A validação em uso é `scripts/spike_seletores.py`, que imprime o campo `juiz` junto aos demais para cada capa diagnosticada, permitindo comparar com o que a página exibe no navegador. Sendo função pura sobre HTML, é trivialmente testável com os fixtures de `data/spike/`. As 4 invariantes estão no [backlog de testes](../../backlog_testes.md).

**Nota do dado real:** na execução do projeto `teste1`, 2 dos 5 processos coletados saíram com `juiz: null` — consistente com a limitação de `completude` acima, e o tipo de distribuição que valeria olhar depois de qualquer coleta.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | `GRAU` passa a alimentar o `PARSER_POR_GRAU` do coletor; o spike importa o mesmo mapa e o roteamento fica com uma fonte só |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 4 decisões virou lista de tópicos; código copiado removido; invariantes migradas para o backlog de testes |
