import base64
import os
import re

from .transport import PaperError
from .sources import validate_pdf
from .pdfmeta import page_count


def parse_pages(value):
    if value is None:
        return None
    pages = set()
    for part in value.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", part)
        if not match:
            raise PaperError("Páginas inválidas; use 1,3-5 (numeração inicia em 1).")
        a, b = int(match[1]), int(match[2] or match[1])
        if a < 1 or b < a or b > 10000:
            raise PaperError("Intervalo de páginas inválido (1 a 10000).")
        pages.update(range(a - 1, b))
    return sorted(pages)


ANNOTATION_FORMAT = {"type": "json_schema", "json_schema": {
    "name": "figure_description", "strict": True, "schema": {
        "type": "object", "properties": {
            "image_type": {"type": "string", "description": "Tipo da figura: gráfico, diagrama, fotografia etc."},
            "description": {"type": "string", "description": "Descreva em português o conteúdo visível da figura, eixos e relações. Não invente valores, tendências ou detalhes ilegíveis. Seja fiel à imagem."}},
        "required": ["image_type", "description"], "additionalProperties": False}}}


class MistralOCR:
    def __init__(self, transport, key=None):
        self.transport = transport
        self.key = key if key is not None else os.getenv("MISTRAL_API_KEY")

    def process(self, pdf, model="mistral-ocr-latest", pages=None, describe_images=True, images=True):
        if not self.key:
            raise PaperError("Defina MISTRAL_API_KEY para converter o PDF.")
        validate_pdf(pdf)
        total_pages = page_count(pdf)
        if pages is not None and (not pages or any(type(i) is not int or not 0 <= i < total_pages for i in pages)):
            raise PaperError(f"Seleção inválida: PDF tem {total_pages} páginas. Nenhuma chamada OCR realizada.")
        payload = {"model": model, "document": {"type": "document_url",
            "document_url": "data:application/pdf;base64," + base64.b64encode(pdf).decode()},
            "include_image_base64": images}
        if pages is not None:
            payload["pages"] = pages
        if describe_images:
            payload["bbox_annotation_format"] = ANNOTATION_FORMAT
        response = self.transport.post_json("https://api.mistral.ai/v1/ocr", payload, self.key)
        if not isinstance(response, dict) or not isinstance(response.get("pages"), list) or not response["pages"]:
            raise PaperError("Mistral OCR retornou páginas ausentes ou vazias.")
        indices = set()
        for page in response["pages"]:
            if not isinstance(page, dict) or not isinstance(page.get("markdown"), str) or not isinstance(page.get("index"), int):
                raise PaperError("Mistral OCR retornou página malformada.")
            if page["index"] in indices or page["index"] < 0:
                raise PaperError("Mistral OCR retornou índices de páginas inválidos.")
            indices.add(page["index"])
            if not isinstance(page.get("images", []), list):
                raise PaperError("Mistral OCR retornou imagens malformadas.")
        expected = set(pages) if pages is not None else set(range(total_pages))
        if indices != expected:
            raise PaperError("Mistral OCR não retornou todas as páginas solicitadas; verifique o intervalo.")
        response["pages"].sort(key=lambda p: p["index"])
        response["local_validation"] = {"pdf_page_count": total_pages, "returned_page_indices": sorted(indices), "all_requested_pages_present": True}
        return response
