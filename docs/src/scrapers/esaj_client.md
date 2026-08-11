# Cliente HTTP do e-SAJ – `src/scrapers/esaj_client.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `curl_cffi`, `threading`, `random`, `time` (biblioteca padrão) |

## Contexto e Motivação

Este é o **único** módulo do projeto que toca a rede. A primeira linha da docstring o diz
com todas as letras, e essa exclusividade é o que torna as garantias do módulo
verificáveis: se nenhum outro arquivo importa `curl_cffi`, então nenhuma requisição
escapa da cadência anti-ban.

O segundo fato que molda o módulo é uma peculiaridade do portal:

> O e-SAJ responde HTTP 200 tanto para 'não encontrado' quanto para 'segredo de
> justiça' — a mensagem vem no corpo. Este cliente NÃO decide semântica; devolve
> o HTML e quem classifica é o ClassificadorPagina.

Ou seja: o código de status HTTP não carrega informação de domínio. Um cliente que
tentasse interpretar `200` como sucesso estaria certo tecnicamente e errado no que
importa. A separação é rígida — este módulo entrega texto, o
[`page_state`](page_state.md) entrega significado.

O terceiro é uma coleta que dura semanas contra um portal público que pode cair, entrar
em manutenção ou bloquear o acesso. Uma coleta longa sem detecção de indisponibilidade
não falha: ela **conclui com sucesso aparente**, marcando a fila inteira como erro.

## Decisões de Arquitetura

### Anti-ban por construção: todo GET passa por `_get`

Não existe caminho alternativo. `buscar` e `abrir_detalhe` — os dois únicos métodos
públicos que fazem rede — delegam a `_get`, e `_get` começa chamando `self._dormir()`.
O nome do método foi mantido de propósito:

```python
def _dormir(self):
    """Nome mantido: todo GET passa por aqui, então é impossível esquecer."""
    self.pacer.aguardar()
```

A alternativa — deixar o `sleep` a cargo de quem chama, como um script de coleta comum
faz — depende de disciplina humana em cada ponto de chamada. Basta esquecer em um
caminho para o projeto inteiro perder a garantia, e esse caminho seria justamente o menos
testado.

### Pacer: intervalo **entre** requisições, não sono somado a cada uma

Esta é a decisão central do módulo. A docstring do `Pacer` compara as duas abordagens com
os números do pipeline anterior:

> Diferença frente ao sleep aditivo: lá o ciclo era sleep + latência (3,5s
> para um alvo de 2,1s) — metade da espera não protegia ninguém, só somava a
> latência ao sono. Aqui a latência cabe DENTRO do intervalo.

No modelo aditivo, `sleep(2.1)` seguido de uma requisição que leva 1,4s produz um ciclo de
3,5s. O alvo era 2,1s; a diferença não protege o servidor de nada — só torna a coleta 60%
mais lenta. O `Pacer` inverte a pergunta: em vez de "quanto durmo depois de cada
requisição?", ele responde "quando é o próximo horário livre?". A latência da requisição
anterior é consumida **dentro** do intervalo, não somada a ele.

```python
def aguardar(self):
    with self._lock:
        agora = time.monotonic()
        espera = max(0.0, self._proximo - agora)
        # max(agora, ...) impede acumular crédito quando ficou ocioso.
        self._proximo = max(agora, self._proximo) + random.uniform(
            self.minimo, self.maximo
        )
    if espera > 0:
        time.sleep(espera)
```

Três detalhes densos nessas dez linhas:

- **`max(agora, self._proximo)`** — sem isso, uma pausa longa (o pesquisador foi almoçar,
  o notebook suspendeu) deixaria `_proximo` no passado, e a fila dispararia uma rajada de
  requisições instantâneas ao retomar. O `max` descarta o "crédito" acumulado durante a
  ociosidade. É a linha que separa uma cadência de um limitador de vazão ingênuo.
- **O slot é reservado dentro do lock; o `sleep` acontece fora dele.** A docstring
  registra o porquê: *"senão as threads serializariam no próprio lock"*. Se o `sleep`
  ficasse dentro do `with`, cada thread bloquearia todas as outras durante a espera, e o
  pool de workers viraria um laço sequencial com passos extras.
- **`random.uniform(minimo, maximo)`** — o intervalo é sorteado a cada slot, não fixo. Um
  intervalo constante produz um padrão de tráfego regular, que é exatamente o que
  detecção de automação procura.

### O Pacer é global: workers **não** aumentam a taxa vista pelo e-SAJ

A docstring é explícita quanto ao que a thread-safety compra aqui:

> Thread-safe de propósito: o limite é do AGREGADO, não de cada thread. Vários
> workers compartilhando um Pacer não aumentam a taxa vista pelo e-SAJ; eles
> só evitam que um pico de latência numa página deixe a fila ociosa.

Isto merece ser lido devagar, porque contraria a intuição de "mais workers = mais
requisições por segundo". Com um `Pacer` compartilhado, o teto continua sendo **uma
requisição a cada 1,7–2,5s**, independentemente de haver 1 ou 3 workers. O que os workers
resolvem é outro problema: quando uma página específica demora 8s para responder, o
modelo de thread única deixa os slots seguintes passarem em branco. Com o pool, outro
worker ocupa o slot enquanto o primeiro espera. **A taxa não sobe; a ociosidade cai.**

É por isso que `scripts/menu.py` cria `Pacer()` e `MonitorFalhas()` uma única vez e os
injeta em todos os clientes.

### Circuit breaker compartilhado: `MonitorFalhas`

Sem ele, uma queda do e-SAJ tem um custo assimétrico e silencioso. O comentário do topo
do módulo quantifica:

> CIRCUIT BREAKER: N requisições seguidas falhando aborta a execução. Sem ele,
> uma queda do e-SAJ faz a fila inteira consumir ~12s por número (3 tentativas
> + backoff) e marcar tudo como falha — descoberto só horas depois.

O contador é compartilhado pelo mesmo motivo que o `Pacer`:

> Cada worker tem sua própria Session (curl_cffi não é thread-safe), mas o
> circuito é um só: com contadores por cliente, 3 workers precisariam de 60
> falhas consecutivas para abrir o que deveria abrir em 20.

E o reset em `sucesso()` carrega uma decisão de política:

```python
def sucesso(self):
    with self._lock:
        self.operacoes += 1
        self.falhas_seguidas = 0  # falhas esparsas nunca abrem o circuito
```

Falhas **consecutivas**, não acumuladas. Uma base grande sempre produz alguns timeouts
esparsos; o circuito só deve abrir quando o padrão indica que o problema não é do
processo, é do portal.

Quando abre, a exceção escolhida é `EsajIndisponivelError`, que **não** herda de
`EsajError` — ver [`exceptions`](exceptions.md). É essa escolha de hierarquia que garante
que nenhum `except` do caminho de coleta a capture por engano. A mensagem é escrita para
o pesquisador, não para o log:

> A execução foi interrompida para não marcar a fila inteira como falha. Nada foi
> perdido: o checkpoint no banco permite retomar exatamente daqui.

### `falha()` devolve a decisão **e** o contador que a produziu

```python
def falha(self):
    """Devolve (deve_abrir_o_circuito, falhas_seguidas).

    O contador volta junto para que o chamador monte a mensagem sem ler o
    atributo fora do lock — leitura que poderia trazer o valor de outra
    thread e citar um número que nunca existiu.
    """
    with self._lock:
        self.operacoes += 1
        self.falhas += 1
        self.falhas_seguidas += 1
        return self.falhas_seguidas >= self.limite, self.falhas_seguidas
```

Um booleano puro seria suficiente para **decidir**, e é por isso que a assinatura antiga
funcionava. O problema era outro: a mensagem de erro precisa citar o número de falhas, e
quem a monta está fora do lock. Reler `self.monitor.falhas_seguidas` depois do retorno abre
uma janela em que outra thread já incrementou ou zerou o contador — a exceção diria "23
requisições seguidas falharam" num circuito calibrado em 20, ou pior, citaria um valor que
nunca disparou coisa alguma.

Devolver a tupla fecha a janela sem custo: o número que sai na mensagem é, por construção, o
mesmo que produziu a decisão. É uma correção de **diagnóstico**, não de comportamento — o
circuito sempre abriu na hora certa.

### `requisicoes` e `operacoes` contam coisas diferentes

Os dois contadores são declarados lado a lado, cada um com o seu significado:

```python
self.requisicoes = 0      # tentativas HTTP REAIS (retentativas incluídas)
self.operacoes = 0        # chamadas a _get (1 por página pedida)
```

O que os separa é **onde** cada um é incrementado. `operacoes` sobe em `sucesso()` e em
`falha()`, que rodam uma vez por `_get`, depois do laço de retentativa. `requisicoes` sobe
num método próprio, chamado imediatamente antes de cada `session.get`:

```python
def tentativa(self):
    """Uma requisição HTTP prestes a sair.

    Contada aqui, e não em sucesso/falha, porque um _get que retentou 3
    vezes fez 3 requisições e uma operação. Contar só a operação subnotifica
    justamente o tráfego que o anti-ban precisa vigiar.
    """
```

```python
self._dormir()  # cadência anti-ban em TODA requisição
self.monitor.tentativa()  # conta a requisição que vai sair
resp = self.session.get(url, params=params, timeout=self.timeout)
```

A distinção existe porque as duas grandezas respondem a perguntas diferentes e divergem
exatamente quando a resposta importa. Um `_get` que falhou três vezes é **uma** página
pedida e **três** requisições contra o portal. Com um contador só, a métrica que se lê ao
final de uma execução com muitas falhas subnotifica o tráfego real por um fator de até
`max_tentativas` — e o tráfego real é justamente o que a cadência anti-ban existe para
limitar. Medir a carga sobre o e-SAJ pelo número de páginas pedidas seria medir o que se
queria, não o que se fez.

`tentativa()` é chamado **depois** de `_dormir()` e antes do envio: o contador reflete
requisições que de fato saíram, não intenções.

### `_levantar_falha`: o contrato saiu do comentário e foi para o nome

```python
def _levantar_falha(self, url, ultimo_erro):
    """SEMPRE levanta. O nome carrega o contrato — antes ele existia só num
    comentário, e um `return` acidental no chamador devolveria None como se
    fosse HTML."""
```

`_get` não tem `return` explícito depois do laço de retentativa — a correção da função
depende inteiramente de a última linha nunca retornar:

```python
        self._registrar_sucesso()
        return resp.text
    self._levantar_falha(url, ultimo_erro)
```

O nome antigo, `_registrar_falha`, descrevia contabilidade e não interrupção; quem lesse
`_get` precisava do comentário `# sempre levanta` para saber que a função não cai fora do
laço devolvendo `None`. E o modo de falha era silencioso: `None` chega ao `BeautifulSoup`
como HTML vazio, que o [`page_state`](page_state.md) classifica como `DESCONHECIDO` — o
processo vira `erro_transitorio` e volta para a fila indefinidamente, sem que nada aponte
para o cliente HTTP.

Renomear não altera uma linha de execução. Altera o que o próximo leitor assume ao
encontrar a chamada, que é onde o erro entraria.

### `except` restrito a erros de rede

```python
#: Erros que JUSTIFICAM retentativa. RequestException herda de OSError, então a
#: tupla cobre timeout, DNS, conexão recusada, SSL e 4xx/5xx do raise_for_status.
#: Erros de programação (TypeError, AttributeError) ficam DE FORA de propósito.
_ERROS_DE_REDE = (_ErroBiblioteca, OSError)
```

A docstring do módulo explica o que isso corrige:

> `except` restrito a erros de REDE. Um TypeError do nosso próprio código
> propaga em vez de virar 3 retentativas e um EsajRequisicaoError disfarçado.

Um `except Exception` no laço de retentativa transforma qualquer bug em falha de rede
aparente: o processo é tentado três vezes, marcado como `erro_transitorio`, devolvido à
fila e tentado de novo na execução seguinte — para sempre, sem que ninguém veja o
`TypeError`. Restringindo a tupla, um erro de programação sobe imediatamente e é corrigido
uma vez.

### Session por cliente, Pacer e monitor compartilhados

```python
# Pacer e monitor COMPARTILHADOS: uma cadência e um circuito para todos
# os workers. Só a Session é por cliente.
self.pacer = pacer or Pacer(sleep_min, sleep_max)
self.monitor = monitor or MonitorFalhas(limite_falhas_seguidas)
```

A `Session` do `curl_cffi` não é thread-safe, então cada worker precisa da sua — é o que
`menu.fabrica_cliente` monta com `threading.local()`. Mas duplicar o `Pacer` triplicaria
a taxa de requisições e duplicar o `MonitorFalhas` triplicaria o limiar do circuito. O
padrão `x or Padrão()` mantém o módulo utilizável sozinho (`EsajClient()` funciona, e é
como `scripts/spike_seletores.py` o usa) sem abrir mão da injeção quando há concorrência.

### Backoff com teto e jitter

```python
time.sleep(min(2 ** tentativa, 15) + random.uniform(0, 1))
```

Exponencial para dar tempo de o portal se recuperar, com **teto de 15s** para que
`max_tentativas` alto não produza esperas absurdas, e com jitter para que múltiplos
workers que falharam ao mesmo tempo não retentem em uníssono.

### `impersonate="chrome120"` sozinho: nenhum header manual

O `curl_cffi` é usado pela capacidade de imitar a impressão digital TLS/JA3 de um
navegador real — algo que `requests` não faz e que é a diferença entre ser atendido e ser
bloqueado por um WAF. O que o módulo registra, no lugar onde um `User-Agent` seria
declarado, é por que ele **não** existe:

```python
# NÃO definimos User-Agent manualmente. O `impersonate` do curl_cffi já monta o
# conjunto COMPLETO de headers do navegador escolhido — UA inclusive — junto com
# a impressão digital TLS/HTTP2 correspondente. Um UA nosso por cima só poderia
# divergir do resto do disfarce, que é justamente o que denuncia um cliente
# automatizado. Para mudar de navegador, troque só o parâmetro `impersonate`.
```

A premissa que um `User-Agent` manual carrega é a de que `impersonate` atua só na camada
TLS/HTTP2 e deixa os cabeçalhos por conta de quem chama. Ela é falsa: o `impersonate` monta
o perfil inteiro do navegador, cabeçalhos incluídos. Um UA escrito por cima não acrescenta
disfarce nenhum — ele só pode *estragar* o que já estava coerente.

E a incoerência é o sinal, não o valor. Um cliente que anuncia `Chrome/120` no cabeçalho
enquanto negocia TLS como `chrome124` não parece um Chrome antigo: parece exatamente o que
é, um cliente automatizado que montou o disfarce por partes. Detecção de bot procura essa
discordância antes de olhar a string do UA.

O ganho colateral é operacional. Antes havia dois valores que precisavam permanecer
sincronizados e nada no código os amarrava; hoje há **um** parâmetro, e o comentário diz
onde mexer — trocar `impersonate` troca o disfarce inteiro de uma vez.

```python
# Sem headers manuais: o impersonate já entrega o conjunto coerente.
self.session = curl_requests.Session(impersonate=impersonate)
```

O módulo também absorve uma incompatibilidade entre versões da biblioteca:

```python
try:  # curl_cffi recente
    from curl_cffi.requests.exceptions import RequestException as _ErroBiblioteca
except ImportError:  # versões antigas
    from curl_cffi.requests.errors import RequestsError as _ErroBiblioteca
```

### `abrir_detalhe` aceita três formas de endereço

Href absoluto, path relativo ou o código interno opaco do SAJ. É o que permite ao
[`coletor`](coletor.md) repassar direto o que o [`page_state`](page_state.md) extraiu da
tela de seleção, sem se importar se veio de um `<a href>` ou do `value` de um rádio.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| `requests` ou `httpx` | Não reproduzem a impressão digital TLS de um navegador. O `curl_cffi` com `impersonate` é a razão de o cliente ser atendido. |
| Selenium / Playwright | Peso e lentidão incompatíveis com centenas de milhares de processos; e a capa do e-SAJ é HTML servidor, não exige JavaScript. |
| `sleep` no script que chama, em vez de dentro do cliente | Depende de lembrar em cada ponto de chamada. Um caminho esquecido derruba a garantia inteira — e seria o caminho menos exercitado. |
| Sono fixo somado após cada requisição (modelo do pipeline anterior) | Soma a latência ao sono: 3,5s de ciclo para um alvo de 2,1s. A espera extra não protege o servidor, só reduz a vazão. |
| Intervalo constante em vez de `random.uniform` | Produz padrão de tráfego regular, que é o que detecção de automação identifica. |
| Um `Pacer` por worker | Multiplicaria a taxa real pelo número de workers — exatamente o que a decisão de cadência global existe para impedir. |
| Um `MonitorFalhas` por worker | Com 3 workers, seriam necessárias 60 falhas consecutivas para abrir um circuito calibrado em 20. |
| `sleep` dentro do lock do `Pacer` | As threads serializariam no próprio lock, anulando o pool. |
| `except Exception` no laço de retentativa | Transforma bug do nosso código em falha de rede aparente, que volta para a fila indefinidamente. |
| Circuito por total de falhas em vez de falhas consecutivas | Uma base grande acumula falhas esparsas legítimas; o circuito abriria sem que o portal tivesse caído. |
| Sem circuit breaker, confiando na leitura dos logs | Uma queda do e-SAJ consome ~12s por número e marca a fila inteira como falha, "descoberto só horas depois". |
| Definir `User-Agent` manualmente por cima do `impersonate` | O `impersonate` já entrega o conjunto completo de headers do navegador, UA inclusive. Um valor nosso por cima só pode divergir do resto do disfarce — e é a divergência entre cabeçalho e impressão digital que denuncia automação. |
| `falha()` devolvendo só um booleano | A mensagem da exceção precisa citar o contador, e o chamador está fora do lock. Reler o atributo depois traria o valor de outra thread, citando um número que nunca disparou o circuito. |
| Um contador único de requisições no `MonitorFalhas` | Um `_get` que retentou três vezes é uma operação e três requisições. Com um contador só, a carga real sobre o portal é subnotificada por até `max_tentativas` — justamente a métrica que o anti-ban precisa vigiar. |
| Manter o nome `_registrar_falha`, com o contrato num comentário | O nome descrevia contabilidade, não interrupção, e `_get` não tem `return` após o laço. Um `return` acidental devolveria `None` como se fosse HTML — que vira `DESCONHECIDO` e volta para a fila sem apontar para o cliente. |
| O cliente interpretar o HTML para decidir "não encontrado" | O e-SAJ devolve 200 para todos os casos. Misturar transporte e semântica impediria o [`page_state`](page_state.md) de ser testável sem rede. |

## Limitações Conhecidas

- **Não há tratamento de captcha.** Se o portal passar a exigir verificação humana, as
  páginas retornadas cairão em `DESCONHECIDO` no classificador e virarão
  `erro_transitorio` — o circuit breaker não dispara, porque do ponto de vista HTTP as
  requisições estão sendo bem-sucedidas.

- **O backoff de retentativa é somado à cadência do `Pacer`.** Uma requisição que falha
  três vezes consome três slots do `Pacer` mais duas esperas de backoff. É deliberado
  (backoff serve a outro propósito que a cadência), mas significa que o custo de um
  número que falha é bem maior que o de um que dá certo — a ordem de grandeza de ~12s
  citada na docstring do módulo.

- **`falhas` conta operações, não requisições.** Dos quatro números devolvidos por
  `estatisticas()`, só `requisicoes` mede tentativas HTTP reais. `falhas` é incrementado em
  `falha()`, uma vez por `_get`, depois do laço: um `_get` que falhou três vezes soma **3**
  a `requisicoes` e **1** a `falhas`. A razão `falhas / operacoes` é a taxa de páginas
  perdidas; a taxa de requisições que deram errado não é derivável dos contadores expostos.

- **O `Pacer` não é persistente.** Reiniciar o script zera `_proximo`, e a primeira
  requisição sai imediatamente. Em retomadas frequentes, o intervalo entre a última
  requisição da execução anterior e a primeira da nova não é respeitado.

- **Sem limite de tempo total nem de volume por execução.** O circuito abre por falhas
  consecutivas, não por "requisições demais nesta sessão".

- **A `Session` mantém cookies entre requisições e nunca é reciclada.** É o que faz a
  navegação seleção → detalhe funcionar, mas também significa que um cliente marcado pelo
  portal continua marcado até o fim da execução.

## Exemplo de Uso

Montagem com cadência e circuito compartilhados, em `scripts/menu.py`:

```python
def fabrica_cliente(pacer, monitor):
    """Um EsajClient por thread (a Session do curl_cffi não é thread-safe);
    Pacer e monitor de falhas compartilhados por todas."""
    def obter():
        cliente = getattr(_local, "cliente", None)
        if cliente is None:
            cliente = EsajClient(pacer=pacer, monitor=monitor)
            _local.cliente = cliente
        return cliente
    return obter
```

Uso avulso, sem concorrência — cada `EsajClient()` monta o próprio `Pacer` e o próprio
`MonitorFalhas` com os padrões. É como `scripts/spike_seletores.py` opera:

```python
client = EsajClient()
```

As duas operações de rede, como o [`coletor`](coletor.md) as encadeia:

```python
html = client.buscar(np, grau)
```

```python
html = client.abrir_detalhe(escolha.destino, grau)
```

E as métricas ao final de um diagnóstico:

```python
print(f"Estatísticas do cliente: {client.estatisticas()}")
```

## Testes e Validação

Não há testes automatizados neste repositório. A validação disponível é
`scripts/spike_seletores.py`, que exercita `buscar` nos dois graus para cada número,
salva o HTML recebido em `data/spike/` e imprime `estatisticas()` ao final — permitindo
conferir requisições e falhas contra o número de processos diagnosticados.

O que valeria fixar em teste, e é testável **sem rede**:

- `Pacer.aguardar()` chamado N vezes em sequência produz intervalos dentro de
  `[minimo, maximo]` — verificável com `time.monotonic()`;
- após uma ociosidade longa, a chamada seguinte **não** dispara imediatamente mais de um
  slot (a garantia do `max(agora, self._proximo)`);
- `MonitorFalhas` abre exatamente no `limite`-ésimo `falha()` consecutivo, e um `sucesso()`
  intercalado zera a contagem;
- `Pacer` compartilhado por T threads mantém a mesma taxa agregada que uma thread só —
  a afirmação de que workers não aumentam a taxa vista pelo e-SAJ.

O comportamento do circuit breaker de ponta a ponta é observável desligando a rede
durante a opção 1 do `scripts/menu.py`: após 20 falhas consecutivas a execução precisa
parar com a mensagem de indisponibilidade, em vez de consumir a fila.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Remoção do `User-Agent` manual; `MonitorFalhas` separa `requisicoes` de `operacoes` e ganha `tentativa()`; `falha()` devolve `(deve_abrir, falhas_seguidas)`; `_registrar_falha` renomeado para `_levantar_falha` |

## Pontos em aberto

Nenhum item em aberto.
