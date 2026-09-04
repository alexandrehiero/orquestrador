# Número Único CNJ – `src/scrapers/numero_processo.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `re` — só `src/scrapers/exceptions.py` do projeto |

## Contexto e Motivação

O número de processo é o identificador em torno do qual gira o pipeline inteiro: é a entrada do `.txt`, a chave do banco, o parâmetro da busca no e-SAJ, o alvo da conferência de identidade e o `_id` do documento final. Tratado como `str`, cada camada precisaria saber recortar posições, remontar máscara e recalcular dígito verificador — e cada uma faria isso um pouco diferente.

Este módulo transforma o número num **value object**: imutável na prática, que nasce validado e sabe responder tudo que o pipeline pergunta. A estrutura vem da Resolução CNJ 65/2008: `NNNNNNN-DD.AAAA.J.TR.OOOO`, 20 dígitos.

Há uma segunda motivação. O e-SAJ organiza a consulta por **instância** (`cpopg`, `cposg`), mas o domínio fala em **grau**. Todo o resto do projeto passa `grau=1` ou `grau=2`; a tradução acontece num lugar só.

## Decisões de Arquitetura

- **Value object, não string com funções auxiliares** — `NumeroProcesso("...")` ou falha na construção ou é um número de 20 dígitos: não existe instância inválida circulando. As propriedades recortam o dígito na posição certa uma vez só, e ninguém mais precisa lembrar que o tribunal são os dígitos 14 e 15.
- **`__slots__ = ("_d",)`** — elimina o `__dict__` por instância e impede que alguém acrescente um atributo por engano: `np.grau = 2` levantaria `AttributeError` em vez de criar silenciosamente um estado que o resto do código não conhece.
- **O grau NÃO é atributo do número** — o mesmo número pode existir em 1º e 2º grau, e é justamente por isso que a chave do banco é o par `(processo, grau)`.
- **Só tamanho ≠ 20 é erro duro; DV inválido não levanta exceção** — o mesmo fato ("este DV não fecha") tem duas respostas legítimas conforme onde aparece: na entrada, o número vai para `numeros_invalidos.txt`; num vínculo, vira observação e a aresta é descartada. O value object não tem como saber qual é o caso, então expõe `dv_valido` e `dv_esperado` e deixa a política para quem chamou.
- **`tentar()` como construtor alternativo que devolve `None`** — para laços que não podem quebrar. Os três chamadores reais usam essa forma, nenhum precisa de `try/except`, e um número podre no meio de um arquivo de milhares de linhas não derruba a execução.
- **`instancia_do_grau` é o ponto único de tradução domínio → e-SAJ** — grau desconhecido vira `ValueError` com o valor recebido, em vez de um `KeyError` cru.
- **`params_busca(grau)` concentra a query string do `search.do`** — e o método existe por um detalhe concreto: **os dois graus usam nomes de parâmetro diferentes para a mesma coisa** (`dadosConsulta.valorConsultaNuUnificado` no 1º, `dePesquisaNuUnificado` no 2º). Espalhar isso pelo cliente HTTP significaria dois blocos de `if instancia == "cpopg"` em lugares distintos. É o único ponto a ajustar se o e-SAJ mudar.
- **O roteamento de grau é derivado da própria estrutura do número** — origem `0000` indica processo autuado originariamente no 2º grau (Res. 65/2008, art. 1º §1º-A): agravo de instrumento, ação rescisória. `graus_a_tentar` devolve `(2,)` nesses casos e `(1, 2)` nos demais. Uma requisição economizada por agravo, sem heurística: é o que a Resolução define.
- **`do_tjsp` valida o alvo antes de gastar requisição** — segmento `8` (Justiça Estadual) e tribunal `26` (São Paulo). Com a cadência de uma requisição a cada 1,7–2,5 s, descartar na leitura do arquivo é qualitativamente diferente de descobrir na rede.
- **`__eq__` e `__hash__` operam sobre os dígitos** — dois números construídos a partir de grafias diferentes (com máscara, sem, com ponto no lugar do hífen) são iguais e colidem no mesmo `hash`, porque `so_digitos` normaliza tudo na construção.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Passar o número como `str` e usar funções soltas | Cada camada teria de lembrar de validar antes de usar. Receber um `NumeroProcesso` já é a garantia dos 20 dígitos. |
| Levantar exceção também quando o DV não fecha | Tiraria do chamador uma decisão que tem duas respostas certas conforme o contexto. |
| Guardar o `grau` dentro do `NumeroProcesso` | O mesmo número existe em 1º e 2º grau. Amarrar o grau ao número reproduziria a colisão de chave que embaralhou o relacionamento no pipeline anterior. |
| Falar em `'cpopg'`/`'cposg'` no domínio inteiro | O vocabulário do e-SAJ vazaria para o coletor, o banco e a base final. Se o portal renomear as instâncias, a mudança teria de ser rastreada em toda parte. |
| Montar a query string dentro do `EsajClient` | O cliente passaria a conhecer a estrutura do CNJ. Como os dois graus usam nomes distintos, o `if` de instância apareceria duas vezes, em módulos diferentes. |
| Tentar sempre os dois graus, na ordem 1 → 2 | Desperdiçaria uma requisição em todo processo originário do 2º grau, que por definição nunca existiu em 1ª instância. |
| `NumeroProcesso` mutável, sem `__slots__` | Permitiria anexar estado por fora (`np.grau`, `np.status`) e criar duas fontes de verdade para a mesma informação. |

## Limitações Conhecidas

- **`dv_valido` não é consultado na construção.** É possível ter um `NumeroProcesso` com 20 dígitos e DV incorreto circulando — decisão, não descuido, mas exige que cada ponto de entrada lembre de checar. `ler_numeros` checa, e a lista de órfãos passa pelo mesmo `ler_numeros`.
- **`do_tjsp` cobre apenas segmento e tribunal.** Um número de São Paulo com origem inexistente passa na validação e só será descoberto quando o e-SAJ responder `NAO_ENCONTRADO`.
- **`__eq__` e `__hash__` não são exercitados por nenhum caminho atual.** A desduplicação em `ler_numeros` é feita sobre `np.digitos` (strings), não sobre instâncias. Existem para quando alguém quiser usar o objeto como chave.
- **Números anteriores ao padrão CNJ não são representáveis.** Um `'26747/2005'` é rejeitado no construtor. O projeto lida com isso fora daqui: o [`parser_segundo_grau`](parser_segundo_grau.md) guarda a string original e o [`vinculo`](../transformers/vinculo.md) a transforma em observação.
- **`so_digitos` é reimplementado em outros cinco lugares.** Ver [backlog §1](../../backlog.md).

## Exemplo de Uso

```python
from src.scrapers.numero_processo import NumeroProcesso, instancia_do_grau

np = NumeroProcesso("1000858-24.2022.8.26.0396")   # aceita com ou sem máscara
np.digitos                    # '10008582420228260396'
np.dv_valido, np.dv_esperado  # (True, '24')
np.do_tjsp                    # True  -> segmento 8, tribunal 26
np.graus_a_tentar             # (1, 2)

NumeroProcesso("3000004-25.2019.8.26.0000").graus_a_tentar   # (2,)  <- origem '0000'
NumeroProcesso.tentar("lixo")                                 # None <- não levanta
instancia_do_grau(1)                                          # 'cpopg'
```

`NumeroProcesso("123")` levanta `NumeroProcessoInvalido`: tamanho é o único erro duro.

## Testes e Validação

Não há suíte automatizada. A validação em uso é a inspeção manual via `scripts/spike_seletores.py`, que reporta `digitos`, `origem`, `dv_valido` e `graus_a_tentar` antes de qualquer requisição, mais o `numeros_invalidos.txt` gerado pela opção 1, que registra número e motivo da rejeição linha a linha.

**Este é o módulo mais barato de cobrir do projeto inteiro:** é puro, não faz I/O e todas as respostas são deriváveis de um número conhecido. As 4 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): código copiado removido; invariantes migradas para o backlog de testes |
