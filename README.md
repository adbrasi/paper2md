# paper2md

Pesquise um assunto, escolha papers e entregue PDF + texto completo aos seus agentes. CLI Python pequena, sem servidor, Docker ou índice vetorial local.

## Instalar

Requer Python 3.11 ou superior.

```bash
pip install .
```

Para desenvolvimento: `pip install -e .`.

Funciona sem nenhuma chave: busca (OpenAlex + arXiv) e extração local (pymupdf4llm) são gratuitas. As chaves Mistral e Nanonets são opcionais e habilitam OCR de melhor qualidade. No PowerShell:

```powershell
$env:MISTRAL_API_KEY = "sua-chave"
$env:NANONETS_API_KEY = "sua-chave"
```

No Bash:

```bash
export MISTRAL_API_KEY="sua-chave"
export NANONETS_API_KEY="sua-chave"
```

O arquivo `.env.example` serve como referência; a CLI **não carrega `.env` automaticamente**. Nunca coloque sua chave nos argumentos dos comandos.

## Três comandos

### 1. Pesquisar

```bash
paper2md search "parameter-efficient fine-tuning of diffusion models" "LoRA DoRA text-to-image"
```

Aceita de 1 a 5 consultas em inglês. Cada uma roda no OpenAlex (busca semântica, aceita frases descritivas) e no arXiv (exige **todos** os termos, então prefira 2–5 palavras-chave); os rankings são fundidos e deduplicados. Não há LLM na busca: o agente que chama a ferramenta escreve as consultas. Os papers e metadados vêm sempre das APIs.

Padrão: dez resultados, últimos dois anos móveis, ordenados por relevância. Não amplia a janela silenciosamente. Para métodos fundacionais como LoRA original ou DreamBooth, amplie a data:

```bash
paper2md search "LoRA DoRA DreamBooth diffusion adaptation" --since 2021-01-01 --limit 15
paper2md search "diffusion fine-tuning" --sort recent --json
```

Os IDs de seleção têm a forma `s_abcdef123456:1`. Cada busca tem seu próprio prefixo persistente: dois agentes podem pesquisar sem confundir seus resultados. `--json` inclui abstract completo, autores, datas, venue, citações disponíveis e links. Na tabela humana o abstract aparece abreviado, mas isso não reduz o conteúdo salvo ou o JSON.

### 2. Obter os escolhidos

Use os IDs reais retornados pela sua busca:

```bash
paper2md get s_abcdef123456:1 s_abcdef123456:3
```

Também aceita link direto ou PDF local, sem precisar pesquisar:

```bash
paper2md get "https://arxiv.org/abs/2402.09353"
paper2md get "https://huggingface.co/papers/2402.09353"
paper2md get "https://openreview.net/forum?id=SE0W94BwgQ"
paper2md get ./paper.pdf --format txt
```

**Engines de conversão.** Padrão `auto`: tenta **Mistral OCR** → **Nanonets** → **local**, pulando APIs sem chave. Se uma engine falhar (cota, créditos, timeout, páginas faltando, PDF grande demais), a próxima assume e o aviso fica no resultado e no `manifest.json`. O campo `engine` de cada item diz qual foi usada.

| Engine | Qualidade | Custo / tempo | Limites |
|---|---|---|---|
| `mistral` | Markdown, tabelas, equações, figuras extraídas com descrição | pago, segundos | PDF até 50 MiB |
| `nanonets` | Markdown, tabelas em HTML, equações LaTeX | pago; até 5 páginas síncrono, acima disso assíncrono (~3 min para 23 páginas) | sem figuras extraídas |
| `local` | pymupdf4llm: análise de layout, títulos, tabelas em Markdown | grátis, offline, ~0,5 s/página | não faz OCR de PDF escaneado; equações viram texto simples |

`--engine mistral|nanonets|local` força uma engine. `PAPER2MD_ENGINE` fixa o padrão. Em `auto`, uma conversão já salva de qualquer engine da cadeia é reutilizada (em ordem de prioridade), sem novas chamadas pagas; para trocar uma conversão local por OCR, use `--engine mistral` ou `--engine nanonets`.

A engine local usa [pymupdf4llm](https://pypi.org/project/pymupdf4llm/) com modelo de layout em ONNX (sem PyTorch/GPU). Marker, MinerU e olmOCR pontuam mais em benchmarks de OCR, mas exigem PyTorch, gigabytes de modelos e são lentos em CPU: inadequados para o último fallback.

**Descrições de figuras ativadas por padrão (engine mistral).** Usa BBox Annotations da Mistral e insere descrições em português, identificadas como geradas por IA, junto às imagens. Isso pode custar mais que OCR básico; o valor depende da API/modelo. Desativar:

```bash
paper2md get arxiv:2402.09353 --no-describe-images
paper2md get arxiv:2402.09353 --no-images
```

`--no-images` não salva arquivos de figuras, mas preserva as descrições. A API pode não extrair ou descrever todas as figuras; o resultado traz avisos quando uma figura retornada não tem descrição. Descrições são interpretações do modelo e precisam de conferência quando usadas como evidência.

Cada paper recebe uma pasta em `./papers`, com nome baseado no ID e na configuração:

```text
paper.pdf       PDF original
paper.md        Markdown do OCR, páginas identificadas
ocr.json        Resposta estruturada original da API
manifest.json   Origem, hash PDF, versão, modelo, opções, uso e avisos
assets/        Imagens extraídas, quando disponíveis
paper.txt      Texto adicional quando --format txt
```

`--format json` fornece a resposta estruturada em `ocr.json`; PDF e Markdown são preservados em todos os formatos. `-o DIRETORIO` muda a pasta de destino.

Para testar uma página antes de converter o documento inteiro:

```bash
paper2md get arxiv:2402.09353 --pages 1 --json
```

`--pages 1,3-5` é numeração humana começando em 1. Sem essa opção, converte o documento inteiro. O manifesto identifica conversões parciais.

### 3. Entregar o conteúdo ao agente

```bash
paper2md read arxiv:2402.09353 --json
```

Retorna Markdown **completo**, manifesto e caminhos dos arquivos. Se ainda não existir uma conversão completa compatível, obtém e converte. Nunca usa conversão de uma página como se fosse o documento inteiro.

Sem `--json`, imprime somente o Markdown. O agente consumidor pode comparar VRAM, custo, tempo de treinamento, benchmarks e limitações com referências às páginas. A CLI não faz comparação científica ou resumo por conta própria.

## Uso por agentes

Execute os comandos como subprocessos, leia JSON do stdout e progresso do stderr. `schema_version: 1` identifica o contrato. Exit codes: 0 sucesso; 1 falha ou lote com falhas; 2 argumentos inválidos; 130 interrupção. Um lote pode ter papers obtidos e outros inacessíveis: confira cada item, mesmo com exit code 1.

```python
import json
import subprocess

def run(*args):
    result = subprocess.run(["paper2md", *args, "--json"], capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(result.stdout)
    if result.returncode and not payload.get("items"):
        raise RuntimeError(payload.get("error", result.stderr))
    return payload

found = run("search", "recent diffusion model low-rank adaptation")
chosen = [p["selection_id"] for p in found["results"][:2]]
if chosen:
    acquired = run("get", *chosen)
    for item in acquired["items"]:
        if item["status"] != "error":
            document = run("read", item["id"])
            # Envie document["markdown"] e document["manifest"] ao seu agente.
```

Os módulos `Searcher.search_papers`, `PaperService.get_papers` e `PaperService.read_paper` funcionam sem argparse. Isso permite adicionar MCP posteriormente. MySQL também fica para uma próxima etapa: hoje SQLite não exige serviço adicional.

## Cache e configuração

Buscas e índices de arquivos ficam no diretório de dados do usuário: `%LOCALAPPDATA%/paper2md` no Windows ou `$XDG_DATA_HOME/paper2md` no Linux (padrão `~/.local/share/paper2md`). PDFs e conversões ficam no diretório de saída escolhido.

| Variável | Função |
|---|---|
| `MISTRAL_API_KEY` | OCR Mistral (opcional) |
| `NANONETS_API_KEY` | OCR Nanonets (opcional) |
| `PAPER2MD_ENGINE` | Engine padrão: `auto`, `mistral`, `nanonets` ou `local` |
| `OPENALEX_API_KEY` | Chave opcional para ampliar o orçamento OpenAlex |
| `PAPER2MD_HOME` | Diretório do estado SQLite e locks |
| `OCR_MODEL` | Modelo OCR; padrão `mistral-ocr-latest` |

Repetir `get` reobtém o PDF para conferir seu hash e reutiliza OCR compatível. Mudar páginas, modelo ou opções de figuras cria uma configuração distinta. `read` reutiliza a versão salva e entrega sua data/hash: use `get` para conferir alterações na fonte. Para reprodução exata, use URL arXiv versionada e nome de modelo fixo; o alias `latest` pode mudar no provedor.

`--force` permite substituir um destino existente, mas não força uma nova chamada paga quando há cache compatível. Preserve o estado e os arquivos para manter o cache. Não apagar ou mover bundles enquanto agentes os utilizam.

## Fontes e limites

- arXiv e Hugging Face Papers: resolve PDFs por ID, incluindo versões arXiv.
- OpenReview: PDF público da submissão. Em 2026-10 o OpenReview passou a exigir verificação antibot para clientes automatizados; nesse caso baixe o PDF no navegador e use o arquivo local.
- IEEE e outros sites: tenta PDF público direto ou metadados `citation_pdf_url`/link inequívoco. Bloqueios de login, paywall ou antibot retornam erro; forneça o PDF obtido com seu acesso.
- Registros OpenAlex que não são papers (datasets, software, errata etc.) são descartados. O `venue` costuma aparecer como arXiv mesmo para papers publicados em conferência.
- OpenAlex semântico só filtra por ano; a data exata `--since` é aplicada localmente. Alguns registros OpenAlex trazem só o ano (`AAAA-01-01`).
- OpenAlex/arXiv: busca online reflete o índice disponível, sem garantia de indexação no mesmo dia. Data e origem aparecem nos resultados. Publicação recente, venue e citações não são garantia de qualidade científica.
- OpenAlex usa limites/orçamento próprios; se falhar, o arXiv pode continuar e a CLI mostra cobertura reduzida. Respeita intervalo de 1 segundo OpenAlex e 3 segundos arXiv entre consultas desta instalação.
- Downloads têm limite local de 200 MiB (papers de difusão costumam passar de 50 MiB por causa das imagens). O Mistral OCR aceita até 50 MiB; acima disso `auto` passa para a próxima engine. Com engines de API, o PDF é enviado ao provedor (a Nanonets guarda o arquivo processado em armazenamento próprio).
- PyMuPDF valida a estrutura e conta as páginas antes da chamada paga; a CLI rejeita respostas OCR com páginas ausentes, inclusive a última. Isso verifica cobertura de páginas, não a exatidão de cada palavra extraída.
- Chamadas pagas de OCR não são repetidas automaticamente após timeout. Uma chamada interrompida pode ter sido processada/cobrada pelo provedor.

## Testes

```bash
python -m unittest discover -s tests -v
```

Testes offline usam transporte HTTP simulado, sem créditos ou credenciais. Cobrem seleção persistente, falhas parciais, resolução de links, annotations por padrão, páginas, cache, arquivos existentes, exportação e nomes seguros de imagens.

E2E ao vivo (APIs reais, CLI como subprocesso, como um agente usaria); grava `e2e-report.json`:

```bash
python -X utf8 tests/e2e_live.py              # cadeia auto
python -X utf8 tests/e2e_live.py --engine local
```

Referências: [Mistral Document AI](https://docs.mistral.ai/studio/document-processing/overview), [Annotations](https://docs.mistral.ai/studio/document-processing/annotations), [OpenAlex semantic search](https://help.openalex.org/api/semantic-search/), [arXiv API](https://info.arxiv.org/help/api/index.html), [Nanonets extraction API](https://docstrange.nanonets.com/docs/quickstart).
