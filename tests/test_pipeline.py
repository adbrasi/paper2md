import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx
from paper2md.export import render_document, markdown_to_text
from paper2md.service import PaperService, Options
from paper2md.store import Store
from paper2md.transport import Transport
from pdf_fixture import make_pdf

PDF = make_pdf()


def ocr_response():
    return {"model": "actual-model", "pages": [{"index": 0,
        "markdown": "# Study\n\n![figure](../../escape.png)\n\nA **result**.",
        "images": [{"id": "../../escape.png", "image_base64": "data:image/png;base64," + base64.b64encode(b"png").decode(),
            "image_annotation": json.dumps({"image_type": "chart", "description": "Comparação de métodos."})}]}]}


class PipelineTests(unittest.TestCase):
    def test_assets_cannot_escape_and_annotations_are_inserted(self):
        with tempfile.TemporaryDirectory() as d:
            markdown, warnings = render_document(ocr_response(), Path(d), images=True)
            self.assertIn("Comparação de métodos.", markdown)
            self.assertIn("Descrição gerada por IA", markdown)
            self.assertNotIn("../../escape.png", markdown)
            self.assertTrue((Path(d) / "assets" / "p1-1.png").exists())

    def test_no_images_keeps_description(self):
        with tempfile.TemporaryDirectory() as d:
            markdown, _ = render_document(ocr_response(), Path(d), images=False)
            self.assertIn("Comparação de métodos.", markdown)
            self.assertNotIn("![", markdown)
            self.assertFalse((Path(d) / "assets").exists())

    def test_txt_preserves_code_links_and_equations(self):
        text = markdown_to_text("# Title\n\n**bold** [source](https://example.org)\n\n```py\nx = 1\n```\n\n$x^2$")
        self.assertIn("bold", text)
        self.assertIn("https://example.org", text)
        self.assertIn("x = 1", text)
        self.assertIn("$x^2$", text)
        self.assertNotIn("**", text)

    def test_cached_get_and_read_dont_repeat_ocr(self):
        calls = []
        def handler(request):
            calls.append(request.method)
            return httpx.Response(200, content=PDF) if request.method == "GET" else httpx.Response(200, json=ocr_response())
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            service = PaperService(Store(Path(d) / "state"), Transport(c), key="test")
            options = Options(output=Path(d) / "out")
            first = service.get_papers(["arxiv:2601.12345"], options)
            self.assertEqual(first["items"][0]["status"], "ok")
            second = service.get_papers(["arxiv:2601.12345"], options)
            self.assertEqual(second["items"][0]["status"], "cached")
            content = service.read_paper("arxiv:2601.12345", options)
            self.assertIn("Comparação de métodos.", content["markdown"])
            self.assertEqual(calls.count("POST"), 1)

    def test_batch_partial_failure_keeps_success(self):
        def handler(request):
            if "67890" in str(request.url):
                return httpx.Response(403)
            return httpx.Response(200, content=PDF) if request.method == "GET" else httpx.Response(200, json=ocr_response())
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            service = PaperService(Store(Path(d) / "state"), Transport(c), key="test")
            result = service.get_papers(["arxiv:2601.12345", "arxiv:2601.67890"], Options(output=Path(d) / "out"))
            self.assertFalse(result["ok"])
            self.assertEqual([i["status"] for i in result["items"]], ["ok", "error"])
            self.assertTrue(Path(result["items"][0]["files"]["markdown"]).exists())

    def test_existing_output_rejected_before_paid_call(self):
        calls = []
        def handler(request):
            calls.append(request.method)
            return httpx.Response(200, content=PDF) if request.method == "GET" else httpx.Response(200, json=ocr_response())
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            store = Store(Path(d) / "state")
            service = PaperService(store, Transport(c), key="test")
            options = Options(output=Path(d) / "out")
            result = service.get_papers(["arxiv:2601.12345"], options)
            with store.connect() as db:
                db.execute("DELETE FROM bundles")
            again = service.get_papers(["arxiv:2601.12345"], options)
            self.assertEqual(again["items"][0]["status"], "error")
            self.assertEqual(calls.count("POST"), 1)

    def test_partial_page_cache_is_not_full_read(self):
        calls = []
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, content=PDF)
            payload = json.loads(request.content)
            calls.append(payload)
            return httpx.Response(200, json=ocr_response())
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            service = PaperService(Store(Path(d) / "state"), Transport(c), key="test")
            service.get_papers(["arxiv:2601.12345"], Options(output=Path(d) / "out", pages=[0]))
            service.read_paper("arxiv:2601.12345", Options(output=Path(d) / "out"))
            self.assertEqual(len(calls), 2)
            self.assertNotIn("pages", calls[1])
