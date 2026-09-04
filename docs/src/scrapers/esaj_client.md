# Cliente HTTP do e-SAJ – `src/scrapers/esaj_client.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `curl_cffi`, `threading`, `random`, `time` |

## Contexto e Motivação

Este é o **único** módulo do projeto que toca a rede, e essa exclusividade é o que torna suas garantias verificáveis: se nenhum outro arquivo importa `curl_cffi`, nenhuma requisição escapa da cadência anti-ban.

O segundo fato que molda o módulo é uma peculiaridade do portal: **o e-SAJ responde HTTP 200 tanto para "não encontrado" quanto para "segredo de justiça"** — a mensagem vem no corpo. O código de status não carrega informação de domínio. Um cliente que interpretasse `200` como sucesso estaria certo tecnicamente e errado no que importa, então este módulo entrega texto e o [`page_state`](page_state.md) entrega significado.

O terceiro é uma coleta que dura semanas contra um portal que pode cair, entrar em manutenção ou bloquear o acesso. **Uma coleta longa sem detecção de indisponibilidade não falha: ela conclui com sucesso aparente**, marcando a fila inteira como erro.

## Decisões de Arquitetura

- **Anti-ban por construção: todo GET passa por `_get`** — não existe caminho alternativo, e `_get` começa chamando `_dormir()`. A alternativa (deixar o `sleep` a cargo de quem chama) depende de disciplina humana em cada ponto; basta esquecer em um caminho para perder a garantia, e esse caminho seria o menos exercitado.
- **O `Pacer` mede o intervalo ENTRE requisições, não sono somado a cada uma** — no modelo aditivo, `sleep(2.1)` seguido de uma requisição de 1,4 s produz um ciclo de 3,5 s para um alvo de 2,1 s: metade da espera não protege ninguém, só reduz a vazão em 60%. Aqui a pergunta é "quando é o próximo horário livre?", e a latência cabe **dentro** do intervalo.
- **`max(agora, self._proximo)` descarta o crédito da ociosidade** — sem isso, uma pausa longa (almoço, notebook suspenso) deixaria `_proximo` no passado e a fila dispararia uma rajada instantânea ao retomar. É a linha que separa uma cadência de um limitador ingênuo.
- **O slot é reservado dentro do lock; o `sleep` acontece fora dele** — senão cada thread bloquearia todas as outras durante a espera, e o pool viraria um laço sequencial com passos extras.
- **O intervalo é sorteado, não fixo** — um intervalo constante produz padrão de tráfego regular, que é o que detecção de automação procura.
- **O `Pacer` é global: workers NÃO aumentam a taxa vista pelo e-SAJ** — o teto continua uma requisição a cada 1,7–2,5 s com 1 ou 3 workers. O que eles resolvem é outro problema: quando uma página demora 8 s, o modelo de thread única deixa os slots seguintes passarem em branco. **A taxa não sobe; a ociosidade cai.**
- **O disjuntor é compartilhado pelo mesmo motivo** — com contadores por cliente, 3 workers precisariam de 60 falhas consecutivas para abrir o que deveria abrir em 20. Sem disjuntor nenhum, uma queda do portal faz a fila inteira consumir ~12 s por número (3 tentativas + backoff) e marcar tudo como falha — "descoberto só horas depois".
- **Falhas consecutivas, não acumuladas** — `sucesso()` zera o contador. Uma base grande sempre produz timeouts esparsos; o circuito só deve abrir quando o padrão indica que o problema é do portal, não do processo.
- **`falha()` devolve a decisão E o contador que a produziu** — um booleano bastaria para decidir, mas a mensagem precisa citar o número, e quem a monta está fora do lock. Reler o atributo abriria janela para outra thread já ter incrementado ou zerado: a exceção diria "23 falhas seguidas" num circuito calibrado em 20. É correção de **diagnóstico**, não de comportamento.
- **`requisicoes` e `operacoes` contam coisas diferentes** — um `_get` que retentou três vezes é **uma** página pedida e **três** requisições contra o portal. Com um contador só, a métrica subnotifica o tráfego real por um fator de até `max_tentativas` — e o tráfego real é justamente o que a cadência existe para limitar. `tentativa()` é chamado depois de `_dormir()` e antes do envio: conta requisições que saíram, não intenções.
- **`_levantar_falha` carrega o contrato no nome** — `_get` não tem `return` explícito depois do laço, então sua correção depende de a última linha nunca retornar. O nome antigo (`_registrar_falha`) descrevia contabilidade; um `return` acidental devolveria `None`, que chega ao parser como HTML vazio, vira `DESCONHECIDO` e devolve o processo à fila indefinidamente, sem nada apontar para o cliente HTTP.
- **`except` restrito a erros de rede** — `except Exception` transformaria qualquer bug em falha de rede aparente: três tentativas, `erro_transitorio`, de volta à fila, para sempre, sem que ninguém veja o `TypeError`. Restrito, um erro de programação sobe imediatamente.
- **Session por cliente; `Pacer` e monitor compartilhados** — a `Session` do `curl_cffi` não é thread-safe. O padrão `x or Padrão()` mantém o módulo utilizável sozinho (é como o spike o usa) sem abrir mão da injeção quando há concorrência.
- **Backoff exponencial com teto de 15 s e jitter** — teto para que `max_tentativas` alto não produza esperas absurdas; jitter para que workers que falharam juntos não retentem em uníssono.
- **`impersonate="chrome120"` sozinho, sem nenhum header manual** — a premissa de um UA manual é que `impersonate` atua só na camada TLS/HTTP2; ela é falsa, o perfil inteiro do navegador vem junto. **E a incoerência é o sinal, não o valor**: um cliente que anuncia `Chrome/120` no cabeçalho enquanto negocia TLS como `chrome124` não parece um Chrome antigo, parece o que é. Trocar `impersonate` troca o disfarce inteiro de uma vez.
- **`abrir_detalhe` aceita três formas de endereço** — href absoluto, path relativo ou o código interno opaco do SAJ, para o coletor repassar direto o que a tela de seleção deu, sem se importar com a origem.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| `requests` ou `httpx` | Não reproduzem a impressão digital TLS de um navegador. O `curl_cffi` com `impersonate` é a razão de o cliente ser atendido. |
| Selenium / Playwright | Peso e lentidão incompatíveis com centenas de milhares de processos; e a capa do e-SAJ é HTML servidor, não exige JavaScript. |
| `sleep` no script que chama, em vez de dentro do cliente | Depende de lembrar em cada ponto de chamada. Um caminho esquecido derruba a garantia inteira — e seria o caminho menos exercitado. |
| Sono fixo somado após cada requisição (modelo anterior) | Soma a latência ao sono: 3,5 s de ciclo para um alvo de 2,1 s. A espera extra não protege o servidor, só reduz a vazão. |
| Intervalo constante em vez de `random.uniform` | Produz padrão de tráfego regular, que é o que detecção de automação identifica. |
| Um `Pacer` por worker | Multiplicaria a taxa real pelo número de workers — exatamente o que a cadência global existe para impedir. |
| Um `MonitorFalhas` por worker | Com 3 workers, seriam necessárias 60 falhas consecutivas para abrir um circuito calibrado em 20. |
| `sleep` dentro do lock do `Pacer` | As threads serializariam no próprio lock, anulando o pool. |
| `except Exception` no laço de retentativa | Transforma bug do nosso código em falha de rede aparente, que volta para a fila indefinidamente. |
| Circuito por total de falhas em vez de consecutivas | Uma base grande acumula falhas esparsas legítimas; o circuito abriria sem que o portal tivesse caído. |
| Sem circuit breaker, confiando na leitura dos logs | Uma queda do e-SAJ consome ~12 s por número e marca a fila inteira como falha, "descoberto só horas depois". |
| Definir `User-Agent` manualmente por cima do `impersonate` | O `impersonate` já entrega o conjunto completo de headers. Um valor nosso por cima só pode divergir do resto — e é a divergência entre cabeçalho e impressão digital que denuncia automação. |
| `falha()` devolvendo só um booleano | A mensagem precisa citar o contador, e o chamador está fora do lock. Reler o atributo depois traria o valor de outra thread. |
| Um contador único de requisições | Um `_get` que retentou três vezes é uma operação e três requisições. Com um só, a carga real é subnotificada por até `max_tentativas`. |
| Manter o nome `_registrar_falha`, com o contrato num comentário | O nome descrevia contabilidade, não interrupção. Um `return` acidental devolveria `None` como se fosse HTML. |
| O cliente interpretar o HTML para decidir "não encontrado" | O e-SAJ devolve 200 para todos os casos. Misturar transporte e semântica impediria o `page_state` de ser testável sem rede. |

## Limitações Conhecidas

- **Não há tratamento de captcha.** As páginas cairiam em `DESCONHECIDO` e virariam `erro_transitorio` — e o disjuntor **não** dispara, porque do ponto de vista HTTP as requisições estão sendo bem-sucedidas.
- **O backoff é somado à cadência do `Pacer`.** Uma requisição que falha três vezes consome três slots mais duas esperas — a ordem de grandeza de ~12 s por número que falha.
- **`falhas` conta operações, não requisições.** Dos quatro números de `estatisticas()`, só `requisicoes` mede tentativas HTTP reais. A taxa de requisições que deram errado não é derivável dos contadores expostos.
- **O `Pacer` não é persistente.** Reiniciar zera `_proximo` e a primeira requisição sai imediatamente; em retomadas frequentes, o intervalo entre execuções não é respeitado.
- **Sem limite de tempo total nem de volume por execução.** O circuito abre por falhas consecutivas, não por "requisições demais nesta sessão".
- **A `Session` mantém cookies e nunca é reciclada.** É o que faz a navegação seleção → detalhe funcionar, mas um cliente marcado pelo portal continua marcado até o fim da execução.

## Exemplo de Uso

```python
from src.scrapers.esaj_client import EsajClient, MonitorFalhas, Pacer

# Isolado (é como scripts/spike_seletores.py o usa):
html = EsajClient().buscar(NumeroProcesso("10008582420228260396"), grau=1)

# Concorrente: cadência e circuito criados UMA vez e injetados em todos os clientes.
pacer, monitor = Pacer(), MonitorFalhas()
cliente = EsajClient(pacer=pacer, monitor=monitor)   # um por thread; só a Session é local
print(cliente.estatisticas())
# {'requisicoes': 18, 'operacoes': 14, 'falhas': 0, 'falhas_seguidas': 0}
```

Se `buscar` levantar exceção, **não** tente o outro grau: erro de rede no 1º seguido de sucesso no 2º gravaria o processo com o grau errado. Ver [`coletor`](coletor.md).

## Testes e Validação

Não há suíte automatizada. A validação disponível é `scripts/spike_seletores.py`, que exercita `buscar` nos dois graus, salva o HTML em `data/spike/` e imprime `estatisticas()` ao final. O comportamento do disjuntor de ponta a ponta é observável desligando a rede durante a opção 1: após 20 falhas consecutivas a execução precisa parar, em vez de consumir a fila. As 4 invariantes testáveis sem rede estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Remoção do `User-Agent` manual; `MonitorFalhas` separa `requisicoes` de `operacoes` e ganha `tentativa()`; `falha()` devolve `(deve_abrir, falhas_seguidas)`; `_registrar_falha` renomeado para `_levantar_falha` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 12 decisões virou lista de tópicos; código copiado removido; invariantes migradas para o backlog de testes |
