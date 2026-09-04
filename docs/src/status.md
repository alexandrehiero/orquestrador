# Vocabulário de status – `src/status.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | nenhuma — módulo folha, sem imports do projeto |

## Contexto e Motivação

Este é o menor módulo do projeto e não executa nada: são doze constantes e a docstring que explica por que elas precisam morar num lugar só.

Antes existiam **três declarações independentes** das mesmas strings, em `coletor`, `sqlite_store` e `projecao`. Vale seguir o modo de falha até o fim, porque ele é característico do projeto inteiro. As três cópias não quebram nada enquanto concordam — e concordavam. O problema é o dia em que uma muda: nenhum import falha, nenhuma exceção sobe, nenhum teste acusaria (não há testes). O coletor grava `"segredo_justica"`, o store aceita porque a string está na sua própria lista, e a projeção — com a terceira cópia, agora divergente — não reconhece o valor, cai no `else` e escreve no JSONL que o processo deu **erro persistente**.

O resultado é um registro plausível, internamente consistente e factualmente errado. É a mesma classe de falha que a [regra central do coletor](scrapers/coletor.md) existe para impedir, só que na camada de vocabulário em vez da de roteamento.

## Decisões de Arquitetura

- **O módulo é propositalmente neutro: zero imports do projeto** — se o vocabulário morasse no `sqlite_store`, o `scrapers/coletor` passaria a depender da camada de persistência, que ele não deve conhecer justamente por ser uma função pura que não grava nada.
- **Cinco status, e os comentários descrevem consequência operacional, não significado** — a distinção que carrega mais peso é entre `sem_dados` e `erro_transitorio`: é a versão em vocabulário da diferença entre "perguntei e não existe" e "não consegui perguntar". `sem_dados` é final — o processo nunca mais será tentado; `erro_transitorio` volta à fila. Trocar um pelo outro por engano é gravar uma afirmação falsa e permanente.
- **`segredo_justica` é terminal mas NÃO é ausência de dado** — o grau observado acompanha o registro, porque em qual instância o processo tramita não é informação sigilosa.
- **`STATUS_TERMINAIS` e `STATUS_EXPORTAVEIS` têm nomes diferentes porque respondem a perguntas diferentes** — "isto sai da fila?" e "isto vira linha do JSONL?". Coincidem hoje porque `erro_transitorio` é o único status que não é resultado de nada: é fila de trabalho, e um processo em fila não tem o que exportar.
- **`TETO_TENTATIVAS_PADRAO` mora aqui, não no `sqlite_store`** — é a única constante que não é uma string de status, e a exceção se justifica: o número **define** quando `erro_transitorio` vira `erro_persistente`. Sem ele o vocabulário teria os dois estados e não a aresta entre eles. Que a transição seja um `UPDATE` no SQLite é coincidência de implementação; a regra é de domínio. É também o que fecha o ciclo aberto pelas decisões conservadoras do resto do pipeline: `_capa_suspeita` reprova capas legítimas de propósito, e isso só é sustentável porque o falso positivo tem saída em cinco tentativas.
- **`GRAU_INDETERMINADO = 0`, nunca `NULL`** — o SQLite **aceita** `NULL` em PRIMARY KEY, e como `NULL != NULL` a chave `(processo, grau)` deixaria de barrar duplicatas exatamente nos registros sem observação, que são os mais reprocessados. O sentinela `0` é um valor real: compara, indexa e colide como qualquer outro.
- **Duas origens: `lista` e `orfao`** — um número do arquivo de entrada e um descoberto durante a coleta, como alvo de um vínculo cujo processo não estava na lista. A distinção permite separar a base pedida da base descoberta.

### Os cinco status, e o que cada um autoriza

| Status | Significado | Volta à fila? | Exportável? | Grau |
|---|---|---|---|---|
| `coletado` | A capa foi lida e analisada | Não | Sim | Observado |
| `segredo_justica` | O e-SAJ exigiu senha. O grau é conhecido; o conteúdo, não | Não | Sim | Observado |
| `sem_dados` | O e-SAJ afirmou explicitamente que não existe. **Final** | Não | Sim | `0` |
| `erro_transitorio` | Não foi possível perguntar (rede, layout, seleção irresolvível) | **Sim** | **Não** | `0` |
| `erro_persistente` | Estourou o teto; sai da fila automática para revisão manual | Não | Sim | `0` |

### Quem consome o quê

| Módulo | Constantes importadas |
|---|---|
| `scrapers/coletor.py` | `COLETADO`, `ERRO_TRANSITORIO`, `GRAU_INDETERMINADO`, `SEGREDO_JUSTICA`, `SEM_DADOS` |
| `store/sqlite_store.py` | as quatro acima, mais `ERRO_PERSISTENTE`, `ORIGEM_LISTA`, `STATUS_EXPORTAVEIS`, `STATUS_TERMINAIS`, `TETO_TENTATIVAS_PADRAO` |
| `transformers/projecao.py` | `COLETADO`, `ERRO_PERSISTENTE`, `GRAU_INDETERMINADO`, `SEGREDO_JUSTICA`, `SEM_DADOS` |
| `scripts/menu.py` | `ERRO_TRANSITORIO`, `ORIGEM_LISTA`, `ORIGEM_ORFAO` |

São exatamente os três módulos que antes mantinham cópias, mais o script que os orquestra.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Manter as três declarações independentes | Nada as amarrava. A divergência não levanta erro em lugar nenhum: o valor não reconhecido cai no `else` da projeção e vira "erro persistente" silenciosamente. |
| Colocar o vocabulário no `store/sqlite_store.py` | É onde os status são validados, mas faria `scrapers/coletor` importar da camada de persistência — que ele não deve conhecer. |
| Colocar o vocabulário no `scrapers/coletor.py` | Inverteria o problema: `store` e `transformers` passariam a depender do scraper para saber ler o próprio banco. |
| Usar `enum.Enum` em vez de constantes de string | Os valores vão direto para colunas TEXT e para o JSONL. Um `Enum` exigiria `.value` em cada gravação e comparação, sem ganhar validação onde ela importa — na leitura do banco, onde a string já chegou solta. |
| Deixar `TETO_TENTATIVAS_PADRAO` no `sqlite_store` | O número é a regra de transição entre dois status, não um detalhe de armazenamento. Separá-lo deixaria os dois estados documentados e a aresta entre eles não. |
| `NULL` para grau desconhecido, em vez de `0` | O SQLite aceita `NULL` em PRIMARY KEY e `NULL != NULL`: a chave pararia de barrar duplicatas nos registros sem observação. |
| Manter uma constante `TODOS`, como documentação executável | Nenhum módulo a importava. Numa base recém-criada, constante sem consumidor não é dívida antiga a tolerar — é dívida nova a não contrair. |
| `scripts/menu.py` obter `ERRO_TRANSITORIO` pelo reexport do `coletor` | Funciona, mas o mesmo arquivo passava a mostrar duas procedências para o mesmo vocabulário, sugerindo dois donos onde há um. |

## Limitações Conhecidas

- **`STATUS_EXPORTAVEIS` é o mesmo objeto que `STATUS_TERMINAIS`, não uma cópia.** São tuplas, então não há risco de mutação compartilhada, mas os dois nomes não podem divergir por acidente **nem** por intenção sem alterar essa linha.
- **Nada valida que o status gravado pertença ao vocabulário, exceto num ponto.** Só `registrar_resultado` levanta `ValueError`. Fora dele, uma string arbitrária entraria sem reclamação: a fonte única elimina a divergência **entre módulos**; ela não introduz checagem de tipo. E não há tupla com o vocabulário **completo** — `STATUS_TERMINAIS` cobre quatro dos cinco. Ver [backlog §2](../backlog.md).
- **O módulo não documenta a transição entre status, só os nomes.** Que `erro_transitorio → erro_persistente` aconteça em `registrar_erro`, e que `sem_dados` seja irreversível, são fatos que vivem no `sqlite_store` e no `coletor`. Quem ler só este arquivo conhece o vocabulário e não a máquina.
- **`GRAU_INDETERMINADO` é usado como grau e como sentinela de "sem observação".** As duas leituras coincidem hoje, mas um grau 0 legítimo tornaria o valor ambíguo. É uma aposta sobre o domínio, não uma garantia estrutural.

## Exemplo de Uso

```python
from src.status import (
    ERRO_TRANSITORIO, SEM_DADOS, STATUS_TERMINAIS, TETO_TENTATIVAS_PADRAO,
)

SEM_DADOS in STATUS_TERMINAIS          # True  -> sai da fila para sempre
ERRO_TRANSITORIO in STATUS_TERMINAIS   # False -> volta à fila da opção 2
TETO_TENTATIVAS_PADRAO                 # 5     -> depois disso, revisão manual
```

## Testes e Validação

O módulo não tem comportamento a exercitar — são atribuições de constantes — e sua correção é verificável por leitura: se nenhum outro arquivo declara as mesmas strings, a fonte é única. A conferência que substitui um teste é uma busca:

```bash
grep -rn '"coletado"\|"segredo_justica"\|"sem_dados"\|"erro_transitorio"\|"erro_persistente"' src/ scripts/
```

Hoje ela devolve apenas as linhas de `src/status.py`. **Qualquer ocorrência nova fora daqui é uma quarta cópia nascendo** — e é esse o sinal que este módulo existe para tornar visível. As 3 invariantes estão no [backlog de testes](../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação: extração do vocabulário antes duplicado em `coletor`, `sqlite_store` e `projecao` |
| 2026-08-10 | @alexandrehiero | `TODOS` removido (constante sem consumidor); `scripts/menu.py` passa a importar `ERRO_TRANSITORIO` daqui, não reexportado pelo `coletor` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 7 decisões virou lista de tópicos; os cinco status viraram tabela; invariantes migradas para o backlog de testes |
