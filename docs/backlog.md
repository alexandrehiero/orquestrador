# Backlog técnico

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Cobertura atual     | todo o `src/` (13 módulos) e `scripts/`    |

Dívidas estruturais, riscos não confirmados e verificações ausentes levantados pelos ADRs.
Cada item nasce de uma página, que guarda o contexto completo; aqui fica o enunciado, a
evidência no código e o efeito hoje.

**Nada nesta lista é bug conhecido.** Onde um item já produz comportamento errado, isso
está dito.

Páginas irmãs: [invariantes de teste](backlog_testes.md) · [itens encerrados](backlog_encerrado.md).

## Como ler

- **Efeito hoje** — o que já acontece, não o que poderia acontecer.
- **Risco** — o que muda se a premissa do item deixar de valer.
- Um item sai daqui quando o código muda: a página de origem passa a registrar a decisão e
  a linha migra para [itens encerrados](backlog_encerrado.md).

## 1. Duplicação de utilitários

Cinco utilitários com mais de uma implementação. Nenhum diverge hoje — todas as cópias foram
conferidas e são equivalentes —, e é justamente por isso que a divergência futura seria
silenciosa.

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| `so_digitos` reimplementado | Canônico em `numero_processo.py:30`; reescrito como `_digitos` em `transformers/vinculo.py:35`; embutido como `re.sub(r"\D", "", ...)` em `page_state.py:41`, `parser_base.py:289`, `parser_segundo_grau.py:33` e `scripts/spike_seletores.py:145` | Nenhum: as seis formas são equivalentes | Uma mudança de regra precisa ser replicada em seis lugares, e o esquecimento não quebra nada visivelmente |
| Cálculo do DV do CNJ | `NumeroProcesso.dv_esperado` (`numero_processo.py:85`) e `_dv_ok` (`vinculo.py:39`) | Nenhum: mesma fórmula ISO 7064 MOD 97-10, escrita duas vezes | É a regra mais delicada do projeto — um erro numa cópia só se manifesta em números que a outra aceitaria |
| Máscara de regex CNJ | `_MASCARA_CNJ` idêntico em `page_state.py:24` e `parser_segundo_grau.py:20`; o mesmo padrão embutido em `_PADRAO_PAI_MOV` (`vinculo.py:29`) | Nenhum | Ajustar a máscara exige três edições; a terceira está escondida dentro de outro padrão |
| Formatação da máscara CNJ | `NumeroProcesso.mascara` (`numero_processo.py:109`) e `projecao._mascara` (`projecao.py:29`) | Nenhum | A da projeção opera sobre string de 20 dígitos e não passa pelo value object — divergências de formatação não seriam detectadas por nada |
| `_norm` (minúsculas, sem acento, espaços colapsados) | Idêntico em `page_state.py:27` e `parser_base.py:28`; `limpeza._chave_dedup` faz quase o mesmo com `casefold()` no lugar de `lower()` | Nenhum | Comparações precisam concordar entre módulos para casar; a variante com `casefold()` já é uma terceira semântica |

**Origem:** [`page_state`](src/scrapers/page_state.md), [`parser_base`](src/scrapers/parser_base.md),
[`parser_segundo_grau`](src/scrapers/parser_segundo_grau.md), [`numero_processo`](src/scrapers/numero_processo.md).

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
| A reprojeção de vínculo não reescreve `bruto["observacoes"]` | `SqliteStore.reprojetar_vinculos` atualiza três colunas; as observações foram anexadas ao bruto pelo `menu` na coleta | Um registro antigo sai da base final com `relacionamento.tipo` novo e observação de vínculo velha | Mensagem reescrita ou observação nova não alcança o já coletado. A divergência é silenciosa: os dois campos são plausíveis lado a lado |

**Origem:** [`parser_base`](src/scrapers/parser_base.md), [`page_state`](src/scrapers/page_state.md),
[`status`](src/status.md), [`sqlite_store`](src/store/sqlite_store.md),
[`vinculo`](src/transformers/vinculo.md), [`projecao`](src/transformers/projecao.md).

## 3. Seletores e premissas sobre o HTML do portal

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| Fallback `_PADRAO_SECAO_1A` do `cposg` sem confirmação | `parser_segundo_grau.py` | **Reduzido em 2026-08-11.** `scripts/checar_offline.py` mostra `juiz` e `processo_1a_instancia` preenchidos nas duas capas reais de 2º grau de `data/spike/` — `#relatorProcesso` e `#numeroProcessoPrimeiraInstancia` funcionam. A saída não distingue qual caminho produziu o número | Se o atalho por `id` sair da página, o fallback assume sem nunca ter sido exercitado. `completude` não cobre o campo, então `processo_1a_instancia: null` sistemático não dispara nada |
| Só o primeiro número de 1ª instância é capturado | `_varrer_secao_1a_instancia` devolve na primeira célula com número; `_cnj_de_texto` usa `search()` | Um recurso com mais de um processo de origem registra só um vínculo | A seção chama-se "Números", no plural — os demais são perdidos sem observação |
| Texto original da célula descartado quando o CNJ é extraído | `parser_segundo_grau.py:44` | Foro, vara e juiz de origem, que estão na mesma célula, ficam fora do dict | Assimetria frente à filosofia declarada em `parser_base` (guardar o bruto, projetar depois) |
| `_FRASES_NAO_ENCONTRADO` é lista fechada de três frases | `page_state.py:64` | Correto para as três redações conhecidas | Se o e-SAJ mudar o texto, todo processo inexistente vira `DESCONHECIDO` → `erro_transitorio` → `erro_persistente`. A base não fica errada; a fila de falhas cresce sem explicação óbvia |
| `SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO` são listas fechadas | `parser_base.py:75` e `:78` | Dois seletores de situação confirmados no spike; `.unj-badge` e `.tag` nunca observados | Selo ou rótulo **novo** produz campo vazio, não erro — e campo vazio não dispara nenhuma bandeira de `completude` |

**Origem:** [`parser_segundo_grau`](src/scrapers/parser_segundo_grau.md),
[`page_state`](src/scrapers/page_state.md), [`parser_base`](src/scrapers/parser_base.md).

## 4. Pontos cegos operacionais

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| Captcha é ponto cego do circuit breaker | `esaj_client.py` | Não há tratamento. Páginas de verificação caem em `DESCONHECIDO` → `erro_transitorio` | O breaker **não** dispara: do ponto de vista HTTP as requisições estão sendo bem-sucedidas. A fila inteira consumiria tentativas até o teto sem sinal de que a causa é única |
| Bloqueio, captcha, manutenção e layout novo são indistinguíveis | `EstadoPagina.DESCONHECIDO` | Os quatro produzem o mesmo `erro_transitorio` com o motivo `"página não reconhecida"` | Diagnosticar exige olhar o HTML salvo por `scripts/spike_seletores.py` |
| `motivo` é string livre, sem código estruturado | `ResultadoColeta.motivo` → `ultimo_erro` (truncado em 500 caracteres) | Agrupar falhas por causa exige *parsing* de string | Métricas de qualidade da coleta não são obteníveis em SQL |
| `Pacer` não é persistente | `esaj_client.py:66` | Reiniciar zera `_proximo`; a primeira requisição sai imediatamente | Em retomadas frequentes, o intervalo entre a última requisição da execução anterior e a primeira da nova não é respeitado |
| `Session` mantém cookies e nunca é reciclada | `esaj_client.py:155` | É o que faz a navegação seleção → detalhe funcionar | Um cliente marcado pelo portal continua marcado até o fim da execução |
| Sem limite de tempo ou volume por execução | `EsajClient` | O circuito abre por falhas consecutivas, não por "requisições demais nesta sessão" | Nada limita o total de uma execução longa |
| A reprojeção de vínculo varre a base inteira a cada opção 4 | `SqliteStore.reprojetar_vinculos`, em lotes de 500 | Toda opção 4 lê e desserializa todos os `bruto` gravados, mesmo quando nada muda | Numa base de centenas de milhares de registros é o custo dominante do export local |
| A primeira reprojeção altera registros de erro já publicados | `reprojetar_vinculos` não filtra por status; linhas de erro têm `bruto` nulo | `tipo_vinculo` desses registros passa de `NULL` a `indefinido`; em `erro_persistente`, que é exportável, o `relacionamento.tipo` da base final deixa de ser `null` | É coerente com o critério, mas muda valor em base já entregue, sem que nada no JSONL registre a mudança |

**Origem:** [`esaj_client`](src/scrapers/esaj_client.md), [`coletor`](src/scrapers/coletor.md),
[`page_state`](src/scrapers/page_state.md), [`vinculo`](src/transformers/vinculo.md),
[`exportador`](src/aggregators/exportador.md).

## 5. Operação dos scripts

Nenhum impede a operação hoje; todos são armadilhas para quem for estender ou reutilizar.

| Item | Onde | Efeito hoje | Risco |
|---|---|---|---|
| Metade das funções depende de globais preenchidos por efeito colateral | `ENTRADA`, `SAIDA`, `JSONL`, `ORFAOS`, `FALHAS`, `REVISAO`, `INVALIDOS`, `BANCO` nascem `None` e são definidos por `configurar_projeto()` (`menu.py:55`) | Nenhum: `main()` sempre configura antes de qualquer opção | `atualizar_arquivos_de_falha`, `escrever_relatorio` e `_mostrar` recebem `store` por parâmetro mas leem caminhos de globais — não são reutilizáveis fora do fluxo do menu. A falha seria `AttributeError` em `None.name`, longe da causa |
| A opção 2 reclassifica a origem dos órfãos como `lista` | `executar_coleta(..., ORIGEM_LISTA, "Recoletando")` (`menu.py:287`) | Um órfão que falhou na opção 3 e foi recoletado pela 2 entra numa linha nova com `origem = "lista"` | A coluna existe para separar "a base que pedi" da "base que descobri"; a distinção se perde na recoleta |
| A opção 3 descarta os números inválidos sem registrar | `numeros, _ = ler_numeros(ORFAOS)` (`menu.py:318`) | A opção 1 grava os rejeitados em `numeros_invalidos.txt`; aqui o segundo retorno é ignorado | Como `vinculo._dv_ok` já filtra o DV, o caso restante é um pai **fora do TJSP**: sumiria da fila sem aparecer em lugar nenhum e voltaria a ser listado como órfão em toda opção 4 |
| A docstring do `menu` descreve a opção 4 sem mencionar a reprojeção | Cabeçalho de `menu.py` diz só *"transforma os dados coletados na estrutura JSON final (local, sem rede)"* | A docstring de `opcao_4` já registra os três passos | Quem ler só o topo do arquivo não descobre que a opção 4 **escreve no banco** |
| Duas docstrings do `spike` descrevem invocações diferentes | Cabeçalho de `spike_seletores.py` documenta `# lê data/entrada/processos.txt`; a de `main()` já descreve o nome de projeto | O padrão sem argumento é `processos`, que não existe no repositório (a entrada versionada é `teste1.txt`) | Benigno — a mensagem de arquivo não encontrado orienta —, mas o arquivo diz duas coisas sobre si mesmo |
| Nome de projeto com 20 dígitos vira número de processo | `numeros = [a for a in argumentos if len(re.sub(r"\D", "", a)) == 20]` (`spike_seletores.py:145`) | Nenhum com os nomes em uso | Um projeto como `coleta_20240101_20241231_v2` cairia na lista de números e seria consultado no e-SAJ |

**Origem:** [`menu`](scripts/menu.md), [`spike_seletores`](scripts/spike_seletores.md).

## 6. Ausência de testes

Não há suíte automatizada no repositório. O obstáculo não é técnico: `page_state`,
`parser_base` e `coletor` são funções puras sobre string, e `scripts/spike_seletores.py`
**já produz os fixtures** — os arquivos `data/spike/<numero>_g<grau>.html` são HTML real.

O que existe é `scripts/checar_offline.py`, que reprocessa esses HTMLs sem nenhuma
requisição e imprime o resultado para leitura humana. **Não é teste:** sem asserção, sem
runner, sem veredito passa/falha.

As 91 invariantes que valeria fixar, com a ordem sugerida, estão em
[backlog de testes](backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação: consolidação dos pontos em aberto de `src/status.py` e `src/scrapers/` |
| 2026-08-11 | @alexandrehiero | Cobertura estendida a `store`, `transformers` e `aggregators`; 13 itens encerrados |
| 2026-08-11 | @alexandrehiero | Mais 6 itens encerrados; 3 itens novos, todos consequências da reprojeção |
| 2026-08-11 | @alexandrehiero | Cobertura estendida a `scripts/`: nova §5 (6 itens); "Ausência de testes" passou a §6 |
| 2026-09-04 | @alexandrehiero | Divisão em três páginas: invariantes de teste e itens encerrados ganharam página própria; §6 virou ponteiro |
