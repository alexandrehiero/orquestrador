# Número Único CNJ – `src/scrapers/numero_processo.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re` (biblioteca padrão), `src.scrapers.exceptions` |

## Contexto e Motivação

O número de processo é o identificador em torno do qual gira o pipeline inteiro: ele é a
entrada do `.txt`, a chave do banco, o parâmetro da busca no e-SAJ, o alvo da conferência
de identidade e o `_id` do documento final. Tratado como `str`, cada camada precisaria
saber recortar posições, remontar máscara e recalcular dígito verificador — e cada uma
faria isso um pouco diferente.

Este módulo transforma o número num **value object**: um objeto imutável na prática, que
nasce validado e sabe responder tudo que o pipeline pergunta sobre ele. A estrutura vem
da Resolução CNJ 65/2008, registrada logo na docstring:

```
Estrutura: NNNNNNN-DD.AAAA.J.TR.OOOO  (20 dígitos)
```

Há uma segunda motivação, específica deste projeto. O e-SAJ organiza a consulta por
**instância** (`cpopg` para 1º grau, `cposg` para 2º), mas o domínio do problema fala em
**grau**. A docstring fixa de que lado fica cada vocabulário:

> fala em GRAU (1/2), não em instância. 'cpopg'/'cposg' é detalhe do cliente.

Todo o resto do projeto passa `grau=1` ou `grau=2`. A tradução para a URL do e-SAJ
acontece num único lugar, `instancia_do_grau`.

## Decisões de Arquitetura

- **Value object, não string com funções auxiliares.** `NumeroProcesso("...")` ou falha
  na construção ou é um número de 20 dígitos — não existe instância inválida circulando.
  As propriedades (`sequencial`, `dv`, `ano`, `segmento`, `tribunal`, `origem`) recortam
  o dígito na posição certa uma vez só, e ninguém mais precisa lembrar que o tribunal
  são os dígitos 14 e 15.

- **`__slots__ = ("_d",)`.** Elimina o `__dict__` por instância e, no dia a dia, impede
  que alguém acrescente um atributo por engano — um `np.grau = 2` atribuído fora do
  construtor levantaria `AttributeError` em vez de criar silenciosamente um estado que
  o resto do código não conhece. O grau **não** é atributo do número: o mesmo número
  pode existir em 1º e 2º grau, e é justamente por isso que a chave do banco é o par
  `(processo, grau)` (ver [`store/sqlite_store`](../store/sqlite_store.md)).

- **Só tamanho ≠ 20 é erro duro; DV inválido não levanta exceção.** A decisão está
  explícita na docstring do módulo:

  > valida o dígito verificador (ISO 7064 MOD 97-10) — mas NÃO levanta exceção
  > por DV inválido: o chamador decide (entrada -> numeros_invalidos.txt;
  > relacionamento -> observação). Só o tamanho != 20 é erro duro.

  O mesmo fato — "este DV não fecha" — tem duas respostas legítimas dependendo de onde
  aparece, e o value object não tem como saber qual é o caso. Ele expõe `dv_valido` e
  `dv_esperado` e deixa a política para quem chamou.

- **`tentar()` como construtor alternativo que devolve `None`.** Para laços que não
  podem quebrar:

  ```python
  @classmethod
  def tentar(cls, valor):
      """Devolve NumeroProcesso ou None — para laços que não podem quebrar."""
      try:
          return cls(valor)
      except NumeroProcessoInvalido:
          return None
  ```

  Os três chamadores reais usam exatamente essa forma: `ler_numeros` e `tarefa` em
  `scripts/menu.py`, e `diagnosticar` em `scripts/spike_seletores.py`. Nenhum deles
  precisa de `try/except`, e um número podre no meio de um arquivo de milhares de linhas
  não derruba a execução.

- **`instancia_do_grau` como ponto único de tradução.** A docstring é literal: *"Ponto
  único de tradução domínio -> e-SAJ"*. Grau desconhecido vira `ValueError` com o valor
  recebido, em vez de um `KeyError` cru:

  ```python
  def instancia_do_grau(grau):
      """1 -> 'cpopg', 2 -> 'cposg'. Ponto único de tradução domínio -> e-SAJ."""
      try:
          return _INSTANCIA_POR_GRAU[grau]
      except KeyError:
          raise ValueError(f"Grau desconhecido: {grau!r}") from None
  ```

- **`params_busca(grau)` concentra a query string do `search.do`.** A docstring diz o que
  isso compra: *"ÚNICO ponto a ajustar se o e-SAJ mudar."* E há um detalhe que justifica
  o método existir: **os dois graus usam nomes de parâmetro diferentes para a mesma
  coisa**. O 1º grau manda `dadosConsulta.valorConsultaNuUnificado`; o 2º manda
  `dePesquisaNuUnificado`. Espalhar isso pelo cliente HTTP significaria dois blocos de
  `if instancia == "cpopg"` em lugares distintos.

- **Roteamento de grau derivado da própria estrutura do número.** Origem `0000` indica
  processo autuado originariamente no 2º grau:

  ```python
  @property
  def originario_segundo_grau(self):
      """Origem '0000' = autuado originariamente no 2º grau (Res. 65/2008,
      art. 1º §1º-A). Ex.: Agravo de Instrumento, Ação Rescisória."""
      return self.origem == "0000"
  ```

  `graus_a_tentar` usa isso para devolver `(GRAU_SEGUNDO,)` nesses casos e
  `(GRAU_PRIMEIRO, GRAU_SEGUNDO)` nos demais — uma requisição economizada por agravo,
  sem heurística nenhuma: é o que a Resolução define. A docstring da propriedade também
  registra a regra que o [`coletor`](coletor.md) implementa:

  > O orquestrador só avança para o grau seguinte se o e-SAJ disser NAO_ENCONTRADO
  > explicitamente; erro de rede NUNCA faz avançar.

- **`do_tjsp` valida o alvo antes de gastar requisição.** Segmento `8` (Justiça Estadual)
  e tribunal `26` (São Paulo). A docstring explica o ganho: *"Fora disso, o e-SAJ do TJSP
  não responde — vale avisar na entrada em vez de gastar requisição."* Com a cadência
  global de uma requisição a cada 1,7–2,5s, descartar na leitura do arquivo é
  qualitativamente diferente de descobrir na rede.

- **`__eq__` e `__hash__` sobre os dígitos.** Dois `NumeroProcesso` construídos a partir
  de grafias diferentes do mesmo número (com máscara, sem máscara, com ponto em vez de
  hífen) são iguais e colidem no mesmo `hash`, porque `so_digitos` normaliza tudo na
  construção.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Passar o número como `str` e usar funções soltas (`mascara(num)`, `dv_ok(num)`) | Cada camada teria de lembrar de validar antes de usar. Com o value object, receber um `NumeroProcesso` já é a garantia de que ele tem 20 dígitos. |
| Levantar `NumeroProcessoInvalido` também quando o DV não fecha | Tiraria do chamador uma decisão que tem duas respostas certas: na entrada o número vai para `numeros_invalidos.txt`; num vínculo, ele vira observação e a aresta é descartada. Ver [`exceptions`](exceptions.md). |
| Guardar o `grau` dentro do `NumeroProcesso` | O mesmo número existe em 1º e 2º grau. Amarrar o grau ao número reproduziria a colisão de chave que embaralhou o relacionamento no pipeline anterior. |
| Falar em `'cpopg'`/`'cposg'` no domínio inteiro | O vocabulário do e-SAJ vazaria para o coletor, o banco e a base final. Se o portal renomear as instâncias, a mudança teria de ser rastreada em toda parte em vez de numa linha do `_INSTANCIA_POR_GRAU`. |
| Montar a query string dentro do `EsajClient` | O cliente passaria a conhecer a estrutura do número CNJ. Como os dois graus usam nomes de parâmetro distintos, o `if` de instância apareceria duas vezes, em módulos diferentes. |
| Tentar sempre os dois graus, na ordem 1 → 2 | Desperdiçaria uma requisição em todo processo originário do 2º grau (agravo, rescisória), que por definição nunca existiu em 1ª instância. |
| `NumeroProcesso` mutável, sem `__slots__` | Permitiria anexar estado por fora (`np.grau`, `np.status`) e criar duas fontes de verdade para a mesma informação. |

## Limitações Conhecidas

- **`dv_valido` não é consultado na construção.** É perfeitamente possível ter um
  `NumeroProcesso` com 20 dígitos e DV incorreto circulando pelo pipeline — é uma
  decisão, não um descuido, mas exige que cada ponto de entrada lembre de checar.
  `ler_numeros`, em `scripts/menu.py`, checa; a lista de órfãos passa pelo mesmo
  `ler_numeros`, e portanto também.

- **`do_tjsp` cobre apenas segmento e tribunal.** Um número da Justiça Estadual de São
  Paulo com origem inexistente (foro que nunca existiu) passa na validação e só será
  descoberto quando o e-SAJ responder `NAO_ENCONTRADO`.

- **`__eq__` e `__hash__` estão implementados mas nenhum caminho atual os exercita.** A
  desduplicação em `ler_numeros` é feita sobre `np.digitos` (strings), não sobre
  instâncias:

  ```python
  if np.digitos in vistos:
      continue
  vistos.add(np.digitos)
  ```

  Os dunder existem para quando alguém quiser usar o objeto como chave, mas hoje são
  código não exercitado.

- **Números anteriores ao padrão CNJ não são representáveis.** Um `'26747/2005'` não tem
  20 dígitos e é rejeitado no construtor. O projeto lida com isso fora daqui: o
  [`parser_segundo_grau`](parser_segundo_grau.md) guarda a string original em
  `processo_1a_instancia_bruto` e o [`vinculo`](../transformers/vinculo.md) a transforma
  em observação, em vez de aresta no grafo.

## Exemplo de Uso

Leitura e validação de um arquivo de entrada, como faz `scripts/menu.py`:

```python
np = NumeroProcesso.tentar(linha)
if np is None:
    invalidos.append(f"{linha}\t(não tem 20 dígitos)")
    continue
if not np.dv_valido:
    invalidos.append(f"{linha}\t(DV inválido; esperado {np.dv_esperado})")
    continue
if not np.do_tjsp:
    invalidos.append(f"{linha}\t(não é TJSP: J={np.segmento} TR={np.tribunal})")
    continue
```

Consulta ao e-SAJ, em `EsajClient.buscar` — o cliente nunca monta a query sozinho:

```python
url = f"{self.BASE}/{instancia_do_grau(grau)}/search.do"
return self._get(url, params=numero_processo.params_busca(grau))
```

Roteamento de grau, em `coletar_um`:

```python
for grau in np.graus_a_tentar:
```

E o diagnóstico do `scripts/spike_seletores.py`, que imprime de uma vez os campos que
decidem o comportamento:

```python
print(f"  dígitos={np.digitos} | origem={np.origem} | DV válido={np.dv_valido} "
      f"| graus a tentar={np.graus_a_tentar}")
```

## Testes e Validação

Não há testes automatizados neste repositório. A validação em uso é a inspeção manual
via `scripts/spike_seletores.py`, que reporta `digitos`, `origem`, `dv_valido` e
`graus_a_tentar` para cada número antes de qualquer requisição, e o próprio arquivo
`numeros_invalidos.txt` gerado pela opção 1 do `scripts/menu.py`, que registra número e
motivo da rejeição, linha a linha.

Este é o módulo mais barato de cobrir com testes unitários do projeto inteiro: é puro,
não faz I/O e todas as respostas são deriváveis de um número conhecido. As invariantes
que valeria fixar primeiro:

- número com máscara, sem máscara e com ponto no lugar do hífen produzem o mesmo
  `digitos`;
- `dv_esperado` reproduz o DV de um número real conhecido;
- `origem == "0000"` ⇒ `graus_a_tentar == (2,)`; caso contrário, `(1, 2)`;
- `params_busca(1)` e `params_busca(2)` devolvem conjuntos de chaves diferentes — a
  regressão mais provável se alguém tentar unificar os dois formatos.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |

## Pontos em aberto

- **A extração de dígitos está repetida em cinco módulos.** Este expõe
  `so_digitos(valor)`; `src/transformers/vinculo.py` define `_digitos(valor)` com corpo
  equivalente; e `src/scrapers/page_state.py`, `src/scrapers/parser_base.py` e
  `src/scrapers/parser_segundo_grau.py` fazem `re.sub(r"\D", "", ...)` diretamente.
  Nenhum deles importa `so_digitos`. Não está claro se a duplicação é deliberada (manter
  `page_state` e os parsers independentes do value object) ou acidental — vale registrar
  porque o
  [`limpeza`](../transformers/limpeza.md) foi criado justamente para consolidar as quatro
  implementações de data do pipeline anterior, e este é o mesmo padrão.

- **A validação de DV também está duplicada.** `dv_esperado`/`dv_valido` aqui e
  `_dv_ok(d20)` em `src/transformers/vinculo.py` implementam o mesmo cálculo ISO 7064
  MOD 97-10 sobre representações diferentes (objeto × string de 20 dígitos). Uma
  correção na fórmula precisaria ser feita nos dois lugares.

- **A máscara também.** A propriedade `mascara` monta `NNNNNNN-DD.AAAA.J.TR.OOOO` a partir
  do objeto; `_mascara(d20)` em `src/transformers/projecao.py` monta o mesmo formato a
  partir de uma string do banco. Aqui há uma razão plausível — a projeção é pura e opera
  sobre linhas do SQLite, sem construir value objects —, mas o formato de saída passa a
  ter dois donos.
