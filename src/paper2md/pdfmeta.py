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
