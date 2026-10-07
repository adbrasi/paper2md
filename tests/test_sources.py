import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import httpx
from paper2md.sources import direct_source, fetch_pdf
from paper2md.transport import Transport, PaperError


class SourceTests(unittest.TestCase):
    def test_generic_page_resolves_citation_pdf(self):
        def handler(request):
            if request.url.path == "/paper":
                return httpx.Response(200, text='<meta name="citation_pdf_url" content="/paper.pdf"><meta name="citation_title" content="Study">')
            return httpx.Response(200, content=b"%PDF-example")
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            p = direct_source("https://example.org/paper")
            self.assertEqual(fetch_pdf(p, Transport(c)), b"%PDF-example")
            self.assertEqual(p.title, "Study")

    def test_ambiguous_page_doesnt_select_arbitrary_pdf(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<a href="a.pdf">a</a><a href="b.pdf">b</a>'))) as c:
            with self.assertRaises(PaperError):
                fetch_pdf(direct_source("https://example.org/paper"), Transport(c))

    def test_openreview_attachment_api_fallback(self):
        def handler(request):
            if request.url.path == "/pdf":
                return httpx.Response(404)
            if request.url.path == "/notes":
                return httpx.Response(200, json={"notes": [{"id": "abc", "content": {
                    "title": {"value": "Review Paper"}, "pdf": {"value": "/attachment?id=abc&name=pdf"}}}]})
            return httpx.Response(200, content=b"%PDF-example")
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            p = direct_source("https://openreview.net/forum?id=abc")
            self.assertEqual(fetch_pdf(p, Transport(c)), b"%PDF-example")
            self.assertEqual(p.title, "Review Paper")

    def test_credentials_in_url_rejected(self):
        with self.assertRaises(PaperError):
            direct_source("https://user:secret@example.org/paper.pdf")
