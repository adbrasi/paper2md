from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import httpx
from paper2md.cli import main
from paper2md.models import Paper
from paper2md.store import Store
from paper2md.transport import Transport
from pdf_fixture import make_pdf
from test_api import ATOM


class CLITests(unittest.TestCase):
    def test_search_choose_get_read_json_end_to_end(self):
        pdf = make_pdf()
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path == "/v1/chat/completions":
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                    "technical_query": "low rank adaptation", "arxiv_queries": ["low rank adaptation"]})}}]})
            if request.url.host == "api.openalex.org":
                return httpx.Response(200, json={"results": []})
            if request.url.path == "/api/query":
                return httpx.Response(200, text=ATOM)
            if request.url.path == "/v1/ocr":
                return httpx.Response(200, json={"model": "test", "pages": [{"index": 0, "markdown": "# Full paper\n\nA result.", "images": []}]})
            return httpx.Response(200, content=pdf)
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as c:
            with patch.dict(os.environ, {"PAPER2MD_HOME": str(Path(d) / "state"), "MISTRAL_API_KEY": "test"}), patch("paper2md.cli.Transport", lambda: Transport(c)):
                def command(*args):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(list(args) + ["--json"])
                    return code, json.loads(stdout.getvalue()), stderr.getvalue()
                code, found, _ = command("search", "adaptação com LoRA", "--since", "2025-01-01")
                self.assertEqual(code, 0)
                selected = found["results"][0]["selection_id"]
                code, acquired, progress = command("get", selected, "-o", str(Path(d) / "out"))
                self.assertEqual(code, 0)
                self.assertIn("Obtendo", progress)
                code, document, _ = command("read", selected, "-o", str(Path(d) / "out"))
                self.assertEqual(code, 0)
                self.assertIn("# Full paper", document["markdown"])
                self.assertTrue(document["manifest"]["page_validation"]["all_requested_pages_present"])
                self.assertEqual(sum(r.url.path == "/v1/ocr" for r in requests), 1)

    def test_invalid_selection_produces_json_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"PAPER2MD_HOME": d}):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["get", "s_missing:1", "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stdout.getvalue())["items"][0]["status"], "error")

    def test_concurrent_searches_have_independent_persisted_ids(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            def save(index):
                return store.save_search({"query": str(index)}, [Paper(id=f"openalex:W{index}", title=str(index))])
            with ThreadPoolExecutor(max_workers=4) as pool:
                searches = list(pool.map(save, range(8)))
            self.assertEqual(len({s["search_id"] for s in searches}), 8)
            for i, search in enumerate(searches):
                self.assertEqual(store.resolve(search["results"][0]["selection_id"]).title, str(i))
