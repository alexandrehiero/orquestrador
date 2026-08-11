> **Modelo ADR** — Copie este arquivo, renomeie para o seu estudo (ex.: `docs/notebooks/meu-estudo.md`) e preencha todas as seções. Registre decisões, contexto e aprendizados ao lado do notebook correspondente.

# [Título do Notebook]

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | YYYY-MM-DD                                 |
| Data de atualização | YYYY-MM-DD                                 |
| Autor(es)           | @username_github, @outro_username         |
| Notebook original   | `notebooks/estudo-<nome>/arquivo.ipynb`    |

## Contexto e Motivação

*Qual problema prático motivou este estudo?*  
*Exemplo: A base da PGE possui mais de 200 variações para o mesmo assunto jurídico, inviabilizando análises agregadas.*

## Decisões Técnicas

- **Biblioteca de similaridade escolhida:** `thefuzz` (por leveza e bom custo‑benefício)
- **Threshold utilizado:** 95 (justificativa: capturar apenas variações muito pequenas, como plural e hífen)
- **Pré‑processamento:** remoção de acentos, lower case, eliminação de pontuação (código no notebook)
- **Pós‑processamento manual:** dicionário de correções para falsos positivos (ex: "recalculo" vs "calculo")

## Resultados Alcançados

*Quais foram os principais números ou achados?*  
- Redução de 1.247 assuntos únicos para 312 grupos canônicos.
- Identificação de 23 variações de "licença‑prêmio" que foram normalizadas.

## Aprendizados e Lições

*O que deu certo? O que não deu?*  
- O threshold 95 foi eficaz para evitar agrupamentos incorretos, mas deixou de fora variações legítimas com abreviações (ex: "proc. adm.").  
- Em versões futuras, experimentar `token_sort_ratio` em vez de `ratio`.

## Decisões Pendentes ou Encaminhamentos

- [ ] Validar o dicionário final com o time de domínio (Beto/Étore).
- [ ] Automatizar o processo via script (issue #42).

## Como reproduzir este estudo

```bash
# Comandos para instalar dependências e executar o notebook
uv add thefuzz unidecode pandas
jupyter notebook notebooks/estudo-similaridade/normalizacao_assuntos.ipynb
```

## Referências

- [Documentação do thefuzz](https://github.com/seatgeek/thefuzz)
- Issue original #23 – Normalização de assuntos da PGE *(preencher link da issue)*
