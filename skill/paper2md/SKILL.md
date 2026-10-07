---
name: paper2md
description: Use when a task needs scientific papers as references — finding recent research on a topic, comparing methods (e.g. LoRA vs DoRA vs DreamBooth), checking state of the art, or turning an arXiv/Hugging Face/paper link or PDF into full text an agent can read. Covers "procura papers sobre", "acha estudos", "compara esses métodos", "lê esse paper", literature review for a project. Not for general web search or non-academic sources.
---

# paper2md — find papers, fetch PDF + full text

`paper2md` is an installed CLI (Windows PowerShell and WSL, same commands). It searches OpenAlex + arXiv, keeps numbered results, downloads chosen PDFs and converts them to Markdown/text on disk. Always pass `--json`: stdout is JSON, progress goes to stderr.

## Workflow

### 1. Search — you write the queries

```bash
paper2md search "parameter-efficient fine-tuning of text-to-image diffusion models" "LoRA DoRA diffusion" "DreamBooth personalization" --json
```

- 1–5 queries, **in English**, even when the user speaks Portuguese. There is no LLM inside the tool; query quality is your job.
- Each query runs on both providers. OpenAlex is semantic: one descriptive sentence works well. arXiv requires **every** term of a query: keep keyword queries to 2–5 words, one per method/angle you care about.
- Default window: last 2 years, 10 results, relevance order. `--sort recent` for newest first. `--limit N` (max 50).
- The 2-year window finds *new* work. When the user names methods that are older (LoRA 2021, DreamBooth 2022, DoRA/OFT 2023–24), run a second search for them with `--since` set to their year, so the comparison has the originals **and** the recent successors. Never present only old papers as "current state of the art".
- Results can include off-topic items or name collisions (two different "DoRA"s). Judge by the abstract, not the title.
- Result fields: `selection_id` (e.g. `s_ab12cd34ef56:3`), `id`, `title`, `published`, `venue`, `citations`, `abstract`, `pdf_url`, `url`. Check `warnings` (e.g. one provider down).

### 2. Choose

- If the user wants to choose: show a compact numbered table (selection_id, date, title, venue, one-line gist from the abstract) and wait.
- If you are choosing for a task: prefer on-topic abstracts and recent dates; skip surveys unless an overview is wanted. `venue` often says arXiv even for papers published at ICML/ICLR (the PDF header tells the truth) and `citations` lag for recent work — weak signals only. Selection IDs persist across later searches.

### 3. Get

```bash
paper2md get s_ab12cd34ef56:1 s_ab12cd34ef56:3 --json
```

Also accepts `arxiv:2402.09353`, arXiv/Hugging Face/OpenReview/direct-PDF URLs, `doi:...`, `openalex:W...`, or a local PDF path. Output defaults to `./papers/<id>-<hash>/` in the current directory (`-o DIR` to change); in a git project make sure `papers/` is ignored.

Each `items[]` entry has `status` (`ok` | `cached` | `error`) and `files`: `pdf`, `markdown` (`paper.md`), `json`, `manifest`. Exit code 1 can still mean some items succeeded — check each item.

### 4. Read

Read `files.markdown` with your file-reading tool. Pages are delimited by `<!-- Página N -->` — cite page numbers when you compare or quote. Papers are often 50–150k characters: grep for sections (Method, Experiments, Table, Limitations) or read in chunks instead of loading everything when you only need specific facts.

Each item's `engine` field (also `manifest.json` → `options.engine`) says which engine produced the text. Tables come out as Markdown (`local`, `mistral`) or HTML `<table>` (`nanonets`); equations are LaTeX except with `local`. When an exact number matters and the text looks garbled, check that page in `files.pdf`.

`paper2md read <id> --json` returns `{markdown, manifest, files}` in one shot (and converts if needed); it can be very large on stdout, so prefer reading the file.

For comparing many papers, delegate one paper per subagent with the same extraction checklist (e.g. method, VRAM, training time, data needed, benchmarks, limitations), then merge.

## Engines

Default `auto` tries **Mistral OCR → Nanonets → local**, skipping APIs without a key (`MISTRAL_API_KEY`, `NANONETS_API_KEY`). A failing engine (quota, credits, >50 MiB for Mistral, missing pages, timeout) hands over to the next one; the failure appears in the item's `warnings`. Don't retry manually — just report which engine was used if quality matters.

- `mistral`: best fidelity, figures extracted with AI descriptions (Portuguese). Seconds.
- `nanonets`: good Markdown + HTML tables + LaTeX. >5 pages runs async: **~3 min for a 20-page paper**, so run `get` with a long timeout (≥ 10 min) or in the background.
- `local` (pymupdf4llm): free, offline, ~0.5 s/page, layout-aware with Markdown tables. No OCR for scanned PDFs.
- `--engine X` forces one. In `auto`, an existing conversion from any engine is reused; to upgrade a `local` result to OCR, pass `--engine mistral` or `--engine nanonets`. `--pages 1` tests a paid engine cheaply.

## Failures

- Paywall, login, antibot (IEEE, OpenReview now challenges bots): the item errors. Ask the user to download the PDF and pass the local path.
- "Destino já existe": add `--force`. Stale lock message: a previous run crashed; remove the named lock file.
- Network errors in a sandboxed agent (e.g. Codex `WinError 10013`): the command needs network access — request escalated permission and rerun.
- Never put API keys in command arguments; they come from the environment.
