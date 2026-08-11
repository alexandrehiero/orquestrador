# Spike de seletores – `scripts/spike_seletores.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-11                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `beautifulsoup4`, e os módulos de `src/scrapers/` |

## Contexto e Motivação

Um scraper depende de suposições sobre HTML que ninguém controla. Vários seletores deste
projeto foram escritos a partir da inspeção visual das telas do e-SAJ, e o próprio código
registra quais ainda não foram confirmados contra HTML real — a advertência no topo de
[`parser_segundo_grau`](../src/scrapers/parser_segundo_grau.md) é explícita:
*"Confirmar num agravo real antes da coleta em massa."*

Descobrir que um seletor está errado **durante** uma coleta de semanas é caro de duas
maneiras: gasta requisições contra um portal público e produz registros que precisarão ser
refeitos. Este script existe para antecipar essa descoberta.

> Spike de seletores — diagnóstico ANTES da coleta em massa.
>
> Não grava nada no banco. Para cada número, consulta os dois graus, salva o HTML
> e reporta o que cada seletor pendente devolve.

As três características do enunciado são decisões, não conveniências: **não grava no
banco** (pode rodar sobre um projeto em produção sem contaminá-lo), **consulta os dois
graus** (o oposto do que a coleta faz, de propósito) e **salva o HTML** — que é o que
transforma um diagnóstico pontual em fixture reutilizável.

## Decisões de Pipeline

### O spike consulta sempre os dois graus — ao contrário da coleta

```python
for grau in (1, 2):  # o spike consulta SEMPRE os dois, para comparar
```

O [`coletor`](../src/scrapers/coletor.md) percorre `np.graus_a_tentar` e **para** no primeiro
grau que responde: encontrou em `cpopg`, não olha `cposg`. É a regra central do projeto.

Aqui a lógica é deliberadamente invertida. O objetivo não é decidir onde o processo está, e
sim comparar como as duas instâncias respondem ao mesmo número — que é justamente a
informação que a coleta descarta por construção. Diagnosticar o parser de 2º grau exige ver
a capa de 2º grau, mesmo quando o processo também existe no 1º.

O custo é assumido: dois slots do `Pacer` por número, contra um da coleta no caso feliz.

### O roteamento grau → parser é importado, não redeclarado

```python
from src.scrapers.coletor import PARSER_POR_GRAU
```

```python
# O roteamento grau -> parser vem do coletor. Um dicionário próprio aqui podia
# divergir do usado na coleta real, e o spike deixaria de diagnosticar
# exatamente o caminho que a coleta percorre — que é a razão de ele existir.
```

Um spike que exercita um caminho **parecido** com o da produção não serve para nada: o
valor do diagnóstico depende de ser o mesmo código. Uma cópia local do dicionário poderia
divergir sem que nada acusasse, e o relatório passaria a descrever um pipeline que não
existe.

### Não grava no banco

Nenhum `SqliteStore` é importado. O script pode ser rodado a qualquer momento, sobre
qualquer número, inclusive durante uma coleta em andamento, sem risco de alterar estado. A
única escrita é o HTML em `data/spike/`, que está no `.gitignore`.

Isso também significa que o spike **não** exercita `coletar_um` — a máquina de estados
completa, com decisão de grau, verificação de identidade e reprovação de capa suspeita,
continua sem cobertura. Ele exercita as peças, não a montagem.

### O HTML salvo é o subproduto mais valioso

```python
destino = SAIDA_HTML / f"{np.digitos}_g{grau}.html"
destino.write_text(html, encoding="utf-8")
print(f"  html salvo: {destino.name} ({len(html)} bytes)")
```

O nome do arquivo codifica número e grau, o que torna o diretório um conjunto de casos
nomeados. Como [`page_state`](../src/scrapers/page_state.md) e os
[parsers](../src/scrapers/parser_base.md) são funções puras sobre string, esses arquivos são
fixtures prontas: um teste automatizado do classificador não precisa de rede, precisa de
`data/spike/*.html`. É a observação registrada em várias páginas de `src/` e no
[backlog](../backlog.md#6-ausencia-de-testes).

### Cada relatório é escrito para uma pergunta em aberto

`_relatar_situacao` e `_relatar_distribuicao` não imprimem "o que o parser extraiu" — elas
imprimem **por que** ele extraiu ou deixou de extrair. Quando nenhum seletor candidato
responde, o script procura o texto no documento e mostra onde ele está:

```python
if not achou:
    print("    NENHUM seletor candidato retornou valor.")
    for el in soup.find_all(string=re.compile(r"Extinto|Em andamento|Arquivado", re.I))[:3]:
        pai = el.parent
        print(f"    (texto) <{pai.name} class={pai.get('class')} id={pai.get('id')}> {el.strip()[:60]}")
```

Isto é o que transforma "o campo veio vazio" em "o valor está num `<span class=...>` que
não está na lista" — a diferença entre saber que há um problema e saber como corrigi-lo.
`SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO` são importados do parser, e não copiados, para
que o relatório descreva a lista que a coleta realmente usa.

### O relatório de seleção mostra a decisão, não só os dados

```python
escolha = escolher_na_selecao(html, np)
print(f"    ESCOLHA -> destino={escolha.destino!r} verificada={escolha.verificada}")
print(f"               motivo={escolha.motivo}")
```

Além de listar os rádios encontrados, o spike imprime **qual** o resolvedor escolheu, se o
número foi conferido e por qual critério. É o caminho que o pipeline anterior errava em
silêncio — ver [`page_state`](../src/scrapers/page_state.md).

### `except Exception` amplo, aqui, é correto

```python
for numero in numeros:
    try:
        diagnosticar(numero, client)
    except Exception as erro:
        print(f"  ERRO inesperado em {numero}: {erro!r}")
```

O [`esaj_client`](../src/scrapers/esaj_client.md) restringe seu `except` a erros de rede
justamente para que bugs não virem falha de rede disfarçada. Aqui a escolha oposta é a
certa: o spike é uma ferramenta de diagnóstico rodada sobre poucos números, e um
`AttributeError` num deles não pode impedir os demais de serem diagnosticados. O erro é
impresso com `!r`, preservando o tipo — não é engolido, é relatado.

## Como Executar

```bash
# Diagnosticar números específicos
uv run python scripts/spike_seletores.py 0000001-58.2013.8.26.0477

# Diagnosticar a lista de um projeto (data/entrada/<projeto>.txt)
uv run python scripts/spike_seletores.py teste1

# Sem argumento: procura data/entrada/processos.txt
uv run python scripts/spike_seletores.py
```

Os argumentos são separados por forma, não por posição:

```python
argumentos = sys.argv[1:]
numeros = [a for a in argumentos if len(re.sub(r"\D", "", a)) == 20]
projetos = [a for a in argumentos if a not in numeros]
```

Qualquer argumento com exatamente 20 dígitos é tratado como número de processo; o resto é
nome de projeto. Isso permite misturar as duas formas sem flags.

A saída é longa e feita para ser lida no terminal ou redirecionada:

```bash
uv run python scripts/spike_seletores.py teste1 > data/spike/relatorio.txt
```

## Principais Parâmetros (constantes no código)

| Constante | Valor | Descrição |
|-----------|-------|-------------|
| `RAIZ` | `Path(__file__).resolve().parents[1]` | Raiz do repositório; inserida em `sys.path` para os imports de `src/` |
| `DIR_ENTRADA` | `RAIZ / "data" / "entrada"` | Onde ficam as listas por projeto — a mesma pasta usada pelo [`menu`](menu.md) |
| `SAIDA_HTML` | `RAIZ / "data" / "spike"` | HTMLs salvos, no formato `<20 dígitos>_g<grau>.html`. Ignorado pelo Git |
| `PARSER_POR_GRAU` | importado de `src.scrapers.coletor` | Roteamento grau → parser, compartilhado com a coleta real |
| `SELETORES_SITUACAO` | importado de `src.scrapers.parser_base` | Lista auditada pelo relatório de situação |
| `ROTULOS_DISTRIBUICAO` | importado de `src.scrapers.parser_base` | Rótulos auditados pelo relatório de distribuição |

O `EsajClient` é criado sem argumentos (`EsajClient()`), portanto com os padrões: cadência
de 1,7–2,5s, 3 tentativas e circuito em 20 falhas consecutivas. Como o spike é
monothread, ele monta o próprio `Pacer` e o próprio `MonitorFalhas`.

## Logs e Monitoramento

O script usa `print()` direto — não há barra de progresso, e portanto nenhuma razão para
`tqdm.write`. A saída **é** o produto: cada bloco é um relatório legível, delimitado por uma
régua e pelo número do processo.

Os prefixos entre colchetes marcam a seção do diagnóstico, seguindo o espírito da convenção
do [guia de logging](../guias/logging_padrao.md): `[identidade]`, `[situacao]`,
`[data_distribuicao]`, `[seleção]`, `[parse]`.

O fechamento imprime as métricas do cliente, que permitem conferir requisições e falhas
contra o número de processos diagnosticados:

```python
print(f"\nHTMLs salvos em: {SAIDA_HTML}")
print(f"Estatísticas do cliente: {client.estatisticas()}")
```

Não há arquivo de log. Para preservar um diagnóstico, redirecione a saída — os HTMLs, esses
sim, ficam salvos automaticamente.

## Falhas Conhecidas e Workarounds

- **Problema:** o arquivo do projeto não existe.
  **Workaround:** mensagem explícita com o caminho procurado, em vez de exceção:

  ```python
  if not entrada.exists():
      print(f"Arquivo não encontrado: {entrada}")
      print("Passe o nome do projeto ou os números na linha de comando.")
      return
  ```

- **Problema:** um número da lista tem formato inválido.
  **Workaround:** `NumeroProcesso.tentar` devolve `None`, o script relata e segue para o
  próximo. Note que o spike **não** valida DV nem tribunal, ao contrário do
  [`menu`](menu.md) — ele diagnostica o que for pedido.

- **Problema:** erro inesperado no diagnóstico de um número.
  **Workaround:** capturado e impresso com o tipo preservado; os demais números continuam.

- **Problema:** o processo está em segredo de justiça ou não existe no grau consultado.
  **Workaround:** nenhum — o script imprime só `estado: SENHA_SEGREDO` ou
  `estado: NAO_ENCONTRADO`. Não há relatório detalhado porque não há capa a diagnosticar.

- **Problema:** o e-SAJ está fora do ar.
  **Workaround:** `EsajError` é capturada por grau e o script segue. Se o circuito abrir,
  `EsajIndisponivelError` **não** é `EsajError` (ver
  [`exceptions`](../src/scrapers/exceptions.md)) e cai no `except Exception` do laço
  principal, encerrando o diagnóstico daquele número.

## Decisões Futuras

- [ ] Exercitar o fallback `_PADRAO_SECAO_1A` do `cposg` — as capas reais já confirmaram o
      atalho por `id`, mas a varredura de seção pode nunca ter rodado. Ver o
      [backlog](../backlog.md#3-seletores-e-premissas-sobre-o-html-do-portal).
- [ ] Converter os HTMLs de `data/spike/` em fixtures versionadas (anonimizadas, se
      necessário) para uma suíte de testes de `page_state` e dos parsers.
- [ ] Modo que leia HTML já salvo em vez de consultar a rede, permitindo reexecutar o
      diagnóstico após mudar um seletor sem gastar requisição.
- [ ] Relatório em formato estruturado (JSON) além do texto, para comparar duas execuções e
      detectar regressão de seletor.

## Relação com Outros Artefatos

| Módulo | Usado para |
|---|---|
| [`src/scrapers/coletor`](../src/scrapers/coletor.md) | `PARSER_POR_GRAU` — o mesmo roteamento da coleta real |
| [`src/scrapers/esaj_client`](../src/scrapers/esaj_client.md) | `EsajClient` com padrões; `estatisticas()` no fechamento |
| [`src/scrapers/exceptions`](../src/scrapers/exceptions.md) | `EsajError` capturada por grau |
| [`src/scrapers/numero_processo`](../src/scrapers/numero_processo.md) | `tentar`, e o relatório de `origem`/`dv_valido`/`graus_a_tentar` |
| [`src/scrapers/page_state`](../src/scrapers/page_state.md) | `ClassificadorPagina`, `escolher_na_selecao`, `verificar_identidade` |
| [`src/scrapers/parser_base`](../src/scrapers/parser_base.md) | `SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO`, auditados nos relatórios |

Não importa nada de `src/store/`, `src/transformers/` nem `src/aggregators/` — o spike para
onde a coleta começaria a persistir.

Compartilha com o [`menu`](menu.md) a convenção de projeto (`data/entrada/<nome>.txt`), mas
nenhum estado: rodar o spike não altera banco, filas nem arquivos de saída do projeto.

## Lições Aprendidas

- **Importar o roteamento em vez de recriá-lo é o que dá validade ao diagnóstico.** Um spike
  que exercita um caminho parecido com o de produção informa sobre um pipeline que não
  existe.

- **Salvar o HTML transformou uma ferramenta descartável em ativo permanente.** Os arquivos
  de `data/spike/` são a base de qualquer suíte de testes futura, e foram obtidos de graça
  como subproduto do diagnóstico.

- **Relatar o motivo da ausência vale mais que relatar a ausência.** Mostrar em que elemento
  o texto "Extinto" aparece é o que permite corrigir a lista de seletores; um `None` no
  campo `situacao` só informa que há um problema.

- **Uma ferramenta de diagnóstico tem regras diferentes das de produção.** O `except`
  amplo, que seria um defeito no cliente HTTP, é aqui o comportamento correto — e a
  diferença é o propósito, não o estilo.

- **Consultar os dois graus, contrariando a regra central, é o que torna o spike útil.** A
  informação que a coleta descarta por segurança é exatamente a que o diagnóstico precisa.

## Pontos em aberto

- **O projeto padrão é `processos`, que não existe no repositório.** Sem argumento algum, o
  script procura `data/entrada/processos.txt`:

  ```python
  nome = projetos[0] if projetos else "processos"
  ```

  A pasta de entrada versionada traz `teste1.txt`. O comportamento é benigno — a mensagem de
  arquivo não encontrado explica o que fazer —, mas o padrão não corresponde a nenhum
  projeto real, e a docstring do módulo ainda documenta a forma antiga:

  ```
      python scripts/spike_seletores.py                       # lê data/entrada/processos.txt
  ```

  enquanto a docstring de `main()` já descreve a forma nova, com nome de projeto. As duas
  convivem no mesmo arquivo, dizendo coisas diferentes.

- **Um nome de projeto com 20 dígitos seria lido como número de processo.** A separação de
  argumentos é por forma:

  ```python
  numeros = [a for a in argumentos if len(re.sub(r"\D", "", a)) == 20]
  ```

  Um projeto chamado, por exemplo, `coleta_20240101_20241231_v2` tem exatamente 20 dígitos
  depois de remover os não-dígitos e cairia na lista de números — o spike tentaria
  consultá-lo no e-SAJ. É improvável e o efeito é visível na hora (o número não seria
  encontrado), mas a heurística não tem escape explícito.

- **O spike não exercita `coletar_um`.** Todas as peças da camada de scraping são
  diagnosticadas isoladamente, mas a máquina de estados que as encadeia — decisão de grau,
  reprovação por identidade divergente, `_capa_suspeita` — continua sem cobertura de
  nenhuma espécie. É o item de maior risco na lista de testes ausentes, e o spike, apesar de
  ser a ferramenta mais próxima, deliberadamente não o cobre.
