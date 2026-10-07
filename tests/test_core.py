import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper2md.models import Paper, deduplicate
from paper2md.store import Store
from paper2md.sources import direct_source


class CoreTests(unittest.TestCase):
    def test_arxiv_and_hf_preserve_version(self):
        for url in ["https://arxiv.org/abs/2402.09353v2", "https://huggingface.co/papers/2402.09353v2"]:
            paper = direct_source(url)
            self.assertEqual(paper.id, "arxiv:2402.09353v2")
            self.assertEqual(paper.pdf_url, "https://arxiv.org/pdf/2402.09353v2")

    def test_legacy_arxiv(self):
        p = direct_source("https://arxiv.org/pdf/hep-ex/0307015v1.pdf")
        self.assertEqual(p.id, "arxiv:hep-ex/0307015v1")

    def test_openreview_id(self):
        p = direct_source("https://openreview.net/forum?id=abc_123")
        self.assertEqual(p.pdf_url, "https://openreview.net/pdf?id=abc_123")

    def test_dedup_keeps_pdf_and_sources(self):
        a = Paper(id="openalex:W1", title="A Method", doi="10.1/abc", sources=["openalex"])
        b = Paper(id="arxiv:2401.12345", title="A method", pdf_url="https://arxiv.org/pdf/2401.12345", sources=["arxiv"])
        merged = deduplicate([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].pdf_url, b.pdf_url)
        self.assertEqual(set(merged[0].sources), {"openalex", "arxiv"})

    def test_selection_survives_restart_and_other_search(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            a = store.save_search({"query": "a"}, [Paper(id="arxiv:2401.12345", title="A")])
            b = store.save_search({"query": "b"}, [Paper(id="arxiv:2401.67890", title="B")])
            reopened = Store(Path(d))
            self.assertNotEqual(a["search_id"], b["search_id"])
            self.assertEqual(reopened.resolve(a["results"][0]["selection_id"]).title, "A")
            self.assertEqual(reopened.resolve(b["results"][0]["selection_id"]).title, "B")

    def test_bare_number_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                Store(Path(d)).resolve("1")


if __name__ == "__main__":
    unittest.main()
