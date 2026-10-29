"""Movimentações do sistema Atos da PGE (`data/processos_PGE.json`), prontas para enxerto.

Produz o mesmo bloco que a v5 do GPDR enxertou (`Codigos_dados_GPDR/src/atos_pge.py`):
`movimentos_pge` e `origem_pge`. Um mesmo CNJ pode aparecer em vários documentos
da origem — são incidentes (execuções, cumprimentos), com movimentos disjuntos.
Cada caderno entra inteiro e contíguo, na ordem do arquivo, cada movimento leva o
número do seu incidente, e a ordem de cada caderno é invertida para "mais recente
primeiro", como `movimentos_tjsp`.

Duas diferenças de implementação frente ao GPDR, ambas por memória:

1. **O índice mora num SQLite temporário, não num dict.** Na lista de 2025 são
   123 mil CNJ com par e 1,6 GiB de JSON — o GPDR coube em memória com 63 mil e
   0,9 GiB, mas um ano recente não cabe com folga numa máquina com 3 GiB livres.
   O SQLite é descartável: é reconstruído a cada execução e apagado no fim.
2. **A leitura usa o `json` da biblioteca padrão**, não `ijson`. O
   `JSONDecoder.raw_decode` decodifica um item a partir de uma posição e diz
   onde ele termina; o arquivo é lido em blocos e só um item vive em memória. Sem
   dependência nova, e com o decodificador em C — o `ijson` sem o backend
   `yajl2_c` levaria horas para uma passada.
"""

import codecs
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

CAMPO_MOVIMENTOS = "movimentos_pge"
CAMPO_ORIGEM = "origem_pge"

_BLOCO = 1 << 20  # 1 MB por leitura
#: Item sem fim depois disto é arquivo corrompido, não item grande — o maior
#: documento medido tem 0,16 MB. Sem o teto, "ler mais e tentar de novo" traria
#: o resto dos 9 GB para a memória antes de acusar o erro.
_LIMITE_ITEM = 256 << 20
_ESPACOS = " \t\r\n"
#: Blocos acumulados antes de cada gravação no índice (memória x transações).
_LOTE = 2000


def ler_array_json(caminho, ao_ler=None, bloco=_BLOCO):
    """Itera os itens de um array JSON de vários GB, um por vez.

    Um item que não terminou dentro do texto lido levanta JSONDecodeError; a
    resposta é ler mais e tentar de novo do mesmo ponto. Só no fim do arquivo o
    erro é real. A leitura cresce junto com o item (`max(bloco, pendente)`), para
    que um item maior que o bloco não custe uma tentativa por megabyte.

    `ao_ler(n)` recebe os BYTES lidos a cada bloco — é o que alimenta a barra.
    """
    decodificador = json.JSONDecoder()
    texto_utf8 = codecs.getincrementaldecoder("utf-8-sig")()
    with open(caminho, "rb") as arquivo:
        texto, pos, fim = "", 0, False

        def ler_mais():
            nonlocal texto, pos, fim
            bruto = arquivo.read(max(bloco, len(texto) - pos))
            if ao_ler is not None:
                ao_ler(len(bruto))
            fim = not bruto
            texto = texto[pos:] + texto_utf8.decode(bruto, final=fim)
            pos = 0

        def proximo():
            """Pula espaços e devolve o próximo caractere ('' no fim)."""
            nonlocal pos
            while True:
                while pos < len(texto) and texto[pos] in _ESPACOS:
                    pos += 1
                if pos < len(texto):
                    return texto[pos]
                if fim:
                    return ""
                ler_mais()

        if proximo() != "[":
            raise ValueError(f"{caminho} não começa com um array JSON.")
        pos += 1
        if proximo() == "]":
            return
        while True:
            while True:
                try:
                    item, pos = decodificador.raw_decode(texto, pos)
                    break
                except json.JSONDecodeError:
                    if fim:
                        raise
                    if len(texto) - pos > _LIMITE_ITEM:
                        raise ValueError(f"{caminho}: item com mais de "
                                         f"{_LIMITE_ITEM >> 20} MB sem terminar.")
                    ler_mais()
            yield item
            separador = proximo()
            if separador == "]":
                return
            if separador != ",":
                raise ValueError(f"{caminho}: esperava ',' ou ']' entre itens, "
                                 f"encontrei {separador!r}.")
            pos += 1
            proximo()


def numero_cnj(documento):
    """`processo.numero` reduzido a 20 dígitos, ou None (numeração pré-CNJ)."""
    processo = documento.get("processo") if isinstance(documento, dict) else None
    numero = processo.get("numero") if isinstance(processo, dict) else None
    if not isinstance(numero, str):
        return None
    digitos = "".join(c for c in numero if c.isdigit())
    return digitos if len(digitos) == 20 else None


def bloco_vazio():
    """Bloco inicial, antes de receber qualquer caderno."""
    return {
        CAMPO_MOVIMENTOS: [],
        CAMPO_ORIGEM: {
            "pastaIds": [],
            "nucleos": [],
            "incidentes": [],
            "documentosOrigem": 0,
            "totalMovimentos": 0,
            "primeiroMovimento": None,
            "ultimoMovimento": None,
        },
    }


def _instante(valor):
    texto = valor.get("$date") if isinstance(valor, dict) else None
    if not isinstance(texto, str):
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


def _extremo(atual, candidato, escolher):
    """Escolhe entre duas datas devolvendo o dict original, não uma remontagem.

    Compara como instante, não como texto: "…-02:00" é maior que "…-03:00" como
    texto e menor como instante.
    """
    if candidato is None:
        return atual
    if atual is None:
        return candidato
    instante_atual, instante_candidato = _instante(atual), _instante(candidato)
    if instante_atual is None:
        return candidato
    if instante_candidato is None:
        return atual
    return atual if escolher(instante_atual, instante_candidato) is instante_atual else candidato


def acrescentar(bloco, documento):
    """Junta ao bloco um caderno da origem, preservando-o inteiro e contíguo."""
    processo = documento.get("processo") or {}
    metadados = documento.get("metadados") or {}
    datas = documento.get("datas") or {}
    origem = bloco[CAMPO_ORIGEM]
    incidente = processo.get("incidente")

    # dict.fromkeys, não set: remove repetição preservando a ordem de primeira
    # aparição, que um set não garante entre execuções.
    origem["pastaIds"] = list(dict.fromkeys([*origem["pastaIds"], *(metadados.get("pastaIds") or [])]))
    origem["nucleos"] = list(dict.fromkeys([*origem["nucleos"], *(metadados.get("nucleos") or [])]))
    origem["incidentes"] = list(dict.fromkeys([*origem["incidentes"], incidente]))

    bloco[CAMPO_MOVIMENTOS].extend(
        {**movimento, "incidente": incidente}
        for movimento in reversed(documento.get("movimentos") or [])
    )
    origem["documentosOrigem"] += 1
    origem["totalMovimentos"] = len(bloco[CAMPO_MOVIMENTOS])
    origem["primeiroMovimento"] = _extremo(origem["primeiroMovimento"], datas.get("primeiroMovimento"), min)
    origem["ultimoMovimento"] = _extremo(origem["ultimoMovimento"], datas.get("ultimoMovimento"), max)


class IndicePge:
    """CNJ -> bloco serializado, num SQLite descartável.

        with IndicePge(caminho) as indice:
            indice.montar(origem, cnj_alvo)
            bloco = indice.obter("00000020520258260483")

    Sem journal e sem fsync: o arquivo é derivado e refeito do zero a cada
    execução, então a durabilidade que o SqliteStore paga aqui não protege nada.
    """

    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._apagar()  # sobra de uma execução interrompida
        self.con = sqlite3.connect(str(self.caminho))
        self.con.execute("PRAGMA journal_mode = OFF")
        self.con.execute("PRAGMA synchronous = OFF")
        self.con.execute("CREATE TABLE bloco (numero TEXT PRIMARY KEY, json TEXT NOT NULL)")

    def _apagar(self):
        for sufixo in ("", "-journal", "-wal", "-shm"):
            Path(str(self.caminho) + sufixo).unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()

    def fechar(self):
        if self.con is not None:
            self.con.close()
            self.con = None
        self._apagar()

    def obter(self, numero):
        linha = self.con.execute("SELECT json FROM bloco WHERE numero = ?", (numero,)).fetchone()
        return json.loads(linha[0]) if linha else None

    def montar(self, origem, cnj_alvo, ao_ler=None):
        """Percorre a origem e guarda o bloco de cada CNJ presente em `cnj_alvo`.

        Só os processos da base entram: guardar os outros 300 mil custaria disco
        para dado que ninguém vai ler.
        """
        contadores = Counter()
        pendentes = {}

        def gravar():
            with self.con:
                self.con.executemany(
                    "INSERT OR REPLACE INTO bloco (numero, json) VALUES (?, ?)",
                    ((n, json.dumps(b, ensure_ascii=False)) for n, b in pendentes.items()),
                )
            pendentes.clear()

        for documento in ler_array_json(origem, ao_ler=ao_ler):
            contadores["documentos_origem_lidos"] += 1
            numero = numero_cnj(documento)
            if numero is None:
                contadores["documentos_origem_sem_cnj"] += 1
                continue
            if numero not in cnj_alvo:
                continue
            # O reencontro de um CNJ é raro (46 em 123 mil na lista de 2025):
            # só nele o bloco é relido do índice.
            bloco = pendentes.get(numero) or self.obter(numero) or bloco_vazio()
            acrescentar(bloco, documento)
            pendentes[numero] = bloco
            contadores["documentos_origem_fundidos"] += 1
            if len(pendentes) >= _LOTE:
                gravar()
        gravar()
        contadores["cnj_com_par"] = self.con.execute("SELECT COUNT(*) FROM bloco").fetchone()[0]
        return contadores
