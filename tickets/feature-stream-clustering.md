# Build and measure a persistent LLM/decision-model stream clusterer

Status: Closed
Branch: feat-stream-clustering
Pull request: https://github.com/eob/ld-clustering/pull/1
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

Implementation and measured work are complete. The amended four-arm primary
cohort finished 1,000 text and 100 image points per arm, with empty reassignment
queues and one successful fresh invocation each. The subsequent fixed-catalog
image control finished 100 points per arm. All measured workers are terminal;
no paid experiment or recovery remains pending. Measured runtime and primary
launch source remain `9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c`, with unchanged
frozen executables. Control metadata records documentation checkout
`95d0465a1fc91a416a5ae124ddf11787ece887c4`; its embedded runtime files match
the frozen source byte for byte.
All 58 offline tests, formatting and all-target Clippy passed before those calls.

Complete verified evidence is retained in:

- [Primary archive](../experiments/2026-10-20-main-v2-seed42/), manifest SHA-256
  `95c7c86d5174256e1f1882873534e94f808f7c1b8b2dfce02b0c15919ccbaaff`.
- [Separate post-hoc control archive](../experiments/2026-10-20-frozen-images-v2-seed42/),
  manifest SHA-256
  `514bdadfe78b3469d744e3348484000357c4e444cfa3bf04f0db0dbe9ac1cf1a`.

Independent main verification with `/tmp/ld-clustering-v2-frozen` reproduced the
archived Rust comparisons after relocation and checked pinned input bytes, every
pair score, Decimal costs, SQLite integrity, complete sessions and refusal events.
The control verifier independently replayed exact requests/pages, choices,
progress and output from pinned image/catalog bytes. Both archives preserve raw
records, licenses, prices and immutable source/executable pins. The offline final
analysis is complete at `/tmp/ld-main-v2-final-analysis.{md,json}`.

The [README](../README.md#primary-results) records the actual primary and separate
control tables. Text LD has two retried HTTP 503 attempts without reported usage
at physical journal rows 2661 and 5281, so its known cost remains a subtotal and
no complete text cost ratio is claimed. Lower LD coverage and final-partition
disagreement accompany the observed efficiencies. The LLM is a reference rather
than ground truth; one order and independently stochastic managers do not establish
universal quality or latency. The fixed-catalog result is post-hoc and assignment
only, not a replacement for the primary system comparison.

Both earlier interrupted cohorts remain unchanged in their original archives.
Their complete image replicates and incomplete text prefixes are excluded from
v2 headline results. The historical checkpoints and PID/launch recipes below
record those development phases; they are not current workers or pending actions.

Source [PR #1](https://github.com/eob/ld-clustering/pull/1) merged on 2026-10-20T06:37:51Z with merge commit
[`dc0f7859e49dbf5462bb022d4aef638d32519804`](https://github.com/eob/ld-clustering/commit/dc0f7859e49dbf5462bb022d4aef638d32519804). The merged title was:
feat: add persistent streaming clustering with native Decisions

The AI-authored [report](https://edwardbenson.com/goofing/ld-clustering) is published and was confirmed live on
2026-10-20. Website [PR #2220](https://github.com/eob/kaya-web/pull/2220) merged as
[`19e02bafeac071abd442918d0ab8f67afb576cb6`](https://github.com/eob/kaya-web/commit/19e02bafeac071abd442918d0ab8f67afb576cb6).
Automatic Vercel deployment `dpl_BQv7NDM4B5FMVcXa4vRSFzCnp4Tm` reached Ready and
served the `edwardbenson.com` alias. The public route returned HTTP 200 with the
source-merge, runtime and manifest pins. All 18 live Playwright cases passed at
320/768/1440px, measured charts and provenance were manually inspected, 13 public
assets matched their original bytes, and the social image was 1200×630 pixels.
The requested implementation, evidence and goof publication are complete.

## Historical checkpoints

The sections below retain observations and launch/recovery instructions from
earlier development phases as recorded. Their active PIDs, queued work, pending
analysis and future plans are historical, superseded by Current state above.
The installed archives are immutable; do not rerun their creation commands or
restart the recorded workers. Final reproduction instructions are in the README.

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

## Historical amended-cohort launch and archival recipes

Runtime and launch checkout: 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c. Main
executable SHA-256: 8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160.
`/proc/1128953/exe` was independently hashed to the same bytes after launch.
All four DBs recorded one run_start event with saved_count=0 and prior_wall_ms=0.
Main user systemd unit: `ld-clustering-main-v2-seed42-20261020.service`, supervisor
PID1128943; initial children text LLM1128953, text LD1128954, images LLM1128955,
images LD1128956. RuntimeMaxUSec=infinity; all API calls stay sequential per arm.

The post-hoc control waiter is `ld-clustering-frozen-images-v2-20261020.service`,
PID1129505. Script `runs/frozen-images-v2-seed42/after-main.py` waits for the new
primary supervisor to exit, verifies four exact completed cohorts, empty queues,
clean flags and one successful fresh session per arm, then starts the two controls.
No control call has launched yet. Catalog hash remains
7f0950b69ea360d694fd6d5dc58b30d74e89d69fbc172ad88757499161d16942; control executable
hash is 35e0db257343ed1083bf2ef7187f4e0736985f288ddcf70426dfdd4afbac27ff.
Local frozen executable backups are /tmp/ld-clustering-v2-frozen and
/tmp/ld-clustering-v2-frozen-control. Do not rebuild release binaries or change
runtime files while these measured streams and controls are active.

Main archive/verifier: `/tmp/ld-archive-final.py`, usage
`/tmp/ld-archive-final.README.md`. Nine focused helper checks and a full synthetic
four-arm archive plus relocated compare/verify-only pass against the exact frozen
executable. The synthetic fixture was temporary and is not experimental evidence.
After actual terminal state and all expected counts, run:

```sh
python3 /tmp/ld-archive-final.py \
  --repo /mnt/disks/data/ld-clustering \
  --run runs/main-v2-seed42 \
  --output experiments/2026-10-20-main-v2-seed42 \
  --runtime-source 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c \
  --launch-head 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c \
  --binary-sha256 8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160 \
  --service ld-clustering-main-v2-seed42-20261020.service
```

Do not infer success from collected systemd units (a nonexistent unit may display
Result=success by default). Use actual process absence, DB/session markers, logs
and complete output artifacts. No automatic experiment restart solely because an
observation times out. Unknown usage remains unknown even after successful retry.
The control archive/verifier is ready at `/tmp/ld-control-archive.py`, with usage
and evidence in `/tmp/ld-control-archive.README.md`. Helper SHA-256:
daa1ce85514a660292e86bdcf753d53ea120a12f2568596ab061184b68db611c.
All 14 offline tests passed, including a disposable 100-by-2 archive fixture with
relocated verification, exact raw-byte preservation, refusal-aware page replay,
Decimal pricing and unknown-cost counters. All 370 assignment requests in the
immutable first image archive also match the reconstructed request encoder.
Independent review reran all 14 tests and found no consequential blocker. These
checks used no API calls, builds or live archival; fixtures are not experiment data.
The helper pins amended runtime 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c,
control binary 35e0db257343ed1083bf2ef7187f4e0736985f288ddcf70426dfdd4afbac27ff,
and catalog 7f0950b69ea360d694fd6d5dc58b30d74e89d69fbc172ad88757499161d16942.
Each arm's recorded source commit may be a later documentation commit; creation
checks its embedded files against both that Git commit and the frozen runtime.
Only after both controls are terminal with 100 verified assignments, run:

```sh
python3 /tmp/ld-control-archive.py \
  --repo /mnt/disks/data/ld-clustering \
  --run runs/frozen-images-v2-seed42 \
  --output experiments/2026-10-20-frozen-images-v2-seed42 \
  --service ld-clustering-frozen-images-v2-20261020.service
```

Add `--collect` only if systemd has already collected the unit; its terminal
Result remains unknown, and absence of matching workers plus complete output,
progress and raw-journal replay are still required. This is a separate post-hoc,
assignment-only diagnostic using the originally preselected baseline-derived
11-cluster catalog. Keep its costs and processing times separate from the main
independent evolving-system comparison; it cannot replace the primary results.

## Historical final-analysis and publication preparation

The offline narrative helper `/tmp/ld-final-analysis.py` first verifies the exact
completed archive, then reports known planning versus assignment/reassignment
costs, coverage, active/nonempty clusters, accepted refusal requests versus
distinct event points, maintenance operations and guarded efficiency ratios.
Four focused checks, a complete synthetic archive/replay and independent review
pass. Importing the verifier executes hash-verified source bytes without writing
bytecode caches into the immutable archive. Its SHA-256 is
a71897cf02df2451f1fde4f5001edcfc78a2be23af2b2cae2acdc018b6862dd5.
Run only after main archival:

```sh
python3 /tmp/ld-final-analysis.py \
  --archive /mnt/disks/data/ld-clustering/experiments/2026-10-20-main-v2-seed42 \
  --binary /tmp/ld-clustering-v2-frozen
```

Retain the helper and its README as additional `--operational` files during
archival. No actual final-cohort analysis has been generated yet. The website
import helper `/tmp/ld-fill-publication.py` reads result payloads directly from
the chosen immutable evidence commit and binds each to its committed manifest.
It preserves unknown-cost flags and separate fixed-catalog metrics, and places
the measured runtime/executable pins separately from the later evidence commit.
The mapper's schema assumptions and binding checks received independent review;
it must not be executed until both archives exist and are committed. Publication
still requires the complete LLM text stream, queued control, final browser/build
checks, source PR merge, production goof PR merge and live verification.

## Merge Summary

- Merge date (UTC): 2026-10-20T06:37:51Z
- Pull request: https://github.com/eob/ld-clustering/pull/1
- Merge commit: [`dc0f7859e49dbf5462bb022d4aef638d32519804`](https://github.com/eob/ld-clustering/commit/dc0f7859e49dbf5462bb022d4aef638d32519804)

### Final PR title (verbatim)

feat: add persistent streaming clustering with native Decisions

### Final PR description (verbatim)

## Summary

Adds a standalone Rust/SQLite stream clusterer that uses GPT-6.1 Sol with high reasoning to manage evolving clusters, with either Sol or native GPT-6 Luna Decisions for text/image assignments.

## Why

Repeated LLM assignment calls can be expensive. This implementation makes that backend choice measurable while retaining LLM-managed cluster definitions, bounded candidate requests, persistent assignments, and evidence that can be independently audited.

## What changed

- Add prepare/run/compare commands, a single SQLite state file, transactional create/rename/merge/split/retire operations, and durable queues for older-point reassignment and verified resume.
- Page through every eligible cluster with at most K alternatives plus Other. Typed refusals stop paging, remain unassigned, and are counted separately. Both backends use the same policy; invalid completed manager plans share the bounded three-attempt retry budget.
- Integrate Responses/Sol high and native Decisions/Luna for text and inline images. Keep IDs, paths and evaluation labels outside prompts. Preserve every observed attempt, raw usage, model/pricing pins, input hashes and session boundaries, including uncertainty after missing usage or terminal errors.
- Add licensed deterministic datasets, label-invariant comparison metrics, independently verified raw archives, and a separate post-hoc diagnostic with one shared 11-cluster image catalog. Preserve both earlier interrupted cohorts separately.

## Validation

Frozen measured runtime: `9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c`.

- `cargo test --locked --all-targets`: **58 offline tests passed** — 44 library, 3 CLI, and 11 control-example tests; one paid smoke test explicitly ignored.
- `cargo fmt --check` and `cargo clippy --locked --all-targets -- -D warnings`: passed.
- `cargo build --release --locked --bin ld-clustering --example frozen_catalog`: passed for both frozen executables.
- Six live text/image provider smoke checks passed across both assignment backends and the shared planner.
- Complete source-diff, comment-hygiene and accounting review passed.
- Fourteen offline control-verifier checks passed, including temporary archive creation and relocated replay; independent review reran the checks and found no consequential blocker.

All four primary runs completed their full inputs in one fresh session each: **1,000 text points and 100 images per backend**. Both separate frozen-catalog controls completed **100 images**. Archived verification binds inputs, source/binary hashes, SQLite state or control progress, every raw attempt, independently repriced usage, and recomputed partition metrics.

| Experiment (points per arm) | Token-priced USD, LLM / LD | Loop seconds, LLM / LD | Named coverage, LLM / LD | ARI / pair F1 |
| --- | --- | --- | --- | --- |
| Primary text (1,000) | $3.7861672 / $0.5510947 known subtotal | 7,065.888 / 1,328.795 | 97% / 83.6% | 0.682958 / 0.717356 |
| Primary images (100) | $0.2851850 / $0.0939411 | 669.490 / 277.269 | 100% / 66% | 0.328782 / 0.411382 |
| Separate frozen-catalog images (100) | $0.209070 / $0.0054936 | 491.777 / 18.703 | 98% / 67% | 0.385518 / 0.456801 |

The primary text LD ledger retains **two retried HTTP 503 attempts without usage**; `unknown_usage_calls=2` and `cost_complete=false`, so no total text cost ratio is reported. The LLM/LD loop-time ratio was 5.32×. Primary image LLM/LD token-priced cost and loop-time ratios were 3.04× and 2.41×. The separate control had complete usage for all 251 attempts, 47/100 direct stable-ID agreement, and LLM/LD assignment-cost and loop-time ratios of 38.06× and 26.29×; these control figures exclude catalog generation and management. All six completed runs recorded zero accepted assignment refusals.

- [Primary evidence](https://github.com/eob/ld-clustering/tree/feat-stream-clustering/experiments/2026-10-20-main-v2-seed42): manifest SHA-256 `95c7c86d5174256e1f1882873534e94f808f7c1b8b2dfce02b0c15919ccbaaff`.
- [Separate control evidence](https://github.com/eob/ld-clustering/tree/feat-stream-clustering/experiments/2026-10-20-frozen-images-v2-seed42): manifest SHA-256 `514bdadfe78b3469d744e3348484000357c4e444cfa3bf04f0db0dbe9ac1cf1a`. Installed verify-only replay passed; independent checks repriced all 251 control attempts and checked both archives' payload hashes.

## Ticket

[Build and measure a persistent LLM/decision-model stream clusterer](https://github.com/eob/ld-clustering/blob/feat-stream-clustering/tickets/feature-stream-clustering.md)

## Risks / follow-ups

This is one shuffled order per arm. Independent manager calls can vary, so primary disagreement includes catalog variation as well as assignment differences. The LLM is a reference, not ground truth; the shared-catalog diagnostic is post hoc and uses the same images that produced its catalog. Read agreement alongside lower LD coverage. Primary scores treat each Other point as a singleton. Token-priced usage is not an invoice.

Separate tickets retain [Retry-After handling](https://github.com/eob/ld-clustering/blob/feat-stream-clustering/tickets/considering/bug-provider-retry-after-cap.md), [journal-I/O/failed-control accounting](https://github.com/eob/ld-clustering/blob/feat-stream-clustering/tickets/considering/bug-provider-journal-io-cost-continuity.md), and [legacy timing proof](https://github.com/eob/ld-clustering/blob/feat-stream-clustering/tickets/considering/bug-legacy-comparison-timing-without-session-events.md). None establishes impact on this verified fresh cohort or complete control.

## Agent Metadata

- **Harness:** Codex
- **Machine:** `eob-dev2`
- **Session ID:** `01a15732-077c-7a33-ba98-e8b2509c6a74`
- **Ticket:** [feature-stream-clustering.md](https://github.com/eob/ld-clustering/blob/feat-stream-clustering/tickets/feature-stream-clustering.md)
