# Estado da página e identidade – `src/scrapers/page_state.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `beautifulsoup4`, `re`, `unicodedata` |

## Contexto e Motivação

O [`EsajClient`](esaj_client.md) devolve HTML e nada mais — o e-SAJ responde HTTP 200 para "encontrei", "não existe" e "é sigiloso" indistintamente. Alguém precisa converter texto em significado, e é este módulo.

Mas ele carrega uma responsabilidade maior que classificar páginas: **conferir se a página aberta é a do processo pedido**. Vale insistir no porquê. Um erro de rede aparece no log; um seletor quebrado produz campos vazios. Já entrar no processo errado gera um registro **perfeito** — classe, partes e movimentações preenchidas, tudo válido, tudo do processo errado, arquivado sob o número que você pediu. O relacionamento é montado em cima disso. Numa base de centenas de milhares de linhas esse erro é invisível por construção, e é o que este módulo existe para tornar impossível.

## Decisões de Arquitetura

- **Cinco estados explícitos, incluindo `DESCONHECIDO`** — não é descuido de exaustividade: é o estado que dá ao orquestrador a opção de **não gravar**. A alternativa comum, tratar "não reconheci" como "capa vazia", grava um registro sem dados como se fosse resultado legítimo. Layout novo, manutenção, bloqueio e captcha caem todos aqui e voltam para a fila.
- **A ordem da classificação é parte da lógica** — os testes não são mutuamente exclusivos: uma página pode satisfazer mais de um. Primeiro "não encontrado" e "seleção"; segredo só vale se não houver dados de capa; capa por último.
- **`_e_segredo` exige a senha E a ausência de capa** — o detector óbvio, procurar um campo de senha, classificaria **toda** página como sigilosa, porque o formulário "Identificar-se" está em todas. A conjunção cobre também o caso em que a capa aparece normalmente e o aviso se refere a um documento específico dentro dela.
- **Detector e resolvedor leem os MESMOS seletores** — antes o detector conhecia só `a.linkProcesso` e o resolvedor tinha um fallback a mais. Como o resolvedor só roda **depois** de o detector aprovar, uma página que usasse apenas a segunda forma jamais chegava a ele: o fallback era código morto por construção e a página caía em `DESCONHECIDO`. O erro de fundo é dois lugares responderem "o que é um link de seleção?" com listas diferentes.
- **`escolher_na_selecao` concatena os dois seletores, não usa `or`** — `select(A) or select(B)` embute a suposição falsa de que "existe link do tipo A" equivale a "o número está em algum link do tipo A". Se A existisse sem casar o número, B nunca seria consultado, e a função degradava em silêncio para o **palpite do primeiro rádio**. A ordem dos seletores continua sendo a de preferência, porque o laço percorre a lista concatenada.
- **`_e_selecao` recua diante de uma capa** — a capa de um processo com incidentes exibe links que se parecem exatamente com os de uma tela de seleção. Sem a guarda, uma capa legítima seria tratada como lista de escolha e os dados **do incidente** seriam gravados sob o número do principal. A cláusula `#numeroProcesso` acompanha a ampliação do detector: se a página exibe o número isolado, ela é a página **daquele** processo. O critério é o mesmo de `_e_capa`, o que torna as duas classificações mutuamente exclusivas por construção, não por ordem de teste.
- **As frases de "não encontrado" falham para o lado seguro** — a lista é o gatilho de duas ações irreversíveis: gravar `sem_dados` (terminal) e avançar de grau. Uma mudança de redação degrada para `DESCONHECIDO` → `erro_transitorio`, que volta à fila. **O modo de falha é ruído, nunca dado errado.** Inferir "não encontrado" pela ausência de capa inverteria isso: toda quebra de seletor viraria "este processo não existe".
- **`verificar_identidade` devolve TRÊS valores, não um booleano** — `DIVERGE` é evidência positiva de erro (a página traz números e nenhum é o pedido): abortar sempre. `INDETERMINADO` é ausência de evidência: pode ser layout diferente ou seletor desatualizado. O [`coletor`](coletor.md) combina esse valor com a procedência da navegação e só rejeita quando a chegada à página **também** foi incerta.
- **A comparação é de pertinência a um conjunto, não igualdade de string** — em incidentes o número vem **dentro** da classe, entre parênteses (`'Cumprimento de Sentença ... (0000010-31...)'`), não isolado em `#numeroProcesso`.
- **`escolher_na_selecao` nunca chuta em silêncio** — o código antigo pegava `radios[0]` assumindo que o principal é a primeira opção; quando não é, os dados do incidente eram gravados sob o número do principal. A degradação hoje é explícita e declarada no campo `verificada`.
- **`cnjs_no_texto` devolve um `set`** — dedup nativo, e toda pergunta feita sobre o resultado é de pertinência.
- **O texto é normalizado uma vez no construtor** — minúsculas, sem acento, espaços colapsados. É o que permite escrever as frases de busca sem acento e casar com qualquer variação de grafia ou espaçamento. A máscara CNJ aceita `-` ou `.` após o sequencial, porque números antigos usam ponto.

### A degradação de `escolher_na_selecao`, do mais seguro ao menos

| Passo | Critério | `verificada` | `motivo` |
|---|---|---|---|
| 1 | link cujo texto contém o número exato | `True` | `"link com número exato"` |
| 2 | rádio cuja **linha** (`<tr>`) contém o número exato | `True` | `"rádio com número exato"` |
| 3 | primeiro rádio disponível | `False` | `"PALPITE: primeiro rádio; número não conferido na modal"` |
| — | nada resolvível | `False` | `"nenhuma opção resolvível na seleção"` |

O passo 3 continua existindo, mas deixou de ser silencioso: ele se **declara** palpite, e quem chama fica obrigado a tratá-lo como tal. A última linha devolve `destino=None`, que o coletor converte em `erro_transitorio` — nunca em `sem_dados`.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Confiar que abrir o link da seleção leva ao processo certo | Quando não leva, o resultado é um registro completo e válido do processo **errado**, sob o número pedido. Nenhuma etapa posterior detecta. |
| `verificar_identidade` devolvendo booleano | Colapsaria `DIVERGE` (evidência de erro) e `INDETERMINADO` (ausência de evidência), que exigem respostas diferentes. |
| Comparar o número por igualdade com `#numeroProcesso` | Em incidentes o número vem dentro da classe, entre parênteses. A busca precisa ser por pertinência num conjunto de CNJs extraídos. |
| `radios[0]` como escolha padrão silenciosa (pipeline anterior) | Assume que o processo principal é a primeira opção. Quando não é, grava o incidente sob o número do principal. |
| Remover o passo 3 (palpite) e falhar sempre | Perderia processos recuperáveis. A solução mantém o palpite mas o marca, transferindo a decisão para a validação de identidade da página aberta. |
| Detectar segredo por `input[type="password"]` | O formulário "Identificar-se" existe em toda página do portal — marcaria a base inteira como sigilosa. |
| Detectar seleção antes de checar dados de capa | A capa lista incidentes com links parecidos com os da seleção; uma capa legítima cairia no caminho do palpite. |
| Detector e resolvedor com listas próprias de seletores | O resolvedor só roda depois de o detector aprovar. Um seletor que só ele conhecesse era código inalcançável, e a página caía em `DESCONHECIDO`. |
| `select(A) or select(B)` para os links da seleção | O `or` confunde "existe link do tipo A" com "o número está em algum link do tipo A". A escolha degradava para o palpite do primeiro rádio. |
| Inferir "não encontrado" pela ausência de dados de capa | Toda quebra de seletor viraria `sem_dados`, que é terminal e autoriza avançar de grau. Falha para o lado errado. |
| Não ter estado `DESCONHECIDO`, tratando o resto como capa vazia | Grava registro vazio como resultado legítimo, em vez de devolver o caso à fila. |
| `cnjs_no_texto` devolvendo `list` | Exigiria dedup manual; todas as perguntas sobre o resultado são de pertinência. |

## Limitações Conhecidas

- **`_FRASES_NAO_ENCONTRADO` é lista fechada de três frases.** Se a redação mudar, todo processo inexistente vira `DESCONHECIDO` → `erro_transitorio` → `erro_persistente`. A base não fica errada, mas a fila de falhas cresce sem explicação óbvia — é o primeiro lugar a olhar se a taxa de `erro_persistente` disparar.
- **A invariante de identidade admite uma exceção deliberada.** Na busca direta o coletor assume `verificada = True`, então uma capa `INDETERMINADO` **é gravada**. O raciocínio é que quem resolveu o número foi o próprio portal. O risco residual está confinado a páginas em que nenhum dos três seletores produz um CNJ — o mesmo sintoma que faria os seletores de capa falharem.
- **`verificar_identidade` só olha três seletores.** Uma capa com layout diferente devolve `INDETERMINADO` mesmo exibindo o número em outro lugar. A busca não é feita no texto inteiro **de propósito**: as movimentações citam números de outros processos, e um varrimento global encontraria o alvo em páginas que não são dele.
- **A classificação lê o texto completo da página.** Custo pago uma vez por página — e o coletor classifica duas vezes quando passa pela tela de seleção.
- **Não há distinção entre bloqueio, captcha, manutenção e layout novo.** Os quatro caem em `DESCONHECIDO`, com motivo genérico; diagnosticar exige olhar o HTML salvo pelo spike.
- **`_e_capa` aceita `#numeroProcesso` sozinho.** Uma página com o número e nenhuma tabela é classificada como `DADOS_CAPA` e segue para o parser; a rede de segurança fica na etapa seguinte. Ver [backlog §2](../../backlog.md).

## Exemplo de Uso

```python
from src.scrapers.page_state import (
    ClassificadorPagina, EstadoPagina, Identidade,
    escolher_na_selecao, verificar_identidade,
)

estado = ClassificadorPagina(html).classificar()      # 'DADOS_CAPA' | 'LISTA_SELECAO' | ...

if estado == EstadoPagina.LISTA_SELECAO:
    escolha = escolher_na_selecao(html, np)
    # EscolhaSelecao(destino='1H000AX8O0000', verificada=True, motivo='rádio com número exato')

if estado == EstadoPagina.DADOS_CAPA:
    identidade, achados = verificar_identidade(html, np)
    if identidade == Identidade.DIVERGE:              # a página traz CNJs, nenhum é o alvo
        ...                                           # NÃO GRAVAR — `achados` vai no motivo
```

## Testes e Validação

Não há suíte automatizada. A validação em uso é `scripts/spike_seletores.py`, que salva o HTML recebido em `data/spike/`, imprime o estado classificado e detalha a escolha, a identidade e os CNJs encontrados. **Este é o candidato mais forte do projeto a testes automatizados**, por um motivo concreto: o spike já produz os fixtures, e todas as funções daqui são puras sobre string. As 5 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Seletores de seleção compartilhados entre detector e resolvedor; `#numeroProcesso` na guarda de capa de `_e_selecao`; `or` trocado por concatenação em `escolher_na_selecao` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 11 decisões virou lista de tópicos; código copiado removido; invariantes migradas para o backlog de testes |
