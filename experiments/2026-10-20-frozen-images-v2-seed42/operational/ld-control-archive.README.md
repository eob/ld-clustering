# Offline frozen-catalog image-control archive

Helper: /tmp/ld-control-archive.py

Tests: /tmp/test_ld_control_archive.py

This helper makes no API calls, runs no clustering binary, and edits no source or
run artifact. Creation is only for both completed 100-image control streams.
It refuses live control processes, active systemd units, incomplete/failed outputs,
wrong source/catalog/input bytes, mixed journals, missing progress, or an existing
archive destination. Do not execute creation against the currently queued run.

After the control unit is terminal, root can run:

```sh
python3 /tmp/ld-control-archive.py \
  --repo /mnt/disks/data/ld-clustering \
  --run runs/frozen-images-v2-seed42 \
  --output experiments/2026-10-20-frozen-images-v2-seed42 \
  --service ld-clustering-frozen-images-v2-20261020.service
```

If systemd has already collected the unit, repeat with --collect. That records an
unknown terminal systemd Result, while still requiring complete outputs, exact
raw journal/progress replay, and no process with matching control output paths.
Use repeated --service for additional control supervisor units. Additional
credential-free operational provenance can be included with repeated
--operational PATH. Default binary is target/release/examples/frozen_catalog;
--binary can point at a saved byte-identical copy.

Read-only verification after relocation needs only Python's standard library:

```sh
python3 /tmp/ld-control-archive.py \
  --verify-only /absolute/path/to/2026-10-20-frozen-images-v2-seed42
```

The archive preserves exact output JSON bytes; raw journals/progress/process logs
are gzip-compressed with mtime zero and verified decompressed bytes. It copies the
first archive's pinned input tar, pricing and complete upstream notices. The
original first-cohort baseline SQLite state is retained as catalog-reference.sqlite.gz
and verified to contain exactly the preselected 11 active definitions, including
empty clusters. Catalog/source metadata, exact embedded Rust files, runtime/source
hashes, operational scripts/logs, every-attempt ledger, independent results,
manifest, and SHA256SUMS are included. Staging is atomically installed only after
relocated verification succeeds.

Pins:

- Runtime source: 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c
- Control executable SHA256: 35e0db257343ed1083bf2ef7187f4e0736985f288ddcf70426dfdd4afbac27ff
- Catalog SHA256: 7f0950b69ea360d694fd6d5dc58b30d74e89d69fbc172ad88757499161d16942
- Dataset manifest SHA256: f136049b624f62c1cba01cc22475d1634228daa372ef679e393f78ee12fd623b
- Original input tar SHA256: 32f80f807345fcbd627f8b5ae0674dbe0bf1bf5a6ac4ac878abae926377cc19f
- Catalog-source SQLite gzip SHA256: 83c439f146747f4fb8411a4b111321f71f35f05b27ac7a96e5be354af6f85ee0

Each arm's metadata.source.commit may be a later documentation/archive commit.
Creation reads each embedded file from that recorded Git commit and checks its
SHA256 against the frozen runtime file hashes, rather than requiring HEAD equality.
The archive preserves the source-commit verification record. Relocated verification
checks that record, metadata and every archived source file against the same pins;
it does not require the original Git checkout or image paths.

Replay reconstructs every exact Sol-high/native-Decisions request from each
ordered pinned PNG and catalog page. The page sizes are 8 then 3, each with Other.
Failed retries stay on the same image/page and retain all cost/usage records;
successful choices must agree with the final output and every progress row.
Typed accepted refusal maps to Other and stops paging. assignment_refusal_calls
counts accepted refusal outcomes (error=null); raw_assignment_refusal_attempts
counts every raw refusal, including failed HTTP responses. Both are derived from
the raw response and checked against the provider's extra refusal marker.

Primary ARI/pair metrics treat each Other image as a singleton. Direct stable-ID
agreement counts both Other assignments as equal; shared-Other sensitivity and
dataset-label diagnostics are separate. Decimal costs are recomputed from raw
input/cache-read/cache-write/output token usage for all attempts, including long
context multipliers. Missing usage remains unknown, never zero. Inspect each run's
unknown_usage_calls, cost_complete, known_recorded_cost_usd and failed/unknown
physical JSONL row indices. Counts are requests, not distinct images.

This is an explicitly post hoc, assignment-only diagnostic using a catalog chosen
from the first completed baseline image run. It is baseline-derived and not
preregistered. Do not combine its costs/timing with either full-system cohort or
present it as a replacement for independent evolving catalogs. The ledger verifies
observed records; it does not guarantee billing continuity under journal/disk I/O
failure. Wall seconds are the fresh control's measured processing loop, excluding
input/source validation and launch waiting.

Offline evidence:

```sh
python3 /tmp/test_ld_control_archive.py
python3 -m py_compile /tmp/ld-control-archive.py
```

14 tests pass. They include a disposable 100-by-2 fixture with complete creation,
relocation and verify-only replay; byte-exact gzip; failed/existing artifacts;
active processes and collected services; wrong images/labels/models/catalog pages;
missing/reordered/extra attempts; raw vs accepted refusals and stop-paging; unknown
null transport retries; cached/write/long-context Decimal charges; altered progress;
and recorded-commit source mismatch. Every 370 assignment request in the immutable
first image archive (123 Sol, 247 Decisions) also matches the request encoder.
Fixture outputs are temporary and never published as experiment evidence.

Behavioral reversion evidence: running the refusal-stop test against the preserved
old /tmp/ld-control-archive-v1-unrun.py fails with ValueError: Sol refusal; the amended
helper accepts the typed refusal and passes the same test. No source changes,
builds, live archival, or API calls were used for these checks.
