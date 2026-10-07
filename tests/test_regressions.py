import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import httpx
from paper2md.mistral import MistralOCR
from paper2md.service import PaperService, Options
from paper2md.search import Searcher
from paper2md.store import Store
from paper2md.transport import Transport, PaperError
from test_api import ATOM
from pdf_fixture import make_pdf


class RegressionTests(unittest.TestCase):
    def test_overwrite_never_reuses_a_different_pdf_as_cache(self):
        a, b = make_pdf(label="A"), make_pdf(label="B")
        state = {"pdf": a, "posts": 0}
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, content=state["pdf"])
            state["posts"] += 1
            return httpx.Response(200, json={"model": "test", "pages": [{"index": 0, "markdown": "A" if state["pdf"] == a else "B", "images": []}]})
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            service = PaperService(Store(Path(d) / "state"), Transport(c), key="test")
            options = Options(output=Path(d) / "out", force=True)
            service.get_papers(["arxiv:2601.12345"], options)
            state["pdf"] = b
            service.get_papers(["arxiv:2601.12345"], options)
            state["pdf"] = a
            result = service.get_papers(["arxiv:2601.12345"], options)
            self.assertTrue(result["ok"])
            self.assertEqual(Path(result["items"][0]["files"]["pdf"]).read_bytes(), a)
            self.assertIn("A", Path(result["items"][0]["files"]["markdown"]).read_text())

    def test_malformed_openalex_does_not_abort_arxiv_fallback(self):
        for records in ([None], [{"id": "https://openalex.org/W123", "primary_location": "invalid"}],
                        [{"id": "https://openalex.org/W123", "authorships": [None]}]):
            def handler(request):
                if request.url.host == "api.openalex.org":
                    return httpx.Response(200, json={"results": records})
                return httpx.Response(200, text=ATOM)
            with self.subTest(records=records), tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
                result = Searcher(Store(Path(d)), Transport(c), rate_limit=False).search_papers("LoRA", since="2025-01-01")
                self.assertEqual(result["results"][0]["id"], "arxiv:2601.12345v2")
                self.assertTrue(any("OpenAlex" in w for w in result["warnings"]))

    def test_full_ocr_rejects_missing_middle_page(self):
        response = {"model": "test", "pages": [{"index": i, "markdown": str(i), "images": []} for i in (0, 2)]}
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))) as c:
            with self.assertRaises(PaperError):
                MistralOCR(Transport(c), "test").process(make_pdf(3))

    def test_full_ocr_rejects_missing_last_page(self):
        response = {"pages": [{"index": 0, "markdown": "page one", "images": []}]}
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))) as c:
            with self.assertRaises(PaperError):
                MistralOCR(Transport(c), "test").process(make_pdf(2))
