# Base final de um ano – `scripts_final/preparar_base_final.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-10-23                                 |
| Data de atualização | 2026-10-29                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `tqdm`; [`menu`](../scripts/menu.md) e os módulos `consolidacao`, `atos_pge`, `exportador_gpdr`, `estrutura_gpdr` |

## Contexto e Motivação

O [`menu`](../scripts/menu.md) termina numa base JSONL por projeto. Para virar base de pesquisa, ela ainda precisa responder a duas perguntas e mudar de forma. As perguntas: **a coleta pegou tudo o que a lista do ano pedia? algum processo aparece duas vezes?** A forma é a da base do GPDR (`Codigos_dados_GPDR`, v7), para que as duas se carreguem no mesmo MongoDB e se consultem pelos mesmos campos.

Este script faz as três coisas num comando. O operador copia o JSONL para `data_final/JSONL_final/base_final_<ano>.jsonl` e roda o ano. Se faltar processo, o script **usa o próprio orquestrador** para buscá-lo, acrescenta o resultado ao JSONL, remove os duplicados e grava a estrutura final.

## Decisões de Pipeline

| Passo | O que faz | Rede? |
|---|---|---|
| 1 auditoria | Confronta o JSONL com `data/por_ano/processos_tjsp_<ano>.txt` | Não |
| 2 coleta | Busca no e-SAJ os faltantes, os `erro_persistente` e os `sem_dados` de `9xxx`/`0500` | **Sim** |
| 3 consolidação | Acrescenta a coleta ao JSONL e remove duplicados | Não |
| 4 índice PGE | Separa do `processos_PGE.json` os blocos dos processos da base | Não |
| 5 estrutura | Grava `data_final/JSON_final/base_final_<ano>.json` + `.meta.json` | Não |

- **A coleta é um projeto do menu, `faltantes_<ano>`** — lista em `data/entrada/`, banco em `ORQUESTRADOR_DB_DIR`, saída em `data/saida/`. O laço é o `executar_coleta` do menu, com o mesmo `Pacer` e o mesmo disjuntor. Nada de coleta paralela ao orquestrador: se algo ficar pendente, o operador continua por `menu.py faltantes_<ano>`.
- **`erro_persistente` volta para a coleta** — está na base, mas é "não consegui perguntar". Se a nova tentativa responder, a resposta substitui o erro. Se falhar de novo, vira `erro_persistente` no banco dos faltantes e não volta mais: a segunda execução não insiste.
- **`sem_dados` de rota nova volta para a coleta** — antes do `cposgcr`, todo processo do Colégio Recursal (`9xxx`) virava `sem_dados`; na base de 2025 eram 7.498, nenhum `9xxx` com dado. A auditoria separa os `sem_dados` dessas origens (`menu.rota_nova`) em `rotas_novas.txt` e os manda para a coleta, da base inteira e não só da lista: o erro é do dado. Se a rota certa confirmar o "não existe", o empate fica com a base e o JSONL não muda.
    - **O banco dos faltantes também é reaberto** — antes de montar a fila, `menu.reabrir_rotas_novas` aplica a reabertura da opção 5: um `faltantes_<ano>` de antes das rotas novas guarda esses números como `sem_dados` ou `erro_persistente`, e `numeros_finalizados()` os pularia.
- **`--recoletar` para quando a base tem a linha velha** — os números do arquivo vão para a coleta mesmo com desfecho, na base ou no banco dos faltantes, e com status igual fica a coleta nova (`preferir_coleta` em [`consolidacao`](../src/aggregators/consolidacao.md)). Existe porque o JSONL não guarda o bruto: uma regra de extração corrigida depois (a sucessora do credor no precatório) não alcança a base do ano pela opção 4. É pontual — repetir o argumento recoleta de novo.
- **A recoleta (opção 2) roda sozinha logo depois** — em rodadas, até o teto de tentativas. Termina sempre, porque cada falha soma uma tentativa.
- **Coleta interrompida não consolida** — disjuntor ou `Ctrl+C` encerram com código 1. O banco guarda o que foi pago, e rodar de novo retoma de onde parou.
- **Desduplicação por número, ficando o status mais informativo** — e, no empate, a base. Detalhes em [`consolidacao`](../src/aggregators/consolidacao.md).
- **O JSONL só é reescrito quando algo entra ou sai** — e as linhas removidas vão, byte a byte, para `auditoria/<ano>/removidos_<carimbo>.jsonl`. Com a base completa, o script não usa a rede nem toca no JSONL: a segunda execução é idempotente (conferido por checksum).
- **Os filhos são recalculados sobre a base consolidada** — o registro de um pai não sabe dos filhos acrescentados agora.
- **A amostra não escreve nada com nome de base** — `--amostra N` não coleta, não reescreve o JSONL e grava em `data_final/_amostra/`.

## Como Executar

```bash
uv run python scripts_final/preparar_base_final.py 2025                # fluxo completo
uv run python scripts_final/preparar_base_final.py 2025 --sem-coleta   # sem rede
uv run python scripts_final/preparar_base_final.py 2025 --amostra 2000 # smoke test
uv run python scripts_final/preparar_base_final.py 2025 --recoletar lista.txt  # recoleta pontual
```

O argumento é o sufixo do arquivo em `data/por_ano/` (`2025`, `1913_1973`, `ano_atipico`…).

## Principais Parâmetros (constantes no código)

| Constante / caminho | Valor | Descrição |
|-----------|-------|-------------|
| entrada | `data_final/JSONL_final/base_final_<ano>.jsonl` | Base da coleta, colocada à mão |
| lista | `data/por_ano/processos_tjsp_<ano>.txt` | O que devia ter sido coletado |
| `ATOS_PGE` | `data/processos_PGE.json` | Movimentações do Atos da PGE (o `processos.json` do GPDR) |
| `IPCA` | `data/ipca_mensal.csv` | Tabela 1737 do SIDRA, a mesma do GPDR |
| `FOROS` | `data/unidades_foro_tjsp.md` | Resolução TJSP nº 65/2008, a mesma do GPDR |
| saída | `data_final/JSON_final/base_final_<ano>.json` | Array JSON (`mongoimport --jsonArray`) |
| auditoria | `data_final/auditoria/<ano>/` | `faltantes`, `sem_desfecho`, `rotas_novas`, `duplicados`, `fora_da_lista`, `nao_coletados`, `orfaos`, `invalidos` |
| índice | `<ORQUESTRADOR_DB_DIR>/indice_pge_<ano>.db` | SQLite temporário, apagado no fim |

## Logs e Monitoramento

`print()` e `tqdm.write()`, como o [`menu`](../scripts/menu.md). As barras são por **bytes lidos**, porque o JSONL e o Atos não declaram quantos documentos têm. O `.meta.json` guarda todas as contagens da execução, no molde do `_v{N}.meta.json` do GPDR, e mais `foros_fora_da_tabela`. Ao fim, o script confere se os documentos escritos são exatamente os processos distintos e sai com código 1 se a conta não fechar.

## Falhas Conhecidas e Workarounds

- **e-SAJ fora do ar ou bloqueio durante a coleta.** Nada é consolidado; rode o mesmo comando para retomar.
- **"Pais fora da base" na casa das dezenas de milhares.** É esperado numa base por ano: o pai de um processo de 2025 costuma ser de 2023 ou 2024 e está na base daquele ano. O número que importa é o "dos anos da lista".
- **Foro sem descrição.** A Resolução 65/2008 não traz unidades criadas depois (Núcleos 4.0, `9061`). A capa não serve de substituta, porque mostra o foro atual. Os códigos saem no `.meta.json`.
- **Os `sem_dados` legítimos de `9xxx`/`0500` voltam à fila em toda execução.** Sem rede: o banco dos faltantes já os respondeu, e o empate mantém a base. Só custa a passada local.
- **`tiposParte` vazio.** O JSONL não traz o tipo de parte. Ver [`estrutura_gpdr`](../src/transformers/estrutura_gpdr.md).

## Decisões Futuras

- [ ] Coletar automaticamente os órfãos **dos anos da lista** (opção 3), hoje só listados.
- [ ] Atualizar `unidades_foro_tjsp.md` com os códigos posteriores a 2008.
- [ ] Levar `tipo_parte` à projeção do JSONL, para preencher `tiposParte`.

## Relação com Outros Artefatos

| Artefato | Usado para |
|---|---|
| [`menu`](../scripts/menu.md) | `ler_numeros`, `configurar_projeto`, `executar_coleta`, `atualizar_arquivos_de_falha`, `rota_nova`, `reabrir_rotas_novas` |
| [`exportador`](../src/aggregators/exportador.md) | Export do banco dos faltantes, depois de `reprojetar_vinculos` |
| [`consolidacao`](../src/aggregators/consolidacao.md) | Auditoria, desduplicação, filhos e reescrita do JSONL |
| [`atos_pge`](../src/aggregators/atos_pge.md) | Índice dos blocos `movimentos_pge` / `origem_pge` |
| [`exportador_gpdr`](../src/aggregators/exportador_gpdr.md) | Array JSON final, em streaming |

## Lições Aprendidas

- **Recalcular filhos só sobre a base apaga arestas verdadeiras.** No teste com um recorte da base, 6 de 7 "correções" removiam filhos que estavam fora do recorte. Filho fora da base agora fica como veio.
- **O GPDR é a régua.** Valor corrigido, nomes e blocos da PGE foram conferidos contra a v7: 3.003 valores, 5.003 nomes e 400 blocos, zero diferenças.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-10-23 | @alexandrehiero | Criação |
| 2026-10-29 | @alexandrehiero | `sem_dados` de `9xxx`/`0500` voltam para a coleta (`rotas_novas.txt`); o banco `faltantes_<ano>` é reaberto antes da fila |
| 2026-10-29 | @alexandrehiero | `--recoletar`: recoleta pontual que vence o empate; usado nos 44 precatórios de 2025 sem autor |
