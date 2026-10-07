import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from .models import Paper
from .transport import PaperError, public_url

ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z0-9.-]*/\d{7})(?:v\d+)?\Z")


def arxiv_paper(identifier):
    identifier = identifier.removesuffix(".pdf")
    if not ARXIV_ID.fullmatch(identifier):
        raise PaperError("ID arXiv inválido.")
    return Paper(id="arxiv:" + identifier, title=identifier, url="https://arxiv.org/abs/" + identifier,
                 pdf_url="https://arxiv.org/pdf/" + identifier, sources=["arxiv"])


def direct_source(source):
    if source.startswith("arxiv:"):
        return arxiv_paper(source[6:])
    if ARXIV_ID.fullmatch(source):
        return arxiv_paper(source)
    parsed = urlparse(source)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path)
    if host in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
        match = re.fullmatch(r"/(?:abs|pdf|html)/(.+?)/?", path)
        if match:
            return arxiv_paper(match[1])
    if host in ("huggingface.co", "www.huggingface.co", "hf.co"):
        match = re.fullmatch(r"/papers/(.+?)/?", path)
        if match:
            return arxiv_paper(match[1])
    if host in ("openreview.net", "www.openreview.net"):
        identifier = parse_qs(parsed.query).get("id", [""])[0]
        if path in ("/forum", "/pdf") and re.fullmatch(r"[\w-]+", identifier):
            return Paper(id="openreview:" + identifier, title=identifier, sources=["openreview"],
                         url="https://openreview.net/forum?id=" + identifier,
                         pdf_url="https://openreview.net/pdf?id=" + identifier)
    if source.startswith("doi:"):
        doi = source[4:]
        if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
            raise PaperError("DOI inválido.")
        return Paper(id=source, title=doi, doi=doi, url="https://doi.org/" + quote(doi, safe="/"), sources=["doi"])
    if parsed.scheme in ("https", "http"):
        public_url(source)
        return Paper(id="url:" + hashlib.sha256(source.encode()).hexdigest()[:16], title=Path(path).stem or host,
                     url=source, pdf_url=source if path.lower().endswith(".pdf") else None, sources=[host])
    local = Path(source).expanduser()
    if local.is_file():
        return Paper(id="local:" + hashlib.sha256(str(local.resolve()).encode()).hexdigest()[:16],
                     title=local.stem, url=str(local.resolve()), sources=["local"])
    raise PaperError("Origem desconhecida; forneça link, arquivo PDF ou ID salvo.")


class PdfLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.links, self.title = [], [], None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "meta":
            name = data.get("name", data.get("property", "")).lower()
            if name == "citation_pdf_url" and data.get("content"):
                self.meta.append(data["content"])
            if name in ("citation_title", "og:title"):
                self.title = data.get("content")
        if tag == "a" and data.get("href"):
            link = data["href"]
            if re.search(r"\.pdf(?:[?#]|$)|/stamp/stamp\.jsp", link, re.I):
                self.links.append(link)
        if tag in ("iframe", "embed") and data.get("src"):
            if ".pdf" in data["src"].lower():
                self.links.append(data["src"])


def validate_pdf(data):
    if not data or b"%PDF-" not in data[:1024]:
        raise PaperError("A fonte não retornou um PDF válido; pode exigir login. Forneça o PDF local.")
    return data


def fetch_openreview_pdf(paper, transport):
    try:
        data, final, _ = transport.get(paper.pdf_url, service="OpenReview PDF")
        validate_pdf(data)
        paper.pdf_url = final
        return data
    except PaperError:
        pass
    identifier = paper.id.removeprefix("openreview:")
    for base in ("https://api2.openreview.net", "https://api.openreview.net"):
        try:
            response = transport.json_get(base + "/notes", params={"id": identifier}, service="OpenReview")
            notes = response.get("notes", [])
            note = next((n for n in notes if isinstance(n, dict) and n.get("id") == identifier), None)
            if not note:
                continue
            content = note.get("content") or {}
            attachment = content.get("pdf")
            if isinstance(attachment, dict):
                attachment = attachment.get("value")
            if not isinstance(attachment, str) or not attachment:
                continue
            title = content.get("title")
            if isinstance(title, dict):
                title = title.get("value")
            if isinstance(title, str):
                paper.title = title
            url = urljoin(base, attachment)
            data, final, _ = transport.get(url, service="OpenReview attachment")
            validate_pdf(data)
            paper.pdf_url = final
            return data
        except (PaperError, AttributeError, TypeError):
            continue
    raise PaperError("OpenReview: PDF público indisponível; forneça um PDF local se tiver acesso.")


def fetch_pdf(paper, transport):
    if "local" in paper.sources:
        path = Path(paper.url)
        if path.stat().st_size > transport.max_bytes:
            raise PaperError("PDF local excede limite de tamanho.")
        return validate_pdf(path.read_bytes())
    if paper.id.startswith("openreview:"):
        return fetch_openreview_pdf(paper, transport)
    target = paper.pdf_url or paper.url
    if not target:
        raise PaperError("Paper sem link público; forneça um PDF local.")
    content, final, _ = transport.get(target, service="PDF")
    for _ in range(2):
        if b"%PDF-" in content[:1024]:
            paper.pdf_url = final
            return validate_pdf(content)
        parser = PdfLinks()
        parser.feed(content.decode("utf-8", errors="replace"))
        if parser.title:
            paper.title = parser.title
        candidates = list(dict.fromkeys(urljoin(final, x) for x in (parser.meta or parser.links)))
        if len(candidates) != 1:
            raise PaperError("Não há um único PDF público identificável. Forneça o link direto ou PDF local.")
        content, final, _ = transport.get(candidates[0], service="PDF")
    return validate_pdf(content)
