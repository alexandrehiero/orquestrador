"""Checkpoint da coleta em SQLite — fonte de verdade do orquestrador.

Por que SQLite e não shards em disco:
  - ACID: interrupção no meio de uma gravação faz rollback; nunca há estado
    corrompido. Numa coleta de semanas isso deixa de ser conforto.
  - Retomada O(1) por chave indexada, sem varrer diretório com centenas de
    milhares de arquivos.
  - As consultas de grafo (órfãos, filhos) viram SQL em vez de carregar a base
    inteira em memória.

Chave: (processo, grau). O MESMO número pode existir em 1º e 2º grau — foi a
colisão dessa chave que embaralhou o relacionamento no pipeline anterior.

Convenção de grau:
    1 / 2  -> grau OBSERVADO (a página respondeu em cpopg / cposg)
    0      -> indeterminado (sem_dados, erro) — projetado como null no JSONL.
              Nunca NULL: SQLite não impede NULL em PRIMARY KEY, e como
              NULL != NULL a chave deixaria de barrar duplicatas.

O dict BRUTO do parser é gravado junto. A base final é uma PROJEÇÃO dele, então
corrigir uma regra de transformação (ex.: polo de 'credor') é uma reprojeção
local, sem nenhuma requisição nova.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Vocabulário de status: FONTE ÚNICA em src/status.py. Este módulo declarava as
# mesmas strings que o coletor e a projeção — três cópias que nada impedia de
# divergir, e cuja divergência seria silenciosa.
from ..status import (
    COLETADO,
    ERRO_PERSISTENTE,
    ERRO_TRANSITORIO,
    GRAU_INDETERMINADO,
    ORIGEM_LISTA,
    SEGREDO_JUSTICA,
    STATUS_EXPORTAVEIS,
    STATUS_TERMINAIS,
    TETO_TENTATIVAS_PADRAO,
)

_PASTAS_SINCRONIZADAS = (
    "onedrive", "dropbox", "google drive", "googledrive", "gdrive",
    "icloud", "icloud drive", "box sync", "nextcloud", "owncloud", "pcloud",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registro (
    processo          TEXT    NOT NULL,
    grau              INTEGER NOT NULL,
    status            TEXT    NOT NULL,
    tentativas        INTEGER NOT NULL DEFAULT 0,
    ultimo_erro       TEXT,
    bruto             TEXT,
    processo_pai      TEXT,
    processo_pai_grau INTEGER,
    tipo_vinculo      TEXT,
    origem            TEXT    NOT NULL,
    atualizado_em     TEXT    NOT NULL,
    PRIMARY KEY (processo, grau)
);

CREATE INDEX IF NOT EXISTS idx_registro_status ON registro (status);
CREATE INDEX IF NOT EXISTS idx_registro_pai ON registro (processo_pai, processo_pai_grau);

-- Metadados do próprio banco (ex.: versão da regra de vínculo já aplicada).
CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""


class PastaSincronizadaError(RuntimeError):
    """O .db está dentro de pasta de sincronização — risco de corrupção."""


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _detectar_pasta_sincronizada(caminho):
    """Devolve o nome da pasta suspeita, ou None. Clientes de sync copiam o .db
    e o -wal em momentos diferentes, produzindo um banco incoerente SEM erro."""
    partes = [p.lower() for p in Path(caminho).resolve().parts]
    for parte in partes:
        for suspeita in _PASTAS_SINCRONIZADAS:
            if suspeita in parte:
                return parte
    return None


class SqliteStore:
    """Checkpoint da coleta. Use como context manager para garantir o fechamento.

        with SqliteStore("C:/dados/coleta.db") as store:
            feitos = store.numeros_finalizados()
    """

    def __init__(self, caminho, permitir_pasta_sincronizada=False):
        self.caminho = Path(caminho)
        suspeita = _detectar_pasta_sincronizada(self.caminho)
        if suspeita and not permitir_pasta_sincronizada:
            raise PastaSincronizadaError(
                f"O banco '{self.caminho}' está dentro de '{suspeita}', que parece "
                f"ser uma pasta sincronizada. Clientes de sincronização corrompem "
                f"bancos SQLite ativos SEM emitir erro — semanas de coleta podem ser "
                f"perdidas silenciosamente.\n"
                f"Mova o banco para um disco local (ex.: C:/dados_coleta/) ou, se "
                f"tiver certeza, use permitir_pasta_sincronizada=True."
            )
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.caminho), timeout=30, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self._configurar()
        self.con.executescript(_SCHEMA)

    def _configurar(self):
        # WAL: tolera bem suspensão do notebook e é mais rápido em escrita
        # sequencial. FULL: fsync a cada commit — a ~3,5s por processo o custo é
        # irrelevante e protege contra queda de energia/bateria.
        self.con.execute("PRAGMA journal_mode = WAL")
        self.con.execute("PRAGMA synchronous = FULL")
        self.con.execute("PRAGMA busy_timeout = 30000")
        # Sem PRAGMA foreign_keys: o schema NÃO declara FK de propósito.
        # processo_pai aponta para um processo que legitimamente pode ainda não
        # ter sido coletado — é exatamente essa a definição de órfão. Uma FK
        # rejeitaria a gravação do filho e quebraria o ciclo 4 -> 3 -> 4.

    # --- ciclo de vida -------------------------------------------------------
    def fechar(self):
        if self.con is not None:
            self.con.close()
            self.con = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()

    def backup(self, destino):
        """Cópia consistente do banco (roda com a coleta parada). Copiar o .db
        'na mão' enquanto há -wal pendente produz backup incoerente."""
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        self.con.execute("VACUUM INTO ?", (str(destino),))
        return destino

    # --- gravação ------------------------------------------------------------
    def registrar_resultado(
        self, processo, grau, status, bruto=None,
        processo_pai=None, processo_pai_grau=None, tipo_vinculo=None,
        origem=ORIGEM_LISTA,
    ):
        """Grava um resultado TERMINAL (coletado / segredo / sem_dados).

        Remove, na MESMA transação, a linha de grau indeterminado que o mesmo
        número possa ter deixado numa tentativa anterior que falhou — senão o
        processo apareceria duas vezes na base final.
        """
        if status not in STATUS_TERMINAIS:
            raise ValueError(f"Status não terminal em registrar_resultado: {status!r}")
        with self.con:  # transação
            self.con.execute(
                """INSERT INTO registro
                       (processo, grau, status, tentativas, ultimo_erro, bruto,
                        processo_pai, processo_pai_grau, tipo_vinculo,
                        origem, atualizado_em)
                   VALUES (?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (processo, grau) DO UPDATE SET
                       status            = excluded.status,
                       tentativas        = 0,
                       ultimo_erro       = NULL,
                       bruto             = excluded.bruto,
                       processo_pai      = excluded.processo_pai,
                       processo_pai_grau = excluded.processo_pai_grau,
                       tipo_vinculo      = excluded.tipo_vinculo,
                       atualizado_em     = excluded.atualizado_em""",
                (
                    processo, grau, status,
                    json.dumps(bruto, ensure_ascii=False) if bruto is not None else None,
                    processo_pai, processo_pai_grau, tipo_vinculo,
                    origem, _agora(),
                ),
            )
            if grau != GRAU_INDETERMINADO:
                self.con.execute(
                    "DELETE FROM registro WHERE processo = ? AND grau = ?",
                    (processo, GRAU_INDETERMINADO),
                )

    def registrar_erro(self, processo, erro, teto_tentativas=TETO_TENTATIVAS_PADRAO,
                       origem=ORIGEM_LISTA):
        """Grava falha TRANSITÓRIA (rede, página não reconhecida, seleção sem
        link). Incrementa tentativas; ao estourar o teto vira erro_persistente e
        sai da fila automática, indo para revisão manual — é isso que faz o
        arquivo de falhas ESVAZIAR em vez de girar para sempre.

        Devolve o status resultante.
        """
        with self.con:
            linha = self.con.execute(
                "SELECT tentativas FROM registro WHERE processo = ? AND grau = ?",
                (processo, GRAU_INDETERMINADO),
            ).fetchone()
            tentativas = (linha["tentativas"] if linha else 0) + 1
            status = ERRO_PERSISTENTE if tentativas >= teto_tentativas else ERRO_TRANSITORIO
            self.con.execute(
                """INSERT INTO registro
                       (processo, grau, status, tentativas, ultimo_erro, bruto,
                        processo_pai, processo_pai_grau, tipo_vinculo,
                        origem, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
                   ON CONFLICT (processo, grau) DO UPDATE SET
                       status        = excluded.status,
                       tentativas    = excluded.tentativas,
                       ultimo_erro   = excluded.ultimo_erro,
                       atualizado_em = excluded.atualizado_em""",
                (processo, GRAU_INDETERMINADO, status, tentativas,
                 str(erro)[:500], origem, _agora()),
            )
        return status

    def ler_meta(self, chave):
        linha = self.con.execute(
            "SELECT valor FROM meta WHERE chave = ?", (chave,)
        ).fetchone()
        return linha["valor"] if linha else None

    def gravar_meta(self, chave, valor):
        with self.con:
            self.con.execute(
                "INSERT INTO meta (chave, valor) VALUES (?, ?) "
                "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
                (chave, valor),
            )

    def reprojetar_vinculos(self, derivar, tipo_sem_bruto, versao,
                            forcar=False, log=None):
        """Recalcula tipo_vinculo/processo_pai a partir do BRUTO já gravado.

        Por que existe: `tipo_vinculo` e `processo_pai` são os únicos valores
        derivados que vivem em COLUNA, não na projeção. A coluna é necessária —
        orfaos() e vinculos() são SQL sobre ela — mas sem esta reprojeção mudar
        a regra de derivação exigiria RECOLETAR, quebrando a promessa de que o
        bruto é a verdade e todo o resto é reprocessável localmente.

        Registros sem bruto (segredo, sem_dados) recebem `tipo_sem_bruto`: a
        coleta nunca viu a capa, então afirmar 'sem vínculo' seria afirmar sobre
        o que não foi observado.

        Paginação por CHAVE (não OFFSET, que é O(n) a cada lote) e leitura antes
        da escrita: alterar linhas enquanto um SELECT da mesma tabela é iterado
        tem comportamento indefinido no SQLite.
        """
        # A varredura lê o `bruto` de TODA a base — o grosso do banco. Sem esta
        # guarda, a opção 4 pagaria esse custo em toda execução, mesmo sem
        # nenhuma mudança de regra, dobrando o tempo do export.
        if not forcar and self.ler_meta("versao_regra_vinculo") == versao:
            return {"vistos": 0, "alterados": 0, "pulado": True}

        alterados = 0
        vistos = 0
        ultimo = ("", -1)
        while True:
            lote = self.con.execute(
                """SELECT processo, grau, bruto, tipo_vinculo,
                          processo_pai, processo_pai_grau
                     FROM registro
                    WHERE (processo, grau) > (?, ?)
                 ORDER BY processo, grau
                    LIMIT 500""",
                ultimo,
            ).fetchall()
            if not lote:
                break
            with self.con:
                for linha in lote:
                    ultimo = (linha["processo"], linha["grau"])
                    vistos += 1
                    bruto = json.loads(linha["bruto"]) if linha["bruto"] else None
                    if bruto:
                        v = derivar(bruto, linha["grau"], linha["processo"])
                    else:
                        v = {"tipo": tipo_sem_bruto,
                             "processo_pai": None, "processo_pai_grau": None}
                    atual = (linha["tipo_vinculo"], linha["processo_pai"],
                             linha["processo_pai_grau"],
                             (bruto or {}).get("observacoes") or [])
                    novo_obs = list(v.get("observacoes") or [])
                    novo = (v["tipo"], v["processo_pai"], v["processo_pai_grau"],
                            novo_obs)
                    if novo != atual:
                        # O bruto também é reescrito: a coleta grava as
                        # observações do vínculo DENTRO dele, então atualizar só
                        # as colunas deixaria o tipo novo convivendo com as
                        # observações da regra antiga.
                        bruto_novo = None
                        if bruto is not None:
                            bruto = dict(bruto)
                            bruto["observacoes"] = novo_obs
                            bruto_novo = json.dumps(bruto, ensure_ascii=False)
                        self.con.execute(
                            """UPDATE registro
                                  SET tipo_vinculo = ?, processo_pai = ?,
                                      processo_pai_grau = ?,
                                      bruto = COALESCE(?, bruto),
                                      atualizado_em = ?
                                WHERE processo = ? AND grau = ?""",
                            (v["tipo"], v["processo_pai"], v["processo_pai_grau"],
                             bruto_novo, _agora(),
                             linha["processo"], linha["grau"]),
                        )
                        alterados += 1
            if log and vistos % 5000 == 0:
                log(f"  {vistos} vínculos reprojetados...")
        self.gravar_meta("versao_regra_vinculo", versao)
        return {"vistos": vistos, "alterados": alterados, "pulado": False}

    # --- consultas de fila ---------------------------------------------------
    def numeros_finalizados(self):
        """Números com algum resultado terminal — pulados na retomada."""
        marcas = ",".join("?" * len(STATUS_TERMINAIS))
        cur = self.con.execute(
            f"SELECT DISTINCT processo FROM registro WHERE status IN ({marcas})",
            STATUS_TERMINAIS,
        )
        return {linha["processo"] for linha in cur}

    def numeros_com_erro_transitorio(self):
        """Fila da opção 2 (recoleta), do mais antigo para o mais recente."""
        cur = self.con.execute(
            """SELECT processo, tentativas, ultimo_erro
                 FROM registro
                WHERE status = ?
             ORDER BY atualizado_em""",
            (ERRO_TRANSITORIO,),
        )
        return [dict(linha) for linha in cur]

    def numeros_com_erro_persistente(self):
        """Estouraram o teto: saem da fila automática, vão para revisão manual."""
        cur = self.con.execute(
            """SELECT processo, tentativas, ultimo_erro
                 FROM registro
                WHERE status = ?
             ORDER BY processo""",
            (ERRO_PERSISTENTE,),
        )
        return [dict(linha) for linha in cur]

    # --- consultas de grafo --------------------------------------------------
    def orfaos(self):
        """Pais citados por algum registro que NÃO têm registro NENHUM.

        Critério 1 — 'não tem REGISTRO', não 'não tem dados'. Um processo
        gravado como sem_dados JÁ foi visitado e sai da lista para sempre.

        Critério 2 — casamento pelo NÚMERO, não pelo par (processo, grau).
        Parece uma perda de precisão e é o contrário: a coleta opera por NÚMERO
        (o coletor decide o grau sozinho, pela origem do CNJ), e
        `numeros_finalizados()` também. Casando pelo par, um número coletado no
        grau 2 e citado como pai no grau 1 seria reportado como órfão para
        sempre: a opção 3 o descartaria por já estar finalizado, e ele voltaria
        em toda execução da opção 4 — o oposto do que esta docstring promete.

        Limitação assumida: quando o pai existe só no OUTRO grau, a referência
        aponta para um nó ausente da base. Isso é inconsistência de dado a
        relatar, não trabalho de coleta — recoletar devolveria a mesma resposta.
        `graus_citados` fica na saída para permitir esse diagnóstico.
        """
        cur = self.con.execute(
            """SELECT f.processo_pai AS processo,
                      GROUP_CONCAT(DISTINCT f.processo_pai_grau) AS graus_citados
                 FROM registro f
            LEFT JOIN registro p
                   ON p.processo = f.processo_pai
                WHERE f.processo_pai IS NOT NULL
                  AND p.processo IS NULL
             GROUP BY f.processo_pai
             ORDER BY f.processo_pai"""
        )
        return [dict(linha) for linha in cur]

    def vinculos(self):
        """Arestas filho -> pai. Os FILHOS da base final são a inversão disto —
        derivados, nunca gravados por um passo separado (que era como o
        reconciliador antigo podia divergir do estado real)."""
        cur = self.con.execute(
            """SELECT processo, grau, processo_pai, processo_pai_grau
                 FROM registro
                WHERE processo_pai IS NOT NULL"""
        )
        return [dict(linha) for linha in cur]

    # --- leitura para export -------------------------------------------------
    def iter_exportaveis(self):
        """Itera em STREAMING os registros que vão para o JSONL.

        Streaming é obrigatório: materializar 500 mil registros numa lista foi
        exatamente o que inviabilizou o consolidador anterior.
        """
        marcas = ",".join("?" * len(STATUS_EXPORTAVEIS))
        cur = self.con.execute(
            f"""SELECT processo, grau, status, bruto, ultimo_erro, processo_pai,
                       processo_pai_grau, tipo_vinculo, origem, atualizado_em
                  FROM registro
                 WHERE status IN ({marcas})
              ORDER BY processo, grau""",
            STATUS_EXPORTAVEIS,
        )
        for linha in cur:
            reg = dict(linha)
            reg["bruto"] = json.loads(reg["bruto"]) if reg["bruto"] else None
            yield reg

    # --- métricas ------------------------------------------------------------
    def contagem_por_status(self):
        cur = self.con.execute(
            "SELECT status, COUNT(*) AS n FROM registro GROUP BY status ORDER BY status"
        )
        return {linha["status"]: linha["n"] for linha in cur}

    def contagem_por_grau(self):
        """Só coletado + segredo: são os únicos com grau OBSERVADO. Por isso
        NÃO fecha com total() — sem_dados e erros não têm grau para contar."""
        cur = self.con.execute(
            """SELECT grau, COUNT(*) AS n
                 FROM registro WHERE status IN (?, ?)
             GROUP BY grau ORDER BY grau""",
            (COLETADO, SEGREDO_JUSTICA),
        )
        return {linha["grau"]: linha["n"] for linha in cur}

    def total(self):
        return self.con.execute("SELECT COUNT(*) AS n FROM registro").fetchone()["n"]
    