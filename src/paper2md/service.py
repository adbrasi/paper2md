from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .export import publish_bundle, markdown_to_text
from .mistral import MistralOCR
from .search import openalex_paper
from .sources import direct_source, fetch_pdf
from .store import timestamp
from .transport import PaperError


@dataclass
class Options:
    output: Path = field(default_factory=lambda: Path("papers"))
    format: str = "md"
    model: str = "mistral-ocr-latest"
    pages: list[int] | None = None
    describe_images: bool = True
    images: bool = True
    force: bool = False

    def conversion(self):
        return {"model": self.model, "pages": self.pages, "describe_images": self.describe_images, "images": self.images}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class PaperService:
    def __init__(self, store, transport, key=None):
        self.store, self.transport = store, transport
        self.ocr = MistralOCR(transport, key)

    def resolve(self, source):
        try:
            return self.store.resolve(source)
        except ValueError:
            if source.startswith("s_"):
                raise
        if source.startswith("openalex:"):
            identifier = source[9:]
            if not re.fullmatch(r"W\d+", identifier):
                raise PaperError("ID OpenAlex inválido.")
            paper = openalex_paper(self.transport.json_get("https://api.openalex.org/works/" + identifier, service="OpenAlex"))
        else:
            paper = direct_source(source)
        self.store.save_paper(paper)
        return paper

    def target(self, paper, options):
        slug = re.sub(r"[^A-Za-z0-9._-]", "_", paper.id)[:90]
        return Path(options.output).resolve() / (slug + "-" + digest({"paper_id": paper.id, **options.conversion()})[:12])

    def files(self, bundle):
        names = {"pdf": "paper.pdf", "markdown": "paper.md", "text": "paper.txt", "json": "ocr.json", "manifest": "manifest.json"}
        return {k: str((bundle / name).resolve()) for k, name in names.items() if (bundle / name).is_file()}

    def _get(self, source, options):
        paper = self.resolve(source)
        target = self.target(paper, options)
        with self.store.lock("paper:" + paper.id):
            pdf = fetch_pdf(paper, self.transport)
            pdf_hash = hashlib.sha256(pdf).hexdigest()
            cache_key = digest({"pdf_sha256": pdf_hash, **options.conversion()})
            cached = self.store.bundle(paper.id, cache_key)
            if cached:
                try:
                    saved = json.loads((cached / "manifest.json").read_text(encoding="utf-8"))
                    saved_hash = hashlib.sha256((cached / "paper.pdf").read_bytes()).hexdigest()
                    if saved.get("cache_key") != cache_key or saved_hash != pdf_hash:
                        cached = None
                except (ValueError, OSError, AttributeError):
                    cached = None
            if cached and all((cached / name).is_file() for name in ("paper.md", "paper.pdf", "ocr.json", "manifest.json")):
                if cached == target:
                    if options.format == "txt" and not (cached / "paper.txt").exists():
                        text = markdown_to_text((cached / "paper.md").read_text(encoding="utf-8"))
                        temporary = cached / "paper.txt.tmp"
                        temporary.write_text(text, encoding="utf-8")
                        temporary.replace(cached / "paper.txt")
                    manifest = json.loads((cached / "manifest.json").read_text(encoding="utf-8"))
                    return {"id": paper.id, "status": "cached", "files": self.files(cached), "warnings": manifest.get("warnings", [])}
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or (target.exists() and not options.force):
                raise PaperError("Destino já existe; use --force para substituir. Nenhuma chamada OCR realizada.")
            with tempfile.TemporaryFile(dir=target.parent):
                pass
            if cached:
                response = json.loads((cached / "ocr.json").read_text(encoding="utf-8"))
                manifest = json.loads((cached / "manifest.json").read_text(encoding="utf-8"))
            else:
                response = self.ocr.process(pdf, **options.conversion())
                manifest = {"schema_version": 1, "paper": paper.to_dict(), "fetched_at": timestamp(),
                    "pdf_sha256": pdf_hash, "cache_key": cache_key, "options": options.conversion(),
                    "actual_model": response.get("model"), "usage": response.get("usage_info"),
                    "page_validation": response.get("local_validation"),
                    "partial": options.pages is not None}
            warnings = publish_bundle(target, pdf, response, manifest, options)
            self.store.save_paper(paper)
            self.store.save_bundle(paper.id, cache_key, target)
            return {"id": paper.id, "status": "cached" if cached else "ok", "files": self.files(target), "warnings": warnings}

    def get_papers(self, sources, options=None):
        options = options or Options()
        if options.format not in ("md", "txt", "json"):
            raise PaperError("Formato inválido.")
        items = []
        for source in dict.fromkeys(sources):
            try:
                items.append(self._get(source, options))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                error = str(exc) if isinstance(exc, ValueError) else "Falha ao acessar arquivo, destino ou metadados."
                items.append({"source": source, "status": "error", "error": error})
        result = {"schema_version": 1, "ok": bool(items) and all(i["status"] != "error" for i in items), "items": items}
        return result

    def read_paper(self, source, options=None):
        options = options or Options()
        paper = self.resolve(source)
        bundle = self.store.bundle(paper.id)
        manifest = None
        if bundle and (bundle / "manifest.json").is_file() and (bundle / "paper.md").is_file():
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("partial") or manifest.get("options") != options.conversion():
                bundle = None
        else:
            bundle = None
        if bundle is None:
            full_options = Options(**{**asdict(options), "pages": None})
            result = self.get_papers([source], full_options)
            if not result["ok"]:
                raise PaperError(result["items"][0]["error"])
            bundle = Path(result["items"][0]["files"]["markdown"]).parent
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        return {"schema_version": 1, "id": paper.id, "markdown": (bundle / "paper.md").read_text(encoding="utf-8"),
                "manifest": manifest, "files": self.files(bundle), "from_saved_version": True}
