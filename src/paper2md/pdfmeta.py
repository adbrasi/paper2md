import pymupdf

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


def extract_local(pdf, pages=None):
    """Free offline text extraction, shaped like a Mistral OCR response so export stays shared."""
    total = page_count(pdf)
    if pages is not None and any(not 0 <= i < total for i in pages):
        raise PaperError(f"Seleção inválida: PDF tem {total} páginas.")
    indices = pages if pages is not None else range(total)
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        extracted = [{"index": i, "markdown": document[i].get_text(), "images": []} for i in indices]
    if not any(page["markdown"].strip() for page in extracted):
        raise PaperError("PDF sem camada de texto (provavelmente escaneado); use --engine mistral.")
    return {"model": "pymupdf-" + pymupdf.VersionBind, "pages": extracted,
            "local_validation": {"pdf_page_count": total, "returned_page_indices": list(indices), "all_requested_pages_present": True}}
