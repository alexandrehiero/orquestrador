# Parser base da capa – `src/scrapers/parser_base.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `beautifulsoup4`, `re`, `unicodedata` (biblioteca padrão) |

## Contexto e Motivação

Este módulo extrai os dados da capa do processo. A decisão que o define, porém, é sobre o
que ele **não** faz — e ela governa a arquitetura inteira do pipeline. A primeira linha
da docstring:

> Parser base da capa do e-SAJ. Retorna um DICT BRUTO — NÃO normaliza.

E a justificativa, no parágrafo seguinte:

> Por que bruto: este dict vai inteiro para o SQLite, e a base final é uma
> PROJEÇÃO dele. Limpar aqui (tirar parênteses da classe, converter data, virar
> float) destruiria o original e obrigaria a RECOLETAR quando uma regra de limpeza
> mudasse. Com o bruto guardado, corrigir uma regra é reprojetar — sem rede.

Vale desdobrar o que essa escolha compra, porque é a diferença entre um pipeline que se
corrige e um que se refaz.

Suponha que, três semanas depois de uma coleta terminar, alguém descubra que a limpeza da
classe está removendo parênteses demais, ou que `'credor'` deveria estar no polo ativo.
Num parser que normaliza na hora da coleta, o texto original não existe mais em lugar
nenhum: a única forma de aplicar a regra nova é **coletar tudo de novo** — semanas de
requisições contra um portal público, com toda a exposição a bloqueio que isso implica.
Aqui, o texto original está no SQLite. Corrigir a regra é rodar a opção 4 do
`scripts/menu.py`, que reprojeta localmente, sem uma única requisição.

É por isso que o parser guarda `"Cumprimento de Sentença contra a Fazenda Pública
(0000010-31...)"` como veio, com os parênteses, e deixa a limpeza para
[`transformers/limpeza`](../transformers/limpeza.md). O bruto é o registro do que o portal
respondeu; o JSONL é uma **opinião** sobre esse registro — e opiniões mudam.

## Decisões de Arquitetura

### O dict bruto e o contrato do `parse()`

```python
def parse(self):
    partes = self._extrair_partes()
    return {
        "classe": self._extrair_classe(),
        "assunto": self._extrair_assunto(),
        "foro": self._extrair_foro(),
        "vara": self._extrair_vara(),
        "juiz": self._extrair_juiz(),
        "valor": self._extrair_valor(),
        "situacao": self._extrair_situacao(),
        "data_distribuicao": self._extrair_distribuicao(),
        "partes": partes,
        "movimentacoes": self._extrair_movimentacoes(),
        "processo_principal": self._extrair_processo_principal(),
        "completude": self._completude(partes),
    }
```

Todos os valores de texto saem como vieram do HTML: `valor` é a string `"R$ 3.724,16"`,
não um `float`; `data_distribuicao` é `"09/01/2013 às 11:39 - Livre"`, não uma data ISO.
A conversão acontece na projeção.

### `completude`: quais blocos vieram, não "veio ou não veio"

Esta é a segunda decisão mais importante do módulo, e nasceu de um bug concreto:

> `completude`: diz QUAIS blocos vieram. A validação antiga usava um AND de 4
> condições, então uma quebra só no seletor de partes passava despercebida e
> gravava o processo sem autores nem réus.

```python
def _completude(self, partes):
    """Quais blocos vieram. A validação decide revisão a partir DISTO, não de
    um booleano único — capa com movimentações e ZERO partes é seletor
    quebrado, não processo sem partes."""
    return {
        "tem_classe": bool(self._extrair_classe()),
        "tem_partes": bool(partes),
        "tem_movimentacoes": bool(self.soup.select_one("#tabelaTodasMovimentacoes")),
    }
```

Um booleano único responde "extraí alguma coisa?" — e a resposta é sim mesmo quando o
bloco mais importante veio vazio. O dicionário responde "extraí **o quê**?", e é isso que
permite a [`coletor._capa_suspeita`](coletor.md) aplicar a regra que realmente importa:
capa com classe e movimentações mas **zero** partes não é um processo sem partes, é um
seletor quebrado. Sem essa distinção, a quebra de um seletor se manifesta como milhares
de processos silenciosamente incompletos.

### Partes como lista de dicts, com o rótulo real preservado

> partes viram lista de dicts com o rótulo REAL preservado (Exeqte, Reqdo...),
> em vez de 5 listas paralelas que jogavam o rótulo fora;

```python
partes.append({
    "tipo_parte": rotulo_bruto.rstrip(":").strip(),  # 'Exeqte', 'Reqdo'
    "polo": self._classificar_polo(tipo),            # ATIVO/PASSIVO/OUTRO
    "nome": nome,
    "representantes": reps,
})
```

Cinco listas paralelas (`autores`, `reus`, `advogados_autores`, …) obrigam a decidir o
polo **no momento da extração** e descartam a informação que permitiria revisar essa
decisão depois. Guardando `tipo_parte` ao lado de `polo`, o rótulo original sobrevive: se
amanhã se decidir que `'Terceiro Interessado'` deveria ter tratamento próprio, a
informação está no banco. É a mesma lógica do bruto, aplicada dentro do bruto.

A projeção achata isso em autores/réus — e a decisão de que `tipo_parte` fica só no bruto
está registrada em [`transformers/projecao`](../transformers/projecao.md).

### Classificação de polo por match exato na célula de tipo

```python
# Match EXATO sobre a célula de tipo (que é curta). Nunca sobre a linha inteira,
# senão padrões curtos como 'Ré' casam em qualquer lugar.
```

A célula de tipo tem uma ou duas palavras (`Exeqte`, `Reqdo`, `Apelante`). A linha inteira
tem o nome da parte, os advogados e o que mais houver. Procurar `"re"` na linha inteira
casa com qualquer nome que contenha essas letras; comparar com a célula normalizada é
determinístico.

As três correções de vocabulário frente ao pipeline anterior estão registradas no próprio
código:

```python
"credor", "credora",  # ATIVO: quem executa. Estava em PASSIVO por engano.
```

```python
# 'interessado/interessada' NÃO entram em nenhum dos dois: é rótulo neutro
# (jurisdição voluntária, terceiros). Vão para polo OUTRO.
```

E a terceira, na docstring: *"flexões que faltavam e caíam em OUTRO em silêncio (apelada,
recorrida, impetrada, suscitante/suscitado, devedor/devedora)"*. As três são erros de
classificação jurídica, não de programação — o credor numa execução **é** quem executa, e
classificá-lo como réu inverte o polo de toda uma categoria de processos.

### `_rotulo_estrito`: texto direto exatamente igual ao rótulo

```python
def _rotulo_estrito(self, rotulo):
    """Elemento cujo texto DIRETO é EXATAMENTE o rótulo (evita 'Juizado'
    casar com 'Juiz'); devolve o valor associado (irmão seguinte)."""
    alvo = _norm(rotulo)
    for el in self.soup.find_all(["span", "td", "dt", "th", "label", "div"]):
        direto = _norm(el.find(string=True, recursive=False) or "")
        if direto in (alvo, alvo + ":"):
```

Duas defesas numa função só. `find(string=True, recursive=False)` pega apenas o texto
**direto** do elemento, ignorando o de seus filhos — sem isso, um `<div>` contêiner que
envolve meia página "contém" o rótulo e casaria. E a comparação é de igualdade, não de
`in`: `"Juizado Especial Cível"` não é igual a `"Juiz"`, embora o contenha.

### `_juiz_valido`: nunca devolver a Vara como juiz

```python
_BLOCK_JUIZ = (
    "vara", "juizado", "foro", "camara", "turma", "colegio", "orgao",
    "distribuidor", "comarca", "secao", "gabinete", "area", "classe",
)
```

Uma lista de bloqueio para o valor extraído. Se o que voltou parece nome de órgão, não é
nome de juiz. O [`parser_primeiro_grau`](parser_primeiro_grau.md) explicita a consequência:
*"Na dúvida, ausente — jamais devolve a Vara."* Campo vazio é um dado ausente honesto;
campo preenchido com o nome da vara é um dado **errado** que qualquer agregação por juiz
consumiria sem perceber.

### A comparação é por palavra inteira, não por substring

```python
def _juiz_valido(self, valor):
    """Compara por PALAVRA INTEIRA, não por substring.

    Substring gerava falso negativo em sobrenomes reais: 'Alvarado' contém
    'vara', 'Areal' contém 'area'. O juiz virava None sem aviso.

    Caso irredutível: um juiz de sobrenome 'Câmara' continua rejeitado — a
    palavra é literalmente igual à do órgão. É a escolha 'na dúvida,
    ausente' do projeto, e o dado bruto fica preservado no banco.
    """
    n = _norm(valor)
    if not n:
        return False
    palavras = set(re.findall(r"[a-z0-9]+", n))
    return not (palavras & set(_BLOCK_JUIZ))
```

A implementação anterior era `not any(bloco in n for bloco in _BLOCK_JUIZ)` — pertinência de
substring. Ela funcionava para o caso que a lista descreve e falhava para uma classe de
casos que ninguém tinha em mente ao escrevê-la: **sobrenomes brasileiros que contêm as
sequências bloqueadas**. `'Alvarado'` contém `vara`. `'Areal'` contém `area`. O juiz era
descartado e o campo virava `None`, sem aviso e sem sintoma — o mesmo `null` que um juiz
genuinamente ausente produz.

O que torna esse bug caro não é a frequência, é a invisibilidade. A política declarada do
módulo é "na dúvida, ausente", então o comportamento errado se **disfarça** exatamente de
comportamento correto: uma base com 3% de `juiz: null` a mais não levanta suspeita nenhuma.
Não há `completude` para o campo `juiz` (ver [`parser_primeiro_grau`](parser_primeiro_grau.md)),
nem nada que distinga "não achei" de "achei e joguei fora".

A tokenização usa `re.findall(r"[a-z0-9]+", n)` sobre o texto **já normalizado** por `_norm`
— minúsculo e sem acento —, o que é o que permite `_BLOCK_JUIZ` ser escrito sem acentos
(`camara`, `secao`, `orgao`) e ainda casar com o que a página exibe.

**O caso irredutível permanece, e está registrado no código:** um juiz de sobrenome
`'Câmara'` continua sendo rejeitado, porque a palavra é literalmente igual à do órgão.
Nenhum critério baseado em vocabulário resolve isso — só contexto estrutural, que o layout
`unj` não fornece de forma confiável. A escolha do projeto se mantém: na dúvida, ausente. O
que salva o caso é que o texto original fica preservado no dict bruto guardado no banco,
então corrigir a regra um dia é reprojetar, não recoletar.

### `SELETORES_SITUACAO`: confirmados em HTML real no spike de 2026-08-10

```python
# Confirmados no spike de 2026-08-10 contra HTML real: `.unj-tag` devolveu
# 'Extinto' e 'Suspenso' no 1º grau; `#situacaoProcesso` e `.unj-tag` devolveram
# 'Arquivado administrativamente' no 2º grau. `.unj-badge` e `.tag` seguem como
# rede de segurança não observada.
SELETORES_SITUACAO = ("#situacaoProcesso", ".unj-tag", ".unj-badge", ".tag")
```

A lista nasceu da inspeção visual das telas, e o comentário anterior avisava que nenhum dos
quatro seletores tinha sido visto responder contra HTML real — o que deixava `situacao` num
limbo: um campo vazio em toda a base seria indistinguível de "nenhum processo tem selo".

O spike fechou essa dúvida para dois deles, e o comentário registra exatamente o que foi
observado, sem arredondar. `.unj-tag` respondeu nos dois graus; `#situacaoProcesso`
respondeu no 2º. `.unj-badge` e `.tag` continuam sem observação — permanecem na tupla como
rede de segurança, e é honesto dizer que ninguém sabe se algum dia respondem.

A extração usa a tupla como um grupo CSS único:

```python
el = self.soup.select_one(",".join(SELETORES_SITUACAO))
```

Vale notar a consequência: `select_one` sobre um grupo devolve o primeiro elemento em **ordem
de documento**, não o primeiro seletor da tupla que casar. A ordem da tupla é documental —
do mais específico ao mais genérico —, não uma ordem de precedência efetiva.

### `ROTULOS_DISTRIBUICAO`: a ordem codifica o caso do incidente

```python
# Ordem importa: incidentes/cumprimentos não têm 'Distribuição', têm 'Recebido em'.
ROTULOS_DISTRIBUICAO = ("Distribuição", "Recebido em", "Distribuido em")
```

E a política quando nenhum aparece:

```python
def _extrair_distribuicao(self):
    """Texto bruto: '09/01/2013 às 11:39 - Livre' ou '06/01/2024 às 13:58'.
    Devolve None quando a capa não exibe — nunca infere de movimentação."""
```

A tentação de "estimar" a distribuição pela movimentação mais antiga é grande e a recusa é
deliberada: a movimentação mais antiga **visível** não é necessariamente a primeira do
processo, e um campo inferido é indistinguível de um campo observado depois que vira
JSONL.

### `_extrair_processo_principal`: só o link do topo, nunca a aba Apensos

```python
def _extrair_processo_principal(self):
    """Pai = link 'Processo principal' do TOPO. NUNCA a aba Apensos."""
```

Apenso e incidente são relações diferentes. Apensamento é lateral — dois processos que
tramitam juntos por conveniência processual, sem hierarquia. Incidente é hierárquico: o
processo **nasceu** de outro. Tratar apenso como pai criaria arestas hierárquicas falsas
no grafo, e como a base final expõe `processos_filhos` por inversão (ver
[`transformers/projecao`](../transformers/projecao.md)), o erro se propagaria para os dois
lados da relação.

O número só é aceito se tiver exatamente 20 dígitos — caso contrário, `None`.

### Template Method: a subclasse define o juiz

```python
class ParserCapaBase:
    GRAU = None  # 1 ou 2 — definido pela subclasse
```

```python
def _extrair_juiz(self):
    raise NotImplementedError("Subclasse define a extração do juiz/relator.")
```

Tudo que é comum às duas instâncias fica aqui; o que diverge é declarado abstrato. No 1º
grau existe juiz; no 2º existe relator, e por decisão do projeto ele ocupa o mesmo campo
(ver [`parser_segundo_grau`](parser_segundo_grau.md)). `NotImplementedError` em vez de um
retorno padrão garante que uma terceira subclasse não herde silenciosamente um
comportamento que não faz sentido para ela.

O atributo `GRAU` completa o padrão: além de declarar a qual instância cada subclasse serve,
ele é **lido** — é dele que o [`coletor`](coletor.md) deriva o mapa de roteamento, com um
`{P.GRAU: P for P in (...)}`. A declaração e o roteamento deixaram de ser duas afirmações
independentes sobre o mesmo fato; ver [`parser_primeiro_grau`](parser_primeiro_grau.md).

Vale registrar também que a base **não** é um denominador comum neutro entre as duas
instâncias. `ParserPrimeiroGrau` sobrescreve um único método; `ParserSegundoGrau`
sobrescreve quatro e acrescenta três. A assimetria indica que esta classe foi escrita
contra o HTML de `cpopg`, com o juiz extraído para fora — o que importa para quem for
estendê-la a outra instância ou outro tribunal.

### Movimentações: título e complemento numa string só

```python
def _extrair_movimentacoes(self):
    """Data + descrição. Título e complemento ficam JUNTOS numa string, por
    decisão do projeto."""
```

O e-SAJ separa visualmente o título da movimentação de seu complemento. Mantê-los juntos
simplifica a busca textual — que é o uso principal desse campo — ao custo de não permitir
filtrar só por título. É uma decisão registrada como tal, não um acidente de parsing.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Normalizar durante a coleta (converter data, `float`, limpar classe) | Destrói o texto original. Qualquer correção de regra passaria a exigir recoleta completa — semanas de requisições contra o portal. |
| Guardar só o JSONL final, sem o bruto no banco | Mesma consequência: o pipeline deixa de ser corrigível localmente. |
| Guardar o HTML inteiro em vez do dict bruto | Preservaria ainda mais, mas multiplicaria o tamanho do banco por ordens de grandeza e adiaria todo o custo de parsing para a projeção. O dict bruto é o meio-termo: preserva o texto extraído sem guardar marcação. |
| `completude` como booleano único (`dados_ok`) | Foi o modelo anterior. Um AND de quatro condições esconde a quebra de um seletor específico: o processo é gravado sem partes e ninguém percebe. |
| Cinco listas paralelas (`autores`, `reus`, `advogados_autores`, …) | Descarta o rótulo original (`Exeqte`, `Reqdo`) e congela a decisão de polo no momento da coleta, sem possibilidade de revisão posterior. |
| Classificar o polo procurando o rótulo na linha inteira | Padrões curtos como `'Ré'` casam dentro de nomes próprios e de qualquer outro texto da linha. |
| Manter `'credor'` no polo passivo | Erro de classificação jurídica: na execução, o credor é quem executa. Inverte o polo de uma categoria inteira. |
| Manter `'interessado'` no polo passivo | Rótulo neutro (jurisdição voluntária, terceiros). Forçá-lo a um polo inventa uma informação que o portal não deu. |
| Buscar rótulos com `in` (`"Juiz" in texto`) | `'Juizado Especial'` casaria com `'Juiz'`. Daí o texto **direto** comparado por igualdade. |
| Devolver a Vara quando o juiz não for encontrado | Dado errado é pior que dado ausente: uma agregação por juiz consumiria nomes de órgãos sem perceber. |
| Comparar `_BLOCK_JUIZ` por substring (`bloco in n`) | Sobrenomes reais contêm as sequências bloqueadas — `'Alvarado'` contém `vara`, `'Areal'` contém `area`. O juiz virava `None` sem sintoma, disfarçado da política "na dúvida, ausente". |
| Inferir `data_distribuicao` da movimentação mais antiga | A movimentação mais antiga visível não é necessariamente a primeira, e depois de virar JSONL o campo inferido é indistinguível do observado. |
| Usar a aba Apensos como origem do vínculo | Apensamento é relação lateral, não hierárquica. Criaria arestas de paternidade falsas, propagadas também para `processos_filhos`. |
| `_extrair_juiz` com implementação padrão na base | Uma subclasse futura herdaria silenciosamente um comportamento que não vale para ela. `NotImplementedError` força a decisão. |

## Limitações Conhecidas

- **O dict bruto ganha uma chave depois de sair daqui.** `parse()` não produz
  `observacoes`, mas `scripts/menu.py` acrescenta a chave antes de gravar, com o resultado
  de `derivar_vinculo`:

  ```python
  bruto = dict(bruto)
  bruto["observacoes"] = vinc["observacoes"]
  ```

  E [`transformers/projecao`](../transformers/projecao.md) lê `bruto.get("observacoes")` ao
  projetar. O contrato do bruto, portanto, é maior do que este arquivo revela — quem ler
  só o parser não encontra a origem desse campo.

- **`_extrair_movimentacoes` usa `tds[0]` e `tds[-1]`.** Numa tabela de duas colunas isso é
  exatamente data e descrição. Se o e-SAJ acrescentar uma coluna intermediária, ela é
  descartada sem aviso.

- **`_extrair_partes` cai para `tds[-1]` quando não encontra `td.nomeParteEAdvogado`.** É
  um fallback razoável, mas silencioso: uma mudança de classe CSS no portal degradaria a
  extração de nome sem que `completude` acusasse nada, já que `tem_partes` continuaria
  verdadeiro.

- **A extração de representantes depende da estrutura de `<span>`.** `_parte_nome_e_reps`
  procura um `<span>` cujo texto case `_ROTULO_REPRESENTANTE` (`advogado`, `defensor`,
  `procurador`, `curador`) e pega o irmão seguinte. Qualquer reorganização do HTML nesse
  ponto devolve lista vazia — de novo, sem sinal em `completude`.

- **`_rotulo_estrito` varre todos os `span`, `td`, `dt`, `th`, `label` e `div` da página, e
  é chamado até dez vezes por capa** (classe, assunto, foro, vara, valor, situação, os três
  rótulos de distribuição e o juiz). Como cada chamada só ocorre quando o seletor por `id`
  falhou, o custo real depende de quanto o layout `unj` está em uso.

- **`SELETORES_SITUACAO` e `ROTULOS_DISTRIBUICAO` são listas fechadas.** Um selo ou rótulo
  **novo** no portal produz campo vazio, não erro — e campo vazio não dispara nenhuma das
  três bandeiras de `completude`. Vale a distinção: no caso de `SELETORES_SITUACAO` o risco
  hoje é esse, o de uma marcação nova, e não mais o de os seletores atuais jamais
  responderem — dois deles foram vistos responder em HTML real no spike de 2026-08-10.

## Exemplo de Uso

O parser nunca é instanciado diretamente: quem escolhe a subclasse é o mapa de grau,
derivado do atributo `GRAU` de cada uma. Em `src/scrapers/coletor.py`:

```python
PARSER_POR_GRAU = {P.GRAU: P for P in (ParserPrimeiroGrau, ParserSegundoGrau)}
```

```python
bruto = PARSER_POR_GRAU[grau](html).parse()
suspeita = _capa_suspeita(bruto.get("completude") or {})
```

As duas linhas mostram o ciclo completo da decisão de `completude`: o parser reporta o que
extraiu, e o coletor decide se isso é aceitável.

Em `scripts/spike_seletores.py`, o mesmo `parse()` alimenta o diagnóstico campo a campo —
o mapa vem do coletor, e as duas constantes públicas do módulo são importadas justamente
para serem auditadas:

```python
from src.scrapers.coletor import PARSER_POR_GRAU
from src.scrapers.parser_base import ROTULOS_DISTRIBUICAO, SELETORES_SITUACAO
```

```python
dados = PARSER_POR_GRAU[grau](html).parse()
print("  [parse]")
for campo in ("classe", "assunto", "foro", "vara", "juiz", "valor",
              "situacao", "data_distribuicao", "processo_principal"):
    print(f"    {campo:20}: {dados.get(campo)!r}")
print(f"    completude          : {dados.get('completude')}")
```

## Testes e Validação

Não há testes automatizados neste repositório. A validação em uso é
`scripts/spike_seletores.py`, que roda `parse()` sobre HTML real e imprime cada campo, a
`completude`, todas as partes com `tipo_parte` e `polo`, e as primeiras movimentações —
permitindo conferir a classificação de polo linha a linha contra a capa aberta no
navegador.

O módulo é puro sobre string (recebe HTML, devolve dict) e os HTMLs salvos pelo spike em
`data/spike/` servem de fixture direta. As invariantes que valeria fixar primeiro, todas
verificáveis sem rede:

- `'Exeqte'` e `'Credor'` classificam como `ATIVO`; `'Reqdo'` e `'Devedor'` como
  `PASSIVO`; `'Interessado'` como `OUTRO` — as três correções frente ao pipeline anterior;
- `_rotulo_estrito("Juiz")` **não** casa com um elemento cujo texto seja
  `'Juizado Especial Cível'`;
- `_juiz_valido('Alvarado')` e `_juiz_valido('Areal')` devolvem `True` — os dois casos
  nomeados na docstring, que a comparação por substring reprovava; e
  `_juiz_valido('1ª Vara da Fazenda Pública')` continua devolvendo `False`;
- capa com movimentações e sem partes produz `completude` com `tem_partes: False` e
  `tem_movimentacoes: True` — o par exato que `_capa_suspeita` usa para reprovar;
- `_extrair_processo_principal` devolve `None` quando o único número presente está na aba
  Apensos;
- os campos de texto saem **sem** normalização: uma classe com parênteses continua com
  parênteses, e `valor` continua string.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | `_juiz_valido` compara por palavra inteira; `SELETORES_SITUACAO` confirmado em HTML real pelo spike; `GRAU` passa a alimentar `PARSER_POR_GRAU` |

## Pontos em aberto

- **`_completude` recalcula `_extrair_classe()`.** O valor já foi computado por `parse()`
  na mesma chamada:

  ```python
  return {
      "tem_classe": bool(self._extrair_classe()),
  ```

  Além do trabalho repetido (que pode incluir a varredura completa de `_rotulo_estrito`),
  isso abre a possibilidade teórica de `completude["tem_classe"]` discordar do campo
  `classe` do mesmo dict. Não há nada no código que torne `_extrair_classe` não
  determinístico, então hoje os dois sempre concordam — mas a duplicação é gratuita e não
  está claro se foi intencional.

- **`_norm` é idêntico ao de `page_state.py`**, incluindo a docstring. Ver a anotação em
  [`numero_processo`](numero_processo.md) sobre a duplicação de utilitários de
  normalização entre módulos.
