# Movimentações do Atos da PGE – `src/aggregators/atos_pge.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-23                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `json`, `codecs`, `sqlite3` — sem dependências externas |

## Contexto e Motivação

`data/processos_PGE.json` é o acervo do sistema Atos de toda a Procuradoria: 451.762 documentos, 9 GB, um array JSON. Na base final, cada processo recebe `movimentos_pge` e `origem_pge` vindos dele, ou `null` explícito quando não tem par. É o mesmo enxerto da v5 do GPDR, cujo bloco este módulo reproduz.

Um mesmo CNJ pode aparecer em vários documentos da origem: são incidentes (execuções, cumprimentos) com movimentos disjuntos. Cada caderno entra inteiro e contíguo, na ordem do arquivo, e cada movimento leva o número do incidente. A ordem de cada caderno é invertida para "mais recente primeiro", como `movimentos_tjsp`.

## Decisões de Arquitetura

- **O índice mora num SQLite temporário, não num dict** — na lista de 2025 são 123 mil CNJ com par, 1,6 GiB de JSON. O GPDR coube em memória com 63 mil (0,9 GiB); um ano recente não cabe com folga numa máquina com 3 GiB livres. O arquivo é derivado, sem journal nem fsync, refeito a cada execução e apagado no fim (`IndicePge.fechar`).
- **Leitura com `JSONDecoder.raw_decode`, não `ijson`** — decodifica um item a partir de uma posição e diz onde ele termina; o arquivo é lido em blocos de 1 MB e só um item vive em memória. O decodificador é o C da biblioteca padrão, a ~110–150 MB/s (pouco mais de 1 min para os 9 GB). O `ijson` seria dependência nova e, sem o backend `yajl2_c` (que pode não ter roda para o Python do projeto), levaria horas.
- **Item que não terminou no bloco: ler mais e tentar de novo** — a leitura cresce com o item, para que um item grande não custe uma tentativa por megabyte. Um item sem fim depois de 256 MB é arquivo corrompido, e o erro sai antes de trazer o resto dos 9 GB para a memória.
- **Barra por bytes** — `ao_ler` recebe os bytes de cada bloco, e a decodificação incremental (`utf-8-sig`) não parte um caractere de vários bytes entre dois blocos.
- **Só os CNJ da base entram no índice** — guardar os outros 300 mil custaria disco para dado que ninguém vai ler.
- **`dict.fromkeys` para `pastaIds`, `nucleos` e `incidentes`** — remove repetição preservando a ordem, que um `set` não garante entre execuções.
- **Extremos de data comparados como instante** — `…-02:00` é maior que `…-03:00` como texto e menor como instante.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Índice em dict, como o GPDR | 1,6 GiB de texto em 2025, numa máquina com 3 GiB livres. |
| `ijson` | Dependência nova; sem `yajl2_c`, horas por passada. |
| Ler o arquivo linha a linha | Hoje cada documento ocupa uma linha, mas isso é formatação da origem, não contrato. |
| Manter o índice entre execuções | O conjunto de CNJ muda quando a base é completada; um índice velho daria `null` errado. |

## Limitações Conhecidas

- **O Atos não tem registro antes de 2022-03-04** (medido no GPDR): `movimentos_pge` não é histórico paralelo a `movimentos_tjsp`, e comparar contagens entre os dois não tem significado.
- **A passada pelos 9 GB se repete a cada execução,** mesmo sem nada novo na base: pouco mais de 1 minuto, o preço de não manter um índice que poderia estar velho.

## Exemplo de Uso

```python
from src.aggregators import atos_pge

with atos_pge.IndicePge(DIR_BANCOS / "indice_pge_2025.db") as indice:
    contagens = indice.montar(Path("data/processos_PGE.json"), cnj_da_base)
    bloco = indice.obter("00000073620258260383")   # ou None, sem par
```

## Testes e Validação

- `ler_array_json` contra 120 combinações de formato (compacto, indentado, uma linha por item, com e sem BOM, CRLF) e blocos de 1 a 1 MB, inclusive caracteres de 4 bytes partidos entre blocos; e contra 4 entradas malformadas, todas recusadas.
- 400 blocos reconstruídos de `processos_PGE.json` comparados com `movimentos_pge` e `origem_pge` da v7 do GPDR: **zero diferenças**.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação, com o bloco portado da v5 do GPDR |
