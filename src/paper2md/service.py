from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .export import publish_bundle, markdown_to_text
from .mistral import MistralOCR
from .nanonets import NanonetsOCR
from .pdfmeta import extract_local
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
    engine: str = "auto"  # auto: mistral -> nanonets -> local, skipping API engines without a key

    def conversion(self, engine):
        if engine == "mistral":
            return {"engine": "mistral", "model": self.model, "pages": self.pages,
                    "describe_images": self.describe_images, "images": self.images}
        return {"engine": engine, "pages": self.pages}


ENGINES = ("mistral", "nanonets", "local")
BUNDLE_FILES = ("paper.md", "paper.pdf", "ocr.json", "manifest.json")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class PaperService:
    def __init__(self, store, transport, key=None, nanonets_key=None):
        self.store, self.transport = store, transport
        self.ocr = MistralOCR(transport, key)
        self.nanonets = NanonetsOCR(transport, nanonets_key)

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

    def engines(self, options):
        if options.engine == "auto":
            return [e for e, usable in zip(ENGINES, (self.ocr.key, self.nanonets.key, True)) if usable]
        if options.engine not in ENGINES:
            raise PaperError("Engine inválida; use auto, mistral, nanonets ou local.")
        return [options.engine]

    def convert(self, pdf, options, engine):
        if engine == "mistral":
            return self.ocr.process(pdf, options.model, options.pages, options.describe_images, options.images)
        if engine == "nanonets":
            return self.nanonets.process(pdf, options.pages)
        return extract_local(pdf, options.pages)

    def target(self, paper, options, conversion):
        slug = re.sub(r"[^A-Za-z0-9._-]", "_", paper.id)[:90]
        return Path(options.output).resolve() / (slug + "-" + digest({"paper_id": paper.id, **conversion})[:12])

    def files(self, bundle):
        names = {"pdf": "paper.pdf", "markdown": "paper.md", "text": "paper.txt", "json": "ocr.json", "manifest": "manifest.json"}
        return {k: str((bundle / name).resolve()) for k, name in names.items() if (bundle / name).is_file()}

    def cached(self, paper, pdf_hash, cache_key):
        bundle = self.store.bundle(paper.id, cache_key)
        try:
            if bundle and all((bundle / name).is_file() for name in BUNDLE_FILES) \
                    and load_json(bundle / "manifest.json").get("cache_key") == cache_key \
                    and hashlib.sha256((bundle / "paper.pdf").read_bytes()).hexdigest() == pdf_hash:
                return bundle
        except (ValueError, OSError, AttributeError):
            pass
        return None

    def writable_target(self, target, options):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or (target.exists() and not options.force):
            raise PaperError("Destino já existe; use --force para substituir. Nenhuma conversão realizada.")
        with tempfile.TemporaryFile(dir=target.parent):
            pass

    def _get(self, source, options, engines):
        paper = self.resolve(source)
        # Conversions can take minutes (Nanonets async); a concurrent request for the same paper waits for it.
        with self.store.lock("paper:" + paper.id, timeout=self.nanonets.timeout + 60):
            pdf = fetch_pdf(paper, self.transport)
            pdf_hash = hashlib.sha256(pdf).hexdigest()
            # Any compatible conversion already on disk wins, in engine priority order: no repeated paid calls.
            for engine in engines:
                conversion = options.conversion(engine)
                cache_key = digest({"pdf_sha256": pdf_hash, **conversion})
                cached = self.cached(paper, pdf_hash, cache_key)
                if cached:
                    break
            if cached:
                target = self.target(paper, options, conversion)
                manifest = load_json(cached / "manifest.json")
                if cached == target:
                    if options.format == "txt" and not (cached / "paper.txt").exists():
                        temporary = cached / "paper.txt.tmp"
                        temporary.write_text(markdown_to_text((cached / "paper.md").read_text(encoding="utf-8")), encoding="utf-8")
                        temporary.replace(cached / "paper.txt")
                    return {"id": paper.id, "status": "cached", "engine": conversion["engine"],
                            "files": self.files(cached), "warnings": manifest.get("warnings", [])}
                self.writable_target(target, options)
                response = load_json(cached / "ocr.json")
                failures = []
            else:
                failures = []
                for engine in engines:
                    conversion = options.conversion(engine)
                    target = self.target(paper, options, conversion)
                    self.writable_target(target, options)
                    try:
                        response = self.convert(pdf, options, engine)
                        break
                    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                        failures.append(f"{engine}: {exc if isinstance(exc, ValueError) else type(exc).__name__}")
                else:
                    raise PaperError("Nenhuma engine converteu o PDF. " + " | ".join(failures))
                cache_key = digest({"pdf_sha256": pdf_hash, **conversion})
                manifest = {"schema_version": 1, "paper": paper.to_dict(), "fetched_at": timestamp(),
                    "pdf_sha256": pdf_hash, "cache_key": cache_key, "options": conversion,
                    "actual_model": response.get("model"), "usage": response.get("usage_info"),
                    "page_validation": response.get("local_validation"),
                    "partial": options.pages is not None}
            warnings = publish_bundle(target, pdf, response, manifest, options, ["Engine falhou, usada a próxima: " + f for f in failures])
            self.store.save_paper(paper)
            self.store.save_bundle(paper.id, cache_key, target)
            return {"id": paper.id, "status": "cached" if cached else "ok", "engine": conversion["engine"],
                    "files": self.files(target), "warnings": warnings}

    def get_papers(self, sources, options=None):
        options = options or Options()
        if options.format not in ("md", "txt", "json"):
            raise PaperError("Formato inválido.")
        engines = self.engines(options)
        items = []
        for source in dict.fromkeys(sources):
            try:
                items.append(self._get(source, options, engines))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                error = str(exc) if isinstance(exc, ValueError) else "Falha ao acessar arquivo, destino ou metadados."
                items.append({"source": source, "status": "error", "error": error})
        return {"schema_version": 1, "ok": bool(items) and all(i["status"] != "error" for i in items), "items": items}

    def read_paper(self, source, options=None):
        options = replace(options or Options(), pages=None)
        accepted = [options.conversion(engine) for engine in self.engines(options)]
        paper = self.resolve(source)
        bundle = self.store.bundle(paper.id)
        manifest = None
        if bundle and (bundle / "manifest.json").is_file() and (bundle / "paper.md").is_file():
            manifest = load_json(bundle / "manifest.json")
            if manifest.get("partial") or manifest.get("options") not in accepted:
                bundle = None
        else:
            bundle = None
        if bundle is None:
            result = self.get_papers([source], options)
            if not result["ok"]:
                raise PaperError(result["items"][0]["error"])
            bundle = Path(result["items"][0]["files"]["markdown"]).parent
            manifest = load_json(bundle / "manifest.json")
        return {"schema_version": 1, "id": paper.id, "markdown": (bundle / "paper.md").read_text(encoding="utf-8"),
                "manifest": manifest, "files": self.files(bundle), "from_saved_version": True}
