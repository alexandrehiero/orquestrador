> **Modelo ADR** — Copie este arquivo, renomeie para o módulo (ex.: `docs/src/scraper_tjsp_capa_request.md`) e preencha todas as seções. Registre decisões de arquitetura, alternativas rejeitadas e limitações conhecidas.

# [Nome do Módulo] – `src/caminho/do/modulo.py`

| Metadado            | Valor                                      |
|---------------------|--------------------------------------------|
| Data de criação     | YYYY-MM-DD                                 |
| Data de atualização | YYYY-MM-DD                                 |
| Responsável(is)     | @username_github                           |
| Dependências principais | `curl_cffi`, `beautifulsoup4`          |

## Contexto e Motivação

*Por que este módulo foi criado?*  
*Exemplo: A coleta de processos do TJSP exige um scraper que evite bloqueios por falta de headers atualizados – o `curl_cffi` resolve isso com impersonate.*

## Decisões de Arquitetura

- **Classe principal:** `FaceTJSPScraper` – responsável por requisição, tratamento de múltiplos resultados e parsing.
- **Tratamento de erros:** retorna `None` em caso de falha, loga o erro (não levanta exceção para não interromper pipelines longos).
- **Estratégia de delay:** não incluída no módulo – fica a cargo do script que o utiliza (princípio da separação de responsabilidades).
- **Parsing de partes do processo:** uso de expressões regulares e listas de padrões (`padrão_autores`, `padrão_réus`).

## Alternativas Consideradas

| Alternativa | Motivo da rejeição |
|-------------|--------------------|
| `requests` + `fake_useragent` | Bloqueios frequentes pelo TJSP; `curl_cffi` mostrou maior taxa de sucesso. |
| Selenium | Muito pesado e lento para grandes volumes. |

## Limitações Conhecidas

- Não lida com captchas (até o momento, não foram encontrados).
- A lista de padrões de sentença é extensa – pode ficar desatualizada com novas movimentações.

## Exemplo de Uso

```python
from src.scrapers.scraper_tjsp_capa_request import FaceTJSPScraper

scraper = FaceTJSPScraper()
html = scraper.get_html("https://esaj.tjsp.jus.br/cpopg/show.do?processo.codigo=...")
dados = scraper.parse_process(html)
```

## Testes e Validação

- Teste manual com 50 processos conhecidos (taxa de acerto ~98%).
- Issue #15 reporta falha para processos com nome de parte contendo "Advogado:" – pendente de correção.

## Histórico de Modificações

| Data | Usuário | Alteração |
|------|---------|------------|
| 2025-01-10 | @joao | Criação inicial |
| 2025-02-15 | @maria | Adicionado suporte a múltiplos autores |
