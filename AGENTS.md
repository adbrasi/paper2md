# AGENTS.md — paper2md

CLI that lets an agent **search papers, pick them, and get the PDF + full Markdown text** on disk. No server, no vector index. Search is OpenAlex + arXiv; conversion is a fallback chain of OCR engines.

This file has two parts: **using** the tool (for agents doing research) and **working on** the tool (for agents changing this repo).

---

## Part 1 — Using paper2md

### Install

Requires Python ≥ 3.11. Install once as a global command (editable, so `git pull` updates it):

```bash
uv tool install -e /path/to/paper2md      # Windows PowerShell and WSL/Linux alike
paper2md --version
```

Optional API keys, read from the environment only (never pass keys as arguments):

| Variable | Effect |
|---|---|
| `NANONETS_API_KEY` | Enables Nanonets OCR |
| `MISTRAL_API_KEY` | Enables Mistral OCR (needs a plan with OCR quota; a free plan returns 429 "limite 0") |
| `OPENALEX_API_KEY` | Larger OpenAlex budget (optional) |
| `PAPER2MD_ENGINE` | Default engine: `auto` (default), `mistral`, `nanonets`, `local` |
| `PAPER2MD_HOME` | Where the SQLite state lives (default `%LOCALAPPDATA%\paper2md` or `~/.local/share/paper2md`) |

With no keys at all it still works: search is free and the `local` engine converts offline.

### The workflow: search → choose → get → read

Always pass `--json`. JSON goes to stdout; progress and warnings go to stderr.

**1. Search.** You write 1–5 **English** queries; there is no LLM inside the tool.

```bash
paper2md search "tuning-free image editing with diffusion self-attention" "MasaCtrl mutual self-attention" --json
```

- OpenAlex is semantic: one descriptive sentence works. arXiv requires **every** term of a query, so keep keyword queries to 2–5 words.
- Default window: last 2 years, 10 results, ranked by relevance (`--sort recent`, `--limit N` up to 50).
- For older work the user names explicitly, add `--since YYYY-MM-DD`. Search the recent window as well, so recent work isn't missed.
- Each result has `selection_id` (`s_<12 hex>:<n>`), `id`, `title`, `published`, `venue`, `citations`, `abstract`, `url`, `pdf_url`. Check `warnings` too: one provider can be down while the other answers.
- Judge results by the abstract. `venue` often says arXiv even for papers published at a conference, and `citations` lag behind for recent work.

**2. Choose.** If the user wants to choose, show a compact table (selection_id, date, title, one-line gist) and wait. Selection IDs persist across later searches.

**3. Get.**

```bash
paper2md get s_ab12cd34ef56:1 s_ab12cd34ef56:3 --json
paper2md get https://arxiv.org/abs/2304.08465 --json        # direct link, no search needed
```

Accepted sources: selection IDs, `arxiv:ID`, arXiv / Hugging Face Papers / OpenReview / direct-PDF URLs, `doi:...`, `openalex:W...`, local PDF paths.

Output: `./papers/<id>-<hash>/` under the current directory (`-o DIR` to change). Each item has `status` (`ok` | `cached` | `error`), `engine`, `warnings`, and `files`:

```text
paper.pdf       original PDF
paper.md        full text, pages delimited by <!-- Página N -->
ocr.json        raw engine response
manifest.json   source, PDF sha256, engine/options, page validation, warnings
```

Exit code 1 can still mean some items succeeded; check every item.

**4. Read.** Open `files.markdown` with your file tool and cite page numbers from the `<!-- Página N -->` markers. Papers run 50–150k characters, so grep for sections (Method, Experiments, Table, Limitations) instead of loading everything. `paper2md read <id> --json` returns the Markdown on stdout, but prefer reading the file. To compare many papers, give one paper to each subagent with the same checklist, then merge.

### Engines

`auto` (the default) tries **Mistral → Nanonets → local**, skipping any API without a key. If an engine fails (quota, credits, timeout, missing pages, a PDF over Mistral's 50 MiB limit), the next one takes over and the failure appears in `warnings`.

| Engine | Output | Speed / cost |
|---|---|---|
| `mistral` | Markdown, tables, LaTeX, extracted figures with AI descriptions | seconds, paid |
| `nanonets` | Markdown, HTML `<table>`, LaTeX, `[Figura: description]` | ≤5 pages sync; longer runs async, ~1–3 min per paper; paid |
| `local` | pymupdf4llm: layout-aware Markdown with tables; equations as plain text | ~0.5 s/page, free, offline; no OCR for scanned PDFs |

In `auto`, an existing conversion from any engine is reused with no new paid calls. To upgrade a `local` result, pass `--engine nanonets` or `--engine mistral`. `--pages 1,3-5` converts only those pages (1-based), which is a cheap way to test.

**Run `get` with a long timeout (≥ 10 min) or in the background.** Async OCR takes minutes.

### Failures you will meet

- **Paywall, login or antibot** (IEEE; OpenReview now challenges bots): the item errors. Ask the user for the PDF and pass the local path.
- **"Destino já existe"**: add `--force`.
- **Stale lock message**: a previous run was killed. Remove the lock file it names.
- **Network blocked in a sandboxed agent** (e.g. Codex `WinError 10013`): request network permission and rerun.

### Python API (for an MCP server later)

`Searcher(store, transport).search_papers(queries, since, limit, sort)`, `PaperService(store, transport).get_papers(sources, Options(...))` and `.read_paper(source, options)` in `src/paper2md/` return the same dicts the CLI prints. They work without argparse.

---

## Part 2 — Working on this repo

```text
src/paper2md/
  cli.py        argparse entrypoint; JSON contract (schema_version: 1)
  search.py     OpenAlex semantic + arXiv Atom search, rank fusion, date window
  sources.py    source parsing (arXiv/HF/OpenReview/DOI/URL/local), PDF fetch
  service.py    get/read orchestration, engine chain, cache, bundle publishing
  mistral.py    Mistral OCR client (+ figure annotations)
  nanonets.py   Nanonets client (sync ≤5 pages / async polling) + output cleanup
  pdfmeta.py    page count, page selection, local pymupdf4llm extraction
  export.py     render engine response → paper.md / paper.txt, atomic bundle write
  store.py      SQLite state (searches, papers, bundles) + file locks
  transport.py  httpx wrapper: size limits, retries on GET, API error messages
skill/paper2md/SKILL.md   agent skill (linked into ~/.claude/skills and ~/.codex/skills)
tests/                    offline unittest suite + tests/e2e_live.py
docs/validation.md        what was verified live, and what wasn't
```

### Invariants — don't break these

- **All engines return the same shape:** `{"model", "pages": [{"index", "markdown", "images"}], "local_validation"}`, with `index` zero-based and every requested page present. A response with missing pages is rejected and never saved as complete.
- **No silent paid retries.** `post_json` never retries; the chain moves to the next engine instead.
- **Cache identity** is the PDF sha256 plus the engine's conversion options. Partial (`--pages`) bundles are never served by `read`.
- **Errors are `PaperError` (a `ValueError`) with a Portuguese message.** User-facing strings are pt-BR; code, comments and docs are English.
- **Search results come only from the APIs**; never invent papers or references.

### Verify

```bash
python -m unittest discover -s tests                   # offline, mocked HTTP, ~5 s
python -X utf8 tests/e2e_live.py                       # live APIs; writes e2e-report.json
python -X utf8 tests/e2e_live.py --engine local
```

The live E2E drives the CLI as a subprocess, exactly as an agent would. Run it after any change to search, sources, engines or the JSON contract, and record notable results in `docs/validation.md`.
