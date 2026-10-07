from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import httpx
from paper2md.service import PaperService, Options
from paper2md.store import Store
from paper2md.transport import Transport
from pdf_fixture import make_pdf

PDF = make_pdf(pages=7, label="engine")
# Shape observed from the live API: one "## Page N" heading per page, escaped placeholder tags,
# and the figure-grid repetition loop seen on a real paper.
NANONETS_MARKDOWN = "\n\n---\n\n\n".join(
    f"## Page {n}\n\nText of page {n}.\n\n&lt;page_number&gt;{n}&lt;/page_number&gt;" for n in range(1, 8)
).replace("Text of page 3.", "Text of page 3.\n" + "\n".join(" " * 600 + "&lt;img&gt;" for _ in range(5000)))


def service_for(handler, root, mistral="m-key", nanonets="n-key"):
    service = PaperService(Store(Path(root) / "state"), Transport(httpx.Client(transport=httpx.MockTransport(handler))),
                           key=mistral, nanonets_key=nanonets)
    service.nanonets.poll_seconds = 0
    return service


class EngineChainTests(unittest.TestCase):
    def test_mistral_quota_error_falls_back_to_nanonets_async(self):
        seen = []
        def handler(request):
            seen.append(f"{request.method} {request.url.host}{request.url.path}")
            if request.url.host == "api.mistral.ai":
                return httpx.Response(429, json={"message": "Rate limit exceeded"})
            if request.url.path.endswith("/extract/async"):
                return httpx.Response(202, json={"record_id": "42", "status": "processing"})
            if request.url.path.endswith("/results/42"):
                done = sum("/results/42" in s for s in seen) > 1
                return httpx.Response(200, json={"status": "completed" if done else "processing", "record_id": "42",
                    "result": {"markdown": {"content": NANONETS_MARKDOWN}} if done else None})
            return httpx.Response(200, content=PDF)
        with tempfile.TemporaryDirectory() as d:
            item = service_for(handler, d).get_papers(["arxiv:2601.12345"], Options(output=Path(d) / "out"))["items"][0]
            self.assertEqual((item["status"], item["engine"]), ("ok", "nanonets"))
            self.assertTrue(any("mistral" in w and "429" in w for w in item["warnings"]))
            markdown = Path(item["files"]["markdown"]).read_text(encoding="utf-8")
            self.assertEqual(markdown.count("<!-- Página "), 7)
            self.assertLess(len(markdown), 5000)
            self.assertNotIn("page_number", markdown)

    def test_both_apis_failing_fall_back_to_local_and_cache_is_reused(self):
        posts = []
        def handler(request):
            if request.method == "POST":
                posts.append(request.url.host)
                return httpx.Response(402 if "mistral" in request.url.host else 401, json={"detail": "no credits"})
            return httpx.Response(200, content=PDF)
        with tempfile.TemporaryDirectory() as d:
            service = service_for(handler, d)
            first = service.get_papers(["arxiv:2601.12345"], Options(output=Path(d) / "out"))["items"][0]
            self.assertEqual((first["status"], first["engine"]), ("ok", "local"))
            self.assertIn("engine page 7", Path(first["files"]["markdown"]).read_text(encoding="utf-8"))
            again = service.get_papers(["arxiv:2601.12345"], Options(output=Path(d) / "out"))["items"][0]
            self.assertEqual((again["status"], again["engine"]), ("cached", "local"))
            self.assertEqual(len(posts), 2)

    def test_nanonets_missing_page_is_rejected_not_accepted(self):
        def handler(request):
            if request.url.host == "extraction-api.nanonets.com":
                return httpx.Response(200, json={"status": "completed",
                    "result": {"markdown": {"content": "## Page 1\n\nonly one"}}})
            return httpx.Response(200, content=make_pdf(pages=2))
        with tempfile.TemporaryDirectory() as d:
            result = service_for(handler, d, mistral="").get_papers(["arxiv:2601.12345"], Options(output=Path(d) / "out", engine="nanonets"))
            self.assertEqual(result["items"][0]["status"], "error")
            self.assertIn("todas as páginas", result["items"][0]["error"])


if __name__ == "__main__":
    unittest.main()
