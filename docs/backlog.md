# Backlog técnico consolidado

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Cobertura atual     | todo o `src/` (13 módulos) e `scripts/` (`menu.py`, `spike_seletores.py`) |

Lista única dos pontos em aberto levantados pelos ADRs, para priorização. Cada item nasce
de uma página de documentação e continua registrado lá, com o contexto completo — aqui fica
só o enunciado, a evidência no código e o efeito hoje.

**Nada nesta lista é bug conhecido.** São dívidas estruturais, riscos não confirmados e
verificações ausentes. Onde um item já produz comportamento errado, isso está dito.

## Como ler

- **Efeito hoje** — o que já acontece, não o que poderia acontecer.
- **Risco** — o que muda se a premissa do item deixar de valer.
- Um item sai daqui quando o código muda; a página de origem então registra a decisão e a
  alternativa descartada, e a linha correspondente é removida desta tabela.

---

## 1. Duplicação de utilitários

Cinco utilitários com mais de uma implementação. Nenhum diverge hoje — todas as cópias
foram conferidas e são equivalentes —, e é justamente por isso que a divergência futura
seria silenciosa.

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| `so_digitos` reimplementado | Canônico em `numero_processo.py:30`; reescrito como `_digitos` em `transformers/vinculo.py:35`; embutido como `re.sub(r"\D", "", ...)` em `page_state.py:41`, `parser_base.py:289`, `parser_segundo_grau.py:33` e `scripts/spike_seletores.py:145` | Nenhum: as seis formas são equivalentes | Uma mudança de regra (aceitar outro caractere, tratar `None` diferente) precisa ser replicada em seis lugares, e o esquecimento não quebra nada visivelmente |
| Cálculo do DV do CNJ | `NumeroProcesso.dv_esperado` (`numero_processo.py:85`) e `_dv_ok` (`vinculo.py:39`) | Nenhum: mesma fórmula ISO 7064 MOD 97-10, escrita duas vezes | É a regra mais delicada do projeto — um erro numa cópia só se manifesta em números que a outra aceitaria |
| Máscara de regex CNJ | `_MASCARA_CNJ` idêntico em `page_state.py:24` e `parser_segundo_grau.py:20`; o mesmo padrão embutido em `_PADRAO_PAI_MOV` (`vinculo.py:29`) | Nenhum | Ajustar a máscara (novo separador, sufixo) exige três edições; a terceira está escondida dentro de outro padrão |
| Formatação da máscara CNJ | `NumeroProcesso.mascara` (`numero_processo.py:109`) e `projecao._mascara` (`projecao.py:29`) | Nenhum | A da projeção opera sobre string de 20 dígitos e não passa pelo value object — divergências de formatação não seriam detectadas por nada |
| `_norm` (minúsculas, sem acento, espaços colapsados) | Idêntico, com a mesma docstring, em `page_state.py:27` e `parser_base.py:28`; `limpeza._chave_dedup` faz quase o mesmo com `casefold()` no lugar de `lower()` | Nenhum | Comparações precisam concordar entre módulos para casar; a variante com `casefold()` já é uma terceira semântica |

**Origem:** [`page_state`](src/scrapers/page_state.md), [`parser_base`](src/scrapers/parser_base.md),
[`parser_segundo_grau`](src/scrapers/parser_segundo_grau.md), [`numero_processo`](src/scrapers/numero_processo.md).

---

## 2. Verificações ausentes ou incompletas

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| `_completude` recalcula `_extrair_classe()` | `parser_base.py:110` | Trabalho repetido — pode incluir a varredura completa de `_rotulo_estrito` | Abre a possibilidade teórica de `completude["tem_classe"]` discordar do campo `classe` do mesmo dict |
| `_e_capa` aceita `#numeroProcesso` sozinho | `page_state.py:122` | Página com o número e nenhuma tabela é classificada como `DADOS_CAPA` e segue para o parser | A rede de segurança fica na etapa seguinte (`coletor._capa_suspeita`), não na classificação |
| `juiz` não entra em `completude` | `parser_base.py:105` | As três bandeiras são `tem_classe`, `tem_partes`, `tem_movimentacoes` | Se o seletor de juiz quebrar, **toda** a base fica com `juiz: null` sem que nada acuse — `_capa_suspeita` continua aprovando |
| Nenhuma tupla com o vocabulário completo de status | `status.py` | `STATUS_TERMINAIS` cobre quatro dos cinco; `ERRO_TRANSITORIO` fica fora | Uma validação abrangente precisa montar o conjunto no ponto de uso |
| Só um ponto valida o status gravado | `SqliteStore.registrar_resultado` | Fora dele, string arbitrária entra sem reclamação | A fonte única eliminou a divergência entre módulos; não introduziu checagem de tipo |
| `tipo_vinculo` não é validado contra o vocabulário | `projecao.projetar` copia `reg.get("tipo_vinculo")` | Um valor fora dos quatro sairia na base final sem sinal | Ao contrário do `status`, que tem o ramo `else` para se denunciar |
| Ramo "capa de 2º grau sem 1ª instância" sem cobertura | `vinculo.py:98` | As duas capas de `cposg` em `data/spike/` têm `processo_1a_instancia`; o `elif` nunca é exercitado | A observação que denunciaria uma quebra de seletor nunca foi vista sendo escrita |
| A reprojeção de vínculo não reescreve `bruto["observacoes"]` | `SqliteStore.reprojetar_vinculos` atualiza três colunas; as observações foram anexadas ao bruto pelo `menu` na coleta | Um registro antigo sai da base final com `relacionamento.tipo` novo e observação de vínculo velha | Mensagem reescrita ou observação nova (como a de capa de 2º grau sem 1ª instância) não alcança o já coletado. A divergência é silenciosa: os dois campos são plausíveis lado a lado |

**Origem:** [`parser_base`](src/scrapers/parser_base.md), [`page_state`](src/scrapers/page_state.md),
[`parser_primeiro_grau`](src/scrapers/parser_primeiro_grau.md), [`status`](src/status.md),
[`sqlite_store`](src/store/sqlite_store.md), [`vinculo`](src/transformers/vinculo.md),
[`projecao`](src/transformers/projecao.md).

---

## 3. Seletores e premissas sobre o HTML do portal

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| Fallback `_PADRAO_SECAO_1A` do `cposg` sem confirmação | `parser_segundo_grau.py` | **Reduzido em 2026-08-11.** `scripts/v_checar_offline.py` mostra `juiz` e `processo_1a_instancia` preenchidos nas **duas** capas reais de 2º grau de `data/spike/` (`VICENTE DE ABREU AMADEI`, `JARBAS GOMES`) — `#relatorProcesso` e `#numeroProcessoPrimeiraInstancia` funcionam. A saída não distingue qual caminho produziu o número, então a varredura de seção pode nunca ter rodado | Se o atalho por `id` sair da página, o fallback assume sem nunca ter sido exercitado. `completude` não cobre o campo, então `processo_1a_instancia: null` sistemático não dispara nada. `parser_segundo_grau.md` ainda registra a advertência original e precisa ser revisto |
| Só o primeiro número de 1ª instância é capturado | `_varrer_secao_1a_instancia` devolve na primeira célula com número; `_cnj_de_texto` usa `search()` | Um recurso com mais de um processo de origem registra só um vínculo | A seção chama-se "Números", no plural — os demais são perdidos sem observação |
| Texto original da célula descartado quando o CNJ é extraído | `parser_segundo_grau.py:44` | Foro, vara e juiz de origem, que estão na mesma célula, ficam fora do dict | Assimetria frente à filosofia declarada em `parser_base` (guardar o bruto, projetar depois) |
| `_FRASES_NAO_ENCONTRADO` é lista fechada de três frases | `page_state.py:64` | Correto para as três redações conhecidas | Se o e-SAJ mudar o texto, todo processo inexistente vira `DESCONHECIDO` → `erro_transitorio` → `erro_persistente`. A base não fica errada; a fila de falhas cresce sem explicação óbvia |
| `SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO` são listas fechadas | `parser_base.py:75` e `:78` | Dois seletores de situação confirmados no spike; `.unj-badge` e `.tag` nunca observados | Selo ou rótulo **novo** produz campo vazio, não erro — e campo vazio não dispara nenhuma bandeira de `completude` |

**Origem:** [`parser_segundo_grau`](src/scrapers/parser_segundo_grau.md),
[`page_state`](src/scrapers/page_state.md), [`parser_base`](src/scrapers/parser_base.md).

---

## 4. Pontos cegos operacionais

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| Captcha é ponto cego do circuit breaker | `esaj_client.py` | Não há tratamento. Páginas de verificação caem em `DESCONHECIDO` → `erro_transitorio` | O breaker **não** dispara: do ponto de vista HTTP as requisições estão sendo bem-sucedidas. A fila inteira consumiria tentativas até o teto sem sinal de que a causa é única |
| Bloqueio, captcha, manutenção e layout novo são indistinguíveis | `EstadoPagina.DESCONHECIDO` | Os quatro produzem o mesmo `erro_transitorio` com o motivo `"página não reconhecida"` | Diagnosticar exige olhar o HTML salvo por `scripts/spike_seletores.py` |
| `motivo` é string livre, sem código estruturado | `ResultadoColeta.motivo` → `ultimo_erro` (truncado em 500 caracteres) | Agrupar falhas por causa exige *parsing* de string | Métricas de qualidade da coleta não são obteníveis em SQL |
| `Pacer` não é persistente | `esaj_client.py:66` | Reiniciar zera `_proximo`; a primeira requisição sai imediatamente | Em retomadas frequentes, o intervalo entre a última requisição da execução anterior e a primeira da nova não é respeitado |
| `Session` mantém cookies e nunca é reciclada | `esaj_client.py:155` | É o que faz a navegação seleção → detalhe funcionar | Um cliente marcado pelo portal continua marcado até o fim da execução |
| Sem limite de tempo ou volume por execução | `EsajClient` | O circuito abre por falhas consecutivas, não por "requisições demais nesta sessão" | Nada limita o total de uma execução longa |
| A reprojeção de vínculo varre a base inteira a cada opção 4 | `SqliteStore.reprojetar_vinculos`, em lotes de 500 | Toda opção 4 lê e desserializa todos os `bruto` gravados, mesmo quando nada muda | Numa base de centenas de milhares de registros é o custo dominante do export local. Não há marca de "já reprojetado com esta versão da regra" |
| A primeira reprojeção altera registros de erro já publicados | `reprojetar_vinculos` não filtra por status; linhas de erro têm `bruto` nulo | `tipo_vinculo` desses registros passa de `NULL` a `indefinido`; em `erro_persistente`, que é exportável, o `relacionamento.tipo` da base final deixa de ser `null` | É coerente com o critério (não se olhou a capa), mas muda valor em base já entregue, sem que nada no JSONL registre a mudança |

**Origem:** [`esaj_client`](src/scrapers/esaj_client.md), [`coletor`](src/scrapers/coletor.md),
[`page_state`](src/scrapers/page_state.md), [`vinculo`](src/transformers/vinculo.md),
[`exportador`](src/aggregators/exportador.md).

---

## 5. Operação dos scripts

Itens levantados ao documentar `scripts/`. Nenhum impede a operação hoje; todos são
armadilhas para quem for estender ou reutilizar o código.

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| Metade das funções depende de globais preenchidos por efeito colateral | `ENTRADA`, `SAIDA`, `JSONL`, `ORFAOS`, `FALHAS`, `REVISAO`, `INVALIDOS`, `BANCO` nascem `None` e são definidos por `configurar_projeto()` (`menu.py:55`) | Nenhum: `main()` sempre configura antes de qualquer opção | `atualizar_arquivos_de_falha`, `escrever_relatorio` e `_mostrar` recebem `store` por parâmetro mas leem caminhos de globais — não são reutilizáveis fora do fluxo do menu, e a pré-condição não está declarada em lugar nenhum. A falha seria `AttributeError` em `None.name`, longe da causa |
| A opção 2 reclassifica a origem dos órfãos como `lista` | `executar_coleta(..., ORIGEM_LISTA, "Recoletando")` (`menu.py:287`) | Um órfão que falhou na opção 3 e foi recoletado pela 2 entra numa linha nova com `origem = "lista"` | A coluna existe para separar "a base que pedi" da "base que descobri"; a distinção se perde no caminho da recoleta. Efeito restrito a consultas sobre `origem` — nada no fluxo do menu a utiliza |
| A opção 3 descarta os números inválidos sem registrar | `numeros, _ = ler_numeros(ORFAOS)` (`menu.py:318`) | A opção 1 grava os rejeitados em `numeros_invalidos.txt`; aqui o segundo retorno é ignorado | Como `vinculo._dv_ok` já filtra o DV, o caso restante é um pai **fora do TJSP**: sumiria da fila sem aparecer em lugar nenhum e voltaria a ser listado como órfão em toda opção 4 |
| A docstring do `menu` descreve a opção 4 sem mencionar a reprojeção | Cabeçalho de `menu.py` diz só *"transforma os dados coletados na estrutura JSON final (local, sem rede)"* | A docstring de `opcao_4` já registra os três passos | Quem ler só o topo do arquivo não descobre que a opção 4 **escreve no banco** |
| Duas docstrings do `spike` descrevem invocações diferentes | Cabeçalho de `spike_seletores.py` documenta `# lê data/entrada/processos.txt`; a de `main()` já descreve o nome de projeto | O padrão sem argumento é `processos`, que não existe no repositório (a entrada versionada é `teste1.txt`) | Benigno — a mensagem de arquivo não encontrado orienta —, mas o arquivo diz duas coisas sobre si mesmo |
| Nome de projeto com 20 dígitos vira número de processo | `numeros = [a for a in argumentos if len(re.sub(r"\D", "", a)) == 20]` (`spike_seletores.py:145`) | Nenhum com os nomes em uso | Um projeto como `coleta_20240101_20241231_v2` cairia na lista de números e seria consultado no e-SAJ. A heurística não tem escape explícito |

**Origem:** [`menu`](scripts/menu.md), [`spike_seletores`](scripts/spike_seletores.md).

---

## 6. Ausência de testes

Não há suíte automatizada no repositório. As páginas de ADR já listam, módulo a módulo, as
invariantes que valeria fixar; o obstáculo não é técnico. `page_state`, `parser_base` e
`coletor` são funções puras sobre string, e `scripts/spike_seletores.py` **já produz os
fixtures** — os arquivos `data/spike/<numero>_g<grau>.html` são HTML real do e-SAJ.

### O que existe hoje: `scripts/v_checar_offline.py`

É o mais próximo de regressão que o repositório tem. Reprocessa todos os HTMLs de
`data/spike/` **sem nenhuma requisição** e imprime, para cada um: estado da página,
resultado da verificação de identidade, campos extraídos e vínculo derivado.

| | Módulos |
|---|---|
| **Cobre** | `page_state` (classificação, `escolher_na_selecao`, `verificar_identidade`), `numero_processo`, os dois parsers, `vinculo` |
| **Não cobre** | `sqlite_store`, `exportador`, `projecao`, `limpeza` — e nem `coletar_um`, de quem o script importa apenas o `PARSER_POR_GRAU` |

**Não é uma suíte de testes.** Não há asserção, não há runner, não há resultado
"passou/falhou": a saída é lida por uma pessoa e comparada com o que se esperava. Um
comportamento que mude continua imprimindo normalmente. O próprio script avisa, na docstring,
que analisa a capa mesmo quando a identidade **diverge** — o que a coleta real não faz —,
então parte da saída é artefato de diagnóstico e não reflete o pipeline.

A lacuna de cobertura é justamente a metade do pipeline em que as correções de 2026-08-11
foram feitas: banco, projeção, limpeza e export. `reprojetar_vinculos`, que reescreve colunas
da base inteira, não tem verificação nenhuma além de olhar o par `vistos`/`alterados` que ele
imprime.

Ordem sugerida pelas próprias páginas, por relação risco/custo:

1. `coletar_um` com um `client` dublê — a regra central (erro de rede não avança de grau) é
   verificável pela **ausência** de uma chamada;
2. `page_state` sobre fixtures — capa com incidentes não é `LISTA_SELECAO`; `DIVERGE` não é
   `INDETERMINADO`;
3. `parser_base` — classificação de polo, `_juiz_valido` por palavra inteira, `completude`;
4. `exceptions` — `issubclass(EsajIndisponivelError, EsajError)` é `False`;
5. `limpeza` — é o mais barato de todos (funções puras, sem I/O e sem imports do projeto) e o
   único cujos casos-limite já foram conferidos à mão: `31/02/2020`, `29/02/2024`,
   `'em 2024: R$ 3.724,16'`. Hoje nada disso é reexecutado por ninguém;
6. `reprojetar_vinculos` contra um `SqliteStore(":memory:")` — a idempotência (segunda
   passada devolve `alterados = 0`) e a paginação (`vistos == total()` com mais de 500
   linhas) são verificáveis sem rede e sem fixture, e o método reescreve a base inteira.

---

## Itens encerrados

Registrados aqui para não voltarem como "descoberta nova". O contexto completo, com a
alternativa descartada, está na página de origem.

| Item | Página | Como foi resolvido |
|---|---|---|
| `_registrar_falha` lia `falhas_seguidas` fora do lock | `esaj_client` | `falha()` devolve `(abrir, falhas_seguidas)` |
| Contrato "sempre levanta" só num comentário | `esaj_client` | Renomeado para `_levantar_falha` |
| `_USER_AGENT` podia divergir do `impersonate` | `esaj_client` | UA manual removido |
| `estatisticas()` subnotificava requisições | `esaj_client` | `requisicoes` (HTTP real) separado de `operacoes` |
| Detector e resolvedor de seleção com listas diferentes | `page_state` | Seletores compartilhados em constantes |
| Vocabulário de status em três declarações | `coletor` | Extraído para `src/status.py` |
| Segunda tela de seleção caía no motivo errado | `coletor` | Motivo próprio |
| `NAO_ENCONTRADO` após seleção resolvida avançava de grau | `coletor` | Vira `erro_transitorio` |
| Grau do erro descartado na gravação | `coletor` | Decisão documentada: tentativa não é observação |
| `_juiz_valido` comparava por subcadeia | `parser_base` | Comparação por palavra inteira |
| `SELETORES_SITUACAO` nunca confirmado | `parser_base` | Confirmado no spike de 2026-08-10 |
| `GRAU` declarado e nunca lido | `parser_primeiro_grau` | Alimenta `PARSER_POR_GRAU` |
| `processo_1a_instancia_bruto` inalcançável | `parser_segundo_grau` | Filtro CNJ saiu da varredura |
| Docstring de `_varrer_secao_1a_instancia` contradizia o corpo | `parser_segundo_grau` | Docstring alinhada |
| Atalho por `id` mantinha filtro de CNJ | `parser_segundo_grau` | Mesmo critério `\d{4,}` |
| `TODOS` definido e nunca importado | `status` | Constante removida |
| `menu.py` com duas procedências do vocabulário | `status`, `coletor` | `ERRO_TRANSITORIO` vem de `src.status` |
| `exceptions.md` documentava `falha()` como booleano | `exceptions` | Bloco substituído pelo código real |
| `iter_exportaveis` não selecionava `ultimo_erro` | `sqlite_store` | Coluna no `SELECT`: `erro_persistente` deixou de sair no JSONL sem a causa |
| Ciclo 4 → 3 → 4 podia não convergir | `sqlite_store` | `orfaos()` casa pelo NÚMERO; as três granularidades concordam |
| `import os` sem uso | `sqlite_store` | Import removido |
| `PRAGMA foreign_keys = ON` sem efeito | `sqlite_store` | Pragma removido; a ausência de FK virou decisão explicada no código |
| `contagem_por_grau` não fecha com `total()` sem aviso | `sqlite_store` | Docstring declara que só conta status com grau observado |
| `data_para_iso` aceitava datas inexistentes | `limpeza` | `datetime.date` dentro de `try`, iterando todas as ocorrências |
| `valor_para_float` era ganancioso sobre a string | `limpeza` | Passou a casar um padrão monetário e ignorar o resto (refinado no item abaixo) |
| Tipo do vínculo decidido pelo texto de log | `vinculo` | Contador `descartados` |
| Registro sem `bruto` recebia `sem_vinculo` | `vinculo`, `coletor` | `INDEFINIDO` em `scripts/menu.py` |
| Capa de 2º grau sem 1ª instância não gerava observação | `vinculo` | `elif` registra o caso (sem cobertura de fixture — ver §2) |
| Partes todas em polo `OUTRO` saíam sem sinal | `projecao` | Observação explícita no JSONL |
| `.tmp` sobrava quando o export falhava | `exportador` | `try/except BaseException` remove e re-levanta |
| `pais_com_filhos` não era comparável com nada | `exportador` | `com_filhos` (documentos exportados) + um contador de pares |
| Corrigir uma regra de vínculo exigia RECOLETA | `sqlite_store`, `vinculo`, `projecao` | `reprojetar_vinculos`: a opção 4 recalcula as colunas a partir do bruto, antes do export |
| Alternação única resolvia pelo padrão mais à esquerda | `limpeza` | Busca em dois passos: valor com centavos em toda a string antes de aceitar inteiro solto |
| `pais_citados_sem_registro` era lido como tamanho de `orfaos.txt` | `exportador` | Renomeado para `pares_pai_sem_documento` — o nome passou a dizer a unidade |
| `graus_citados` não chegava a lugar nenhum | `exportador`, `sqlite_store` | Gravado em `orfaos_diagnostico.txt`, separado porque `orfaos.txt` é lido de volta pela opção 3 |
| `.tmp` sem proteção em `escrever_lista_orfaos` | `exportador` | Mesmo `try/except BaseException` das demais escritas |
| Docstring de `v_checar_offline.py` com o nome errado do arquivo | `backlog` §5 | Corrigida para `python scripts/v_checar_offline.py` |

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação: consolidação dos pontos em aberto de `src/status.py` e `src/scrapers/` |
| 2026-08-11 | @alexandrehiero | Cobertura estendida a `store`, `transformers` e `aggregators`; 13 itens encerrados; `v_checar_offline.py` registrado na §5 |
| 2026-08-11 | @alexandrehiero | Mais 6 itens encerrados (`reprojetar_vinculos`, valor em dois passos, `pares_pai_sem_documento`, `orfaos_diagnostico.txt`, `.tmp`, docstring); 3 itens novos, todos consequências da reprojeção |
| 2026-08-11 | @alexandrehiero | Cobertura estendida a `scripts/`: nova §5 (operação dos scripts, 6 itens); "Ausência de testes" passou a §6 |
