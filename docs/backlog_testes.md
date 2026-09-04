# Backlog de testes

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-09-04                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Origem              | seção "Testes e Validação" dos 14 ADRs de `src/` |

Lista única das invariantes que valeria fixar em teste. Cada uma nasceu de um ADR, ao
documentar o módulo, e continua ligada a ele pela coluna **Módulo**.

**Nenhuma delas é bug conhecido.** São afirmações que o código faz hoje e que nada verifica.

## O que existe hoje

Não há suíte automatizada no repositório. Existem duas coisas próximas:

- `scripts/checar_offline.py` reprocessa os HTMLs de
  `data/spike/` **sem nenhuma requisição** e imprime estado, identidade, campos e vínculo de
  cada capa. Não há asserção nem veredito: a saída é lida por uma pessoa. Cobre
  `page_state`, `numero_processo`, os dois parsers e `vinculo`; **não** cobre `sqlite_store`,
  `exportador`, `projecao`, `limpeza` nem `coletar_um`.
- A validação operacional do [`menu`](scripts/menu.md): contagem por status impressa ao fim
  de cada execução, e `falhas_pendentes.txt` / `revisao_manual.txt` regenerados do banco.

Os fixtures já existem: os 14 arquivos `data/spike/<numero>_g<grau>.html` são HTML real do
e-SAJ, e a maior parte da camada de análise é composta de funções puras sobre string.

## Ordem sugerida

Por relação risco/custo, conforme as próprias páginas de origem:

1. `coletar_um` com um `client` dublê — a regra central é verificável pela **ausência** de uma chamada;
2. `page_state` sobre os fixtures do spike;
3. `parser_base` — classificação de polo, `_juiz_valido`, `completude`;
4. `exceptions` — uma linha, sem I/O nenhum;
5. `limpeza` — o mais barato: funções puras e casos-limite já conferidos à mão;
6. `reprojetar_vinculos` contra `SqliteStore(":memory:")` — idempotência e paginação.

## Invariantes

### scrapers

| Módulo | Invariante |
|---|---|
| `coletor` | `EsajRequisicaoError` no grau 1 devolve `erro_transitorio` e o dublê **não** recebe chamada do grau 2 — a regra central |
| `coletor` | `NAO_ENCONTRADO` no grau 1 **faz** o dublê receber a chamada do grau 2 |
| `coletor` | `NAO_ENCONTRADO` após seleção resolvida devolve `erro_transitorio` **sem** chamar o grau 2 |
| `coletor` | Segunda `LISTA_SELECAO` após abrir o detalhe usa o motivo da seleção aninhada, não "página não reconhecida" |
| `coletor` | `NAO_ENCONTRADO` nos dois graus devolve `sem_dados` com `grau == GRAU_INDETERMINADO` |
| `coletor` | `SENHA_SEGREDO` no grau 2 devolve `segredo_justica` com `grau == 2`, não `0` |
| `coletor` | Capa com identidade divergente devolve `erro_transitorio` e os CNJs achados aparecem no motivo |
| `coletor` | Capa com movimentações e sem partes devolve `erro_transitorio`, não `coletado` |
| `coletor` | `EsajIndisponivelError` do dublê **propaga** para fora, em vez de virar `erro_transitorio` |
| `esaj_client` | `Pacer.aguardar()` em sequência produz intervalos dentro de `[minimo, maximo]` |
| `esaj_client` | Após ociosidade longa, a chamada seguinte não dispara mais de um slot (`max(agora, _proximo)`) |
| `esaj_client` | `MonitorFalhas` abre no `limite`-ésimo `falha()` consecutivo; um `sucesso()` intercalado zera |
| `esaj_client` | `Pacer` compartilhado por T threads mantém a mesma taxa agregada de uma thread só |
| `exceptions` | `issubclass(EsajIndisponivelError, EsajError)` é `False` — a invariante da qual tudo depende |
| `exceptions` | Com `limite` alto e uma falha, `_levantar_falha` levanta `EsajRequisicaoError`, não `EsajIndisponivelError` |
| `numero_processo` | Número com máscara, sem máscara e com ponto no lugar do hífen produzem o mesmo `digitos` |
| `numero_processo` | `dv_esperado` reproduz o DV de um número real conhecido |
| `numero_processo` | `origem == "0000"` ⇒ `graus_a_tentar == (2,)`; caso contrário `(1, 2)` |
| `numero_processo` | `params_busca(1)` e `params_busca(2)` devolvem conjuntos de chaves diferentes |
| `page_state` | Capa com tabela de partes **não** é `LISTA_SELECAO` (guarda de `_e_selecao`) |
| `page_state` | Página com o formulário "Identificar-se" **não** é `SENHA_SEGREDO` |
| `page_state` | HTML vazio ou irreconhecível devolve `DESCONHECIDO`, nunca `DADOS_CAPA` nem `NAO_ENCONTRADO` |
| `page_state` | `escolher_na_selecao` devolve `verificada=True` com o número exato num rádio que **não** é o primeiro |
| `page_state` | `verificar_identidade` devolve `DIVERGE`, não `INDETERMINADO`, quando há CNJs e nenhum é o alvo |
| `parser_base` | `'Exeqte'` e `'Credor'` são `ATIVO`; `'Reqdo'` e `'Devedor'`, `PASSIVO`; `'Interessado'`, `OUTRO` |
| `parser_base` | `_rotulo_estrito("Juiz")` **não** casa com `'Juizado Especial Cível'` |
| `parser_base` | `_juiz_valido('Alvarado')` e `_juiz_valido('Areal')` são `True`; `'1ª Vara da Fazenda Pública'` é `False` |
| `parser_base` | Capa com movimentações e sem partes produz `tem_partes: False` e `tem_movimentacoes: True` |
| `parser_base` | `_extrair_processo_principal` devolve `None` quando o número só aparece na aba Apensos |
| `parser_base` | Os campos saem **sem** normalização: classe mantém parênteses, `valor` continua string |
| `parser_primeiro_grau` | Capa com `#juizProcesso` preenchido devolve exatamente esse valor |
| `parser_primeiro_grau` | Capa sem o id, com rótulo `Juiz` no layout `unj`, cai no passo 2 e devolve o nome |
| `parser_primeiro_grau` | Capa cujo texto próximo ao rótulo é nome de vara devolve `None` — o passo 3 |
| `parser_primeiro_grau` | `'Juizado Especial Cível'` na página não é confundido com o rótulo `'Juiz'` |
| `parser_segundo_grau` | Capa com seção "Números de 1ª Instância" devolve o CNJ em `processo_1a_instancia` |
| `parser_segundo_grau` | Número de origem citado numa movimentação **não** vira vínculo — a parada no próximo título |
| `parser_segundo_grau` | `foro` e `vara` não recebem as colunas homônimas da tabela de 1ª instância |
| `parser_segundo_grau` | Capa com `Processo principal` **e** número de 1ª instância preenche os dois campos |
| `parser_segundo_grau` | Formato antigo (`26747/2005`) dá `processo_1a_instancia: None` **e** `_bruto` preenchido — nos dois caminhos: tabela da seção e `#numeroProcessoPrimeiraInstancia` sozinho |

### status, store, transformers e aggregators

| Módulo | Invariante |
|---|---|
| `status` | Todo status é aceito por `SqliteStore` no caminho apropriado, sem `ValueError` |
| `status` | Todo status ramificado pela `projecao` é um dos declarados no módulo |
| `status` | `registrar_erro` promove a `erro_persistente` exatamente na `TETO_TENTATIVAS_PADRAO`-ésima tentativa |
| `sqlite_store` | `(N, 0, erro_transitorio)` seguido de `(N, 1, coletado)` deixa **uma** linha para `N` |
| `sqlite_store` | `registrar_erro` no teto devolve `erro_persistente` só na última, `erro_transitorio` antes |
| `sqlite_store` | `registrar_resultado` com `erro_transitorio` levanta `ValueError` |
| `sqlite_store` | `(N, 1)` e `(N, 2)` coexistem como registros distintos — a razão da chave composta |
| `sqlite_store` | `orfaos()` não devolve pai gravado como `sem_dados`, mas devolve pai nunca gravado |
| `sqlite_store` | `orfaos()` não devolve pai citado no grau 1 que existe no grau 2; `graus_citados` traz o grau citado |
| `sqlite_store` | `iter_exportaveis()` traz `ultimo_erro` num `erro_persistente` e `None` num `coletado` que falhara |
| `sqlite_store` | `iter_exportaveis()` não devolve nenhum registro `erro_transitorio` |
| `sqlite_store` | Caminho com `OneDrive` levanta `PastaSincronizadaError`; com o escape explícito, abre |
| `sqlite_store` | `reprojetar_vinculos` é **idempotente**: a segunda passada devolve `alterados = 0` |
| `sqlite_store` | Registro gravado com regra antiga sai com o valor novo após uma passada, **sem** requisição |
| `sqlite_store` | `vistos == total()` — nenhum registro escapa da paginação, inclusive o primeiro (cursor `("", -1)`) |
| `sqlite_store` | Com mais de 500 registros, `vistos == total()` e nenhuma linha é visitada duas vezes |
| `sqlite_store` | A reprojeção altera as três colunas de vínculo, `atualizado_em` e `bruto["observacoes"]` — e nada mais do `bruto` |
| `sqlite_store` | Com `versao_regra_vinculo` já gravado e `forcar=False`, a reprojeção devolve `{"pulado": True}` sem ler nenhuma linha |
| `sqlite_store` | Interromper a reprojeção e rodar de novo termina o serviço com o mesmo resultado |
| `limpeza` | Toda função devolve `None` — nunca `''` — para entrada vazia ou não convertível |
| `limpeza` | `limpar_classe` resolve parênteses aninhados e múltiplos numa passada |
| `limpeza` | `dedup_nomes` preserva a grafia da **primeira** aparição e mantém a ordem |
| `limpeza` | `dedup_movimentacoes` ordena por data crescente, com as datas `None` **no fim** |
| `limpeza` | `valor_para_float(3724.16)` devolve `3724.16` — idempotência sobre valor já convertido |
| `limpeza` | Um valor com centavos vence um ano que apareça **antes** dele — a razão dos dois passos |
| `vinculo` | Auto-referência no link do topo devolve `indefinido` com observação |
| `vinculo` | A aresta `(N, 2) → (N, 1)` é preservada: devolve `recurso` com `processo_pai_grau = 1` |
| `vinculo` | Link do topo e 1ª instância juntos devolvem `incidente`, com o recurso em `observacoes` |
| `vinculo` | Entre duas movimentações, vence a de data mais antiga; data ilegível **não** vence |
| `vinculo` | CNJ sem a expressão "processo principal" antes **não** gera vínculo |
| `vinculo` | Pai com DV inválido devolve `indefinido` mesmo se a **mensagem** da observação for reescrita |
| `vinculo` | Grau 1 sem sinal devolve `sem_vinculo` com `observacoes` vazia |
| `vinculo` | Grau 2 sem 1ª instância devolve `sem_vinculo` com **uma** observação |
| `vinculo` | Após `reprojetar_vinculos`, `segredo_justica` com `sem_vinculo` vira `indefinido`; a 2ª passada não altera |
| `projecao` | `segredo_justica` com filhos preserva `processos_filhos` — o sigilo não corta a topologia |
| `projecao` | Os quatro status produzem o **mesmo conjunto de chaves**; status fora do vocabulário gera a observação própria |
| `projecao` | `erro_persistente` com `ultimo_erro` produz **duas** observações: a frase genérica e a causa |
| `projecao` | `chave(p,1) != chave(p,2)` e `chave(p,0) == chave(p,None)` |
| `projecao` | `grau = 0` no banco vira `grau: null` no documento |
| `projecao` | `inverter_filhos` de `(N,2) → (N,1)` mapeia `(N,1)` para `{(N,2)}` |
| `projecao` | Observações repetidas nas duas origens aparecem uma vez só, na ordem de primeira aparição |
| `projecao` | Partes todas em `OUTRO` produzem autores e réus vazios **com** a observação correspondente |
| `exportador` | Linhas do arquivo == `resumo["total"]` == soma de `por_status` |
| `exportador` | **Nenhuma linha tem `status: "erro_transitorio"`** — a garantia de `STATUS_EXPORTAVEIS` |
| `exportador` | Cada linha é JSON válido isoladamente e todas têm o mesmo conjunto de chaves |
| `exportador` | Os `_id` são únicos no arquivo — a chave `(processo, grau)` respeitada de ponta a ponta |
| `exportador` | `com_filhos <= total` e `com_filhos + pares_pai_sem_documento == len(mapa_filhos)` |
| `exportador` | Exceção no laço deixa o arquivo anterior intacto e **não** deixa `.tmp` — JSONL e órfãos |
| `exportador` | `KeyboardInterrupt` produz o mesmo resultado — a razão de o `except` ser `BaseException` |
| `exportador` | Pai sem registro aparece em `orfaos.txt`; gravado como `sem_dados`, não aparece mais |
| `exportador` | **Toda linha de `orfaos.txt` sobrevive a `ler_numeros`** — nenhuma tem 21 dígitos |
| `exportador` | `orfaos_diagnostico.txt` tem uma linha de dados por linha de `orfaos.txt`, na mesma ordem |
| `exportador` | Pai citado no grau 1 que existe no grau 2 não entra em `orfaos.txt`, mas conta em `pares_pai_sem_documento` |

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-09-04 | @alexandrehiero | Criação: consolidação das 89 invariantes antes dispersas na seção "Testes e Validação" dos 14 ADRs de `src/` |
