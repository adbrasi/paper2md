# paper2md execution ledger

Plan: docs/superpowers/plans/2026-10-07-paper2md.md
User approved creation and requested image descriptions by default.
Ruling: work directly in supplied empty project workspace; Git metadata is read-only, so commits/worktree scripts cannot operate. Source files and tests remain reviewable.
Interfaces: store owns persisted Paper records; search writes them, service resolves them. Export consumes only validated OCR responses.

Task 1 complete: 6 core tests passed. Task 2 complete: 14 tests passed after correcting a mock response that returned one page for a three-page request. Task 3 complete: 21 tests passed, CLI/source/README written.
Task 4 live test blocked: Python network connections fail with WinError 10013; pip download fails identically. No API credential used or saved, no OCR charge triggered.
Ruling: use preinstalled dependencies to validate offline install instead of downloading dependencies. Live API integration remains unverified, to be documented prominently.

Independent review: three Important findings confirmed with failing regression tests: overwritten bundles referenced by stale cache rows, malformed OpenAlex records aborting fallback, and missing OCR pages accepted as complete. All fixed in one review pass, suite 29/29 green.
Ruling: add PyMuPDF for reliable pre-call PDF page counts, including detection of missing last page. This adds a native dependency but avoids claiming completeness from OCR metadata alone.
Ruling: include paper identity in target hash, validate cached manifest/PDF hash and invalidate all old records for an overwritten path. Preserves correct cache identity after source changes.

Final suite: 32/32 tests passed in virtual environment; concurrent search snapshots and public CLI JSON search/get/read verified with simulated HTTP. Installation, --help, --version and wheel build verified offline. No deferred reviewer findings. Live test remains blocked by environment, disclosed in docs/validation.md.
