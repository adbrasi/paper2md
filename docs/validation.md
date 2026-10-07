# Validação da entrega

## 2026-10-07 — teste ao vivo (Windows 10, Python 3.13)

- 32 testes offline aprovados (`python -m unittest discover -s tests`).
- E2E ao vivo `tests/e2e_live.py --engine local`: 9/9 checagens aprovadas — busca com OpenAlex + arXiv, janela de datas respeitada, `get` de dois IDs de seleção, repetição servida do cache, `read` com todas as páginas do PDF, link Hugging Face Papers.
- Problemas encontrados ao vivo e corrigidos:
  - OpenAlex retornava HTTP 400: `search.semantic` não aceita `from_publication_date`; agora usa `publication_year` e a data exata é filtrada localmente.
  - A expansão de busca via Mistral foi removida: o consumidor é um agente LLM que escreve as consultas; `search` aceita até 5 consultas e funde os rankings.
  - Adicionada engine `local` (PyMuPDF) para extração gratuita; ordem padrão do PyMuPDF preserva leitura coluna a coluna em papers de duas colunas.
- **Mistral OCR não verificado ao vivo**: a chave fornecida autentica, mas a conta tem cota 0 para `mistral-ocr-latest` (`x-ratelimit-limit-req-minute: 0`, HTTP 429). A CLI devolve erro orientando `--engine local`. Depois de liberar a cota no console Mistral, execute `python -X utf8 tests/e2e_live.py --engine mistral`.
- OpenReview bloqueia clientes automatizados com verificação antibot (HTTP 403 challenge), inclusive a API; use PDF local.
- Teste de uso real por um subagente seguindo só a skill (comparar alternativas a LoRA em difusão) revelou e motivou: limite de download elevado de 50 para 200 MiB (papers de difusão com muitas imagens; Mistral OCR continua limitado a 50 MiB com erro orientando `--engine local`); descarte de registros OpenAlex que não são papers (datasets/software); remoção de caracteres de controle da extração local (faziam `grep` tratar o Markdown como binário); orientações na skill sobre janela de datas, venue/citações e tabelas.
- E2E ao vivo repetido após as correções: 10/10. Paper LyCORIS (arXiv 2309.14859, > 50 MiB) obtido com sucesso. CLI instalada via `uv tool install -e` no Windows e no WSL Debian; smoke test search + get ao vivo no WSL aprovado.
