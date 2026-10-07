import html
import os
import re
import time

from .pdfmeta import CONTROL, check_pages, page_count, select_pages
from .transport import PaperError

API = "https://extraction-api.nanonets.com/api/v1/extract"
SYNC_MAX_PAGES = 5  # the sync endpoint rejects longer documents
PAGE_HEADING = re.compile(r"(?m)^## Page (\d+)[ \t]*$")


def clean_page(markdown):
    # The OCR model emits escaped placeholder tags and can loop on figure grids (thousands of
    # indented "<img>" lines); collapse that noise so a single page cannot flood the agent's context.
    markdown = re.sub(r"&lt;page_number&gt;.*?&lt;/page_number&gt;", "", markdown)
    markdown = markdown.replace("&lt;img&gt;", "[Figura]")
    markdown = re.sub(r"[ \t]{3,}", " ", markdown)
    lines = []
    for line in markdown.split("\n"):
        if line.strip() and lines and line.strip() == lines[-1].strip():
            continue
        lines.append(line)
    return CONTROL.sub("", "\n".join(lines).strip().removesuffix("---").strip())


class NanonetsOCR:
    def __init__(self, transport, key=None, poll_seconds=5, timeout=1200):
        self.transport = transport
        self.key = key if key is not None else os.getenv("NANONETS_API_KEY")
        self.poll_seconds, self.timeout = poll_seconds, timeout

    def process(self, pdf, pages=None):
        if not self.key:
            raise PaperError("Defina NANONETS_API_KEY para usar a Nanonets.")
        total = page_count(pdf)
        indices = check_pages(pages, total)
        document = pdf if pages is None else select_pages(pdf, indices)
        form = {"output_format": "markdown"}
        files = {"file": ("paper.pdf", document, "application/pdf")}
        if len(indices) <= SYNC_MAX_PAGES:
            result = self.transport.post_form(API + "/sync", form, files, self.key, service="Nanonets")
        else:
            result = self.transport.post_form(API + "/async", form, files, self.key, service="Nanonets")
            result = self.wait(result)
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise PaperError("Nanonets: extração não concluída.")
        try:
            content = result["result"]["markdown"]["content"]
        except (KeyError, TypeError):
            raise PaperError("Nanonets: resposta sem Markdown.") from None
        parts = PAGE_HEADING.split(content if isinstance(content, str) else "")
        numbers, bodies = [int(n) for n in parts[1::2]], parts[2::2]
        if numbers != list(range(1, len(indices) + 1)):
            raise PaperError("Nanonets não retornou todas as páginas solicitadas.")
        model = (result.get("request_config") or {}).get("model_type") or "nanonets"
        return {"model": model, "record_id": result.get("record_id"),
                "pages": [{"index": i, "markdown": html.unescape(clean_page(body)), "images": []} for i, body in zip(indices, bodies)],
                "local_validation": {"pdf_page_count": total, "returned_page_indices": indices, "all_requested_pages_present": True}}

    def wait(self, queued):
        record = queued.get("record_id") if isinstance(queued, dict) else None
        if not record or not re.fullmatch(r"[\w-]+", str(record)):
            raise PaperError("Nanonets: job assíncrono sem record_id.")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(self.poll_seconds)
            result = self.transport.json_get(f"{API}/results/{record}", headers={"Authorization": "Bearer " + self.key},
                                             service="Nanonets")
            status = result.get("status") if isinstance(result, dict) else None
            if status == "completed":
                return result
            if status != "processing":
                raise PaperError(f"Nanonets: job {record} falhou.")
        raise PaperError(f"Nanonets: job {record} excedeu {self.timeout // 60} min.")
