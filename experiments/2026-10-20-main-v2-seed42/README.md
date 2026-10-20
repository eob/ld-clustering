# Main amended-protocol seed-42 cohort

All four primary streams finished: 1,000 text and 100 image points per arm.
Frozen runtime source: https://github.com/eob/ld-clustering/tree/9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c
Frozen binary SHA-256: `8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160`.
Dataset manifest SHA-256: `f136049b624f62c1cba01cc22475d1634228daa372ef679e393f78ee12fd623b`.
`source-commit.txt` preserves launch checkout `9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c`;
`runtime-source-commit.txt` identifies the actual runtime commit above. Later
documentation/provenance commits are identified separately in `runtime.json` and
do not change measured runtime source.

Raw SQLite states, exact request journals and process logs are compressed without
changing their decompressed bytes. Gzip timestamps are zero. Inputs, pricing and
upstream notices are byte-identical to the verified earlier archive. Source code
is BSD-3-Clause; CLINC150 remains CC BY 3.0 and Fashion-MNIST remains MIT.

`text-results.json` and `images-results.json` come from the frozen Rust compare
command. `independent-verification.json` enumerates every unordered pair instead
of using its contingency-table implementation, and verifies primary, shared-Other
and dataset-label scores. Mutually-covered scores are explicitly post hoc and do
not replace the full-population results. `*-partitions.json` provides readable
cluster definitions, evaluation labels, point assignments and maintenance plans.

`attempt-ledger.jsonl.gz` indexes every observed API attempt. `attempt-outcome.json`
and `cost-split.json` retain all failures and the original 1-based JSONL row numbers
for missing usage. Known token-priced costs are not invoices; attempts without
reported usage have unknown cost. Read each result's `cost_complete` and
`timing_complete` before reporting efficiency ratios. `resume-provenance.json` records clean invocation proof or links byte-preserved
external recovery histories. For resumed roles the Rust `wall_seconds` field is
the sum of measured active-loop segments; external downtime is excluded. It is
not uninterrupted start-to-finish elapsed time, even if `timing_complete` remains
true after a graceful failure. `attempt-outcome.json` labels this distinction. Planning costs include
bootstrap and later management. Assignment costs include all reassignment.

The initial manager can produce different catalogs for identical prompts; these
are independent evolving systems, not an assignment-only experiment. Both original-protocol cohorts remain separately archived as interrupted text
experiments with complete image replicates. This cohort uses accepted assignment
refusal-to-Other handling and at most three same-body attempts for completed invalid
manager plans; all attempts remain recorded. No frozen-catalog control is mixed into this cohort. Operational Python files
under `operational/` supervise processes, wait, or archive and verify evidence; the clusterer runtime
and model protocol remain the frozen Rust implementation.

Verify `sha256sum -c SHA256SUMS`, decompress the four SQLite states and request
journals to a scratch directory, and run the frozen Rust `compare` command there
with `--expected 1000` for text and `--expected 100` for images. Comparison does
not access the historical image or journal paths embedded in database metadata.
The archived JSONL inputs preserve original paths and bytes; use `prepare` from
the frozen source to regenerate local paths for a new paid run. Dataset ordered
IDs and PNG hashes remain location independent.

The archive manifest hashes every payload; SHA256SUMS also covers the manifest.
Publish links to the immutable Git commit containing this directory. Runtime
source and archived evidence may live at different commits. Collected systemd units are recorded as collected/unobservable, with unknown
terminal Result rather than an assumed success. Completion is checked against
all four database markers, terminal resume history and absence of matching
/proc run processes. The original supervisor may have failed before a separate
resume finished. This archive step and both comparison verifiers make no API calls.
