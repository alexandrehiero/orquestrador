# Parser da capa de 1º grau – `src/scrapers/parser_primeiro_grau.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `src.scrapers.parser_base` |

## Contexto e Motivação

Com 19 linhas, este é o menor módulo do projeto — e o tamanho é a informação.

O e-SAJ separa a consulta em duas instâncias: `cpopg` (1º grau) e `cposg` (2º grau). As
capas são parecidas o suficiente para compartilhar quase tudo, mas divergem num ponto que
não tem como ser abstraído: **no 1º grau existe juiz; no 2º grau existe relator**. O
[`ParserCapaBase`](parser_base.md) declara essa divergência como método abstrato e deixa
cada subclasse resolvê-la:

```python
def _extrair_juiz(self):
    raise NotImplementedError("Subclasse define a extração do juiz/relator.")
```

Esta classe é a implementação para `cpopg`. Tudo o mais — classe, assunto, foro, vara,
valor, situação, distribuição, partes, movimentações, processo principal e `completude` —
vem herdado sem alteração.

Há uma leitura estrutural que só aparece comparando as duas subclasses. O
[`parser_segundo_grau`](parser_segundo_grau.md) tem 118 linhas e precisa sobrescrever
`parse`, `_extrair_foro`, `_extrair_vara` e `_extrair_juiz`, além de acrescentar três
métodos próprios. Este precisa de um. Isso diz algo concreto sobre a herança: **o
`ParserCapaBase` foi escrito contra o HTML de 1º grau**. Ele não é um denominador comum
neutro entre as duas instâncias — é o parser de `cpopg` com o juiz extraído para fora.
Quem for estender o projeto para outra instância ou outro tribunal precisa saber disso
antes de assumir que a base é genérica.

## Decisões de Arquitetura

### Cascata de três passos, com desistência explícita

```python
def _extrair_juiz(self):
    # 1) Caminho canônico: id estável.
    val = self._por_id("#juizProcesso")
    if val and self._juiz_valido(val):
        return val
    # 2) Layout unj sem id: rótulo EXATO 'Juiz' + blocklist.
    val = self._rotulo_estrito("Juiz")
    if val and self._juiz_valido(val):
        return val
    # 3) Na dúvida, ausente — jamais devolve a Vara.
    return None
```

Os três passos são uma degradação ordenada, do mais confiável ao menos, terminando em
desistência — não em chute:

1. **`#juizProcesso`** é o identificador estável do layout tradicional. Quando existe, é
   resposta direta e sem ambiguidade.
2. **`_rotulo_estrito("Juiz")`** cobre o layout `unj` (o tema mais recente do portal), em
   que o campo pode não ter `id`. A busca é por texto **direto exatamente igual** ao
   rótulo — é o que impede `'Juizado Especial Cível'` de casar com `'Juiz'`. O mecanismo
   está detalhado em [`parser_base`](parser_base.md).
3. **`None`.** Não há terceiro palpite.

### `_juiz_valido` é aplicado nos dois caminhos, inclusive no canônico

Repare que o passo 1 não confia no `id`: `if val and self._juiz_valido(val)`. Um `id`
estável poderia, em tese, conter o texto certo no lugar errado — e a blocklist de
`_BLOCK_JUIZ` custa uma comparação de string. Validar os dois caminhos com o mesmo critério
também significa que só existe **uma** definição de "isto parece nome de juiz" no projeto,
em vez de uma por caminho de extração.

### Campo ausente em vez de campo errado

O comentário do passo 3 é a política inteira em oito palavras:

```python
# 3) Na dúvida, ausente — jamais devolve a Vara.
```

Sem a blocklist, o passo 2 é perfeitamente capaz de devolver `"1ª Vara da Fazenda
Pública"` como nome de juiz: é um texto que aparece perto do rótulo, num layout onde a
estrutura mudou. Uma vez gravado no JSONL, esse valor é indistinguível de um nome real —
um agrupamento por juiz passaria a contar varas como se fossem pessoas, e nada no
pipeline acusaria. `None` é um dado ausente honesto, que qualquer análise sabe filtrar.

Vale notar a assimetria de custo: um juiz que existe e não foi extraído produz um `null` a
mais numa base que já tem muitos; um juiz extraído errado contamina uma agregação inteira.

### `GRAU = 1` deixou de ser decorativo

```python
class ParserPrimeiroGrau(ParserCapaBase):
    GRAU = 1
```

O atributo sempre esteve aqui, mas até então ninguém o lia: o pareamento grau → parser era
feito por dicionários escritos à mão, um no `coletor` e outro no spike, ambos repetindo um
pareamento que estas classes já declaravam. Hoje o mapa é **derivado** dele:

```python
#: Derivado do atributo GRAU de cada parser — que assim deixa de ser decorativo.
#: Um dicionário escrito à mão aceitaria {1: ParserSegundoGrau} sem reclamar e
#: rodaria o parser errado em silêncio. Público de propósito: o spike importa
#: DESTE dicionário em vez de manter o seu.
PARSER_POR_GRAU = {P.GRAU: P for P in (ParserPrimeiroGrau, ParserSegundoGrau)}
```

A mudança é pequena no diff e grande no que ela elimina. Antes havia **três** afirmações
sobre a mesma coisa — `GRAU = 1` aqui, a chave `1` no dicionário do coletor, a chave `1` no
dicionário do spike — e nada obrigava as três a concordarem. `{1: ParserSegundoGrau}` seria
aceito sem reclamação por qualquer uma delas: nenhum import falha, nenhuma exceção sobe. O
parser de 2º grau rodaria sobre uma capa de 1º e devolveria classe, partes e movimentações
corretas (vêm da base) com `juiz: None`, porque `#relatorProcesso` não existe em `cpopg`. Um
`null` a mais, indistinguível de um juiz genuinamente ausente — o mesmo modo de falha
silenciosa que a blocklist deste módulo existe para evitar no valor extraído.

Derivado, o erro deixa de ser expressável: a chave **é** o `GRAU` da classe, e não há onde
digitá-la errado. E o roteamento passa a ter uma fonte só — o spike importa do coletor, com
o motivo registrado no próprio script:

```python
from src.scrapers.coletor import PARSER_POR_GRAU
```

```python
# O roteamento grau -> parser vem do coletor. Um dicionário próprio aqui podia
# divergir do usado na coleta real, e o spike deixaria de diagnosticar
# exatamente o caminho que a coleta percorre — que é a razão de ele existir.
```

Isso fecha um risco específico do diagnóstico: um spike que rodasse por um caminho diferente
do da coleta poderia confirmar seletores que a coleta nunca usaria — pior que não
diagnosticar, porque produz confiança infundada.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Devolver a vara, o foro ou o órgão quando o juiz não for encontrado | Dado errado é pior que dado ausente. Uma agregação por juiz consumiria nomes de órgãos como se fossem pessoas, sem qualquer sinal de erro. |
| Só o passo 1 (`#juizProcesso`) | Perderia todas as capas servidas no layout `unj`, em que o campo pode não ter `id`. |
| Só o passo 2 (busca por rótulo) | Descartaria o caminho mais confiável e barato em favor de uma varredura de todos os `span`/`td`/`div` da página. |
| Inverter a ordem, tentando o rótulo primeiro | Mesma perda: a busca textual é mais cara e mais frágil que um `id` estável. |
| Confiar no `id` sem passar por `_juiz_valido` | Criaria dois critérios diferentes de "é nome de juiz" no mesmo método, e o caminho canônico ficaria sem rede de proteção. |
| Não criar a subclasse e usar `if self.GRAU == 1` dentro do `ParserCapaBase` | Espalharia condicionais de instância pela classe base. O ponto do Template Method é que a divergência fique declarada num lugar só. |
| Tratar juiz e relator como campos separados no dict bruto | O projeto decidiu que o relator ocupa o campo `juiz` no 2º grau — ver [`parser_segundo_grau`](parser_segundo_grau.md). Manter um campo só simplifica a projeção e a análise. |

## Limitações Conhecidas

- **`juiz` não entra em `completude`.** As três bandeiras reportadas pelo parser são
  `tem_classe`, `tem_partes` e `tem_movimentacoes`. Se `#juizProcesso` sumir do portal e o
  rótulo mudar de texto, **toda** a base passa a ter `juiz: null` sem que nenhuma
  verificação acuse: `_capa_suspeita` continuará aprovando as capas, porque partes e
  movimentações seguem chegando. A detecção depende de alguém olhar a distribuição do
  campo depois da coleta.

- **Um juiz cujo sobrenome seja exatamente uma palavra da blocklist é descartado.** A
  comparação de `_juiz_valido` passou a ser por palavra inteira, o que eliminou os falsos
  negativos por subcadeia (`'Alvarado'`, `'Areal'`), mas o caso da palavra idêntica
  permanece: um juiz de sobrenome `'Câmara'` continua virando `None`. Ver a anotação em
  [`parser_base`](parser_base.md). O efeito aqui é sempre para o lado seguro, e é uma perda
  silenciosa — mas o texto original fica preservado no dict bruto.

- **Não há distinção entre juiz titular, substituto ou plantonista.** O campo guarda o que
  a capa exibir no momento da coleta, que pode mudar ao longo da vida do processo. O dado
  é um retrato, não um histórico.

- **A subclasse não valida que o HTML recebido é mesmo de 1º grau.** Instanciar
  `ParserPrimeiroGrau` com uma capa de `cposg` não levanta erro: `#juizProcesso` não
  existiria, `_rotulo_estrito("Juiz")` não acharia nada e o campo viria `None`, enquanto os
  demais campos seriam extraídos normalmente. Quem garante o pareamento é o mapa de grau do
  [`coletor`](coletor.md) — que, sendo derivado do próprio `GRAU`, não pode mais parear
  errado por engano de digitação. O que continua sem verificação é o outro lado: se o grau
  pedido ao e-SAJ e o HTML devolvido divergirem, o parser certo rodará sobre a capa errada.

## Exemplo de Uso

A classe nunca é instanciada diretamente pelo pipeline. O pareamento grau → parser é feito
por um dicionário derivado do atributo `GRAU`, em `src/scrapers/coletor.py`:

```python
PARSER_POR_GRAU = {P.GRAU: P for P in (ParserPrimeiroGrau, ParserSegundoGrau)}
```

```python
bruto = PARSER_POR_GRAU[grau](html).parse()
```

E, para diagnóstico, em `scripts/spike_seletores.py` — que importa o mesmo dicionário, em
vez de manter o seu:

```python
from src.scrapers.coletor import PARSER_POR_GRAU
```

```python
dados = PARSER_POR_GRAU[grau](html).parse()
```

O `parse()` chamado é o herdado de [`ParserCapaBase`](parser_base.md) — esta classe não o
sobrescreve. O único ponto em que seu código roda é dentro dele, quando a linha
`"juiz": self._extrair_juiz()` é avaliada.

## Testes e Validação

Não há testes automatizados neste repositório. A validação em uso é
`scripts/spike_seletores.py`, que imprime o campo `juiz` junto aos demais para cada capa
diagnosticada, permitindo comparar com o que a página exibe no navegador.

Sendo uma função pura sobre HTML, é trivialmente testável com os fixtures que o spike já
salva em `data/spike/`. As invariantes que valeria fixar:

- capa com `#juizProcesso` preenchido devolve exatamente esse valor;
- capa sem `#juizProcesso`, mas com um rótulo `Juiz` no layout `unj`, cai no passo 2 e
  devolve o nome;
- capa cujo único texto próximo ao rótulo seja o nome de uma vara devolve `None` — a
  garantia do passo 3, e o caso que mais interessa cobrir;
- `'Juizado Especial Cível'` presente na página não é confundido com o rótulo `'Juiz'`.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | `GRAU` passa a alimentar o `PARSER_POR_GRAU` do coletor; o spike importa o mesmo mapa e o roteamento fica com uma fonte só |

## Pontos em aberto

Nenhum item em aberto.
