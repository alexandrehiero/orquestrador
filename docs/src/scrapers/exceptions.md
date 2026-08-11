# Exceções de domínio – `src/scrapers/exceptions.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | nenhuma (apenas biblioteca padrão)     |

## Contexto e Motivação

O pipeline tem três camadas que precisam falar sobre os mesmos erros: o value object
`NumeroProcesso` (validação de entrada), o cliente HTTP `EsajClient` (rede) e os parsers
(leitura da capa). Se cada uma definisse sua própria exceção, o cliente precisaria
importar o value object para levantar `NumeroProcessoInvalido` e o value object
precisaria importar o cliente para capturar erros de rede — import circular.

Concentrar as exceções num módulo sem dependência nenhuma corta o ciclo: todo mundo
importa `exceptions`, e `exceptions` não importa ninguém. É a razão explícita registrada
na docstring do módulo:

> Centralizar as exceções aqui evita imports circulares entre o value object
> `NumeroProcesso`, o cliente HTTP e os parsers.

Mas o módulo carrega uma decisão bem maior que organização de imports: **a hierarquia
codifica quem pode ser capturado e quem tem de derrubar a execução.**

## Decisões de Arquitetura

- **`EsajError` como base de operações contra o e-SAJ.** É o guarda-chuva que significa
  "esta falha é *deste* processo, siga para o próximo". Quem quer capturar tudo que veio
  do e-SAJ usa a base — é o caso de `scripts/spike_seletores.py`, que assim não aborta o
  diagnóstico num número que falhou. Quem quer ser específico captura a subclasse — é o
  caso de `coletar_um`, que só trata `EsajRequisicaoError`.

- **`EsajRequisicaoError(EsajError)` — falha de rede que sobreviveu às retentativas.**
  Levantada por `EsajClient._levantar_falha` só depois de esgotar `max_tentativas`.
  Quem captura é `coletar_um`, que a converte em `erro_transitorio` sem tocar no grau
  seguinte.

    O nome do método que a levanta não é acidental: `_levantar_falha` **sempre** levanta,
    uma das duas exceções, nunca retorna. `_get` depende disso — não há `return` depois do
    laço de retentativa, e um caminho que retornasse devolveria `None` como se fosse HTML.
    O contrato ficou no identificador justamente porque antes vivia num comentário. Ver
    [`esaj_client`](esaj_client.md).

- **`EsajIndisponivelError(RuntimeError)` — NÃO herda de `EsajError`, de propósito.**
  Esta é a decisão central do módulo, e a docstring a justifica sem meias palavras:

  ```python
  class EsajIndisponivelError(RuntimeError):
      """Falhas consecutivas demais: o e-SAJ caiu ou bloqueou o acesso.

      NÃO herda de EsajError de propósito. O laço de coleta trata EsajError como
      'falha deste processo' e segue adiante; se esta exceção fosse EsajError,
      o script continuaria queimando ~12s por número numa fila de 500 mil,
      marcando tudo como falha. Ela precisa ABORTAR a execução.
      """
  ```

  A herança **é** o mecanismo de controle. Como `EsajIndisponivelError` está fora da
  árvore de `EsajError`, todo `except EsajError` existente no projeto a deixa passar
  por construção — não há como um `except` bem-intencionado engolir o circuit breaker
  por descuido. Em `scripts/menu.py` ela é capturada num ponto só, e para parar de
  submeter trabalho novo:

  ```python
  except EsajIndisponivelError as erro:
      # Para de submeter, mas drena o que já está em voo:
      # esses resultados foram pagos e não podem ser perdidos.
      parada = str(erro)
      continue
  ```

- **`NumeroProcessoInvalido(ValueError)` — herda de `ValueError`, não de `EsajError`.**
  Número CNJ malformado é erro de *entrada*, não de comunicação com o e-SAJ: acontece
  antes de qualquer requisição. Herdar de `ValueError` mantém a semântica que qualquer
  programador Python espera de um construtor que recebeu argumento inválido. E, de novo,
  ficar fora de `EsajError` importa: um número inválido não deve ser contabilizado como
  falha de coleta.

  Ela só é levantada quando os dígitos não somam 20. Dígito verificador incorreto **não**
  levanta exceção — quem decide o que fazer é o chamador, como registra a docstring de
  `numero_processo.py`.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Uma única exceção (`EsajError`) para tudo, com um campo `fatal=True/False` | O `except` deixaria de discriminar. Todo ponto de captura teria de lembrar de reerguer quando `fatal` fosse verdadeiro — e esquecer disso em **um** lugar reintroduz exatamente a falha que o circuit breaker existe para evitar. A hierarquia faz o compilador de exceções trabalhar por nós. |
| `EsajIndisponivelError` herdando de `EsajError` | Seria capturada por todo `except EsajError` do projeto, e a queda do e-SAJ marcaria a fila inteira como falha ao custo de ~12s por número. É o cenário descrito na própria docstring. |
| Definir cada exceção no módulo que a levanta | Import circular entre `numero_processo`, `esaj_client` e os parsers — o problema declarado na docstring do módulo. |
| `NumeroProcessoInvalido` herdando de `EsajError` | Confundiria erro de entrada com erro de rede: um `.txt` com números malformados inflaria as métricas de falha do e-SAJ e poderia até contar para o circuit breaker. |
| Levantar exceção também para DV inválido | Tiraria a decisão do chamador. Na entrada, DV inválido vai para `numeros_invalidos.txt`; num relacionamento, vira observação e o vínculo é ignorado (`vinculo._dv_ok`). São respostas diferentes para o mesmo fato. |

## Limitações Conhecidas

- O módulo não tem estado nem carrega contexto estruturado: `EsajRequisicaoError` embute
  a URL na mensagem em vez de expor um atributo `url`. Quem quiser agregar falhas por
  endpoint precisa fazer parsing de string.
- `EsajIndisponivelError` herda de `RuntimeError` e não de `BaseException`. Um
  `except Exception` genérico ainda a captura. O projeto evita esse padrão, mas nada no
  módulo impede que apareça — a única barreira efetiva é não escrever `except Exception`
  no caminho de coleta. Vale notar que `scripts/spike_seletores.py` usa
  `except Exception` no laço de `main()`; lá é aceitável, porque o spike é diagnóstico e
  não grava nada.
- Não há exceção específica para "página não reconhecida" ou "seleção irresolvível".
  Esses casos não viram exceção: `coletar_um` os devolve como `ResultadoColeta` com
  status `erro_transitorio` e um `motivo` em texto.

## Exemplo de Uso

As duas capturas reais do projeto, que mostram a hierarquia funcionando:

```python
from .exceptions import EsajRequisicaoError

for grau in np.graus_a_tentar:
    try:
        html = client.buscar(np, grau)
    except EsajRequisicaoError as erro:
        # NÃO tenta o próximo grau: não sabemos se o processo está aqui.
        return _erro(f"falha de rede no grau {grau}: {erro}", grau)
```

*(`src/scrapers/coletor.py`)*

`EsajIndisponivelError` atravessa esse `except` sem ser capturada — ela não é
`EsajRequisicaoError` — e sobe até `scripts/menu.py`, que interrompe a submissão de
trabalho novo.

O levantamento fica num ponto só, `EsajClient._levantar_falha` — e é ali que a escolha
entre "falha deste processo" e "parada geral" acontece:

```python
def _levantar_falha(self, url, ultimo_erro):
    """SEMPRE levanta. O nome carrega o contrato — antes ele existia só num
    comentário, e um `return` acidental no chamador devolveria None como se
    fosse HTML."""
    abrir, seguidas = self.monitor.falha()
    if abrir:
        raise EsajIndisponivelError(...) from ultimo_erro

    raise EsajRequisicaoError(
        f"Falha após {self.max_tentativas} tentativas em {url}"
    ) from ultimo_erro
```

Duas coisas nessa desestruturação merecem atenção de quem for mexer aqui.

**`falha()` devolve uma tupla, não um booleano.** `abrir, seguidas = ...` é o único uso
correto. Escrever `if self.monitor.falha():` — a forma óbvia, e a que a assinatura antiga
autorizava — passaria a ser um bug silencioso e grave: toda tupla não vazia é verdadeira em
Python, então a condição seria satisfeita **sempre**, e a primeira falha de rede de toda a
execução abriria o circuito e abortaria a coleta. O `if` não daria erro de tipo, não
emitiria aviso e faria exatamente o oposto do pretendido.

**O contador volta junto por causa do lock.** `seguidas` é usado na mensagem de
`EsajIndisponivelError`, e quem monta a mensagem está fora da região protegida do
`MonitorFalhas`. Reler `self.monitor.falhas_seguidas` depois do retorno traria o valor
naquele instante — possivelmente já incrementado ou zerado por outra thread —, e a exceção
citaria um número que nunca disparou coisa alguma. Devolvendo o contador junto da decisão,
o número da mensagem é, por construção, o mesmo que produziu a abertura.

E a validação de entrada, em `NumeroProcesso.__init__`:

```python
raise NumeroProcessoInvalido(
    f"Número CNJ deve ter 20 dígitos após limpeza; "
    f"recebido {len(digitos)} a partir de {valor!r}."
)
```

## Testes e Validação

Não há testes automatizados neste repositório — nem para este módulo, nem para os
demais. A validação disponível é manual, via `scripts/spike_seletores.py`, que exercita
o caminho de erro ao capturar `EsajError` por número:

```python
except EsajError as erro:
    print(f"  FALHA: {erro!r}")
    continue
```

O comportamento de `EsajIndisponivelError` (abortar em vez de ser capturada) é
verificável na prática desligando a rede durante uma execução da opção 1 do
`scripts/menu.py`: após 20 falhas seguidas — o `limite` padrão de `MonitorFalhas` — a
execução precisa parar e imprimir a mensagem de interrupção, em vez de continuar
consumindo a fila.

Como o módulo é puro (sem I/O, sem dependências externas), é o candidato mais barato a
receber os primeiros testes unitários do projeto: basta afirmar que
`issubclass(EsajIndisponivelError, EsajError)` é `False` — a invariante da qual todo o
resto depende.

Vale acrescentar uma segunda, que cobre o ponto de levantamento: com um `MonitorFalhas` de
`limite` alto e uma única falha, `_levantar_falha` precisa levantar `EsajRequisicaoError` e
**não** `EsajIndisponivelError` — a asserção que pegaria a leitura da tupla como booleano.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Correção: `_registrar_falha` → `_levantar_falha`; o exemplo tratava o retorno de `falha()` como booleano, quando hoje é `(abrir, falhas_seguidas)` |
