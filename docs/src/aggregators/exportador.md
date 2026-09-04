# Export da base final – `src/aggregators/exportador.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `json`, `os`, `pathlib`, `collections.Counter`; `src.transformers.projecao` |

## Contexto e Motivação

Este módulo produz o artefato que sai do projeto: o arquivo que outro pesquisador vai importar no MongoDB ou abrir no pandas. São 126 linhas e três decisões que só fazem sentido na escala em que ele opera.

**Streaming é obrigatório.** O consolidador antigo montava uma lista com todos os registros e chamava `json.dumps` sobre ela. O custo é duplo, e o segundo é o que mata: além dos objetos Python em memória, `json.dumps` monta **a string inteira** antes de escrever o primeiro byte. O processo precisa segurar simultaneamente a estrutura e sua serialização. É uma operação que não fica lenta — ela simplesmente não termina.

As outras duas: **JSONL e não array JSON**, porque o `mongoimport` consome JSONL nativamente em streaming; e **escrita atômica**, porque interromper no meio nunca pode deixar uma base truncada por cima da anterior.

## Decisões de Arquitetura

- **JSONL, não array JSON** — um array só é válido depois do `]`, o que obriga qualquer leitor a processar o arquivo inteiro antes de entregar o primeiro registro. Cada linha do JSONL é um documento completo: o `mongoimport` consome em streaming, `head`/`grep`/`wc -l` funcionam, e a escrita é incremental.
- **`ensure_ascii=False`** — mantém acentos como UTF-8 em vez de escapes `\uXXXX`: arquivo menor e legível a olho nu, com o encoding já declarado na abertura.
- **Memória constante, com uma exceção declarada** — o laço não acumula nada: `iter_exportaveis` é gerador, `projetar` é pura, o documento é descartado após ser escrito. O que fica residente é o `mapa_filhos`, e a docstring diz isso em vez de fingir constância absoluta. A exceção é inevitável: para saber os filhos de um processo é preciso ter visto **todas** as arestas.
- **Os filhos são calculados agora, nunca lidos de um campo** — o banco guarda uma direção (filho → pai) e a outra é derivada no export. Reconstruído a cada opção 4, o mapa não pode estar desatualizado: não existe janela entre "gravar o pai" e "atualizar o filho".
- **Escrita atômica com `.tmp` + `os.replace`** — atômico dentro do mesmo sistema de arquivos, e o `.tmp` fica no mesmo diretório para garantir isso. Sem ele, um `Ctrl+C` no meio deixaria um JSONL truncado **por cima** do anterior, que estava íntegro — e o truncado nem parece quebrado: as linhas que existem são JSON válido.
- **O `.tmp` é removido quando o export falha** — a base anterior já estava protegida pelo `os.replace`; o que este bloco resolve é operacional: um `.tmp` de vários GB esquecido no disco após uma queda. Usa `BaseException` (não `Exception`) porque o caso real é `KeyboardInterrupt`, e `raise` nu para re-levantar com o traceback intacto.
- **`erro_transitorio` fica de fora por construção, não por filtro** — não há `if status != ...` neste módulo. A exclusão vem de `STATUS_EXPORTAVEIS`, em [`status`](../status.md). Mudar o que entra na base final é mudar o vocabulário num lugar só. O motivo de fundo é conceitual: `erro_transitorio` não é resultado, é item de fila.
- **O resumo é devolvido, não impresso** — o módulo calcula e o [`menu`](../../scripts/menu.md) apresenta. Isso é o que permite passar `tqdm.write` como `log`, necessário para a mensagem não corromper a barra de progresso.
- **`com_filhos` e `pares_pai_sem_documento` contam populações diferentes, e o nome carrega a unidade** — `total`, `com_pai` e `com_filhos` falam de **documentos escritos**; `pares_pai_sem_documento` fala de **pares `(pai, grau)` citados** que nenhum documento reivindicou. A chave antiga, `len(mapa_filhos)`, incluía pais citados e não coletados e era impressa ao lado de `com_pai`, convidando a uma subtração sem significado. O nome anterior, `pais_citados_sem_registro`, descrevia com precisão **outra** coisa — os órfãos, que são números sem registro.
- **`escrever_lista_orfaos` usa o critério "não tem REGISTRO", não "não tem dados"** — é o que faz o ciclo 4 → 3 → 4 **convergir**: um processo que o e-SAJ afirma não existir foi visitado e sai da lista definitivamente.
- **`orfaos.txt` tem uma coluna só** — o arquivo é lido de volta pela opção 3, e `ler_numeros` aplica `so_digitos` à **linha inteira**. Uma linha `...\t1` viraria 21 dígitos e seria rejeitada: o órfão sairia da fila em silêncio. Não é preferência de formato — acrescentar qualquer coisa **quebra** o consumidor.
- **O diagnóstico vai para arquivo separado** — `orfaos_diagnostico.txt` guarda `processo\tgraus_citados`, com aviso de que é leitura humana. É o que faz o `GROUP_CONCAT` de `orfaos()` chegar ao disco em vez de ser calculado e descartado, e é o insumo para reconhecer "o pai existe, mas só no outro grau".
- **Escrever só o número é a granularidade correta, não uma perda** — as quatro etapas do ciclo falam de números, e `coletar_um` escolhe o grau sozinho pela origem do CNJ. Não há a quem entregar um grau.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Montar uma lista e chamar `json.dumps` sobre ela | Modelo do consolidador anterior: dezenas de GB em RAM **mais** a string inteira materializada antes do primeiro byte. Não fica lento, não termina. |
| Array JSON (`[{...}, {...}]`) | Só é válido depois do `]`: obriga o leitor a processar tudo antes do primeiro registro, e 15 GB ficam ilegíveis por qualquer ferramenta. |
| CSV | A estrutura tem aninhamento (partes por polo, movimentações, referências com número e grau). Achatá-la perderia a forma ou exigiria JSON dentro de CSV. |
| `ensure_ascii=True` (padrão do `json`) | Acentos viram `\uXXXX`: arquivo maior e ilegível, sem ganho — o encoding já está declarado como UTF-8. |
| Escrever direto no arquivo final | Uma interrupção deixa a base truncada por cima da anterior, que estava íntegra. E o truncado não parece quebrado. |
| Gravar os filhos no banco e apenas ler aqui | Duas fontes de verdade para a mesma aresta, com janela de divergência entre gravar o pai e atualizar o filho. |
| Filtrar `erro_transitorio` neste módulo | Espalharia a definição do que entra na base final. Ela vive em `STATUS_EXPORTAVEIS`, num lugar só. |
| Imprimir o resumo aqui | Amarraria o módulo ao console. Devolvendo o dicionário, quem chama decide o formato — e é o que permite ao menu usar `tqdm.write`. |
| Calcular as contagens numa segunda passada | Exigiria reler o arquivo escrito. Os contadores custam nada acumulados no mesmo laço. |
| Reportar `len(mapa_filhos)` como "pais com filhos" | Conta pais citados e não coletados, que não estão na base final. Ao lado de `com_pai`, convidava a uma comparação sem significado. |
| `except Exception` na limpeza do `.tmp` | Não pega `KeyboardInterrupt`, que é justamente o caso real: `Ctrl+C` no meio de um export longo. |
| Deixar o `.tmp` no disco para inspeção pós-falha | Vários GB esquecidos sem aviso, num projeto que roda em notebook. O traceback já diz o que falhou. |
| Gravar o grau na lista de órfãos | Além de não haver a quem entregá-lo, `ler_numeros` extrai dígitos da linha inteira: o grau viraria um 21º dígito e o órfão sairia da fila em silêncio. |
| Descartar `graus_citados` de vez | Perderia o único insumo para diagnosticar "o pai existe, mas só no outro grau". |
| Deixar o diagnóstico só no console | Some com a rolagem do terminal. O arquivo fica ao lado da base final e pode ser conferido depois. |

## Limitações Conhecidas

- **`mapa_filhos` cresce com o número de arestas.** É a única estrutura residente; numa base em que a maioria dos processos tem vínculo, ele se aproxima do tamanho da base.
- **`pares_pai_sem_documento` e `orfaos.txt` medem populações diferentes.** O nome novo torna a diferença legível, não a elimina: quem comparar os dois precisa saber que a divergência é informativa, não erro.
- **`escrever_lista_orfaos` faz duas escritas de arquivo e nenhuma é transação.** Uma falha entre os dois `os.replace` deixa a lista atualizada e o diagnóstico velho — inconsistência que nenhum dos dois denuncia. Risco baixo, não zero.
- **O diagnóstico é regravado inteiro a cada opção 4.** Não guarda histórico; comparar duas rodadas exige ter copiado o arquivo antes.
- **`por_grau` usa a chave `None` para grau indeterminado.** O resumo sai como `{None: 12, 1: 340, 2: 88}`.
- **O export não registra quando foi feito.** O JSONL não tem cabeçalho nem metadados, e `atualizado_em` não é projetado: duas bases exportadas em momentos diferentes são indistinguíveis pelo conteúdo.
- **`escrever_lista_orfaos` não usa o `log` injetável.** Irrelevante hoje: a consulta é única e a escrita é curta.

## Exemplo de Uso

As duas funções são chamadas em sequência pela opção 4, que é inteiramente local — sem rede. A **ordem é parte do contrato**: as duas leem as colunas de vínculo, e quem as regrava é [`reprojetar_vinculos`](../store/sqlite_store.md). Exportar antes produziria um JSONL e uma lista de órfãos coerentes com a regra **antiga**, sem nenhum sinal.

```python
from src.aggregators.exportador import escrever_lista_orfaos, exportar_jsonl

store.reprojetar_vinculos(derivar_vinculo, INDEFINIDO, VERSAO_REGRA)   # PRIMEIRO
resumo = exportar_jsonl(store, JSONL, log=tqdm.write)
orfaos = escrever_lista_orfaos(store, ORFAOS)      # grava também orfaos_diagnostico.txt

# resumo = {'arquivo': ..., 'total': 9, 'por_status': {'coletado': 5, ...},
#           'por_grau': {None: 1, 1: 6, 2: 2}, 'com_pai': 3, 'com_filhos': 3,
#           'pares_pai_sem_documento': 0}
```

Lista vazia fecha o ciclo: todo processo citado no relacionamento tem registro.

## Testes e Validação

Não há suíte automatizada, e `scripts/checar_offline.py` **não alcança este módulo**: para no parser e no vínculo, sem tocar em banco nem em export. A validação em uso é o resumo impresso pela opção 4 — `total` deve bater com a soma de `por_status` e com `wc -l base_final.jsonl`, o que só é possível **porque** a saída é JSONL e todo registro produz exatamente uma linha. O módulo é testável contra `SqliteStore(":memory:")` populado à mão. As 11 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-11 | @alexandrehiero | Ponto em aberto resolvido pela mudança de critério em `orfaos()`; `com_filhos` e limpeza do `.tmp` documentados |
| 2026-08-11 | @alexandrehiero | `pares_pai_sem_documento`; `orfaos_diagnostico.txt`; `.tmp` protegido também em `escrever_lista_orfaos` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 10 decisões virou lista de tópicos; código copiado removido; invariantes migradas para o backlog de testes |
