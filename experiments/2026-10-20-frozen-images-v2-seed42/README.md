# Post hoc frozen-catalog image diagnostic

This separate assignment-only diagnostic was selected after the first primary
image comparison showed substantial disagreement. It uses the original completed
LLM arm's final 11 active cluster definitions, including empty clusters, for both
backends. The catalog is verified directly against the immutable archived SQLite
state. It is a baseline-derived catalog, not an independent or preregistered one.

Both arms process the same 100 pinned images in order, with K=8 plus Other, stable
catalog IDs, first matching page wins, and Other only after all pages reject.
Sol gpt-6.1-sol uses high reasoning; native Decisions uses gpt-6-luna. No management
calls occur. Accepted typed assignment refusals map to Other and stop paging;
each output/progress row preserves its refused flag. Raw refusal attempts and
accepted refusal outcomes are counted separately, including charged failed calls.
This control isolates assignment under one shared catalog; it cannot
replace the primary independent evolving-system experiment. Its costs and timing
must remain separate from primary results.

Both output JSON documents are original bytes. Request/progress/process files
are gzip-compressed with zero timestamps and exact decompressed bytes. Every
attempt is retained. The verifier reconstructs every request from pinned image
bytes and exact catalog pages, skips failed attempts without advancing, decodes
successful choices, and binds their ordered assignments to progress and outputs.
All 100 PNG hashes, original JSONL bytes, image-byte input fingerprint, catalog,
embedded source files, and executable hash are checked against fixed evidence.
At creation each arm's recorded Git commit is independently checked for the same
embedded source bytes; later documentation-only commits are allowed. The preserved
source-commit verification record distinguishes these commits from runtime source.
Original image paths inside inputs are preserved; verification never opens them.

independent-results.json enumerates every unordered pair and uses rational ARI.
Primary ARI treats each Other point as a singleton. Direct ID agreement counts
two Other assignments as equal; shared-Other sensitivity is also reported.
Dataset labels are evaluation-only and never enter reconstructed model requests.
The attempt ledger reprices all reported raw input/output/cache tokens using
Decimal standard-tier prices. Known recorded costs are not invoices. Failed
attempts without usage have unknown cost; inspect unknown_usage_calls and
cost_complete. The ledger verifies observed records, not continuity after disk
or journal I/O failure. Wall seconds are each fresh control's measured processing
loop, including calls/retries; inputs/source validation and launch waiting are
excluded. Collected units retain unknown terminal systemd Result.

Code is BSD-3-Clause. The copied inputs, prices, and upstream notices are pinned
byte-for-byte to the first archive; CLINC150 remains CC BY 3.0 and Fashion-MNIST
remains MIT. source/ preserves the exact embedded files. The binary itself is
identified by SHA-256 rather than included. operational/ contains only offline
orchestration and verification helpers, not replacement clustering logic.

Verify SHA256SUMS and run the archived Python helper with --verify-only pointing
at this directory. Verification works after relocation, requires only Python's
standard library, and makes no API calls. Publish links to the immutable commit
containing this directory; runtime and evidence commits can differ.
