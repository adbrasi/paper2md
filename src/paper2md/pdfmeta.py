import re

import pymupdf
import pymupdf4llm

from .sources import validate_pdf
from .transport import PaperError


def page_count(pdf):
    validate_pdf(pdf)
    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            if document.needs_pass:
                raise PaperError("PDF protegido por senha; forneça uma cópia desbloqueada.")
            count = document.page_count
            if not 1 <= count <= 10000:
                raise PaperError("PDF deve ter de 1 a 10000 páginas.")
            return count
    except PaperError:
        raise
    except (RuntimeError, ValueError):
        raise PaperError("Não foi possível ler a estrutura do PDF; arquivo inválido ou danificado.") from None


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # PDF text can carry control chars that make tools treat it as binary


def check_pages(pages, total):
    if pages is not None and (not pages or any(type(i) is not int or not 0 <= i < total for i in pages)):
        raise PaperError(f"Seleção inválida: PDF tem {total} páginas. Nenhuma conversão realizada.")
    return list(pages) if pages is not None else list(range(total))


def select_pages(pdf, pages):
    """Return a PDF containing only the given zero-based pages, for engines without a page parameter."""
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        document.select(pages)
        return document.tobytes(garbage=3, deflate=True)


def extract_local(pdf, pages=None):
    """Free offline extraction (layout analysis, Markdown tables), shaped like a Mistral OCR response."""
    total = page_count(pdf)
    indices = check_pages(pages, total)
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        chunks = pymupdf4llm.to_markdown(document, pages=indices, page_chunks=True, show_progress=False)
    extracted = [{"index": chunk["metadata"]["page_number"] - 1, "markdown": CONTROL.sub("", chunk["text"]), "images": []}
                 for chunk in chunks]
    if [page["index"] for page in extracted] != indices:
        raise PaperError("Extração local não retornou todas as páginas solicitadas.")
    if not any(page["markdown"].strip() for page in extracted):
        raise PaperError("PDF sem camada de texto (provavelmente escaneado); extração local indisponível.")
    return {"model": "pymupdf4llm-" + pymupdf4llm.__version__, "pages": extracted,
            "local_validation": {"pdf_page_count": total, "returned_page_indices": indices, "all_requested_pages_present": True}}
