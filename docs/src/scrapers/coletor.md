# Coleta de um processo (máquina de estados) – `src/scrapers/coletor.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | `collections.namedtuple` — sem dependências externas |

## Contexto e Motivação

O [`EsajClient`](esaj_client.md) traz HTML, o [`page_state`](page_state.md) diz o que aquele HTML é, os [parsers](parser_base.md) extraem os campos — e o `coletor` decide o que tudo isso significa para **um** processo: foi coletado, é sigiloso, não existe, ou não deu para saber.

A regra que governa o módulo: **só um `NAO_ENCONTRADO` explícito autoriza avançar de grau.**

Vale seguir o cenário que a justifica, porque ele explica a arquitetura do projeto inteiro. Um processo com origem diferente de `0000` tem `graus_a_tentar == (1, 2)`. A consulta ao 1º grau cai — o Wi-Fi oscilou. Um coletor ingênuo interpreta "não consegui" como "não achei" e tenta o 2º grau. E o 2º grau **responde**: processos sobem de instância, então existe mesmo um registro daquele número em `cposg`. O processo é gravado com `grau = 2`.

O resultado é um registro perfeitamente formado, com dados verdadeiros, sob o grau errado. Como a chave do banco é `(processo, grau)` e o relacionamento é construído sobre ela, o recurso passa a ocupar no grafo o lugar do processo originário. Nada detecta: a base fica internamente consistente e factualmente errada. Daí a regra — **"não consegui perguntar" nunca pode ser confundido com "perguntei e não existe"**.

## Decisões de Arquitetura

- **Função pura: não grava e não conhece o banco** — roda dentro das threads do pool; a gravação acontece na thread principal. É essa separação que permite ao [`SqliteStore`](../store/sqlite_store.md) não precisar ser thread-safe.
- **O resultado é uma tupla nomeada `(status, grau, bruto, motivo)`** — quatro campos cobrem os quatro desfechos sem classes distintas nem exceções para controle de fluxo.
- **`EsajIndisponivelError` atravessa sem ser capturada** — o `except` pega `EsajRequisicaoError`, e a exceção do disjuntor sequer pertence a essa hierarquia (ver [`exceptions`](exceptions.md)). A queda do portal sobe até o menu e interrompe a submissão, em vez de virar mais um `erro_transitorio` numa fila que continuaria consumindo.
- **Uma única linha do módulo avança de grau, e ela é guardada** — todos os demais caminhos terminam em `return`. Não existe queda para o grau seguinte por omissão: a estrutura torna o erro impossível em vez de depender de revisão.
- **`NAO_ENCONTRADO` após uma seleção resolvida NÃO avança** — é o ponto em que a letra e o fundamento da regra se separam, e a correção escolheu o fundamento: a tela de seleção já **provou** que o processo existe naquele grau. Um destino que responde "não existe" aponta para o destino (código de sessão expirado, link inválido), não para a ausência do processo.
- **Seleção irresolvível é erro, nunca "não existe"** — a tela de seleção é prova de existência. Gravar `sem_dados`, que é terminal, trocaria falha recuperável por afirmação falsa e permanente.
- **Uma segunda tela de seleção tem motivo próprio** — o tratamento seria idêntico ao ramo final, mas o texto gravado diria "página não reconhecida" para uma página perfeitamente reconhecida. O destinatário do campo `motivo` é uma pessoa decidindo o que fazer; um diagnóstico que aponta para o lugar errado custa o tempo dela.
- **A identidade é conferida antes de qualquer gravação** — `DIVERGE` reprova sempre; `INDETERMINADO` só reprova quando a chegada à página **também** foi incerta (palpite na modal), porque numa busca direta quem resolveu o número foi o portal. Os CNJs achados entram na mensagem: a auditoria registra **qual** processo foi aberto por engano.
- **O grau observado acompanha o segredo de justiça** — o conteúdo é suprimido, mas em qual instância o processo tramita não é informação sigilosa: foi o portal que respondeu naquele grau. Já `sem_dados` sai com grau indeterminado, porque nenhuma observação foi bem-sucedida.
- **O grau de uma falha vai na mensagem, não em coluna** — em todo o resto do banco `grau` significa grau **observado**. Guardar tentativas frustradas na mesma coluna faria uma consulta inocente como "quantos processos no grau 2" somar o que se sabe com o que só se tentou saber. O parâmetro é obrigatório: esquecê-lo vira `TypeError` na hora.
- **`_capa_suspeita`: capa sem partes é seletor quebrado** — a validação antiga exigia que os quatro blocos estivessem vazios, então uma quebra só no seletor de partes passava e gravava o processo sem autores nem réus. O falso positivo consome tentativas até o teto e vai para revisão manual: o desenho aceita retrabalho em troca de nunca gravar em silêncio uma capa incompleta.
- **`PARSER_POR_GRAU` é derivado do atributo `GRAU`, não escrito à mão** — `{1: ParserSegundoGrau}` é um dicionário válido: nada falha, e o parser errado devolve campos plausíveis com `juiz: None`. Derivado, o erro não tem como ser escrito. É público de propósito: o spike importa deste dicionário, para diagnosticar exatamente o caminho que a coleta percorre.
- **O vocabulário de status vem de fora** — o candidato natural seria o `sqlite_store`, que valida e grava os status; mas esta é uma função que **não conhece o banco**, e importar de `store/` inverteria a dependência sem ganho. Ver [`status`](../status.md).

### A máquina de estados

O laço percorre `np.graus_a_tentar`. A coluna do motivo importa: é o texto que chega a `ultimo_erro` e ao `revisao_manual.txt` lido por gente.

| Situação | Resultado | Avança de grau? |
|---|---|---|
| `EsajRequisicaoError` na busca | `erro_transitorio` — `falha de rede no grau {g}` | **Não** |
| `LISTA_SELECAO` sem opção resolvível | `erro_transitorio` — `seleção sem opção resolvível` | **Não** |
| `EsajRequisicaoError` ao abrir o detalhe | `erro_transitorio` — `falha ao abrir detalhe` | **Não** |
| `LISTA_SELECAO` de novo, após abrir o detalhe | `erro_transitorio` — `segunda tela de seleção` | **Não** |
| `SENHA_SEGREDO` | `segredo_justica`, com o grau observado | Terminal |
| `DADOS_CAPA` + identidade `DIVERGE` | `erro_transitorio` — `identidade divergente`, com os CNJs achados | **Não** |
| `DADOS_CAPA` + `INDETERMINADO` e escolha não verificada | `erro_transitorio` — `escolha não verificada` | **Não** |
| `DADOS_CAPA` sem partes, com classe ou movimentações | `erro_transitorio` — `capa sem partes (possível seletor quebrado)` | **Não** |
| `DADOS_CAPA` sem bloco nenhum | `erro_transitorio` — `capa sem nenhum bloco extraído` | **Não** |
| `DADOS_CAPA` íntegra | `coletado`, com o grau observado e o `bruto` | Terminal |
| `NAO_ENCONTRADO` **depois** de uma seleção resolvida | `erro_transitorio` — `destino provavelmente expirado` | **Não** |
| `NAO_ENCONTRADO` na busca direta | — | **Sim** |
| `DESCONHECIDO` | `erro_transitorio` — `página não reconhecida` | **Não** |
| Todos os graus responderam `NAO_ENCONTRADO` | `sem_dados`, grau indeterminado | — |
| `EsajIndisponivelError` | **não é capturada** — propaga | — |

`NAO_ENCONTRADO` aparece duas vezes, com desfechos opostos: a mesma resposta do portal significa coisas diferentes conforme a procedência da navegação, que a variável `veio_de_selecao` carrega.

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Tratar qualquer falha no 1º grau como "não está aqui" | O cenário do Wi-Fi: o processo é encontrado no 2º grau e gravado com o grau errado, contaminando o grafo em silêncio. |
| Gravar `sem_dados` quando a seleção não é resolvível | A tela de seleção prova que o processo existe. `sem_dados` é terminal — trocaria falha recuperável por afirmação falsa e permanente. |
| Manter o `continue` no `NAO_ENCONTRADO` após seleção resolvida | Coerente com a letra da regra e contrário ao seu fundamento: a seleção já provou que o processo existe neste grau. |
| Zerar o grau nos registros de segredo de justiça | O grau não é dado sigiloso: foi o portal que respondeu naquele grau. Zerá-lo perderia informação verdadeira e assimetrizaria o grafo. |
| Deixar o coletor gravar no banco | Obrigaria o `SqliteStore` a ser thread-safe, com lock ou thread escritora dedicada — mais código e mais risco. |
| Usar exceções para os desfechos (`ProcessoNaoEncontrado`, `ProcessoSigiloso`) | Fluxo de controle por exceção para casos esperados. A tupla nomeada expressa os quatro desfechos sem custo nem ambiguidade. |
| Capturar `EsajError` (a base) em vez de `EsajRequisicaoError` | Não mudaria o comportamento hoje, mas alargaria a captura para qualquer erro futuro derivado da base — inclusive os que deveriam interromper. |
| Validar a capa com um booleano `dados_ok` (AND de quatro condições) | Modelo anterior: a quebra de um seletor específico passava e o processo era gravado sem autores nem réus, invisível numa base grande. |
| Aceitar a capa sem partes por precaução, para não perder processos | Trocaria retrabalho por dado incompleto gravado em silêncio. O teto de tentativas resolve o falso positivo sem abrir mão da verificação. |
| Conferir a identidade só quando a escolha veio de palpite | `DIVERGE` acontece também na busca direta (redirecionamentos, códigos reaproveitados). A conferência é sempre feita; o que varia é a resposta ao `INDETERMINADO`. |
| Deixar a segunda tela de seleção cair no ramo de `DESCONHECIDO` | O tratamento seria o mesmo, mas o motivo diria "página não reconhecida" para uma página reconhecida. O relatório é lido por gente. |
| Gravar o grau tentado numa coluna dos registros de erro | A coluna `grau` significa "grau observado" em todo o resto do banco. Uma contagem por instância somaria o que se sabe com o que só se tentou saber. |
| Manter o default `grau=GRAU_INDETERMINADO` em `_erro` | Nunca era usado, e um default num parâmetro que só serve ao diagnóstico convida a omiti-lo. Obrigatório, a omissão vira `TypeError` imediato. |
| `PARSER_POR_GRAU` escrito à mão | `{1: ParserSegundoGrau}` é um dicionário válido: nada falha, e o parser errado devolve campos plausíveis com `juiz: None`. |
| Manter o vocabulário de status declarado aqui | Eram três cópias que nada impedia de divergir, e a divergência é silenciosa: o valor não reconhecido cai no `else` da projeção e vira "erro persistente". |
| Mover o vocabulário para o `sqlite_store` | Faria uma função que não conhece o banco importar da camada de persistência. O módulo folha `src/status.py` serve os dois lados. |

## Limitações Conhecidas

- **`_capa_suspeita` reprova capas legítimas sem partes.** O custo assumido é o processo ser tentado até o teto antes de ir para revisão manual — cinco coletas gastas num caso que nunca vai passar.
- **O motivo do erro é string livre.** Agrupar falhas por causa exige *parsing* de string; não há código de erro estruturado.
- **A página é classificada duas vezes quando há tela de seleção.** É o custo de não confiar no que a seleção prometeu.
- **O `bruto` só existe para `coletado`.** `segredo_justica` e `sem_dados` retornam `bruto=None`, e é por isso que o menu grava o vínculo padrão `INDEFINIDO` nesses casos.
- **Não há distinção entre os motivos de `DESCONHECIDO`.** Layout novo, bloqueio, captcha e manutenção produzem o mesmo texto; diagnosticar depende do HTML salvo por `scripts/spike_seletores.py`.

## Exemplo de Uso

```python
from src.scrapers.coletor import coletar_um

# Dentro da thread do worker: só rede e parse, sem tocar no banco.
r = coletar_um(NumeroProcesso("10008582420228260396"), cliente)
# ResultadoColeta(status='coletado', grau=1, bruto={...}, motivo=None)

# Na thread principal, as duas ramificações que a tupla sustenta:
if r.status == ERRO_TRANSITORIO:
    store.registrar_erro(numero, r.motivo, origem=origem)
else:
    store.registrar_resultado(numero, r.grau, r.status, bruto=bruto, ...)
```

## Testes e Validação

Não há suíte automatizada. `scripts/spike_seletores.py` exercita as mesmas peças e importa daqui o `PARSER_POR_GRAU`, mas **não** chama `coletar_um` — consulta sempre os dois graus, o oposto da lógica de roteamento deste módulo. É o módulo com a melhor relação risco/facilidade de teste: `coletar_um` aceita um `client` dublê que devolve HTMLs de `data/spike/`, sem rede. As 9 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Status importado de `src/status.py`; `PARSER_POR_GRAU` derivado do atributo `GRAU`; motivo próprio para a segunda tela de seleção; `NAO_ENCONTRADO` após seleção resolvida vira `erro_transitorio` |
| 2026-08-10 | @alexandrehiero | `_erro` passa a exigir o `grau`; docstring registra por que o grau tentado não vira coluna |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): narrativa das 12 decisões virou lista de tópicos; código copiado removido; invariantes migradas para o backlog de testes |
