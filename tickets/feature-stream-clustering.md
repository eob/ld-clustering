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
pins. Six paid protocol smoke calls passed. Full experiments are running from
source commit `59656c06db2e2ec8599b3bc31f90144a451e27b3` at
`runs/main-seed42`; the directory retains binary hash, source commit, dataset
manifest, launch UTC, four SQLite files and independent raw API/process journals.
The website is built in its separate Kaya worktree and still displays pending
results honestly.

Recovery handles: unified exec session 38062 owns benchmark.sh PID 955592 and
four children 955603/955604/955605/955606 (text LLM/text LD/images LLM/images LD).
Always poll the confirmed live handle/process before deciding to resume. Do not
restart solely because observation times out. Source/image mutation after the
freeze requires a new experimental series rather than mixed-source measurements.

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
