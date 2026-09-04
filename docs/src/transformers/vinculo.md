# Derivação do vínculo – `src/transformers/vinculo.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re` (biblioteca padrão) — sem imports do projeto |

## Contexto e Motivação

Este módulo responde a uma pergunta só: **de onde este processo nasceu?** A resposta vira duas colunas no SQLite (`processo_pai`, `processo_pai_grau`) mais o rótulo `tipo_vinculo`, que é a base de todo o grafo de relacionamento da pesquisa.

É o **único escritor** de `tipo`, e isso corrige o pipeline IAMSPE, onde o campo tinha dois donos — normalizador e `vincular_pais` — e o segundo desfazia o primeiro. Dois escritores para o mesmo campo é uma condição de corrida sem concorrência: basta executar as etapas na ordem errada para que o valor final dependa do histórico de execução em vez do dado. E como ambos gravavam valores plausíveis, a divergência não aparecia como erro.

## Decisões de Arquitetura

- **Vocabulário fechado de quatro valores, atribuídos só com evidência** — `incidente` (link "Processo principal" no topo, ou a movimentação de origem), `recurso` (capa de 2º grau declarando o número de 1ª instância), `indefinido` (há indício, mas o número é inválido ou antigo), `sem_vinculo` (nenhum sinal de pai).
- **O grau do pai é inferido do tipo, não observado** — incidente corre na mesma instância, logo `pai_grau = grau`; recurso vem de 1ª instância por definição, logo `pai_grau = 1`. São inferências do domínio jurídico, e por isso ficam explícitas num lugar só.
- **O rótulo `'Ação de Conhecimento (Pai)'` foi removido** — afirmava duas coisas não verificadas: que o processo é ação de conhecimento (a `classe` já responde isso, e podia divergir) e que ele é pai. "Ser pai" não é observável na capa do próprio processo: só se sabe quando **outro** aponta para ele, o que [`projecao.inverter_filhos`](projecao.md) calcula no export.
- **A ordem em que os candidatos entram na lista É a prioridade** — link do topo > movimentação de origem > número de 1ª instância. Não há sorteio nem heurística.
- **O incidente vence o recurso** — é o pai **direto**: um agravo que também é incidente de outro processo nasceu do incidente e só depois subiu de instância.
- **O vínculo perdedor vira observação, nunca é descartado** — o modelo guarda um pai por processo; a informação sobre os demais fica em texto, recuperável por quem precisar.
- **Entre movimentações, vence a de data mais antiga** — é a que registra a origem; as posteriores são referências de tramitação. Data ilegível recebe `(9999, 99, 99)` e vai para o fim, para nunca virar "a mais antiga" por acidente.
- **O padrão é ancorado no rótulo `processo principal`** — despachos citam números em prosa corrida; buscar "um CNJ nas movimentações" transformaria qualquer menção de passagem em aresta de paternidade. É a diferença entre ler uma declaração e colher uma coincidência.
- **O DV do pai é validado antes de criar a aresta** — é aritmética sobre 20 dígitos contra o custo de uma aresta falsa, que viraria órfão permanente e consumiria requisições da opção 3 para descobrir o que a conta já sabia.
- **A guarda de auto-referência compara o PAR, não só o número** — está no laço que percorre os candidatos, para cobrir todos os caminhos sem depender de lembrar. Comparar só o número mataria a aresta legítima `(N, 2) → (N, 1)`, que é a razão de a chave do banco ser composta.
- **`indefinido` ≠ `sem_vinculo`** — `sem_vinculo` é "olhei e não há sinal de pai"; `indefinido` é "há sinal, mas não consegui transformá-lo em aresta". Colapsá-las esconderia os casos que merecem revisão, pelo mesmo raciocínio que separa `sem_dados` de `erro_transitorio` em [`status`](../status.md).
- **O tipo é decidido por um contador, não pelo texto das observações** — a condição era `any("ignorado" in o for o in obs)`: controle de fluxo passando por texto de log. Trocar `"Vínculo ignorado"` por `"Vínculo descartado"` faria todos esses registros migrarem de `indefinido` para `sem_vinculo`, sem teste vermelho e sem nada de errado à vista.
- **A capa de 2º grau sem número de 1ª instância deixa rastro** — é o caminho pelo qual uma quebra de seletor do `cposg` chegaria à base final, indistinguível de competência originária. O tipo continua `sem_vinculo` (não houve sinal); a observação torna o caso contável, sem afirmar o que não se viu.
- **Sem bruto, o padrão é `indefinido`, aplicado fora deste módulo** — `segredo_justica` e `sem_dados` chegam com `bruto=None` e nunca passam por aqui. `sem_vinculo` afirmaria uma verificação que não aconteceu, e uma consulta por processos sem pai incluiria os sigilosos como se tivessem sido conferidos. A regra vale nos dois caminhos que escrevem a coluna: `scripts/menu.py` na coleta e `reprojetar_vinculos` no reprocessamento.
- **O vínculo é reprojetável** — [`reprojetar_vinculos`](../store/sqlite_store.md) relê o bruto, rechama esta função e regrava as colunas. Antes disso, corrigir uma regra daqui valia só para o que fosse coletado dali em diante: após a mudança do padrão sem bruto, os `segredo_justica` já gravados continuavam com `sem_vinculo`, e recoletar um processo sigiloso gasta requisição sem trazer conteúdo.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Derivar o vínculo num passo posterior, sobre o banco | Foi o modelo anterior: dois donos do campo `tipo`, e o segundo desfazia o primeiro. O valor final passava a depender da ordem de execução. |
| Manter o rótulo `'Ação de Conhecimento (Pai)'` | Afirmava a classe (que já existe em campo próprio) e a paternidade (que só se sabe invertendo as arestas, depois da coleta). |
| Vocabulário aberto, aceitando qualquer string descritiva | Impossibilita agregação. Quatro valores fechados são consultáveis; texto livre não. |
| Deixar o recurso vencer o incidente | O incidente é o pai direto — o processo nasceu dele e só depois subiu de instância. |
| Descartar o vínculo perdedor | Perderia informação real sobre a topologia. Em `observacoes` ele continua recuperável. |
| Aceitar vários pais por processo | Complicaria o modelo (o grafo deixaria de ser floresta) para representar um caso que a observação já cobre. |
| Buscar qualquer CNJ nas movimentações | Despachos citam números em prosa; toda menção de passagem viraria aresta de paternidade. |
| Usar a movimentação mais recente | As citações posteriores são referências de tramitação; a de origem é a primeira. |
| Ordenar datas sem tratar as ilegíveis | Uma data que não casa o padrão viraria a "mais antiga" e determinaria a origem do processo. |
| Não validar o DV do pai | Cria aresta apontando para número inexistente, que vira órfão permanente e consome requisições da opção 3. |
| Guarda de auto-referência só comparando o número | Mataria a aresta legítima `(N, 2) → (N, 1)`, razão de a chave do banco ser `(processo, grau)`. |
| Um único valor para "sem pai" | Colapsaria "não há sinal" e "há sinal que não resolvi", escondendo os casos que merecem revisão. |
| Decidir o tipo procurando `"ignorado"` nas observações | Fluxo de controle por texto de log: reescrever a mensagem mudaria o tipo de todos esses registros em silêncio. |
| Deixar a capa de 2º grau sem 1ª instância passar sem observação | É o caminho por onde uma quebra de seletor do `cposg` chegaria à base final indistinguível de competência originária. |
| Classificar essa capa como `indefinido` | Inventaria um indício que a página não trouxe. A observação registra o caso sem afirmar o que não se viu. |
| `sem_vinculo` como padrão para registro sem bruto | Afirma "olhei e não há sinal de pai" sobre uma capa cujo conteúdo a coleta não chegou a ver. |
| Recoletar para aplicar uma regra de vínculo nova | Gasta requisições para reprocessar dado que já está no banco. O bruto guardado tem tudo de que esta função precisa. |
| Derivar o vínculo na projeção, abandonando as colunas | `orfaos()` e `vinculos()` deixariam de ser SQL. A reprojeção mantém a coluna e recalcula seu conteúdo. |

## Limitações Conhecidas

- **Um processo tem no máximo um pai.** O modelo é floresta, não grafo geral. O segundo vínculo vira texto em `observacoes` — recuperável por leitura, não por consulta.
- **O grau do pai é inferido, nunca observado.** Um incidente que tramite em instância diferente da do processo principal seria registrado com o grau errado.
- **O tipo não é validado depois daqui.** A [projeção](projecao.md) copia `reg.get("tipo_vinculo")` direto para o JSONL, sem conferir contra o vocabulário.
- **`_dv_ok` reimplementa o cálculo que `NumeroProcesso.dv_esperado` já faz.** Mantém o módulo puro ao custo de duas cópias da regra mais delicada do projeto — ver [backlog §1](../../backlog.md).
- **`_PADRAO_PAI_MOV` embute a máscara CNJ em vez de reaproveitá-la.** É a cópia mais fácil de esquecer num ajuste, porque está escondida dentro de outro padrão.
- **O rótulo `'processo principal'` é uma lista de uma frase só.** Se o e-SAJ escrever "autos principais" ou "processo de origem", a movimentação deixa de ser reconhecida — sem erro e sem observação.
- **O ramo da capa de 2º grau sem 1ª instância não tem cobertura.** As duas capas de `cposg` em `data/spike/` têm `processo_1a_instancia` preenchido, então o `elif` nunca é exercitado pelas fixtures atuais.

## Exemplo de Uso

```python
from src.transformers.vinculo import INDEFINIDO, VERSAO_REGRA, derivar_vinculo

# Sem bruto (segredo de justiça, sem dados) o tipo é INDEFINIDO, não sem_vinculo:
# nunca se chegou a olhar a capa.
vinc = {"tipo": INDEFINIDO, "processo_pai": None,
        "processo_pai_grau": None, "observacoes": []}
if bruto:
    vinc = derivar_vinculo(bruto, grau, numero)
    bruto = dict(bruto)
    bruto["observacoes"] = vinc["observacoes"]   # a 4ª chave viaja dentro do bruto

# {'tipo': 'recurso', 'processo_pai': '10110499020188260066',
#  'processo_pai_grau': 1, 'observacoes': []}
```

As três primeiras chaves viram colunas em `registrar_resultado`; `observacoes` é anexada ao bruto e chega à base final pela projeção.

## Testes e Validação

Não há suíte automatizada. O módulo é puro (dict, int, str → dict) e não precisa de HTML nem de rede. `scripts/checar_offline.py` imprime o vínculo derivado das capas de `data/spike/` — sem asserção, mas é a única execução sobre dado real: hoje devolve `incidente` para duas capas, `recurso` para uma e `sem_vinculo` para outra. As 9 invariantes que valeria fixar estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Os três pontos em aberto viraram correção de código; registrados como decisões |
| 2026-08-11 | @alexandrehiero | `reprojetar_vinculos` no store: a limitação "corrigir vínculo exige recoleta" deixou de existir |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas). Removida a limitação "a reprojeção não reescreve as observações", que o código já contradiz: `reprojetar_vinculos` reescreve `bruto["observacoes"]` |
