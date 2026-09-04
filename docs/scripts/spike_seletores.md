# Spike de seletores – `scripts/spike_seletores.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `beautifulsoup4`, e os módulos de `src/scrapers/` |

## Contexto e Motivação

Um scraper depende de suposições sobre HTML que ninguém controla. Vários seletores deste projeto nasceram da inspeção visual das telas, e o próprio código registra quais ainda não foram confirmados — a advertência de [`parser_segundo_grau`](../src/scrapers/parser_segundo_grau.md) é explícita: *"Confirmar num agravo real antes da coleta em massa."*

Descobrir que um seletor está errado **durante** uma coleta de semanas é caro de duas maneiras: gasta requisições contra um portal público e produz registros que precisarão ser refeitos. Este script antecipa a descoberta.

As três características do enunciado são decisões, não conveniências: **não grava no banco** (pode rodar sobre um projeto em produção sem contaminá-lo), **consulta os dois graus** (o oposto do que a coleta faz, de propósito) e **salva o HTML** — que é o que transforma um diagnóstico pontual em fixture reutilizável.

## Decisões de Pipeline

- **Consulta sempre os dois graus, ao contrário da coleta** — o [`coletor`](../src/scrapers/coletor.md) para no primeiro grau que responde; essa é a regra central do projeto. Aqui a lógica é deliberadamente invertida: o objetivo não é decidir onde o processo está, e sim comparar como as duas instâncias respondem ao mesmo número — a informação que a coleta descarta por construção. Diagnosticar o parser de 2º grau exige ver a capa de 2º grau, mesmo quando o processo também existe no 1º. O custo é assumido: dois slots do `Pacer` por número.
- **O roteamento grau → parser é importado, não redeclarado** — um spike que exercita um caminho **parecido** com o de produção não serve para nada: o valor do diagnóstico depende de ser o mesmo código. Uma cópia local poderia divergir sem que nada acusasse, e o relatório passaria a descrever um pipeline que não existe.
- **Não grava no banco** — nenhum `SqliteStore` é importado. Pode rodar a qualquer momento, inclusive durante uma coleta em andamento. A única escrita é o HTML em `data/spike/`.
- **O HTML salvo é o subproduto mais valioso** — o nome do arquivo codifica número e grau, tornando o diretório um conjunto de casos nomeados. Como `page_state` e os parsers são funções puras sobre string, esses arquivos são **fixtures prontas**: um teste do classificador não precisa de rede, precisa de `data/spike/*.html`.
- **Cada relatório é escrito para uma pergunta em aberto** — os relatórios de situação e de distribuição não imprimem "o que o parser extraiu", e sim **por que** ele extraiu ou deixou de extrair. Quando nenhum seletor responde, o script procura o texto no documento e mostra em qual elemento ele está. É a diferença entre saber que há um problema e saber como corrigi-lo.
- **As listas auditadas são importadas do parser, não copiadas** — `SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO` vêm de `parser_base` para que o relatório descreva a lista que a coleta realmente usa.
- **O relatório de seleção mostra a decisão, não só os dados** — além de listar os rádios encontrados, imprime **qual** o resolvedor escolheu, se o número foi conferido e por qual critério. É o caminho que o pipeline anterior errava em silêncio.
- **`except Exception` amplo, aqui, é correto** — o [`esaj_client`](../src/scrapers/esaj_client.md) restringe o dele justamente para que bugs não virem falha de rede disfarçada. Aqui a escolha oposta é a certa: um `AttributeError` num número não pode impedir os demais de serem diagnosticados. O erro é impresso com `!r`, preservando o tipo — não é engolido, é relatado. **A diferença é o propósito, não o estilo.**

## Como Executar

```bash
uv run python scripts/spike_seletores.py 0000001-58.2013.8.26.0477   # números específicos
uv run python scripts/spike_seletores.py teste1                      # a lista de um projeto
uv run python scripts/spike_seletores.py teste1 > data/spike/relatorio.txt
```

Os argumentos são separados **por forma, não por posição**: qualquer argumento com exatamente 20 dígitos é tratado como número de processo; o resto é nome de projeto. Isso permite misturar as duas formas sem flags.

## Principais Parâmetros (constantes no código)

| Constante | Valor | Descrição |
|-----------|-------|-------------|
| `DIR_ENTRADA` | `data/entrada` | Listas por projeto — a mesma pasta usada pelo [`menu`](menu.md) |
| `SAIDA_HTML` | `data/spike` | HTMLs salvos como `<20 dígitos>_g<grau>.html`. Ignorado pelo Git |
| `PARSER_POR_GRAU` | importado de `src.scrapers.coletor` | Roteamento grau → parser, compartilhado com a coleta real |
| `SELETORES_SITUACAO` | importado de `src.scrapers.parser_base` | Lista auditada pelo relatório de situação |
| `ROTULOS_DISTRIBUICAO` | importado de `src.scrapers.parser_base` | Rótulos auditados pelo relatório de distribuição |

O `EsajClient` é criado sem argumentos, portanto com os padrões: cadência de 1,7–2,5 s, 3 tentativas e circuito em 20 falhas consecutivas. Como o spike é monothread, ele monta o próprio `Pacer` e o próprio `MonitorFalhas`.

## Logs e Monitoramento

Usa `print()` direto — não há barra de progresso, e portanto nenhuma razão para `tqdm.write`. **A saída é o produto**: cada bloco é um relatório legível, delimitado por uma régua e pelo número do processo. Os prefixos entre colchetes marcam a seção, seguindo o espírito do [guia de logging](../guias/logging_padrao.md): `[identidade]`, `[situacao]`, `[data_distribuicao]`, `[seleção]`, `[parse]`.

O fechamento imprime `client.estatisticas()`, o que permite conferir requisições e falhas contra o número de processos diagnosticados. Não há arquivo de log: para preservar um diagnóstico, redirecione a saída — os HTMLs, esses, ficam salvos automaticamente.

## Falhas Conhecidas e Workarounds

- **O arquivo do projeto não existe.** Mensagem explícita com o caminho procurado, em vez de exceção.
- **Um número da lista tem formato inválido.** `NumeroProcesso.tentar` devolve `None`, o script relata e segue. Note que o spike **não** valida DV nem tribunal, ao contrário do menu — ele diagnostica o que for pedido.
- **Erro inesperado num número.** Capturado e impresso com o tipo preservado; os demais continuam.
- **Processo sigiloso ou inexistente no grau consultado.** Imprime só o estado; não há capa a diagnosticar.
- **O e-SAJ está fora do ar.** `EsajError` é capturada por grau e o script segue. Se o circuito abrir, `EsajIndisponivelError` **não** é `EsajError` e cai no `except Exception` do laço principal, encerrando o diagnóstico daquele número.
- **O projeto padrão é `processos`, que não existe no repositório** (a entrada versionada é `teste1.txt`), e a docstring do módulo ainda documenta a forma antiga enquanto a de `main()` descreve a nova. Benigno, mas o arquivo diz duas coisas sobre si mesmo. Ver [backlog §5](../backlog.md).
- **Um nome de projeto com 20 dígitos seria lido como número.** `coleta_20240101_20241231_v2` cairia na lista de números. Improvável e visível na hora, mas a heurística não tem escape explícito. Ver [backlog §5](../backlog.md).

## Decisões Futuras

- [ ] Exercitar o fallback `_PADRAO_SECAO_1A` do `cposg` — as capas reais confirmaram o atalho por `id`, mas a varredura de seção pode nunca ter rodado.
- [ ] Converter os HTMLs de `data/spike/` em fixtures versionadas para uma suíte de `page_state` e dos parsers.
- [ ] Modo que leia HTML já salvo em vez de consultar a rede, permitindo reexecutar o diagnóstico após mudar um seletor sem gastar requisição.
- [ ] Relatório em JSON além do texto, para comparar duas execuções e detectar regressão de seletor.

## Relação com Outros Artefatos

| Módulo | Usado para |
|---|---|
| [`coletor`](../src/scrapers/coletor.md) | `PARSER_POR_GRAU` — o mesmo roteamento da coleta real |
| [`esaj_client`](../src/scrapers/esaj_client.md) | `EsajClient` com padrões; `estatisticas()` no fechamento |
| [`exceptions`](../src/scrapers/exceptions.md) | `EsajError` capturada por grau |
| [`numero_processo`](../src/scrapers/numero_processo.md) | `tentar`, e o relatório de `origem`/`dv_valido`/`graus_a_tentar` |
| [`page_state`](../src/scrapers/page_state.md) | `ClassificadorPagina`, `escolher_na_selecao`, `verificar_identidade` |
| [`parser_base`](../src/scrapers/parser_base.md) | `SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO`, auditados nos relatórios |

Não importa nada de `store/`, `transformers/` nem `aggregators/` — o spike para onde a coleta começaria a persistir. Compartilha com o [`menu`](menu.md) a convenção de projeto, mas nenhum estado.

**O spike não exercita `coletar_um`.** As peças da camada de scraping são diagnosticadas isoladamente, mas a máquina de estados que as encadeia continua sem cobertura de nenhuma espécie. É o item de maior risco no [backlog de testes](../backlog_testes.md), e o spike, apesar de ser a ferramenta mais próxima, deliberadamente não o cobre.

## Lições Aprendidas

- **Importar o roteamento em vez de recriá-lo é o que dá validade ao diagnóstico.** Um spike que exercita um caminho parecido com o de produção informa sobre um pipeline que não existe.
- **Salvar o HTML transformou uma ferramenta descartável em ativo permanente.** Os arquivos de `data/spike/` são a base de qualquer suíte futura, obtidos de graça como subproduto.
- **Relatar o motivo da ausência vale mais que relatar a ausência.** Mostrar em que elemento o texto "Extinto" aparece é o que permite corrigir a lista; um `None` só informa que há um problema.
- **Uma ferramenta de diagnóstico tem regras diferentes das de produção.**
- **Consultar os dois graus, contrariando a regra central, é o que torna o spike útil.** A informação que a coleta descarta por segurança é exatamente a que o diagnóstico precisa.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-11 | @alexandrehiero | Criação |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 8 decisões virou lista de tópicos; código copiado removido; "Pontos em aberto" migrou para o backlog |
