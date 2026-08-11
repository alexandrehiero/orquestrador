"""Cliente HTTP do e-SAJ — ÚNICO ponto que toca a rede.

Anti-ban por construção: todo GET passa por `_get`, então é impossível esquecer
o sleep aleatório em algum caminho.

O e-SAJ responde HTTP 200 tanto para 'não encontrado' quanto para 'segredo de
justiça' — a mensagem vem no corpo. Este cliente NÃO decide semântica; devolve
o HTML e quem classifica é o ClassificadorPagina.

Diferenças frente ao pipeline IAMSPE:
  - `except` restrito a erros de REDE. Um TypeError do nosso próprio código
    propaga em vez de virar 3 retentativas e um EsajRequisicaoError disfarçado.
  - CIRCUIT BREAKER: N requisições seguidas falhando aborta a execução. Sem ele,
    uma queda do e-SAJ faz a fila inteira consumir ~12s por número (3 tentativas
    + backoff) e marcar tudo como falha — descoberto só horas depois.
  - API por GRAU (1/2), não por instância ('cpopg'/'cposg').
"""

import random
import threading
import time

from curl_cffi import requests as curl_requests

try:  # curl_cffi recente
    from curl_cffi.requests.exceptions import RequestException as _ErroBiblioteca
except ImportError:  # versões antigas
    from curl_cffi.requests.errors import RequestsError as _ErroBiblioteca

from .exceptions import EsajIndisponivelError, EsajRequisicaoError
from .numero_processo import instancia_do_grau

# NÃO definimos User-Agent manualmente. O `impersonate` do curl_cffi já monta o
# conjunto COMPLETO de headers do navegador escolhido — UA inclusive — junto com
# a impressão digital TLS/HTTP2 correspondente. Um UA nosso por cima só poderia
# divergir do resto do disfarce, que é justamente o que denuncia um cliente
# automatizado. Para mudar de navegador, troque só o parâmetro `impersonate`.

#: Erros que JUSTIFICAM retentativa. RequestException herda de OSError, então a
#: tupla cobre timeout, DNS, conexão recusada, SSL e 4xx/5xx do raise_for_status.
#: Erros de programação (TypeError, AttributeError) ficam DE FORA de propósito.
_ERROS_DE_REDE = (_ErroBiblioteca, OSError)


class Pacer:
    """Cadência GLOBAL: garante intervalo mínimo ENTRE requisições.

    Diferença frente ao sleep aditivo: lá o ciclo era sleep + latência (3,5s
    para um alvo de 2,1s) — metade da espera não protegia ninguém, só somava a
    latência ao sono. Aqui a latência cabe DENTRO do intervalo.

    Thread-safe de propósito: o limite é do AGREGADO, não de cada thread. Vários
    workers compartilhando um Pacer não aumentam a taxa vista pelo e-SAJ; eles
    só evitam que um pico de latência numa página deixe a fila ociosa.

    O slot é reservado DENTRO do lock e o sono acontece FORA dele — senão as
    threads serializariam no próprio lock.
    """

    def __init__(self, minimo=1.7, maximo=2.5):
        if minimo <= 0 or maximo < minimo:
            raise ValueError("Intervalo inválido para o Pacer.")
        self.minimo = minimo
        self.maximo = maximo
        self._lock = threading.Lock()
        self._proximo = 0.0  # time.monotonic() do próximo slot livre

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


class MonitorFalhas:
    """Circuit breaker e métricas COMPARTILHADOS entre clientes.

    Cada worker tem sua própria Session (curl_cffi não é thread-safe), mas o
    circuito é um só: com contadores por cliente, 3 workers precisariam de 60
    falhas consecutivas para abrir o que deveria abrir em 20.
    """

    def __init__(self, limite=20):
        self.limite = limite
        self._lock = threading.Lock()
        self.requisicoes = 0      # tentativas HTTP REAIS (retentativas incluídas)
        self.operacoes = 0        # chamadas a _get (1 por página pedida)
        self.falhas = 0
        self.falhas_seguidas = 0

    def tentativa(self):
        """Uma requisição HTTP prestes a sair.

        Contada aqui, e não em sucesso/falha, porque um _get que retentou 3
        vezes fez 3 requisições e uma operação. Contar só a operação subnotifica
        justamente o tráfego que o anti-ban precisa vigiar.
        """
        with self._lock:
            self.requisicoes += 1

    def sucesso(self):
        with self._lock:
            self.operacoes += 1
            self.falhas_seguidas = 0  # falhas esparsas nunca abrem o circuito

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

    def estatisticas(self):
        with self._lock:
            return {
                "requisicoes": self.requisicoes,
                "operacoes": self.operacoes,
                "falhas": self.falhas,
                "falhas_seguidas": self.falhas_seguidas,
            }


class EsajClient:
    BASE = "https://esaj.tjsp.jus.br"

    def __init__(
        self,
        sleep_min=1.7,
        sleep_max=2.5,
        timeout=30,
        max_tentativas=3,
        impersonate="chrome120",
        limite_falhas_seguidas=20,
        pacer=None,
        monitor=None,
    ):
        # Pacer e monitor COMPARTILHADOS: uma cadência e um circuito para todos
        # os workers. Só a Session é por cliente.
        self.pacer = pacer or Pacer(sleep_min, sleep_max)
        self.monitor = monitor or MonitorFalhas(limite_falhas_seguidas)
        self.timeout = timeout
        self.max_tentativas = max_tentativas
        # Sem headers manuais: o impersonate já entrega o conjunto coerente.
        self.session = curl_requests.Session(impersonate=impersonate)

    def _dormir(self):
        """Nome mantido: todo GET passa por aqui, então é impossível esquecer."""
        self.pacer.aguardar()

    def _registrar_sucesso(self):
        self.monitor.sucesso()

    def _levantar_falha(self, url, ultimo_erro):
        """SEMPRE levanta. O nome carrega o contrato — antes ele existia só num
        comentário, e um `return` acidental no chamador devolveria None como se
        fosse HTML."""
        abrir, seguidas = self.monitor.falha()
        if abrir:
            raise EsajIndisponivelError(
                f"{seguidas} requisições seguidas falharam — o e-SAJ "
                f"provavelmente está fora do ar ou bloqueou o acesso.\n"
                f"A execução foi interrompida para não marcar a fila inteira como "
                f"falha. Nada foi perdido: o checkpoint no banco permite retomar "
                f"exatamente daqui.\n"
                f"Último erro: {ultimo_erro!r}"
            ) from ultimo_erro

        raise EsajRequisicaoError(
            f"Falha após {self.max_tentativas} tentativas em {url}"
        ) from ultimo_erro

    def _get(self, url, params=None):
        """GET com sleep anti-ban, retentativa com backoff e circuit breaker."""
        ultimo_erro = None
        for tentativa in range(1, self.max_tentativas + 1):
            try:
                self._dormir()  # cadência anti-ban em TODA requisição
                self.monitor.tentativa()  # conta a requisição que vai sair
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
            except _ERROS_DE_REDE as erro:
                ultimo_erro = erro
                if tentativa < self.max_tentativas:
                    time.sleep(min(2 ** tentativa, 15) + random.uniform(0, 1))
                continue
            self._registrar_sucesso()
            return resp.text
        self._levantar_falha(url, ultimo_erro)

    # --- operações -----------------------------------------------------------
    def buscar(self, numero_processo, grau):
        """Busca por número no grau dado. `numero_processo` é um NumeroProcesso.

        IMPORTANTE para quem chamar: se esta chamada levantar exceção, NÃO tente
        o outro grau. Erro de rede no 1º grau seguido de sucesso no 2º gravaria o
        processo com o GRAU ERRADO, em silêncio — que é exatamente o problema que
        este orquestrador existe para resolver. Só um NAO_ENCONTRADO explícito
        autoriza avançar de grau.
        """
        url = f"{self.BASE}/{instancia_do_grau(grau)}/search.do"
        return self._get(url, params=numero_processo.params_busca(grau))

    def abrir_detalhe(self, href_ou_codigo, grau):
        """Abre a página de capa. Aceita href completo, path relativo ou o
        `processo.codigo` interno do SAJ (opaco, ex.: '1H000AX8O0000')."""
        alvo = str(href_ou_codigo)
        if alvo.startswith("http"):
            return self._get(alvo)
        if alvo.startswith("/"):
            return self._get(self.BASE + alvo)
        url = f"{self.BASE}/{instancia_do_grau(grau)}/show.do"
        return self._get(url, params={"processo.codigo": alvo})

    # --- métricas ------------------------------------------------------------
    def estatisticas(self):
        return self.monitor.estatisticas()
    