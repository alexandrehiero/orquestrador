# Estrutura do GPDR – `src/transformers/estrutura_gpdr.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-23                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `src.transformers.monetario`, `src.transformers.nomes`, `src.status` — sem dependências externas |

## Contexto e Motivação

A base do GPDR (`Codigos_dados_GPDR`, v7) é o Data Lake da PGE no MongoDB do centro de pesquisa. Para que uma base do orquestrador se consulte pelos mesmos campos, cada documento do JSONL é projetado na forma dela. Este módulo é essa projeção, e é função pura, como [`projecao`](projecao.md): mudar a estrutura é rodar de novo sobre o JSONL, sem requisição.

Fica de fora só `metadados`, que é o cadastro administrativo da PGE e não existe para um processo coletado pelo orquestrador.

## Decisões de Arquitetura

- **A v7 é a régua: nomes, aninhamento, ordem de chaves e convenções de valor** — a ordem `processo, tribunal, grau, orgaoJulgador, datas, partes, movimentos_tjsp, _id, movimentos_pge, origem_pge` é a medida na v7, para que um diff entre as bases seja legível. `grau.nome` usa o sinal de grau (`1° Grau`, U+00B0), como lá.
- **O que o GPDR não tem onde guardar entra no objeto a que pertence, sempre no FIM** — `status` e `situacao` em `processo`, `juiz` em `orgaoJulgador` (no 2º grau, o relator), e `relacionamento` e `observacoes` no nível de `processo`, fechando o documento. As chaves comuns mantêm a ordem da v7. Sem `status`, um segredo de justiça e um processo inexistente seriam o mesmo documento vazio.
- **Campo sem dado é `null`, nunca ausente** — na v7 `valorCorrigido` some quando não há valor; aqui todo documento tem as mesmas chaves (o princípio de `projecao.esqueleto`). No Mongo, `{campo: null}` casa com as duas formas.
- **O polo só entra se tiver alguém** — como na v7, que não cria item para polo ausente.
- **Foro pela tabela, nunca pela capa** — o código `OOOO` do CNJ é a unidade de **origem**, e é definicional. A capa mostra o foro **atual**: o mesmo código `0385` aparece como Praia Grande, Peruíbe e Jacupiranga. Código fora da tabela fica com `descricao: null` e o código observado.
- **`movimentos_pge` existe em todo status** — é dado da PGE, não do e-SAJ. Um segredo de justiça tem o conteúdo da capa suprimido porque a coleta nunca o viu, mas o Atos é outra fonte.
- **Filhos chegam de fora** — de [`consolidacao.mapa_filhos`](../aggregators/consolidacao.md), recalculados sobre a base consolidada.

| JSONL do orquestrador | Estrutura final |
|---|---|
| `processo` | `processo.numero` |
| `classe`, `assunto_principal` | `processo.classe.descricao`, `processo.assunto.descricao` |
| `valor_acao` (+ `valor_acao_moeda`, `data_distribuicao`) | `processo.valorAcao`, `processo.valorCorrigido` ([`monetario`](monetario.md)) |
| código `OOOO` do número | `processo.foro` `{codigo, descricao}` |
| — | `tribunal` (constante TJSP) |
| `grau` | `grau` `{sigla, nome, numero}` ou `null` |
| `status`, `situacao` | `processo.status`, `processo.situacao` |
| `vara`, `juiz` | `orgaoJulgador.nome`, `orgaoJulgador.juiz` |
| `data_distribuicao` | `datas.ultimaDistribuicao` `{"$date"}` |
| `movimentacoes[0]` | `datas.ultimoMovimento` |
| `partes.autores` / `partes.reus` | `partes[]` com `polo` `ATIVO` / `PASSIVO` ([`nomes`](nomes.md)) |
| `movimentacoes[]` `{data, movimento}` | `movimentos_tjsp[]` `{descricao, dataHora}` |
| `_id` | `_id` (texto `processo__grau`, não ObjectId) |
| — | `movimentos_pge`, `origem_pge` ([`atos_pge`](../aggregators/atos_pge.md)) |
| `relacionamento`, `observacoes` | `relacionamento`, `observacoes` (últimas chaves do documento) |

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Descartar o que a v7 não tem | `status` e o relacionamento são o que o orquestrador existe para produzir; sem eles, documentos vazios ficam indistinguíveis. |
| Um bloco próprio (`coleta`) para tudo o que a v7 não tem | Primeira versão, descartada em 2026-10-23: separava do processo dados que são dele (status, situação, juiz). |
| Juiz como item de `partes` | O juiz não é parte; `partes` continua só com os polos. |
| Gerar `ObjectId` no `_id` | Aleatório: cada reimportação duplicaria a base. A chave do orquestrador é determinística. |
| Usar o foro da capa quando o código não está na tabela | A capa mostra o foro atual, não a unidade de origem. |
| Omitir campos sem dado, como a v7 | Quebra a forma única dos documentos, e a contagem deixa de fechar por inspeção. |

## Limitações Conhecidas

- **`tiposParte` sai sempre vazio.** O tipo de parte (Reqte, Exeqte…) fica no bruto do SQLite; o JSONL, que é a entrada, não o traz. Ver [backlog](../../backlog.md).
- **`_id` em texto convive com ObjectId.** Numa mesma coleção do Mongo funciona; quem cruzar as bases pelo `_id` precisa saber disso. A chave de junção é `processo.numero`.
- **Valor sem símbolo vira `R$` antes de chegar aqui** ([`limpeza.moeda_do_valor`](limpeza.md)). Num processo de 1994 sem símbolo, isso pode tratar como Real um valor em CR$. O GPDR só assumia Real a partir de 1995.

## Exemplo de Uso

```python
from src.transformers import estrutura_gpdr, monetario

foros = estrutura_gpdr.carregar_foros(Path("data/unidades_foro_tjsp.md"))
ipca = monetario.carregar_ipca(Path("data/ipca_mensal.csv"))
doc = estrutura_gpdr.projetar(reg, foros, ipca, filhos, bloco_pge, Counter())
```

## Testes e Validação

Sem suíte automatizada. Smoke test em 2.000 documentos de 2025 (`--amostra`) e execução completa sobre os 368.722 de 2025; ordem de chaves conferida contra o censo da v7. As peças portadas foram conferidas contra a v7, com zero diferenças (ver [`monetario`](monetario.md) e [`nomes`](nomes.md)).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação |
| 2026-10-23 | @alexandrehiero | Fim do bloco `coleta`: status e situação em `processo`, juiz em `orgaoJulgador`, relacionamento e observações no fim do documento |
