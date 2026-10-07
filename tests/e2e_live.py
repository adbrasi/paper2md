"""Live end-to-end check against the real APIs, driven exactly as an agent would: subprocess + JSON.

Run: python -X utf8 tests/e2e_live.py [--engine local|mistral]
Writes e2e-report.json in the working directory. Uses an isolated state/output directory.
"""
import argparse
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time


def run(env, *args):
    started = time.time()
    result = subprocess.run([sys.executable, "-m", "paper2md", *args, "--json"], capture_output=True,
                            text=True, encoding="utf-8", env=env)
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return {"args": list(args), "exit": result.returncode, "seconds": round(time.time() - started, 1),
            "stderr": result.stderr.strip()[-600:]}, payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("local", "mistral"), default="local")
    engine = parser.parse_args().engine
    work = Path(tempfile.mkdtemp(prefix="paper2md-e2e-"))
    env = {**os.environ, "PAPER2MD_HOME": str(work / "state"), "PYTHONUTF8": "1"}
    out = str(work / "papers")
    steps, checks = [], {}

    step, found = run(env, "search", "parameter-efficient fine-tuning diffusion models",
                      "LoRA DoRA text-to-image", "--limit", "6")
    steps.append(step)
    results = found.get("results", [])
    checks["search_has_results"] = step["exit"] == 0 and len(results) >= 3
    checks["search_both_providers"] = set(found.get("providers", [])) == {"OpenAlex", "arXiv"}
    checks["search_respects_window"] = all(r["published"] >= found["filters"]["since"] for r in results)

    chosen = [r["selection_id"] for r in results if r["id"].startswith("arxiv:")][:2]
    step, acquired = run(env, "get", *chosen, "-o", out, "--engine", engine)
    steps.append(step)
    items = acquired.get("items", [])
    checks["get_all_ok"] = len(chosen) == 2 and step["exit"] == 0 and all(i["status"] == "ok" for i in items)
    checks["get_files_exist"] = all(Path(i["files"][k]).stat().st_size > 1000 for i in items if "files" in i
                                    for k in ("pdf", "markdown"))

    step, again = run(env, "get", chosen[0], "-o", out, "--engine", engine) if chosen else ({"exit": -1}, {})
    steps.append(step)
    checks["get_repeat_is_cached"] = [i["status"] for i in again.get("items", [])] == ["cached"]

    step, document = run(env, "read", items[0]["id"], "-o", out, "--engine", engine) if items else ({"exit": -1}, {})
    steps.append(step)
    manifest = document.get("manifest", {})
    pages = (manifest.get("page_validation") or {})
    checks["read_full_markdown"] = step["exit"] == 0 and len(document.get("markdown", "")) > 5000
    checks["read_all_pages"] = (not manifest.get("partial")) and pages.get("all_requested_pages_present") is True \
        and document["markdown"].count("<!-- Página ") == pages.get("pdf_page_count")

    step, direct = run(env, "get", "https://huggingface.co/papers/2402.09353", "-o", out, "--engine", engine, "--pages", "1")
    steps.append(step)
    checks["get_huggingface_link"] = step["exit"] == 0 and direct["items"][0]["status"] in ("ok", "cached")

    report = {"engine": engine, "workdir": str(work), "passed": all(checks.values()), "checks": checks,
              "selected": [{"id": i.get("id"), "files": i.get("files"), "warnings": i.get("warnings")} for i in items],
              "read_preview": document.get("markdown", "")[:800], "manifest": manifest, "steps": steps}
    Path("e2e-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    print("Report: e2e-report.json | files: " + str(work))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
