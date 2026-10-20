# Build and measure a persistent LLM/decision-model stream clusterer

Status: In Progress
Branch: feat-stream-clustering
Pull request: https://github.com/eob/ld-clustering/pull/1 (draft)
Session: 01a15732-077c-7a33-ba98-e8b2509c6a74 (Codex)

## Goal

Implement a standalone Rust clusterer with a single SQLite state file. Compare
gpt-6.1-sol high ordinary assignments with gpt-6-luna decisions; both use Sol high
for cluster creation/maintenance. Publish BSD source and reproducible measurements
for 1,000 text inputs and 100 images. Publish the illustrated report separately
as edwardbenson.com's goofing/ld-clustering page.

## Plan

- Verify provider contract/prices and primary-source clustering literature.
- Prepare licensed deterministic text and image datasets with hidden eval labels.
- Pin bounded choices/Other, assignment persistence and maintenance invariants
  using offline tests, then implement state, stream processing and providers.
- Record request/response payloads, usage, elapsed time and computed token costs.
- Smoke-test live APIs; execute complete independent streaming arms and a
  controlled frozen-catalog comparison if needed to separate catalog divergence.
- Compute label-invariant baseline agreement and secondary label metrics; report
  actual counts, failures, outliers, shared overhead and limits.
- Simplify, test, lint, publish eob repository, and release evidence plus report.

## Acceptance criteria

- At most K cluster alternatives and Other in every model assignment call.
- Novelty buffer and configurable cluster cap govern cluster growth.
- Merge, split, rename and retire can revise assignments; Other always exists.
- Atomic SQLite maintenance and restartable stream processing preserve every point.
- No labels or upstream category names enter model evidence.
- Exactly 1,000 text and 100 image points per full arm; incomplete runs cannot be
  reported as complete. Raw evidence, dataset hashes and model/pricing pins survive.
- Source, offline tests, CLI documentation and real cost/time/agreement artifacts.

## Research brief

Question: Does replacing assignment-time Sol calls with the OpenAI Decisions API
retain agreement with an LLM-only stream clusterer while reducing total cost and
elapsed time, including shared LLM planning and maintenance?
Hypotheses: decisions may agree well and reduce assignment cost; planning may
dominate total cost; divergent early decisions may change the cluster catalogs;
image inputs may differ from text. One run cannot establish universal quality or
latency. Public benchmark labels are a secondary check, not the baseline truth.

## Current state

Rust state, engine, provider, dataset preparation, metrics, comparison CLI and
benchmark runner are implemented. Public repository and draft PR are backed up.
Dataset preparation verified 1,000 text and 100 image points with license/source
pins. Six paid protocol smoke calls passed. The first cohort at
`runs/main-seed42` used source commit 59656c06db2e2ec8599b3bc31f90144a451e27b3.
Its supervisor received SIGTERM (terminal exec status 143) after roughly 20 minutes.
The LLM text arm stopped at 216 points; the LD text arm completed 1,000 but one
HTTP 503 response omitted usage. Its unknown charge cannot be replaced with zero.
Both image arms completed with fully measured cost/time. All first-cohort raw
states, calls, selected inputs, notices, summaries and uncertainty are archived
under `experiments/2026-10-20-main-seed42/` with status `interrupted`.

A fresh complete cohort is now running at `runs/main-seed42-detached`, managed
outside the interactive exec session by user systemd unit
`ld-clustering-main-seed42-20261020.service`. It uses the exact same runtime
source, input bytes and executable (SHA-256 ef1d211d0808a688554f46995cd3370ee98d53b78760dff2fd2026c382c203ee).
The new run records HEAD bdee72c as its source commit; its runtime files match
59656c06 byte-for-byte. `RuntimeMaxUSec=infinity` was verified on the active unit.
The website remains unpublished with provisional first-image measurements;
final headline values will come from the complete fresh cohort.

Both image arms in the first cohort completed and passed `compare` with complete cost and
timing, no API errors and no orphan successes. LLM: $0.293542 / 731.163 seconds /
11 clusters / full coverage. LD: $0.0641622 / 165.873 seconds / 9 clusters /
69% coverage. Final partition ARI is 0.3383630749849558 and pair F1 is
0.41985353946297804. Thus cost/time savings accompany substantial disagreement;
do not present this as quality-preserving replacement. Independent pair
enumeration and taxonomy/rejection diagnostics are archived in `image-analysis.json`.

The first completed result changes the remaining investigation: add an image
control using the same frozen final LLM catalog for both assigners, reclassifying
the same 100 inputs with K=8 and Other. This separates assignment differences
from independent manager/catalog differences. It is a post-result diagnostic,
not an independently pre-registered main benchmark, and its assignment-only
cost/time must remain separate from the full systems. Implement as a separate
Rust example/binary so main runtime source and executable remain frozen.

Recovery: poll the systemd unit's ActiveState/SubState/MainPID and inspect its
live `/proc` process identity before deciding it stopped. Initial Main PID 1039692
owns children 1039703/1039704/1039705/1039706 (text LLM/text LD/images LLM/images LD).
The unit's stdout/stderr append to `runs/main-seed42-detached/supervisor.log`.
The old exec handle 38062 is terminal 143, not a live wait. Never restart solely
because an observation times out. Source/image mutation after the freeze needs
a new experimental series rather than mixed-source measurements.

Independent review demonstrated and fixed a journal/database association defect
using a wrong shared journal. Run identity, successful-call coverage and raw usage
prices are now verified before comparison and resumed spending. Unclean exit
recovery marks timing incomplete. Review sampling now allocates actual quotas
before selecting representatives, so a crowded catalog cannot hide newest Other
evidence. Both defects have meaningful regressions.

## Validation evidence

Initial store maintenance regression (before implementation),
`cargo test --lib store::tests::maintenance_creates_clusters_and_queues_other -- --exact`:

```text
---- store::tests::maintenance_creates_clusters_and_queues_other stdout ----
Error: maintenance is not implemented
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 3 filtered out
```

Bounded assignment Red:

```text
---- engine::tests::bounded_pages_visit_every_candidate_until_a_match stdout ----
Error: bounded assignment is not implemented
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 14 filtered out
```

Initial full gate: `cargo test` 24 passed, 1 explicitly paid-live test ignored;
`cargo clippy --all-targets -- -D warnings` passed; release binary built. Source
base is initial repository commit 6345fcd, before the experimental implementation
commit. Provider/research tickets retain scoped red and live smoke evidence.

Frozen-source gate on `59656c0`: `cargo test --locked` 35 offline tests passed,
one explicitly paid live test ignored; `cargo fmt --check`,
`cargo clippy --locked --all-targets -- -D warnings`, and release build passed.

Post-hoc frozen-catalog example adds eight offline tests. `cargo test --locked
--all-targets` now passes 43 offline tests with one paid smoke ignored; formatting
and all-target Clippy pass. It is a separate executable; original runtime source
and binary remain unchanged. Archived image evidence was decompressed into a
different directory and the frozen Rust `compare` output matched its summary
exactly; checksums and SQLite integrity/foreign-key checks passed.
