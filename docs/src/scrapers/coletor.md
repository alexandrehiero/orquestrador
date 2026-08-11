# Coleta de um processo (máquina de estados) – `src/scrapers/coletor.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-08-10                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `src.status`, `src.scrapers.page_state`, `src.scrapers.parser_primeiro_grau`, `src.scrapers.parser_segundo_grau`, `src.scrapers.exceptions` |

## Contexto e Motivação

Este módulo é onde as peças anteriores viram uma decisão. O
[`EsajClient`](esaj_client.md) traz HTML, o [`page_state`](page_state.md) diz o que aquele
HTML é, os [parsers](parser_base.md) extraem os campos — e o `coletor` decide o que tudo
isso significa para **um** processo: foi coletado, é sigiloso, não existe, ou não deu para
saber.

A docstring abre com a regra que governa o módulo:

> REGRA CENTRAL — só um NAO_ENCONTRADO explícito autoriza avançar de grau.
> Queda de rede, página não reconhecida ou seleção irresolvível devolvem
> erro_transitorio SEM tocar no grau seguinte. Se erro de rede fizesse avançar,
> um processo de 1º grau cuja consulta caiu por Wi-Fi seria buscado no 2º grau,
> encontrado lá e gravado com o GRAU ERRADO — contaminando em silêncio o
> relacionamento que este orquestrador existe para consertar.

Vale seguir esse cenário até o fim, porque ele explica a arquitetura do projeto inteiro.

Um processo tem número CNJ terminando em origem diferente de `0000`, então
`graus_a_tentar` devolve `(1, 2)`. A consulta ao 1º grau cai — Wi-Fi oscilou, o portal
demorou, qualquer coisa. Um coletor ingênuo interpreta "não consegui" como "não achei" e
tenta o 2º grau. E o 2º grau **responde**: processos sobem de instância, então existe mesmo
um registro daquele número em `cposg`. O coletor grava o processo com `grau = 2`.

O resultado é um registro perfeitamente formado, com dados verdadeiros, sob o grau errado.
E como a chave do banco é o par `(processo, grau)` e o relacionamento é construído sobre
essa chave, o recurso passa a ocupar o lugar do processo originário no grafo. Nada no
pipeline detecta — a base fica internamente consistente e factualmente errada.

Daí a regra: **"não consegui perguntar" nunca pode ser confundido com "perguntei e não
existe"**. Só a segunda resposta autoriza mudar de grau, e ela precisa ser explícita.

## Decisões de Arquitetura

### Função pura: não grava, não conhece o banco

> Esta função NÃO grava nada e NÃO conhece o banco. Ela devolve um resultado; quem
> persiste é o orquestrador.

O `coletar_um` roda dentro de threads do pool; a gravação acontece na thread principal
(ver [`scripts/menu`](../../scripts/menu.md)). Essa separação é o que permite ao
[`SqliteStore`](../store/sqlite_store.md) não precisar ser thread-safe — os workers só
fazem rede e parse, e devolvem valores.

O resultado é uma tupla nomeada:

```python
#: grau 0 = indeterminado (não houve observação bem-sucedida).
ResultadoColeta = namedtuple("ResultadoColeta", "status grau bruto motivo")
```

Quatro campos que cobrem os quatro desfechos possíveis sem precisar de classes distintas
nem de exceções para controle de fluxo.

### `EsajIndisponivelError` atravessa sem ser capturada

> EsajIndisponivelError (circuit breaker) atravessa sem ser capturada: é parada geral,
> não falha deste processo.

O `try/except` do laço captura `EsajRequisicaoError`, não a base `EsajError` — e a
exceção do circuit breaker sequer pertence a essa hierarquia, por decisão registrada em
[`exceptions`](exceptions.md). O resultado é que a queda do portal sobe até
`scripts/menu.py` e interrompe a submissão de trabalho novo, em vez de virar mais um
`erro_transitorio` numa fila que continuaria consumindo.

### A máquina de estados

O laço percorre `np.graus_a_tentar` e, para cada grau, atravessa esta sequência. A coluna do
motivo importa: é o texto que chega a `ultimo_erro` no banco e ao `revisao_manual.txt` lido
por gente.

| Situação | Resultado | Motivo gravado | Avança de grau? |
|---|---|---|---|
| `EsajRequisicaoError` na busca | `erro_transitorio` | `falha de rede no grau {g}: {erro}` | **Não** |
| `LISTA_SELECAO` sem opção resolvível | `erro_transitorio` | `seleção sem opção resolvível (grau {g})` | **Não** |
| `EsajRequisicaoError` ao abrir o detalhe | `erro_transitorio` | `falha ao abrir detalhe (grau {g}): {erro}` | **Não** |
| `LISTA_SELECAO` **de novo**, depois de abrir o detalhe | `erro_transitorio` | `segunda tela de seleção após abrir o detalhe (grau {g})` | **Não** |
| `SENHA_SEGREDO` | `segredo_justica`, com o grau observado | — (`None`) | Não (é terminal) |
| `DADOS_CAPA` + identidade `DIVERGE` | `erro_transitorio` | `identidade divergente (grau {g}): a página traz {achados}` | **Não** |
| `DADOS_CAPA` + `INDETERMINADO` e escolha não verificada | `erro_transitorio` | `escolha não verificada e identidade indeterminada (grau {g})` | **Não** |
| `DADOS_CAPA` sem partes, mas com classe ou movimentações | `erro_transitorio` | `capa sem partes (possível seletor quebrado) (grau {g})` | **Não** |
| `DADOS_CAPA` sem bloco nenhum | `erro_transitorio` | `capa sem nenhum bloco extraído (grau {g})` | **Não** |
| `DADOS_CAPA` íntegra | `coletado`, com o grau observado e o `bruto` | — (`None`) | Não (é terminal) |
| `NAO_ENCONTRADO` **depois** de uma seleção resolvida | `erro_transitorio` | `a seleção resolveu um destino, mas a página aberta responde 'não encontrado' (grau {g}) — destino provavelmente expirado` | **Não** |
| `NAO_ENCONTRADO` na busca direta | — | — | **Sim** |
| `DESCONHECIDO` | `erro_transitorio` | `página não reconhecida (grau {g})` | **Não** |
| Todos os graus responderam `NAO_ENCONTRADO` | `sem_dados`, grau `GRAU_INDETERMINADO` | — (`None`) | — |
| `EsajIndisponivelError` em qualquer chamada ao cliente | **não é capturada** — propaga para fora de `coletar_um` | — | — |

Duas leituras que a tabela torna visíveis:

- **`NAO_ENCONTRADO` aparece duas vezes, com desfechos opostos.** A mesma resposta do portal
  significa coisas diferentes conforme a procedência da navegação — e é a variável
  `veio_de_selecao` que carrega essa procedência.
- **Quase todas as linhas de `LISTA_SELECAO`, `SENHA_SEGREDO`, `DADOS_CAPA` e `DESCONHECIDO`
  são alcançáveis por dois caminhos**: direto da busca, ou depois de a tela de seleção ter
  sido resolvida e o detalhe aberto. O bloco de seleção reescreve `estado` e a execução
  segue pela mesma cadeia de `if`.

Uma única linha do módulo avança, e ela é guardada:

```python
if estado == EstadoPagina.NAO_ENCONTRADO:
    if veio_de_selecao:
        ...
    continue  # ÚNICO caminho que autoriza tentar o próximo grau
```

Todos os demais caminhos terminam em `return`. Não existe queda para o grau seguinte por
omissão — a estrutura torna o erro impossível, em vez de depender de revisão.

### O vocabulário de status vem de fora do módulo

```python
from ..status import (
    COLETADO,
    ERRO_TRANSITORIO,
    GRAU_INDETERMINADO,
    SEGREDO_JUSTICA,
    SEM_DADOS,
)
```

As cinco constantes eram declaradas aqui, e as mesmas strings existiam de novo no
`sqlite_store` e na `projecao` — três cópias que nada amarrava. Hoje há uma fonte só, em
[`src/status.py`](../status.md), e este módulo é apenas mais um consumidor.

O lugar do vocabulário não é arbitrário. O candidato natural seria o `sqlite_store`, que é
quem valida e grava os status; mas `coletar_um` é uma função que **não conhece o banco**, e
importar de `store/` para saber escrever `"coletado"` inverteria a direção da dependência
sem ganho nenhum. Um módulo folha, sem imports do projeto, deixa os dois lados livres.

### `PARSER_POR_GRAU` é derivado, não escrito à mão

```python
#: Derivado do atributo GRAU de cada parser — que assim deixa de ser decorativo.
#: Um dicionário escrito à mão aceitaria {1: ParserSegundoGrau} sem reclamar e
#: rodaria o parser errado em silêncio. Público de propósito: o spike importa
#: DESTE dicionário em vez de manter o seu.
PARSER_POR_GRAU = {P.GRAU: P for P in (ParserPrimeiroGrau, ParserSegundoGrau)}
```

O dicionário resolvido é o mesmo de antes — `{1: ParserPrimeiroGrau, 2: ParserSegundoGrau}`.
O que muda é de onde vem a chave. Escrita à mão, ela era uma segunda afirmação sobre o grau
de cada parser, independente do atributo `GRAU` que as classes já declaravam; derivada, é a
**mesma** afirmação, lida de onde ela mora.

A diferença aparece no erro. `{1: ParserSegundoGrau}` é um dicionário perfeitamente válido:
nenhum import falha, nenhuma exceção sobe. O parser errado roda sobre a capa e devolve
campos plausíveis — classe, partes e movimentações vêm da classe base e saem corretos — com
`juiz: None`, porque `#relatorProcesso` não existe numa capa de 1º grau. Um `null` a mais
numa base que já tem muitos. Na forma derivada, esse erro não tem como ser escrito: a chave
**é** o `GRAU` da classe.

O nome perdeu o sublinhado por motivo concreto. `scripts/spike_seletores.py` mantinha o
próprio dicionário, com o mesmo pareamento repetido, e hoje importa deste:

```python
from src.scrapers.coletor import PARSER_POR_GRAU
```

```python
# O roteamento grau -> parser vem do coletor. Um dicionário próprio aqui podia
# divergir do usado na coleta real, e o spike deixaria de diagnosticar
# exatamente o caminho que a coleta percorre — que é a razão de ele existir.
```

Um spike de diagnóstico que rode por um caminho diferente do da coleta pode confirmar
seletores que a coleta nunca usará — o que é pior que não diagnosticar, porque produz
confiança infundada.

### Uma segunda tela de seleção tem motivo próprio

```python
if estado == EstadoPagina.LISTA_SELECAO:
    # Segunda tela de seleção. O tratamento seria o mesmo do ramo
    # final, mas o MOTIVO gravado diria "página não reconhecida" —
    # e esta página é reconhecida. Diagnóstico honesto importa: o
    # relatório de revisão manual é lido por humanos.
    return _erro(
        f"segunda tela de seleção após abrir o detalhe (grau {grau})",
        grau,
    )
```

Depois de a seleção ser resolvida e o detalhe aberto, o estado é reclassificado — mas o
bloco que trata `LISTA_SELECAO` já ficou para trás. Sem esta guarda, uma segunda tela de
seleção não casaria com nenhum `if` seguinte e cairia no `return` final, que existe para
`DESCONHECIDO`.

O tratamento seria idêntico: `erro_transitorio`, sem avançar de grau. **O comportamento
nunca esteve errado.** O que estava errado era o texto: `revisao_manual.txt` registraria
"página não reconhecida" para uma página que foi perfeitamente reconhecida — como seleção
aninhada. Quem lesse o relatório procuraria layout novo, bloqueio ou captcha, quando o caso
é outro e tem tratamento próprio.

Vale registrar por que isso justifica um ramo a mais num módulo que preza por caminhos
poucos e explícitos: o destinatário do campo `motivo` é uma pessoa decidindo o que fazer com
um processo que a automação não resolveu. Um diagnóstico que aponta para o lugar errado
custa o tempo dessa pessoa, que é o recurso mais caro do pipeline.

### `NAO_ENCONTRADO` depois de uma seleção resolvida **não** avança de grau

```python
if estado == EstadoPagina.NAO_ENCONTRADO:
    if veio_de_selecao:
        # A tela de seleção já PROVOU que o processo existe neste grau.
        # Se a página aberta agora diz que não existe, o problema é do
        # destino (código de sessão expirado, link inválido) — não é
        # prova de ausência, e descer de grau produziria um registro com
        # o grau errado. Volta para a fila.
        return _erro(
            f"a seleção resolveu um destino, mas a página aberta responde "
            f"'não encontrado' (grau {grau}) — destino provavelmente expirado",
            grau,
        )
    continue  # ÚNICO caminho que autoriza tentar o próximo grau
```

Este é o ponto em que a **letra** e o **fundamento** da regra central se separavam, e a
correção escolheu o fundamento.

Pela letra: o `NAO_ENCONTRADO` foi explícito, o portal afirmou que não existe, logo avançar
de grau está autorizado. Pelo fundamento: a regra existe para nunca trocar de grau sem saber
se o processo está no atual — e a tela de seleção **já havia provado que está**. O e-SAJ só
exibe seleção quando encontrou resultados naquele grau.

Quando as duas coisas se contradizem, uma delas está errada, e não é a seleção. Um destino
resolvido que responde "não existe" aponta para o destino — `processo.codigo` de sessão
expirada, link inválido, código reaproveitado —, não para a ausência do processo. Tratar
essa resposta como prova de ausência levaria a buscar no 2º grau um processo que existe no
1º e a gravá-lo com o grau errado: exatamente a contaminação que o módulo inteiro existe
para impedir, entrando pela única porta que ele deixava aberta.

Como `erro_transitorio`, o caso volta para a fila — e uma nova tentativa começa por uma
busca nova, com destino novo, que é justamente o que resolve um destino expirado.

### Seleção irresolvível é erro, nunca "não existe"

```python
escolha = escolher_na_selecao(html, np)
if escolha.destino is None:
    # Antes isto virava registro vazio e, no orquestrador novo,
    # viraria 'sem_dados' PERMANENTE: "existe, mas não soube
    # escolher" gravado como "não existe".
    return _erro(f"seleção sem opção resolvível (grau {grau})", grau)
```

Uma tela de seleção é **prova** de que o processo existe: o e-SAJ só a exibe quando
encontrou mais de um resultado. Registrar isso como `sem_dados` — que é terminal, e
portanto nunca mais tentado — trocaria uma falha recuperável por uma afirmação falsa e
permanente. Como `erro_transitorio`, o caso volta para a fila da opção 2.

### O grau observado acompanha o segredo de justiça

```python
if estado == EstadoPagina.SENHA_SEGREDO:
    # Grau OBSERVADO é conhecido e não é sigiloso — vai junto.
    return ResultadoColeta(SEGREDO_JUSTICA, grau, None, None)
```

O conteúdo é suprimido; o `bruto` vai `None`. Mas **em qual instância o processo tramita
não é informação sigilosa** — foi o próprio portal que respondeu naquele grau. Preservar o
grau mantém o registro utilizável para contagens e para a topologia do grafo, que é a
mesma lógica aplicada adiante em [`transformers/projecao`](../transformers/projecao.md):
segredo de justiça suprime conteúdo, não topologia.

Já `sem_dados` sai com grau indeterminado, porque nenhuma observação foi bem-sucedida — não
há grau a afirmar:

```python
# Todos os graus responderam NAO_ENCONTRADO explicitamente.
return ResultadoColeta(SEM_DADOS, GRAU_INDETERMINADO, None, None)
```

A convenção de `0` em vez de `NULL` nasce de uma peculiaridade do SQLite e está explicada em
[`status`](../status.md), junto da constante.

### A identidade é conferida antes de qualquer gravação

```python
identidade, achados = verificar_identidade(html, np)
if identidade == Identidade.DIVERGE:
    return _erro(
        f"identidade divergente (grau {grau}): a página traz "
        f"{sorted(achados)}",
        grau,
    )
if identidade == Identidade.INDETERMINADO and not verificada:
    # Palpite na modal + página sem número conferível = risco de
    # gravar os dados de um processo sob o número de outro.
    return _erro(
        f"escolha não verificada e identidade indeterminada "
        f"(grau {grau})",
        grau,
    )
```

O `verificada` é a variável que carrega a procedência da navegação ao longo da função.
Ela nasce otimista e só é rebaixada quando a escolha na tela de seleção foi um palpite:

```python
verificada = True  # busca direta: o próprio e-SAJ resolveu o número
```

A combinação é deliberada. `DIVERGE` reprova sempre — há evidência de erro.
`INDETERMINADO` só reprova quando a chegada à página **também** foi incerta, porque numa
busca direta quem resolveu o número foi o portal, a partir dos parâmetros de
`params_busca`. Os limites exatos dessa garantia estão em [`page_state`](page_state.md).

Repare que `achados` entra na mensagem de erro. Quando a identidade diverge, a auditoria
registra **qual** processo foi aberto por engano — não só que houve divergência.

### O grau de uma falha vai na mensagem, não em coluna

```python
def _erro(motivo, grau):
    """`grau` é o grau TENTADO, não observado — vai só para a mensagem.

    Obrigatório de propósito: o default nunca era usado, e um default aqui
    convidaria a esquecer o grau justamente no diagnóstico. A gravação continua
    em GRAU_INDETERMINADO: uma tentativa que falhou não é observação, e criar
    coluna para ela convidaria a tratá-la como se fosse.
    """
    return ResultadoColeta(ERRO_TRANSITORIO, grau, None, motivo)
```

O grau em que a falha ocorreu aparece no texto do motivo (`"(grau 1)"`) e **não** numa coluna
consultável: `SqliteStore.registrar_erro` grava sempre em `GRAU_INDETERMINADO`. A assimetria
é deliberada e vale explicitar, porque a alternativa é sedutora.

Uma coluna `grau` preenchida num registro de erro pareceria útil — permitiria agrupar falhas
por instância em SQL, que hoje exige *parsing* de string. O problema é o que ela passaria a
significar. Em todo o resto do banco, `grau` é o grau **observado**: o e-SAJ respondeu
naquela instância, e o registro afirma isso. Num erro, não houve resposta — só houve
tentativa. Guardar os dois fatos na mesma coluna faria uma consulta inocente como "quantos
processos no grau 2" somar observações e tentativas frustradas, e a distinção entre "sei" e
"tentei saber" é justamente a que este módulo inteiro existe para preservar.

O parâmetro `grau` também deixou de ter valor padrão. O default `GRAU_INDETERMINADO` nunca
era exercitado — todos os pontos de chamada já passavam o grau —, e um default silencioso
num parâmetro que só serve ao diagnóstico é um convite a omiti-lo justamente quando ele mais
importa. Obrigatório, esquecê-lo vira `TypeError` na hora, não um motivo vago meses depois.

### `_capa_suspeita`: capa sem partes é seletor quebrado

```python
def _capa_suspeita(completude):
    """Capa com classe/movimentações mas SEM partes é seletor quebrado, não
    processo sem partes. A validação antiga exigia que os QUATRO blocos
    estivessem vazios, então uma quebra só no seletor de partes passava e
    gravava o processo sem autores nem réus — invisível numa base de 500 mil.

    Falso positivo é tratado pelo contador de tentativas: após o teto, vira
    erro_persistente e vai para revisão manual em vez de girar para sempre.
    """
    if not completude.get("tem_partes"):
        if completude.get("tem_classe") or completude.get("tem_movimentacoes"):
            return "capa sem partes (possível seletor quebrado)"
        return "capa sem nenhum bloco extraído"
    return None
```

É aqui que a `completude` produzida pelo [`parser_base`](parser_base.md) vira decisão. A
lógica distingue dois cenários que um booleano confundiria: página que trouxe conteúdo mas
não partes (quebra localizada de seletor) e página que não trouxe nada (problema geral).
Ambas reprovam, com motivos diferentes no log.

E a docstring já responde à objeção óbvia — "e se o processo realmente não tiver partes?".
O falso positivo não gira para sempre: ele consome tentativas até o teto e é promovido a
`erro_persistente`, saindo da fila automática para revisão manual. O desenho aceita
retrabalho em troca de nunca gravar em silêncio uma capa incompleta.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Tratar qualquer falha no 1º grau como "não está aqui" e tentar o 2º | O cenário do Wi-Fi: o processo é encontrado no 2º grau e gravado com o grau errado, contaminando o grafo em silêncio. É o bug que o orquestrador existe para consertar. |
| Gravar `sem_dados` quando a seleção não é resolvível | A tela de seleção prova que o processo existe. `sem_dados` é terminal — trocaria falha recuperável por afirmação falsa e permanente. |
| Zerar o grau nos registros de segredo de justiça | O grau não é dado sigiloso: foi o portal que respondeu naquele grau. Zerá-lo perderia informação verdadeira e assimetrizaria o grafo. |
| Deixar o coletor gravar no banco | Obrigaria o `SqliteStore` a ser thread-safe, com lock de escrita ou thread escritora dedicada — mais código e mais risco que devolver valores e gravar na thread principal. |
| Usar exceções para os desfechos (`ProcessoNaoEncontrado`, `ProcessoSigiloso`) | Fluxo de controle por exceção para casos esperados. A tupla nomeada expressa os quatro desfechos sem custo nem ambiguidade. |
| Capturar `EsajError` (a base) em vez de `EsajRequisicaoError` | Não mudaria o comportamento hoje, mas alargaria a captura para qualquer erro futuro derivado da base — inclusive erros que talvez devessem interromper. |
| Validar a capa com um booleano `dados_ok` (AND de quatro condições) | Modelo anterior: a quebra de um seletor específico passava e o processo era gravado sem autores nem réus, invisível numa base grande. |
| Aceitar a capa sem partes por precaução, para não perder processos | Trocaria retrabalho por dado incompleto gravado em silêncio. O teto de tentativas resolve o falso positivo sem abrir mão da verificação. |
| Conferir a identidade só quando a escolha veio de palpite | `DIVERGE` pode acontecer também na busca direta (redirecionamentos, códigos reaproveitados). A conferência é sempre feita; o que varia é a resposta ao `INDETERMINADO`. |
| Manter o vocabulário de status declarado aqui | Eram três cópias (aqui, no `sqlite_store` e na `projecao`) que nada impedia de divergir, e a divergência é silenciosa: o valor não reconhecido cai no `else` da projeção e vira "erro persistente" sem erro nenhum. |
| Mover o vocabulário para o `sqlite_store`, onde os status são validados | Faria uma função que não conhece o banco importar da camada de persistência. O módulo folha `src/status.py` serve os dois lados sem criar a dependência. |
| `PARSER_POR_GRAU` escrito à mão | `{1: ParserSegundoGrau}` é um dicionário válido: nada falha, e o parser errado devolve campos plausíveis com `juiz: None`. Derivado do atributo `GRAU`, o erro não tem como ser escrito. |
| Deixar a segunda tela de seleção cair no ramo de `DESCONHECIDO` | O tratamento seria o mesmo, mas o motivo gravado diria "página não reconhecida" para uma página reconhecida. O relatório de revisão manual é lido por gente, e um diagnóstico que aponta para o lugar errado custa o tempo dela. |
| Manter o `continue` no `NAO_ENCONTRADO` após uma seleção resolvida | Coerente com a **letra** da regra central e contrário ao seu fundamento: a tela de seleção já provou que o processo existe neste grau. Um destino expirado levaria a gravar o processo com o grau errado. |
| Gravar o grau tentado numa coluna dos registros de erro | A coluna `grau` significa "grau observado" em todo o resto do banco. Guardar tentativas frustradas ali faria uma contagem por instância somar o que se sabe com o que só se tentou saber. |
| Manter o default `grau=GRAU_INDETERMINADO` em `_erro` | Nunca era usado, e um default num parâmetro que só serve ao diagnóstico convida a omiti-lo. Obrigatório, a omissão vira `TypeError` imediato em vez de um motivo vago no relatório. |

## Limitações Conhecidas

- **`_capa_suspeita` reprova capas legítimas sem partes.** O código assume o risco
  explicitamente. O custo é o processo ser tentado até o teto de tentativas antes de ir
  para `revisao_manual.txt` — cinco coletas completas gastas num caso que nunca vai passar.

- **O motivo do erro é uma string livre.** `ResultadoColeta.motivo` é texto formatado para
  leitura humana, e é o que o [`SqliteStore`](../store/sqlite_store.md) guarda em
  `ultimo_erro` (truncado em 500 caracteres). Agrupar falhas por causa exige *parsing* de
  string; não há código de erro estruturado.

- **A página é classificada duas vezes quando há tela de seleção.** Dois
  `ClassificadorPagina` são construídos sobre HTMLs diferentes, cada um lendo o texto
  completo do documento. É o custo de não confiar no que a seleção prometeu.

- **O `bruto` só existe para `coletado`.** `segredo_justica` e `sem_dados` retornam
  `bruto=None`, e é isso que faz `scripts/menu.py` gravar o vínculo padrão `INDEFINIDO`
  nesses casos — não há de onde derivar relacionamento, e `sem_vinculo` afirmaria "não há
  sinal de pai" sobre uma capa que a coleta não chegou a ver (ver
  [`vinculo`](../transformers/vinculo.md)).

- **Não há distinção entre os motivos de `DESCONHECIDO`.** Layout novo, bloqueio, captcha e
  manutenção produzem o mesmo `erro_transitorio` com o mesmo texto. O diagnóstico depende
  de `scripts/spike_seletores.py`, que salva o HTML.

## Exemplo de Uso

A chamada única do pipeline, dentro da tarefa que roda em cada worker
(`scripts/menu.py`):

```python
def tarefa(numero):
    np = NumeroProcesso.tentar(numero)
    if np is None:
        return numero, None
    return numero, coletar_um(np, fabrica())
```

E o consumo do resultado, na thread principal — as duas ramificações que a tupla nomeada
sustenta:

```python
if r.status == ERRO_TRANSITORIO:
    st = store.registrar_erro(numero, r.motivo, origem=origem)
    resumo[st] += 1
    tqdm.write(f"[{st}] {numero}: {r.motivo}")
    return
```

```python
store.registrar_resultado(
    numero, r.grau, r.status, bruto=bruto,
    processo_pai=vinc["processo_pai"],
    processo_pai_grau=vinc["processo_pai_grau"],
    tipo_vinculo=vinc["tipo"], origem=origem,
)
```

## Testes e Validação

Não há testes automatizados neste repositório. `scripts/spike_seletores.py` exercita as
mesmas peças (`ClassificadorPagina`, `escolher_na_selecao`, `verificar_identidade`, os
parsers) e importa daqui o `PARSER_POR_GRAU`, mas **não** chama `coletar_um` — ele consulta
sempre os dois graus para comparar, justamente o oposto da lógica de roteamento que este
módulo implementa. A máquina de estados em si, hoje, só é exercitada pela execução real do
menu.

É o módulo com a melhor relação entre risco e facilidade de teste: `coletar_um` recebe um
`NumeroProcesso` e um `client`, e o `client` pode ser um dublê que devolve HTMLs de
`data/spike/` numa sequência definida pelo teste — sem rede nenhuma. As invariantes que
valeria fixar, em ordem de gravidade:

- `EsajRequisicaoError` no grau 1 devolve `erro_transitorio` e o dublê **não** recebe
  nenhuma chamada para o grau 2 — a regra central, verificada pela ausência da chamada;
- `NAO_ENCONTRADO` no grau 1 **faz** o dublê receber a chamada do grau 2;
- `NAO_ENCONTRADO` no grau 1 **depois de uma seleção resolvida** devolve `erro_transitorio` e
  o dublê **não** recebe a chamada do grau 2 — o caminho oposto ao anterior, e o único ponto
  do módulo em que o mesmo estado tem dois desfechos;
- uma segunda `LISTA_SELECAO` depois de aberto o detalhe devolve `erro_transitorio` com o
  motivo da seleção aninhada, não com `"página não reconhecida"`;
- `NAO_ENCONTRADO` nos dois graus devolve `sem_dados` com `grau == GRAU_INDETERMINADO`;
- `SENHA_SEGREDO` no grau 2 devolve `segredo_justica` com `grau == 2`, não `0`;
- capa cuja identidade diverge devolve `erro_transitorio`, e os CNJs encontrados aparecem
  no `motivo`;
- capa com movimentações e sem partes devolve `erro_transitorio`, não `coletado`;
- `EsajIndisponivelError` levantada pelo dublê **propaga** para fora de `coletar_um`, em
  vez de virar `erro_transitorio`.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Status importado de `src/status.py`; `PARSER_POR_GRAU` derivado do atributo `GRAU`; motivo próprio para a segunda tela de seleção; `NAO_ENCONTRADO` após seleção resolvida vira `erro_transitorio` |
| 2026-08-10 | @alexandrehiero | `_erro` passa a exigir o `grau`; docstring registra por que o grau tentado não vira coluna |

## Pontos em aberto

Nenhum item em aberto.
