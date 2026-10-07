import json
import tempfile
import unittest
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper2md.transport import Transport, PaperError
from paper2md.store import Store
from paper2md.search import Searcher
from paper2md.mistral import MistralOCR, parse_pages
from pdf_fixture import make_pdf


ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2601.12345v2</id><title>Recent low rank adaptation</title>
<published>2026-01-01T00:00:00Z</published><updated>2026-02-01T00:00:00Z</updated>
<summary>Adaptation with small memory.</summary><author><name>Ada</name></author>
<link href="https://arxiv.org/pdf/2601.12345v2" type="application/pdf"/></entry></feed>'''


class APITests(unittest.TestCase):
    def test_partial_provider_failure_retains_arxiv_and_warning(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.host == "api.openalex.org":
                return httpx.Response(403)
            return httpx.Response(200, text=ATOM)
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as client:
            searcher = Searcher(Store(Path(d)), Transport(client), rate_limit=False)
            result = searcher.search_papers("low rank", since="2025-01-01", limit=10)
            self.assertEqual(result["results"][0]["id"], "arxiv:2601.12345v2")
            self.assertTrue(any("OpenAlex" in x for x in result["warnings"]))
            self.assertIn("search.semantic", seen[0].url.params)
            self.assertIn("submittedDate", seen[1].url.params["search_query"])

    def test_both_providers_fail_is_error(self):
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as c:
            with self.assertRaises(PaperError):
                Searcher(Store(Path(d)), Transport(c), rate_limit=False).search_papers("query")

    def test_multiple_queries_hit_both_providers_and_fuse(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.host == "api.openalex.org":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, text=ATOM)
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            result = Searcher(Store(Path(d)), Transport(c), rate_limit=False).search_papers(["LoRA", "DoRA"], since="2025-01-01")
            self.assertEqual(result["queries"], ["LoRA", "DoRA"])
            self.assertEqual(len(seen), 4)
            self.assertEqual([r["id"] for r in result["results"]], ["arxiv:2601.12345v2"])

    def test_openalex_metadata_and_date_filter(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.host == "api.openalex.org":
                return httpx.Response(200, json={"results": [{"id": "https://openalex.org/W123", "title": "Recent method",
                    "publication_date": "2026-01-01", "doi": "https://doi.org/10.1234/a",
                    "primary_location": {"source": {"display_name": "ICLR"}, "pdf_url": "https://example.org/a.pdf"},
                    "authorships": [{"author": {"display_name": "Ada"}}],
                    "abstract_inverted_index": {"A": [0], "method": [1]}, "cited_by_count": 2}]})
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"/>')
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            result = Searcher(Store(Path(d)), Transport(c), rate_limit=False).search_papers("method", since="2025-01-01")
            self.assertEqual(result["results"][0]["abstract"], "A method")
            self.assertEqual(result["results"][0]["venue"], "ICLR")
            # OpenAlex semantic search rejects date filters; only publication_year is accepted.
            self.assertEqual(f"publication_year:2025-{date.today().year}", seen[0].url.params["filter"])

    def test_ocr_annotations_are_default_and_pages_zero_based(self):
        seen = []
        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"pages": [{"index": i, "markdown": "# Paper", "images": []} for i in (0, 2, 3)], "model": "actual"})
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            response = MistralOCR(Transport(c), "test").process(make_pdf(4), pages=parse_pages("1,3-4"))
            self.assertIn("bbox_annotation_format", seen[0])
            self.assertTrue(seen[0]["include_image_base64"])
            self.assertEqual(seen[0]["pages"], [0, 2, 3])
            self.assertEqual(response["model"], "actual")

    def test_disable_annotations_and_reject_malformed_ocr(self):
        seen = []
        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"pages": []})
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            with self.assertRaises(PaperError):
                MistralOCR(Transport(c), "test").process(make_pdf(), describe_images=False)
            self.assertNotIn("bbox_annotation_format", seen[0])

    def test_invalid_pages(self):
        for value in ("0", "3-1", "a", "", "1,,2"):
            with self.assertRaises(ValueError):
                parse_pages(value)

    def test_download_rejects_oversized_body(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"a" * 20))) as c:
            with self.assertRaises(PaperError):
                Transport(c, max_bytes=10).get("https://example.org/file")
