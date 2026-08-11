# Estado da página e invariante de identidade – `src/scrapers/page_state.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `beautifulsoup4`, `re`, `unicodedata` (biblioteca padrão) |

## Contexto e Motivação

O [`EsajClient`](esaj_client.md) devolve HTML e nada mais — o e-SAJ responde HTTP 200 para
"encontrei", "não existe" e "é sigiloso" indistintamente. Alguém precisa converter texto
em significado, e é este módulo.

Mas ele carrega uma responsabilidade maior que classificar páginas. A docstring abre com
as duas funções que o distinguem do pipeline anterior:

> `verificar_identidade`: confere se a página ABERTA é a do processo PEDIDO.
> Sem isso, abrir a página errada grava os dados de um processo sob o número de
> outro — e nada no pipeline detecta.

Vale insistir nesse "nada no pipeline detecta". Um erro de rede aparece no log. Um seletor
quebrado produz campos vazios. Já entrar no processo errado gera um registro **perfeito**:
classe preenchida, partes preenchidas, movimentações preenchidas — tudo válido, tudo do
processo errado, arquivado sob o número que você pediu. O relacionamento é montado em
cima disso. Numa base de centenas de milhares de linhas, esse erro é invisível por
construção, e é o que este módulo existe para tornar impossível.

## Decisões de Arquitetura

### Cinco estados explícitos, incluindo `DESCONHECIDO`

```python
class EstadoPagina:
    DADOS_CAPA = "DADOS_CAPA"
    LISTA_SELECAO = "LISTA_SELECAO"
    SENHA_SEGREDO = "SENHA_SEGREDO"
    NAO_ENCONTRADO = "NAO_ENCONTRADO"
    DESCONHECIDO = "DESCONHECIDO"
```

`DESCONHECIDO` não é um descuido de exaustividade — é o estado que dá ao orquestrador a
opção de **não gravar**. A docstring:

> Cada estado é explícito, e DESCONHECIDO existe para o orquestrador mandar o caso
> para recoleta em vez de gravar lixo silenciosamente.

A alternativa comum — tratar "não reconheci" como "capa vazia" e seguir — grava um
registro sem dados como se fosse resultado legítimo. Layout novo, manutenção do portal,
bloqueio e captcha caem todos aqui e voltam para a fila.

### A ordem da classificação é parte da lógica

```python
def classificar(self):
    # Ordem importa: 'não encontrado' e 'seleção' primeiro; segredo só vale se
    # NÃO houver dados de capa; capa por último.
    if self._e_nao_encontrado():
        return EstadoPagina.NAO_ENCONTRADO
    if self._e_selecao():
        return EstadoPagina.LISTA_SELECAO
    if self._e_segredo():
        return EstadoPagina.SENHA_SEGREDO
    if self._e_capa():
        return EstadoPagina.DADOS_CAPA
    return EstadoPagina.DESCONHECIDO
```

Os testes não são mutuamente exclusivos: uma página do e-SAJ pode satisfazer mais de um
ao mesmo tempo. A ordem é que resolve os empates, e cada posição tem razão de ser.

### `_e_segredo` exige a senha **e** a ausência de capa

```python
def _e_segredo(self):
    # Bloqueio real = pede a "senha do processo" E não há dados de capa. NÃO
    # usar input[type=password]: o formulário 'Identificar-se' existe em TODA
    # página e marcaria todo mundo como segredo.
    return "senha do processo" in self._texto and not self._tem_dados_capa()
```

O detector óbvio — procurar um campo de senha no HTML — classificaria **toda** página do
portal como sigilosa, porque o formulário de login está em todas elas. E a conjunção com
`not self._tem_dados_capa()` cobre o caso em que a capa é exibida normalmente e o aviso de
senha se refere a algum documento específico dentro dela.

### Detector e resolvedor olham para os **mesmos** seletores

As duas funções que lidam com a tela de seleção — `_e_selecao`, que a reconhece, e
`escolher_na_selecao`, que decide o que abrir nela — leem de constantes compartilhadas:

```python
# Detector (_e_selecao) e resolvedor (escolher_na_selecao) usam ESTA lista.
# Antes o detector conhecia só `a.linkProcesso` e o resolvedor tinha um fallback
# a mais: uma página que só tivesse o segundo seletor jamais chegaria ao
# resolvedor — o fallback era inalcançável.
_SELETORES_LINK_SELECAO = ("a.linkProcesso", 'a[href*="processo.codigo="]')
_SELETOR_RADIO_SELECAO = 'input[type="radio"][name="processoSelecionado"]'
```

A assimetria que isso corrige tinha uma consequência precisa. O detector só reconhecia
`a.linkProcesso`; o resolvedor conhecia também `a[href*="processo.codigo="]`, como rede de
segurança. Mas o resolvedor **só é chamado depois** de o detector classificar a página como
`LISTA_SELECAO`. Uma página de seleção que usasse apenas a segunda forma, sem rádios e sem o
texto "selecione o processo", jamais chegava ao resolvedor — o fallback era código morto por
construção, e a página caía em `DESCONHECIDO`.

O erro de fundo é o de dois lugares diferentes responderem "o que é um link de seleção?" com
listas diferentes. Extrair a lista para uma constante única não é organização de código: é
o que garante que o que o detector reconhece seja exatamente o que o resolvedor sabe tratar.

O mesmo vale para o rádio. `_SELETOR_RADIO_SELECAO` é consultado por `_e_selecao` para
detectar e por `escolher_na_selecao` para percorrer as opções — uma string, dois usos.

### `escolher_na_selecao` tenta os dois seletores, não o primeiro que responder

```python
links = []
for seletor in _SELETORES_LINK_SELECAO:
    links.extend(soup.select(seletor))
for a in links:
    if alvo in cnjs_no_texto(a.get_text(" ", strip=True)) and a.get("href"):
```

A forma anterior era `soup.select(A) or soup.select(B)`, e o `or` embutia uma suposição
falsa: que a presença de `a.linkProcesso` na página significa que o número procurado está
**em algum deles**. São perguntas diferentes. Se a página trouxesse links `a.linkProcesso`
sem que nenhum casasse com o número pedido, `select(A)` devolveria uma lista não vazia, o
`or` daria curto-circuito, e `a[href*="processo.codigo="]` nunca seria consultado — mesmo
que o link certo estivesse justamente ali.

A degradação resultante era silenciosa e do tipo pior: em vez de achar o link exato
(`verificada=True`), a função caía no passo 3 e devolvia o **primeiro rádio** como palpite.
Concatenar as duas listas troca "pare no primeiro seletor que der resultado" por "considere
todos os candidatos", que é o que a pergunta pede. A ordem dos seletores continua sendo a
ordem de preferência, porque o laço percorre a lista concatenada na ordem em que foi montada.

### `_e_selecao` recua diante de uma capa

```python
def _e_selecao(self):
    # Guarda: se há tabela de partes/movimentações OU o número do processo
    # exibido isolado, isto é uma CAPA. A capa tem links para incidentes com
    # `processo.codigo=`, e sem esta guarda — agora que o detector conhece
    # esse seletor — uma capa legítima cairia no caminho do palpite.
    if self._tem_dados_capa() or self.soup.select_one("#numeroProcesso"):
        return False
```

Este é o tipo de bug que só aparece em produção. A capa de um processo com incidentes
exibe links para eles — links que se parecem exatamente com os de uma tela de seleção.
Sem a guarda, uma capa perfeitamente legítima seria tratada como lista de escolha, o
orquestrador escolheria um dos incidentes e gravaria os dados **do incidente** sob o
número do processo principal. A guarda inverte a prioridade: onde há tabela de partes ou
de movimentações, há capa.

A cláusula `#numeroProcesso` foi acrescentada junto com a unificação dos seletores, e é
consequência direta dela. Ao ensinar o detector a reconhecer `a[href*="processo.codigo="]`,
ampliou-se o que ele aceita como seleção — e os links de incidente na capa têm exatamente
essa forma. Uma capa que exibisse o número mas cujas tabelas ainda não estivessem
carregadas, ou cujos `id` de tabela mudassem, passaria a casar. A guarda acompanha a
ampliação: se a página exibe o número do processo isolado, ela é a página **daquele**
processo, não uma lista para escolher entre vários.

O critério é o mesmo de `_e_capa` (`#numeroProcesso` **ou** dados de capa), o que torna as
duas classificações mutuamente exclusivas por construção, e não por ordem de teste.

### As frases de "não encontrado" falham para o lado seguro

```python
# Só o e-SAJ afirmando explicitamente que não existe autoriza gravar 'sem_dados'
# e avançar de grau. Se a frase mudar, o caso vira DESCONHECIDO -> erro
# transitório: falha para o lado SEGURO (nunca vira "não existe" por engano).
_FRASES_NAO_ENCONTRADO = (
    "nao existem informacoes disponiveis",
    "nao foram encontrados resultados",
    "nao foi encontrado processo",
)
```

Esta lista é o gatilho de duas ações irreversíveis: gravar `sem_dados` (que é terminal —
o processo nunca mais será tentado) e **avançar de grau**. O desenho garante que uma
mudança de redação no portal degrade para `DESCONHECIDO`, e daí para `erro_transitorio`,
que volta para a fila. O modo de falha é ruído, nunca dado errado.

A alternativa — inferir "não encontrado" pela ausência de dados de capa — inverteria isso:
qualquer quebra de seletor viraria "este processo não existe", gravado como terminal. É
a diferença entre "sei que não existe" e "não consegui perguntar", que atravessa todo o
projeto (ver a taxonomia de status em [`status`](../status.md)).

### `verificar_identidade`: a conferência antes de gravar

```python
def verificar_identidade(html, numero_processo):
    """A página aberta é a do processo pedido? Devolve (Identidade, cnjs_achados).

    Chamar SEMPRE depois de abrir uma capa. Sem esta checagem, entrar no processo
    errado grava autores, réus e movimentações de um processo sob o número de
    outro — e o relacionamento é montado em cima disso.
    """
```

O retorno tem **três** valores, não dois:

```python
class Identidade:
    CONFERE = "CONFERE"              # o número pedido está na página
    DIVERGE = "DIVERGE"              # há número(s), mas não o pedido -> NÃO GRAVAR
    INDETERMINADO = "INDETERMINADO"  # não achou número algum para conferir
```

Um booleano colapsaria `DIVERGE` e `INDETERMINADO` em "não confere", e os dois exigem
respostas diferentes. `DIVERGE` é evidência positiva de erro: a página traz números e
nenhum é o pedido — abortar sempre. `INDETERMINADO` é ausência de evidência: pode ser
layout diferente, pode ser seletor desatualizado. O [`coletor`](coletor.md) combina esse
valor com a procedência da navegação, e só rejeita quando a chegada à página **também**
foi incerta:

```python
if identidade == Identidade.INDETERMINADO and not verificada:
    # Palpite na modal + página sem número conferível = risco de
    # gravar os dados de um processo sob o número de outro.
```

Os seletores consultados carregam uma descoberta sobre o portal:

```python
# Onde o número do processo pode aparecer. Em incidentes ele vem DENTRO da
# classe, entre parênteses (ex.: 'Cumprimento de Sentença ... (0000010-31...)'),
# e não isolado em #numeroProcesso — por isso a busca é por pertinência.
_SELETORES_IDENTIDADE = (
    "#numeroProcesso",
    ".unj-larger",
    "#classeProcesso",
)
```

Por isso a comparação é de **pertinência a um conjunto**, não igualdade de string:
`cnjs_no_texto` extrai todos os CNJs de um trecho e a pergunta vira `alvo in encontrados`.

### `escolher_na_selecao` nunca chuta em silêncio

```python
#: destino: href ou processo.codigo | verificada: o número foi CONFERIDO?
EscolhaSelecao = namedtuple("EscolhaSelecao", "destino verificada motivo")
```

O campo `verificada` é o coração da função. A docstring narra o bug que ela corrige:

> O passo (2) é a correção central: o código antigo pegava `radios[0]`
> assumindo que o principal é a primeira opção. Quando não é, os dados do
> incidente eram gravados sob o número do principal. Aqui o número é conferido
> na linha do rádio; e mesmo no palpite (3) o chamador é obrigado a validar a
> identidade da página aberta antes de gravar qualquer coisa.

A ordem de resolução é degradação explícita, do mais seguro ao menos:

| Passo | Critério | `verificada` | `motivo` |
|---|---|---|---|
| 1 | link cujo texto contém o número exato | `True` | `"link com número exato"` |
| 2 | rádio cuja **linha** (`<tr>`) contém o número exato | `True` | `"rádio com número exato"` |
| 3 | primeiro rádio disponível | `False` | `"PALPITE: primeiro rádio; número não conferido na modal"` |
| — | nada resolvível | `False` | `"nenhuma opção resolvível na seleção"` |

O passo 3 continua existindo, mas deixou de ser silencioso: ele se **declara** palpite, e
quem chama fica obrigado a tratá-lo como tal. O passo 4 devolve `destino=None`, que o
[`coletor`](coletor.md) converte em `erro_transitorio` — nunca em `sem_dados`.

### `cnjs_no_texto` devolve um `set`

```python
def cnjs_no_texto(texto):
    """Conjunto de CNJs (20 dígitos) presentes no texto. `set()` por decisão de
    projeto — dedup nativo, e a pergunta que fazemos é sempre de pertinência."""
```

Toda pergunta feita sobre o resultado é `x in conjunto`. Uma lista exigiria dedup manual
e não descreveria a intenção.

### `_norm` para comparação robusta

O texto da página é normalizado uma vez no construtor (`self._texto`) — minúsculas, sem
acento, espaços colapsados. É o que permite escrever as frases de busca sem acento
(`"nao existem informacoes disponiveis"`) e casar com o que o portal escrever, seja
"Não existem informações disponíveis" ou qualquer variação de espaçamento.

A máscara aceita as duas grafias do separador:

```python
# Máscara CNJ aceitando '-' ou '.' após o sequencial (números antigos usam ponto).
_MASCARA_CNJ = re.compile(r"\d{7}[-.]?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}")
```

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Confiar que abrir o link da seleção leva ao processo certo | Quando não leva, o resultado é um registro completo e válido do processo **errado**, sob o número pedido. Nenhuma etapa posterior detecta. |
| `verificar_identidade` devolvendo booleano | Colapsaria `DIVERGE` (evidência de erro) e `INDETERMINADO` (ausência de evidência), que exigem respostas diferentes. |
| Comparar o número por igualdade com `#numeroProcesso` | Em incidentes o número vem dentro da classe, entre parênteses. A busca precisa ser por pertinência num conjunto de CNJs extraídos. |
| `radios[0]` como escolha padrão silenciosa (pipeline anterior) | Assume que o processo principal é a primeira opção. Quando não é, grava o incidente sob o número do principal. |
| Remover o passo 3 (palpite) e falhar sempre que não houver número exato | Perderia processos recuperáveis. A solução adotada mantém o palpite mas o marca, transferindo a decisão para a validação de identidade da página aberta. |
| Detectar segredo por `input[type="password"]` | O formulário "Identificar-se" existe em toda página do portal — marcaria a base inteira como sigilosa. |
| Detectar seleção antes de checar dados de capa | A capa lista incidentes com links parecidos com os da seleção; uma capa legítima cairia no caminho do palpite. |
| Detector e resolvedor com listas próprias de seletores | O resolvedor só roda depois de o detector aprovar. Um seletor que só o resolvedor conhecesse era código inalcançável, e a página caía em `DESCONHECIDO`. |
| `select(A) or select(B)` para os links da seleção | O `or` confunde "existe link do tipo A" com "o número está em algum link do tipo A". Links A que não casassem o número impediriam B de ser consultado, e a escolha degradava para o palpite do primeiro rádio. |
| Inferir "não encontrado" pela ausência de dados de capa | Toda quebra de seletor viraria `sem_dados`, que é terminal e autoriza avançar de grau. Falha para o lado errado. |
| Não ter estado `DESCONHECIDO`, tratando o resto como capa vazia | Grava registro vazio como resultado legítimo, em vez de devolver o caso à fila. |
| `cnjs_no_texto` devolvendo `list` | Exigiria dedup manual; todas as perguntas feitas sobre o resultado são de pertinência. |

## Limitações Conhecidas

- **`_FRASES_NAO_ENCONTRADO` é uma lista fechada de três frases.** Se o e-SAJ mudar a
  redação, nenhum processo inexistente será reconhecido como tal: todos virarão
  `DESCONHECIDO` → `erro_transitorio` → `erro_persistente` após o teto de tentativas. A
  base não fica errada, mas a fila de falhas cresce sem explicação óbvia. É o preço
  aceito pela falha para o lado seguro, e o primeiro lugar a olhar se a taxa de
  `erro_persistente` disparar.

- **A invariante de identidade admite uma exceção, e ela é deliberada.** Quando a busca
  direta resolve o número (sem passar por tela de seleção), o [`coletor`](coletor.md)
  assume `verificada = True` — *"busca direta: o próprio e-SAJ resolveu o número"*. Nesse
  caminho, uma capa cuja identidade seja `INDETERMINADO` **é gravada**. O raciocínio é
  que quem resolveu o número foi o próprio portal, a partir dos parâmetros de
  `params_busca`. O risco residual é real, mas está confinado a páginas em que nenhum dos
  três seletores de identidade produz um CNJ — o mesmo sintoma que faria os seletores de
  capa falharem.

- **`verificar_identidade` só olha três seletores.** Uma capa com layout diferente devolve
  `INDETERMINADO` mesmo exibindo o número em outro lugar da página. A busca não é feita no
  texto inteiro de propósito: as movimentações citam números de outros processos, e um
  varrimento global encontraria o alvo em páginas que não são dele.

- **A classificação lê o texto completo da página** (`self.soup.get_text(" ")` no
  construtor). Para HTMLs grandes isso tem custo, pago uma vez por página classificada —
  e `coletar_um` classifica duas vezes quando passa pela tela de seleção, construindo dois
  `ClassificadorPagina` sobre HTMLs diferentes.

- **Não há distinção entre bloqueio, captcha, manutenção e layout novo.** Os quatro caem
  em `DESCONHECIDO`. O motivo registrado pelo coletor é genérico (`"página não
  reconhecida"`), e diagnosticar exige olhar o HTML salvo por `scripts/spike_seletores.py`.

## Exemplo de Uso

Classificação, como o [`coletor`](coletor.md) a faz — uma vez após a busca e outra após
abrir o detalhe:

```python
estado = ClassificadorPagina(html).classificar()
```

Resolução da tela de seleção e verificação da capa aberta, o par que sustenta a
invariante:

```python
escolha = escolher_na_selecao(html, np)
if escolha.destino is None:
    return _erro(f"seleção sem opção resolvível (grau {grau})", grau)
verificada = escolha.verificada
```

```python
identidade, achados = verificar_identidade(html, np)
if identidade == Identidade.DIVERGE:
    return _erro(
        f"identidade divergente (grau {grau}): a página traz "
        f"{sorted(achados)}",
        grau,
    )
```

O `achados` devolvido não é decorativo: ele entra na mensagem de erro, para que a auditoria
mostre **qual** processo foi aberto por engano.

Diagnóstico manual, em `scripts/spike_seletores.py`:

```python
identidade, achados = verificar_identidade(html, np)
print(f"  [identidade] {identidade} | CNJs no cabeçalho: {sorted(achados)}")
```

```python
escolha = escolher_na_selecao(html, np)
print(f"    ESCOLHA -> destino={escolha.destino!r} verificada={escolha.verificada}")
print(f"               motivo={escolha.motivo}")
```

## Testes e Validação

Não há testes automatizados neste repositório. A validação em uso é
`scripts/spike_seletores.py`, que para cada número salva o HTML recebido em `data/spike/`,
imprime o estado classificado e — quando cai em seleção ou capa — detalha a escolha, a
identidade e os CNJs encontrados.

Este módulo é o candidato mais forte do projeto a testes automatizados, e por um motivo
concreto: **o spike já produz os fixtures**. Os arquivos `data/spike/<numero>_g<grau>.html`
são HTML real do e-SAJ, e todas as funções daqui são puras sobre string. Um teste seria
`classificar(open(fixture).read()) == EstadoPagina.DADOS_CAPA`, sem rede nenhuma.

As invariantes que valeria fixar, em ordem de risco:

- capa com tabela de partes **não** é classificada como `LISTA_SELECAO` (a guarda de
  `_e_selecao`), usando o HTML de um processo com incidentes;
- página qualquer com o formulário "Identificar-se" **não** é `SENHA_SEGREDO`;
- HTML vazio ou irreconhecível devolve `DESCONHECIDO`, nunca `DADOS_CAPA` nem
  `NAO_ENCONTRADO`;
- `escolher_na_selecao` devolve `verificada=True` quando o número exato está na linha de
  um rádio que **não** é o primeiro — o cenário exato do bug do pipeline anterior;
- `verificar_identidade` devolve `DIVERGE` (e não `INDETERMINADO`) quando a página traz
  CNJs e nenhum é o alvo.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Seletores de seleção compartilhados entre detector e resolvedor; `#numeroProcesso` na guarda de capa de `_e_selecao`; `or` trocado por concatenação em `escolher_na_selecao` |

## Pontos em aberto

- **`_norm` está duplicado literalmente entre este módulo e `parser_base.py`** — mesma
  implementação, mesma docstring (*"Minúsculas, sem acento, espaços colapsados — para
  comparação robusta."*). `limpeza._chave_dedup` faz quase o mesmo, com `casefold()` no
  lugar de `lower()`. Três cópias de uma normalização que precisa ser consistente para
  que as comparações casem.

- **`_MASCARA_CNJ` também está duplicada**, com o mesmo padrão e o mesmo comentário
  explicativo, entre este módulo e `parser_segundo_grau.py`; e o mesmo trecho de regex
  aparece embutido em `_PADRAO_PAI_MOV`, em `transformers/vinculo.py`. Um ajuste na
  máscara — por exemplo, para aceitar outro separador — precisaria ser replicado nos três.

- **`_e_capa` aceita `#numeroProcesso` sozinho, sem exigir dados de capa.** Uma página que
  exiba o número mas nenhuma tabela é classificada como `DADOS_CAPA` e segue para o
  parser, que devolve `completude` com tudo falso. O caso é interceptado adiante por
  `coletor._capa_suspeita`, mas a classificação em si já foi otimista — o que não é
  necessariamente errado, só vale saber que a rede de segurança está na etapa seguinte.

    A guarda acrescentada a `_e_selecao` usa o mesmo critério, então essa página é hoje
    inequivocamente capa e nunca seleção — o que remove a ambiguidade entre os dois
    estados, mas não muda o otimismo da classificação nem move a rede de segurança.
