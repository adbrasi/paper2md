import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .mistral import parse_pages
from .search import Searcher
from .service import Options, PaperService
from .store import Store
from .transport import Transport, PaperError


def parser():
    root = argparse.ArgumentParser(description="Busque papers, escolha IDs e obtenha PDF + Markdown completo.")
    root.add_argument("--version", action="version", version=f"paper2md {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="Pesquisar por descrição do assunto")
    search.add_argument("query")
    search.add_argument("--since", help="Data inicial YYYY-MM-DD; padrão: últimos dois anos")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--sort", choices=("relevance", "recent"), default="relevance")
    search.add_argument("--json", action="store_true", help="Saída estruturada para agentes")
    get = commands.add_parser("get", help="Obter PDF, Markdown e metadados dos escolhidos")
    get.add_argument("sources", nargs="+", help="selection_id, ID canônico, URL ou PDF local")
    read = commands.add_parser("read", help="Retornar Markdown completo de um paper")
    read.add_argument("source")
    for cmd in (get, read):
        cmd.add_argument("-o", "--output", type=Path, default=Path("papers"), help="Diretório de saída")
        cmd.add_argument("--no-describe-images", action="store_true", help="Desativar descrições (ativadas por padrão)")
        cmd.add_argument("--no-images", action="store_true", help="Não salvar imagens; preservar descrições")
        cmd.add_argument("--model", default=os.getenv("OCR_MODEL", "mistral-ocr-latest"))
        cmd.add_argument("--json", action="store_true")
        cmd.add_argument("--force", action="store_true", help="Permitir substituir destino existente")
    get.add_argument("--format", choices=("md", "txt", "json"), default="md", help="TXT adicional ou JSON OCR; MD e PDF sempre salvos")
    get.add_argument("--pages", help="Selecionar páginas (ex.: 1,3-5); padrão: documento completo")
    return root


def emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None):
    # Consistent UTF-8 for Windows terminals and agent subprocess pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    transport = None
    try:
        store = Store()
        transport = Transport()
        if args.command == "search":
            print("Pesquisando fontes online...", file=sys.stderr)
            result = Searcher(store, transport).search_papers(args.query, args.since, args.limit, args.sort)
            for warning in result["warnings"]:
                print("Aviso: " + warning, file=sys.stderr)
            if args.json:
                emit(result)
            else:
                print(f"Busca {result['search_id']} | desde {result['filters']['since']}\n")
                for paper in result["results"]:
                    print(f"{paper['selection_id']}  {paper['published'] or '?'}  {paper['title']}")
                    print(f"  {paper['venue'] or ', '.join(paper['sources'])} | PDF: {'link disponível' if paper['pdf_url'] else 'a resolver'}")
                    if paper["abstract"]:
                        print("  " + paper["abstract"][:320] + ("…" if len(paper["abstract"]) > 320 else ""))
                    print("  " + (paper["url"] or paper["id"]) + "\n")
                print("Escolha: paper2md get <selection_id> <selection_id>")
            return 0
        options = Options(output=args.output, model=args.model, describe_images=not args.no_describe_images,
                          images=not args.no_images, force=args.force,
                          format=getattr(args, "format", "md"), pages=parse_pages(getattr(args, "pages", None)))
        service = PaperService(store, transport)
        if args.command == "read":
            result = service.read_paper(args.source, options)
            if args.json:
                emit(result)
            else:
                sys.stdout.write(result["markdown"])
            return 0
        print("Obtendo PDFs e conteúdo...", file=sys.stderr)
        result = service.get_papers(args.sources, options)
        if args.json:
            emit(result)
        else:
            for item in result["items"]:
                if item["status"] == "error":
                    print(f"Erro: {item['source']}: {item['error']}", file=sys.stderr)
                else:
                    print(f"{item['id']} [{item['status']}]\n  PDF: {item['files']['pdf']}\n  Markdown: {item['files']['markdown']}")
                    if item["files"].get("text"):
                        print("  TXT: " + item["files"]["text"])
                    for warning in item["warnings"]:
                        print("Aviso: " + warning, file=sys.stderr)
        return 0 if result["ok"] else 1
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "Falha ao acessar os arquivos locais. Verifique permissões e diretórios."
        if getattr(args, "json", False):
            emit({"schema_version": 1, "ok": False, "error": message})
        print("Erro: " + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrompido; uma chamada OCR em andamento pode ter sido cobrada.", file=sys.stderr)
        return 130
    finally:
        if transport:
            transport.close()


def entrypoint():
    raise SystemExit(main())
