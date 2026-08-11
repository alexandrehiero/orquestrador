"""Regressão offline: roda o pipeline de análise sobre os HTMLs de data/spike/.

Zero requisições — reprocessa páginas já baixadas. Serve para confirmar que
mudanças em page_state/parsers não alteraram o comportamento observado.

ATENÇÃO ao ler a saída: este script analisa a capa mesmo quando a identidade
DIVERGE, para permitir inspecionar a página. A coleta real NÃO faz isso — o
coletar_um barra antes de chamar o parser. Linhas de `vinculo` sob
`identidade: DIVERGE` são artefato do diagnóstico, não comportamento do pipeline.

Uso: python scripts/checar_offline.py
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.scrapers.coletor import PARSER_POR_GRAU
from src.scrapers.numero_processo import NumeroProcesso
from src.scrapers.page_state import (
    ClassificadorPagina, EstadoPagina, escolher_na_selecao, verificar_identidade,
)
from src.transformers.vinculo import derivar_vinculo

SPIKE = RAIZ / "data" / "spike"


def main():
    arquivos = sorted(SPIKE.glob("*_g[12].html"))
    if not arquivos:
        print(f"Nenhum HTML em {SPIKE}. Rode o spike primeiro.")
        return

    for caminho in arquivos:
        m = re.match(r"(\d{20})_g([12])\.html$", caminho.name)
        if not m:
            continue
        digitos, grau = m.group(1), int(m.group(2))
        np = NumeroProcesso.tentar(digitos)
        html = caminho.read_text(encoding="utf-8")
        estado = ClassificadorPagina(html).classificar()
        print(f"\n{digitos} g{grau} -> {estado}")

        if estado == EstadoPagina.LISTA_SELECAO:
            e = escolher_na_selecao(html, np)
            print(f"   escolha: verificada={e.verificada} | {e.motivo}")
        elif estado == EstadoPagina.DADOS_CAPA:
            ident, achados = verificar_identidade(html, np)
            d = PARSER_POR_GRAU[grau](html).parse()
            v = derivar_vinculo(d, grau, digitos)
            print(f"   identidade: {ident}")
            print(f"   classe={d['classe']!r}")
            print(f"   juiz={d['juiz']!r} | situacao={d['situacao']!r}")
            print(f"   distribuicao={d['data_distribuicao']!r}")
            print(f"   partes={len(d['partes'])} | movs={len(d['movimentacoes'])}")
            if grau == 2:
                print(f"   1a_inst={d.get('processo_1a_instancia')!r} "
                      f"bruto={d.get('processo_1a_instancia_bruto')!r}")
            print(f"   vinculo: {v['tipo']} -> {v['processo_pai']}")


if __name__ == "__main__":
    main()
