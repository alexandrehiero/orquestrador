# Exceções de domínio – `src/scrapers/exceptions.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | 2026-08-10                                 |
| Data de atualização | 2026-09-04                                 |
| Responsável(is)     | @alexandrehiero                            |
| Dependências principais | nenhuma — módulo folha, sem imports |

## Contexto e Motivação

Três camadas precisam falar sobre os mesmos erros: o value object `NumeroProcesso` (validação de entrada), o `EsajClient` (rede) e os parsers (leitura da capa). Se cada uma definisse sua própria exceção, o cliente precisaria importar o value object e o value object precisaria importar o cliente — import circular. Concentrá-las num módulo sem dependência nenhuma corta o ciclo.

Mas o módulo carrega uma decisão bem maior que organização de imports: **a hierarquia codifica quem pode ser capturado e quem tem de derrubar a execução.**

## Decisões de Arquitetura

- **`EsajError` é o guarda-chuva de "esta falha é *deste* processo, siga para o próximo"** — quem quer capturar tudo que veio do e-SAJ usa a base (é o caso do `spike_seletores`, que assim não aborta o diagnóstico num número que falhou); quem quer ser específico captura a subclasse (é o caso de `coletar_um`).
- **`EsajRequisicaoError(EsajError)` é a falha de rede que sobreviveu às retentativas** — levantada só depois de esgotar `max_tentativas`. `coletar_um` a converte em `erro_transitorio` **sem tocar no grau seguinte**.
- **`EsajIndisponivelError` NÃO herda de `EsajError`, de propósito** — esta é a decisão central do módulo. **A herança *é* o mecanismo de controle:** como a exceção está fora da árvore de `EsajError`, todo `except EsajError` do projeto a deixa passar **por construção**. Não há como um `except` bem-intencionado engolir o disjuntor por descuido. Se ela fosse `EsajError`, uma queda do portal faria o script queimar ~12 s por número numa fila de centenas de milhares, marcando tudo como falha.
- **`NumeroProcessoInvalido` herda de `ValueError`, não de `EsajError`** — número CNJ malformado é erro de *entrada*, não de comunicação: acontece antes de qualquer requisição. Herdar de `ValueError` mantém a semântica que qualquer programador Python espera de um construtor que recebeu argumento inválido. E ficar fora de `EsajError` importa: um número inválido não deve ser contabilizado como falha de coleta nem alimentar o disjuntor.
- **Só o tamanho ≠ 20 levanta** — dígito verificador incorreto não vira exceção; quem decide é o chamador.
- **`_levantar_falha` sempre levanta, uma das duas, nunca retorna** — `_get` depende disso: não há `return` depois do laço de retentativa, e um caminho que retornasse devolveria `None` como se fosse HTML. O contrato ficou no identificador justamente porque antes vivia num comentário.

### A hierarquia, e o que cada ramo autoriza

```
Exception
├── EsajError                    "falha deste processo, siga adiante"
│   └── EsajRequisicaoError      rede, após esgotar as 3 tentativas
├── RuntimeError
│   └── EsajIndisponivelError    PARADA GERAL — fora da árvore de EsajError
└── ValueError
    └── NumeroProcessoInvalido   erro de entrada, antes de qualquer requisição
```

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| Uma única exceção com um campo `fatal=True/False` | O `except` deixaria de discriminar. Todo ponto de captura teria de lembrar de reerguer quando `fatal` fosse verdadeiro — e esquecer disso em **um** lugar reintroduz exatamente a falha que o disjuntor existe para evitar. A hierarquia faz o mecanismo de exceções trabalhar por nós. |
| `EsajIndisponivelError` herdando de `EsajError` | Seria capturada por todo `except EsajError` do projeto, e a queda do e-SAJ marcaria a fila inteira como falha ao custo de ~12 s por número. |
| Definir cada exceção no módulo que a levanta | Import circular entre `numero_processo`, `esaj_client` e os parsers. |
| `NumeroProcessoInvalido` herdando de `EsajError` | Confundiria erro de entrada com erro de rede: um `.txt` com números malformados inflaria as métricas de falha e poderia contar para o disjuntor. |
| Levantar exceção também para DV inválido | Tiraria a decisão do chamador. Na entrada, DV inválido vai para `numeros_invalidos.txt`; num relacionamento, vira observação e o vínculo é ignorado. São respostas diferentes para o mesmo fato. |

## Limitações Conhecidas

- **Nenhuma exceção carrega contexto estruturado.** `EsajRequisicaoError` embute a URL na mensagem em vez de expor um atributo `url`: agregar falhas por endpoint exige parsing de string.
- **`EsajIndisponivelError` herda de `RuntimeError`, não de `BaseException`.** Um `except Exception` genérico ainda a captura. A única barreira efetiva é não escrever `except Exception` no caminho de coleta. O `spike_seletores` usa esse padrão no laço de `main()`, mas lá é aceitável: é diagnóstico e não grava nada.
- **Não há exceção para "página não reconhecida" ou "seleção irresolvível".** Esses casos não viram exceção: `coletar_um` os devolve como `ResultadoColeta` com status `erro_transitorio` e um `motivo` em texto — fluxo de controle por exceção para casos esperados foi rejeitado.

## Exemplo de Uso

As duas capturas reais do projeto, que mostram a hierarquia funcionando:

```python
from src.scrapers.exceptions import EsajIndisponivelError, EsajRequisicaoError

# Em coletar_um: falha DESTE processo, não avança de grau.
try:
    html = client.buscar(np, grau)
except EsajRequisicaoError as erro:
    return _erro(f"falha de rede no grau {grau}: {erro}", grau)

# EsajIndisponivelError atravessa o except acima — ela não é EsajRequisicaoError —
# e sobe até scripts/menu.py, onde é capturada UMA vez, para parar de submeter:
except EsajIndisponivelError as erro:
    parada = str(erro)      # drena o que está em voo; nada do que foi pago se perde
    continue
```

## Testes e Validação

Não há suíte automatizada. O módulo é puro (sem I/O, sem dependências) e é **o candidato mais barato a receber os primeiros testes do projeto**: basta afirmar que `issubclass(EsajIndisponivelError, EsajError)` é `False` — a invariante da qual todo o resto depende.

O comportamento de ponta a ponta é verificável desligando a rede durante a opção 1: após 20 falhas seguidas a execução precisa parar e imprimir a mensagem de interrupção, em vez de continuar consumindo a fila. As 2 invariantes estão no [backlog de testes](../../backlog_testes.md).

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2026-08-10 | @alexandrehiero | Criação e testes iniciais |
| 2026-08-10 | @alexandrehiero | Correção: `_registrar_falha` → `_levantar_falha`; o exemplo tratava o retorno de `falha()` como booleano, quando hoje é `(abrir, falhas_seguidas)` |
| 2026-09-04 | @alexandrehiero | Reescrita enxuta (≤150 linhas): código copiado removido; a hierarquia virou diagrama; invariantes migradas para o backlog de testes |
