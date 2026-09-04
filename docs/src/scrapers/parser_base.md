# Parser base da capa – `src/scrapers/parser_base.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `beautifulsoup4`, `re`, `unicodedata` (biblioteca padrão) |

## Contexto e Motivação

Este módulo extrai os dados da capa. A decisão que o define é sobre o que ele **não** faz: **retorna um dict BRUTO, não normaliza.**

Suponha que, três semanas depois de uma coleta terminar, alguém descubra que a limpeza da classe remove parênteses demais, ou que `'credor'` deveria estar no polo ativo. Num parser que normaliza na hora, o texto original não existe mais em lugar nenhum: a única forma de aplicar a regra nova é **coletar tudo de novo** — semanas de requisições contra um portal público, com toda a exposição a bloqueio que isso implica. Aqui o texto original está no SQLite, e corrigir a regra é rodar a opção 4, sem uma única requisição.

Por isso o parser guarda `"Cumprimento de Sentença contra a Fazenda Pública (0000010-31...)"` como veio e deixa a limpeza para [`limpeza`](../transformers/limpeza.md). O bruto é o registro do que o portal respondeu; o JSONL é uma **opinião** sobre esse registro — e opiniões mudam.

## Decisões de Arquitetura

- **`parse()` devolve 12 chaves, todas cruas** — `valor` é a string `"R$ 3.724,16"`, não `float`; `data_distribuicao` é `"09/01/2013 às 11:39 - Livre"`, não data ISO. A conversão acontece na projeção.
- **`completude` diz QUAIS blocos vieram, não "veio ou não veio"** — um booleano único responde "extraí alguma coisa?", e a resposta é sim mesmo quando o bloco mais importante veio vazio. As três bandeiras (`tem_classe`, `tem_partes`, `tem_movimentacoes`) permitem a [`coletor._capa_suspeita`](coletor.md) reprovar a capa com classe e movimentações mas **zero** partes — que é seletor quebrado, não processo sem partes.
- **Partes viram lista de dicts com o rótulo real preservado** — cinco listas paralelas (`autores`, `reus`, `advogados_autores`…) obrigam a decidir o polo no momento da extração e descartam a informação que permitiria revisar essa decisão. Guardando `tipo_parte` (`Exeqte`, `Reqdo`) ao lado de `polo`, o rótulo original sobrevive. É a lógica do bruto, aplicada dentro do bruto.
- **O polo é classificado por match exato na célula de tipo** — a célula tem uma ou duas palavras; a linha inteira tem o nome da parte e os advogados. Procurar `"re"` na linha casa com qualquer nome que contenha essas letras.
- **Três correções de vocabulário jurídico frente ao pipeline anterior** — `credor/credora` movidos para ATIVO (na execução, o credor é quem executa); `interessado/interessada` removidos de PASSIVO (rótulo neutro, vai para OUTRO); e as flexões que faltavam e caíam em OUTRO em silêncio (apelada, recorrida, impetrada, suscitante/suscitado, devedor/devedora).
- **`_rotulo_estrito` compara o texto DIRETO por igualdade** — `find(string=True, recursive=False)` ignora o texto dos filhos, senão um `<div>` contêiner que envolve meia página "contém" o rótulo e casaria. E a igualdade, não `in`, é o que impede `'Juizado Especial Cível'` de casar com `'Juiz'`.
- **`_juiz_valido` nunca devolve a Vara como juiz** — uma lista de bloqueio (`vara`, `juizado`, `foro`, `camara`, `orgao`…) reprova o valor que parece nome de órgão. Campo vazio é ausência honesta; campo com o nome da vara é dado **errado** que qualquer agregação por juiz consumiria sem perceber.
- **A comparação com a lista de bloqueio é por palavra inteira** — a versão por substring reprovava sobrenomes reais: `'Alvarado'` contém `vara`, `'Areal'` contém `area`. O juiz virava `None` sem sintoma, **disfarçado da política declarada** "na dúvida, ausente" — e não há bandeira de `completude` para o campo que distinguisse "não achei" de "achei e joguei fora".
- **O caso irredutível permanece registrado** — um juiz de sobrenome `'Câmara'` continua rejeitado, porque a palavra é igual à do órgão. Nenhum critério de vocabulário resolve isso; o que salva é o bruto preservado, que torna a correção futura uma reprojeção.
- **`SELETORES_SITUACAO` teve dois dos quatro confirmados em HTML real** — no spike de 2026-08-10, `.unj-tag` respondeu nos dois graus e `#situacaoProcesso` no 2º. `.unj-badge` e `.tag` seguem como rede de segurança **nunca observada**, e o código diz isso sem arredondar. Nota: `select_one` sobre o grupo devolve o primeiro elemento em ordem de **documento**, não o primeiro seletor da tupla — a ordem é documental, não de precedência.
- **A ordem de `ROTULOS_DISTRIBUICAO` codifica o caso do incidente** — incidentes e cumprimentos não têm "Distribuição", têm "Recebido em". Quando nenhum aparece, devolve `None`: **nunca infere de movimentação**, porque a mais antiga visível não é necessariamente a primeira, e um campo inferido é indistinguível de um observado depois de virar JSONL.
- **`_extrair_processo_principal` usa só o link do topo, nunca a aba Apensos** — apensamento é relação lateral (tramitam juntos por conveniência); incidente é hierárquico (o processo nasceu de outro). Tratar apenso como pai criaria arestas falsas, propagadas para os dois lados pela inversão em `processos_filhos`.
- **Template Method: a subclasse define o juiz** — `_extrair_juiz` levanta `NotImplementedError` em vez de ter retorno padrão, para que uma terceira subclasse não herde em silêncio um comportamento que não vale para ela. O atributo `GRAU` é **lido**: é dele que o coletor deriva o mapa de roteamento.
- **A base não é um denominador comum neutro** — `ParserPrimeiroGrau` sobrescreve um método; `ParserSegundoGrau` sobrescreve quatro e acrescenta três. A assimetria indica que esta classe foi escrita contra o HTML de `cpopg`, o que importa para quem for estendê-la a outro tribunal.
- **Movimentações guardam título e complemento numa string só** — simplifica a busca textual, que é o uso principal do campo, ao custo de não permitir filtrar só por título. É decisão registrada, não acidente de parsing.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Normalizar durante a coleta (converter data, `float`, limpar classe) | Destrói o texto original. Qualquer correção de regra passaria a exigir recoleta completa — semanas de requisições contra o portal. |
| Guardar só o JSONL final, sem o bruto no banco | Mesma consequência: o pipeline deixa de ser corrigível localmente. |
| Guardar o HTML inteiro em vez do dict bruto | Preservaria mais, mas multiplicaria o tamanho do banco por ordens de grandeza e adiaria todo o custo de parsing para a projeção. |
| `completude` como booleano único (`dados_ok`) | Foi o modelo anterior. Um AND de quatro condições esconde a quebra de um seletor específico: o processo é gravado sem partes e ninguém percebe. |
| Cinco listas paralelas (`autores`, `reus`, …) | Descarta o rótulo original e congela a decisão de polo no momento da coleta, sem possibilidade de revisão posterior. |
| Classificar o polo procurando o rótulo na linha inteira | Padrões curtos como `'Ré'` casam dentro de nomes próprios e de qualquer outro texto da linha. |
| Manter `'credor'` no polo passivo | Erro de classificação jurídica: na execução, o credor é quem executa. Inverte o polo de uma categoria inteira. |
| Manter `'interessado'` no polo passivo | Rótulo neutro (jurisdição voluntária, terceiros). Forçá-lo a um polo inventa informação que o portal não deu. |
| Buscar rótulos com `in` (`"Juiz" in texto`) | `'Juizado Especial'` casaria com `'Juiz'`. Daí o texto **direto** comparado por igualdade. |
| Devolver a Vara quando o juiz não for encontrado | Dado errado é pior que dado ausente: uma agregação por juiz consumiria nomes de órgãos sem perceber. |
| Comparar `_BLOCK_JUIZ` por substring | Sobrenomes reais contêm as sequências bloqueadas. O juiz virava `None` sem sintoma, disfarçado da política "na dúvida, ausente". |
| Inferir `data_distribuicao` da movimentação mais antiga | A mais antiga visível não é necessariamente a primeira, e depois de virar JSONL o campo inferido é indistinguível do observado. |
| Usar a aba Apensos como origem do vínculo | Apensamento é relação lateral, não hierárquica. Criaria arestas de paternidade falsas. |
| `_extrair_juiz` com implementação padrão na base | Uma subclasse futura herdaria silenciosamente um comportamento que não vale para ela. |

## Limitações Conhecidas

- **O dict bruto ganha uma chave depois de sair daqui.** `parse()` não produz `observacoes`, mas `scripts/menu.py` a acrescenta antes de gravar, com o resultado de `derivar_vinculo`. O contrato do bruto é maior do que este arquivo revela.
- **`_extrair_movimentacoes` usa `tds[0]` e `tds[-1]`.** Se o e-SAJ acrescentar uma coluna intermediária, ela é descartada sem aviso.
- **`_extrair_partes` cai para `tds[-1]` quando não acha `td.nomeParteEAdvogado`.** Fallback razoável mas silencioso: uma mudança de classe CSS degradaria a extração sem que `completude` acusasse, porque `tem_partes` continuaria verdadeiro.
- **A extração de representantes depende da estrutura de `<span>`.** Qualquer reorganização do HTML devolve lista vazia — de novo, sem sinal em `completude`.
- **`_rotulo_estrito` varre todos os `span`, `td`, `dt`, `th`, `label` e `div`, até dez vezes por capa.** Cada chamada só ocorre quando o seletor por `id` falhou, então o custo depende de quanto o layout `unj` está em uso.
- **`SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO` são listas fechadas.** Um selo ou rótulo **novo** produz campo vazio, não erro — e campo vazio não dispara nenhuma das três bandeiras.
- **`_completude` recalcula `_extrair_classe()`**, já computado por `parse()` na mesma chamada. Hoje os dois sempre concordam; a duplicação é gratuita. Ver [backlog §2](../../backlog.md).
- **`_norm` é idêntico ao de `page_state.py`**, docstring incluída. Ver [backlog §1](../../backlog.md).

## Exemplo de Uso

O parser nunca é instanciado diretamente: quem escolhe a subclasse é o mapa derivado do atributo `GRAU`.

```python
from src.scrapers.coletor import PARSER_POR_GRAU
from src.scrapers.parser_base import ROTULOS_DISTRIBUICAO, SELETORES_SITUACAO

bruto = PARSER_POR_GRAU[grau](html).parse()
# {'classe': 'Cumprimento de Sentença ... (0000010-31...)',   <- cru, com parênteses
#  'valor': 'R$ 3.724,16',                                     <- cru, string
#  'partes': [{'tipo_parte': 'Exeqte', 'polo': 'ATIVO', ...}],
#  'completude': {'tem_classe': True, 'tem_partes': True, 'tem_movimentacoes': True}}

suspeita = _capa_suspeita(bruto.get("completude") or {})   # o parser reporta, o coletor decide
```

## Testes e Validação

Não há suíte automatizada. A validação em uso é `scripts/spike_seletores.py`, que roda `parse()` sobre HTML real e imprime cada campo, a `completude` e todas as partes com `tipo_parte` e `polo` — permitindo conferir a classificação de polo linha a linha contra a capa aberta no navegador. O módulo é puro sobre string e os HTMLs de `data/spike/` servem de fixture direta. As 6 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | `_juiz_valido` compara por palavra inteira; `SELETORES_SITUACAO` confirmado em HTML real pelo spike; `GRAU` passa a alimentar `PARSER_POR_GRAU` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 12 decisões virou lista de tópicos; código copiado removido; "Pontos em aberto" migrou para o backlog e as invariantes para o backlog de testes |
