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

The amended Rust runtime is ready to freeze for a new matched four-arm cohort.
It distinguishes Cluster, Other and Refused; accepted assignment refusals remain
unassigned with per-point events and priced request counters. Invalid completed
manager plans may retry within the existing shared three-attempt budget. Run
session boundaries and conservative terminal-error cost markers make resumption
and possible unjournaled charges visible. All 58 offline tests pass (44 library,
3 CLI, 11 control-example), with one explicitly paid smoke ignored; formatting
and all-target Clippy pass. No new paid calls have started under this amendment.

Both earlier cohorts are terminal and preserved unchanged under
`experiments/2026-10-20-main-seed42/` and
`experiments/2026-10-20-main-seed42-detached/`. Each has a complete image pair;
neither has a complete text comparison. The second archive manifest SHA-256 is
ae602400ee66cb701d1582f501eb861b0a35b9b55e1f540839ba6ba659e47035.
Its 397-point LLM text arm was stopped deliberately after the 779-point LD arm
refused classification. All eight archived DB/journal files were independently
compared with original bytes. The original executable remains locally available
at `/tmp/ld-clustering-v1-frozen`; archived source/binary pins identify it.

The old primary, recovery and control-waiter units are inactive; none should be
restarted. The website remains unpublished and all primary measurements are reset
to pending until the fresh amended four-arm cohort is complete. The post-hoc
image control still uses the originally selected final 11-cluster LLM catalog;
its new executable will implement the same refusal semantics as the new runtime.
A dedicated persistent worker will launch it only after the new primary ends.

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

## Superseded replacement-cohort checkpoint and queued diagnostic

The fresh image pair completed with clean timing: baseline 663.815 seconds,
LD 223.233 seconds. ARI is 0.17315386804613866, pair F1 0.25662251655629137;
LD assigns 63 images to named clusters versus all 100 for baseline. Known
recorded token costs are $0.271528 baseline and $0.0871249 LD. Two LD assignment
HTTP 503 attempts (journal rows 88 and 242, counting header as row 1) omit usage;
LD cost_complete is false, and the website labels it a subtotal without a total
cost ratio. Both text streams are still running; do not archive active state.

The prepared fixed-catalog diagnostic is queued in user systemd unit
`ld-clustering-frozen-images-20261020.service`, current waiting worker PID1072847.
Its operational script is `runs/frozen-images-seed42/after-main.py`. It waits for
primary supervisor PID1039692 to exit, then requires all four expected cohorts,
clean timing and empty queues before starting the two controls. No control API
call has begun at this checkpoint. It uses the original first-cohort LLM final
11-cluster catalog, SHA-256 7f0950b69ea360d694fd6d5dc58b30d74e89d69fbc172ad88757499161d16942,
and separate executable SHA-256 4c8d89a76cd475d7e8e2ac21c4de2c146ac97cfc31883703a896d70cbb9489df.
The unit has no runtime limit and owns its entire process group. Inspect its
supervisor log/output statuses before inferring that it has launched or finished.

An isolated offline review proved a reporting defect: an unclean resumed history
can lose an in-flight request even when every recorded row has usage. The old
verifier incorrectly called that subtotal complete. A conservative fix and
unknown_usage_calls counter are prepared outside this source tree at
`/tmp/ld-cost-unclean-history.results.patch`; its focused Red/Green evidence and
README changes are at `/tmp/ld-cost-unclean-history.docs.patch`. Apply only after
the frozen primary runtime finishes. No active runtime file or executable has
been changed. This reporting-only correction does not require rerunning paid
streams; retain their pinned runtime source commit and binary separately.

The fresh text LD process later exited cleanly at 607 points because Sol returned
`retire 25` twice in one plan. Validation rejected the duplicate before state
mutation; 607 assignments and no pending queue survived. The failed HTTP 200 plan
is preserved at physical journal line 5547, with known token cost $0.0056778.
A separate Decisions 503 at line 4674 omitted usage. One explicit recovery uses
the exact frozen runtime, configuration, database and journal under user unit
`ld-clustering-text-ld-resume1-20261020.service`, supervisor PID1080591.
Its `resume-text-ld.py`, `text-ld-resume-history.json`, `resume-supervisor.log` and
`text-ld.resume1.process.log` preserve the recovery. The history records the prior
1,114.812 measured loop seconds and a 196.849-second gap from the last recorded
attempt to resume startup. On completion it will record final metadata and
calendar duration separately. SQLite wall_ms accumulates active loop intervals,
excluding the manual pause; do not call it uninterrupted end-to-end latency.
The first resume made progress beyond 650 points without a runtime/source change.

## Protocol amendment after a model refusal

The first recovery stopped cleanly at 779 points when the Decisions API returned
`{"name":"cluster","type":"refusal"}` for the classification input “can you
fill in my credit card number on the screen”. The model was asked to classify
that text, not perform the requested action. Physical journal line 9582 reports
15 input tokens and 0 output tokens; that known charge is retained. The strict
parser treated the valid refusal outcome as a protocol failure, so the stream
could not finish. Other data and configuration were intact. This proves a missing
assignment outcome in the prototype rather than a need to force a cluster choice.

The old primary unit and queued control waiter were stopped deliberately; all
owned primary/resume/waiter PIDs were confirmed absent. The second cohort will be
archived as interrupted: its image pair is complete, but its text arms do not
supply a complete primary comparison. The stopped LLM request may have completed
upstream without a journal row, so its charge/timing remain uncertain. Preserve
both old cohorts; do not continue a paid prefix with changed runtime semantics.

Before the next full four-arm run, add a typed assignment outcome distinguishing
Cluster, Other and Refused. A refusal ends paging, remains unassigned in Other,
and records a per-point refusal event and separate refusal-call count. Apply the
same rule to both assignment backends; do not retry the refusal or force a choice.
Manager refusals remain errors. A completed, usage-bearing manager response with
an invalid plan may retry the same request within the existing total maximum of
three attempts; every rejected reply and its usage stay in the journal. An invalid
plan never changes cluster state. No model or prompt fallback is introduced.

Pin a new runtime commit and executable only after focused refusal/invalid-plan
regressions, full offline tests, formatting and Clippy pass. Then launch fresh
1,000-text/100-image streams for all four arms with the original seed, order,
models and configuration. The report's headline data will come entirely from this
new matched cohort. The frozen-catalog diagnostic still uses the originally
preselected 11-cluster image catalog and starts only after the new cohort ends.

## Amended runtime verification

Provider behavioral Red before changing the compiling Option API:

```text
ld assignment refusal must be an accepted outcome
test result: FAILED. 0 passed; 1 failed; 0 ignored; 34 filtered out
completed invalid planner reply must consume one bounded retry: Some("plan attempt 1; recorded in request log")
test result: FAILED. 0 passed; 1 failed; 0 ignored; 35 filtered out
```

After the typed outcome/retry changes, all 15 offline provider tests pass, including
shared network/semantic attempt budget, charged exhausted replies, and planner
refusal/incomplete-response termination. Eleven control-example tests cover
refusal-stop-paging, per-point refusal output, missing usage and accepted-refusal
counters. A malformed refused response is an error rather than an accepted
non-assignment; the counter regression failed with 2 versus 1 before the guard.

The terminal-error continuity regression was checked causally by reverting only
the new persistence guard: expected Some("false"), received None. Restoring the
guard passes. The comparison verifier also rejects forged refusal flags, exposes
unknown_usage_calls, conservatively marks interrupted histories incomplete, and
validates matching session boundaries and accumulated measured milliseconds.
`cargo test --locked --all-targets`: 58 offline tests passed; one paid smoke
ignored. `cargo fmt --check` and `cargo clippy --locked --all-targets -- -D warnings`
passed. Full logs remain in /tmp/ld-clustering-v2-{all-tests,clippy,fmt}.log; the
brief failure excerpts above preserve the durable evidence.
