# Provider evidence

Status: In Review
Parent ticket: feature-stream-clustering.md
Parent pull request: https://github.com/eob/ld-clustering/pull/1 (draft; finalization pending)

## Final phase completion

The primary and separate fixed-catalog experiments are complete and their
archives verified. This is phase evidence under parent PR #1, not an independent
work item. See the [parent current state](feature-stream-clustering.md#current-state),
[primary archive](../experiments/2026-10-20-main-v2-seed42/) and
[control archive](../experiments/2026-10-20-frozen-images-v2-seed42/).
The development checkpoints below preserve historical evidence; old pending
notes and launch recipes are superseded by those final records and the README.

## Behavioral red evidence

Before implementing request construction, response decoding, or pricing, `cargo test provider::tests -- --nocapture` produced:

```text
assignment_wire_hides_evaluation_label_and_uses_native_decisions:
evaluation label leaked into request: {"input":{"clusters":[{"description":"Invoices and payment questions","id":7,"name":"Payments"}],"item":{"id":"a","label":"SECRET_GROUND_TRUTH","text":"My invoice is incorrect"},"task":"Group support messages"},"model":"ld"}
cache_reads_writes_and_reasoning_output_have_distinct_prices:
assertion `left == right` failed
  left: 0
 right: 1000
native_choice_is_decoded_and_unknown_choice_is_refused:
called `Result::unwrap()` on an `Err` value: typed assignment decoding is not implemented
test result: FAILED. 0 passed; 3 failed; 0 ignored
```

## Protocol and price pins

Retrieved 2026-10-20 from official OpenAI documentation:

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/guides/decisions
- https://developers.openai.com/api/reference/resources/decisions/methods/create
- https://developers.openai.com/api/docs/guides/structured-outputs

Use `gpt-6.1-sol` and `reasoning.effort=high` for LLM assignment and planning.
Use `gpt-6-luna` only through `/v1/decisions` for LD assignment.
Standard Sol rates per million tokens: input $2, cached reads $0.10,
cache writes $2.50, output $10. Output already includes reasoning tokens;
never add reasoning tokens a second time.
Decisions input costs $0.10 per million tokens; the endpoint has no
cache-read, cache-write, or output-token charges. All experiments remain
below the >272K-input long-context price boundary and use standard processing.
Prices are estimates from recorded provider usage, not reconciled invoices.
Requests above 272K input apply 2x input/cache and 1.5x output rates;
regression tests pin this boundary even though these experiments stay below it.

Authenticated GET `/v1/models` returned HTTP 200 and listed both model IDs.
Credentials were not printed. Model listing alone is not inference verification.

## Recovery and retry policy

Every dispatched HTTP attempt is flushed to append-only JSONL, including failed
responses and semantic refusals. Journal rows retain the exact credential-free
request, response, usage, elapsed time, status, attempt index, and error.
The SQLite call record contains the final successful attempt; account for retries
from JSONL when computing complete experimental cost.

Up to three attempts are permitted for HTTP 429/502/503/529 and connection
establishment failures. Other transport failures and HTTP 500/504 may have
completed upstream; retain the attempt and fail rather than retry automatically.
No provider error or refusal silently changes models, picks Other, or returns an
unmeasured fabricated result.

## Verification

| Gate | Result |
| --- | --- |
| Initial behavioral Red | 3 focused tests failed for label leakage, absent typed decode, and zero token usage |
| Reversion check | Restoring the original request construction reproduced the same label-leak failure (exit 101); restored implementation passed |
| `cargo test --lib provider::tests -- --nocapture` | 9 passed, 0 failed; 1 paid live test ignored |
| `cargo clippy --lib --tests -- -D warnings` | Passed |
| Explicit `live_text_image_provider_smoke` | 6 live calls passed; labels absent from all logged requests |

The new repository has no base commit yet. Provider source was reviewed with
`simplifyfu`: one HTTP path serves assignments and plans, and shared pure helpers
cover evidence serialization, response decoding, pricing, and plan invariants.
No SDK or Kaya dependency was introduced.

Live smoke command:

```sh
LD_SMOKE_LOG=/tmp/ld-provider-smoke-20261020.jsonl cargo test provider::tests::live_text_image_provider_smoke -- --ignored --nocapture
```

| Call | Model | Elapsed ms | Estimated USD |
| --- | --- | ---: | ---: |
| Text assignment, LLM | gpt-6.1-sol high | 2993 | 0.00062800 |
| Image assignment, LLM | gpt-6.1-sol high | 2222 | 0.00060200 |
| Text assignment, LD | gpt-6-luna Decisions | 513 | 0.00001890 |
| Image assignment, LD | gpt-6-luna Decisions | 114 | 0.00001860 |
| Text planning | gpt-6.1-sol high | 4675 | 0.00242400 |
| Image planning | gpt-6.1-sol high | 3987 | 0.00186400 |

These six synthetic protocol probes are not benchmark observations. Every call
returned HTTP 200, usage, the expected assignment or a valid plan, and no retry.
The benchmark must measure full workflows independently.

All provider requests exclude `Item.label`, original IDs, and image paths; image
bytes are encoded inline. The task and current cluster descriptions are the only
category guidance. The permanent Other choice is always last. Native Decisions
needs at least one existing cluster, because its choice schema requires two
options including Other; the engine bootstraps before model assignment.

`usage_available=false` identifies failed attempts without reported usage. Their
zero-valued `Usage` does not prove no charge. Do not report a complete known cost
when such potentially dispatched failures remain unresolved. SQLite successful
call rows alone omit failed/retried attempts; the JSONL journal is authoritative
for full experiment provider costs. Workflow wall time includes retry backoff.

## Journal binding and measurement audit follow-up

Independent review reproduced a false completion: two completed databases with
no calls could be compared against the same unrelated one-row log, yielding
`status=complete`, `cost_complete=true`, and an invented tiny measured cost.
The committed regression initially failed with:

```text
complete_databases_reject_one_unrelated_shared_journal:
a wrong shared log was accepted as complete measured evidence
test result: FAILED. 0 passed; 1 failed
```

CLI runs now bind a random run ID in SQLite to a first-line JSONL header and
the canonical request-log path. A fresh database refuses a nonempty existing
log. Resume checks every committed SQLite call against a journal success before
spending, ignoring only the engine's later `assign` to `reassign` phase change.
Comparison repeats this coverage check, rejects wrong/truncated logs and
tampered usage/cost/model fields, recomputes token charges from raw responses,
and includes any bound-log successful calls that were not committed to SQLite
as `uncommitted_success_calls`. Such orphan calls are billed rather than hidden.
Copied database/log evidence remains comparable by run ID; resuming execution
requires the original canonical log path.

`timing_complete` comes from the engine's clean-run markers; missing metadata or
an interrupted session makes timing explicitly incomplete. Assignment completion
alone does not establish cost/timing completeness for publication.

Input fingerprints now include raw JSONL bytes and the ordered local image bytes
with domain separation and length prefixes. Changing an image at the same path
changes the run identity. The reproducible CLI rejects HTTP image URLs with an
instruction to download the file; direct provider protocols still support them.

Verification added five result audit tests and three CLI binding/hash tests.
The full offline suite passed (31 library tests plus 3 CLI tests; one paid live
provider test ignored), as did formatting and all-target Clippy.

## Live evidence audit — 2026-10-20 03:16:20 UTC

This read-only audit checked **every complete request-attempt row** in the four
journal snapshots, not a sample: **3,529 rows**. Each database was held in a
read-only transaction before reading its journal, so all committed calls in its
SQLite snapshot had already been flushed to the observed log. No trailing partial
JSONL rows were present. The text arms remained live; their counts below are
partial observations, not completed benchmark results.

Frozen source commit: `59656c06db2e2ec8599b3bc31f90144a451e27b3`.
All source files, Cargo manifests/lockfile, and the runner matched that commit.
The source tree's later HEAD contained documentation only. The pinned release
binary and `/proc/955603/exe`, `/proc/955604/exe`, and `/proc/955605/exe` all had
SHA-256 `ef1d211d0808a688554f46995cd3370ee98d53b78760dff2fd2026c382c203ee`.
The copied run manifest and current dataset manifest both had SHA-256
`f136049b624f62c1cba01cc22475d1634228daa372ef679e393f78ee12fd623b`.
The runner's recorded launch was `2026-10-20T03:03:12Z`.

Independently recomputed JSONL-plus-image fingerprints matched both arms:

- Text: `30fb8469f7e89d39e4f1188ca889db48f8b702c28a99c10978b7d78e6cff15c0`.
- Images: `171e3079431bf25c7762eb18b255e18c2f300bc9203a47c85c754e598ac89a2e`.

Every row used the expected request and response model: Sol high for planning
and LLM assignment, and the native Luna Decisions choice shape for LD assignment.
Every assignment offered at most eight unique numeric cluster alternatives and
one final Other option. Candidate IDs existed and were active within the recorded
creation/retirement intervals. No nonstandard processing tier was requested or
returned. Raw input/cache-read/cache-write/output token categories reproduced each
stored cost exactly within floating-point tolerance; no failures or missing usage
were observed.

The audit inspected all user evidence parts: text matched actual dataset text or
an explicit current-cluster example marker; all images were inline and their
decoded bytes matched the pinned dataset PNG hashes. Original opaque point IDs,
local paths, and evaluation-label keys were absent from model requests. Generated
cluster names and descriptions remained legitimate model context.

All maintenance/reassignment events were replayed to reconstruct the exact final
catalog in each snapshot. Point/assignment counts matched, every stored point
matched the expected input prefix, reassignment events referenced live clusters,
and historical and current active counts respected 16. Pending work was retained
in SQLite. Every committed model call matched one successful journal row. There
were no unmatched successful rows in this snapshot.

| Snapshot | Points | Calls | Plans | Assignment calls | Pending | Active / historical max | Complete |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Text LLM | 167 | 332 | 6 | 326 | 0 | 11 / 11 | No |
| Text LD | 706 | 2817 | 31 | 2786 | 0 | 15 / 16 | No |
| Images LLM | 100 | 128 | 5 | 123 | 0 | 11 / 11 | Yes |
| Images LD | 100 | 252 | 5 | 247 | 0 | 9 / 9 | Yes |

Snapshot run identities and full-row journal SHA-256 values:

- Text LLM run `61b99517884ab8038d86e812c24f45be`:
  `568b4706825aebc9e5a39c139243fd1a34bf0f3a145f78915435ad8d0f5a2b49`.
- Text LD run `54c56650f8ddf60abac1800fbb632b61`:
  `3d9b7e5d90f8e104c3a51a068a07d0d296848e7a7bb8913efcb56fa615474f2f`.
- Images LLM run `21d7ec59bb723361c5e28560658231c7`:
  `89222bbbb7c8935a4f9c3fbebae935039e5682fd8db3b074b91f9611a2321624`.
- Images LD run `a3812afc72fb62cffbb612e9333cb909`:
  `c2bd3de6538a3a9ba5e944eda603d128a0e5d8e842cf5332a4c479ff5346eb0f`.

Both completed image states had `completed_count=100`, `run_in_progress=0`,
`timing_complete=true`, zero pending reassignment, complete reported usage, and no
orphan calls. Independently recomputed total provider costs were **$0.293542**
for LLM and **$0.0641622** for LD. SQLite measured total workflow times were
**731.163 seconds** and **165.873 seconds**, respectively: 4.575x lower cost and
4.408x less elapsed time for this image run.

Independent pair counting on the final image assignments, treating each Other
point as a separate singleton, gave ARI **0.3383630749849558**, positive-pair
precision **0.4607142857142857**, recall **0.38565022421524664**, and F1
**0.41985353946297804**. There were 258 shared positive pairs, 669 baseline
positive pairs, and 560 LD positive pairs. Other counts were 0 for LLM and 31
for LD. Thus the measured image savings accompany substantial disagreement;
these results do not support a claim of matching clustering quality. The text
comparison remains unproven until both 1,000-point arms complete.

## Frozen-catalog image diagnostic

The primary image runs disagree substantially, and their managers produced
separate catalogs. A **post-result diagnostic**, implemented only in
`examples/frozen_catalog.rs`, isolates assignment behavior using the completed
LLM arm's 11 active cluster definitions and original IDs in ascending order.
The catalog export and provenance are `runs/frozen-images-seed42/catalog.json`
and `catalog-source.json`. Both diagnostic arms will receive the same 100
image inputs, task, immutable catalog, K=8, and first-matching-page/Other policy.
There are no management calls. This is a local-choice control using descriptions
learned from the primary run, not another independent streaming benchmark.
Diagnostic costs and time must remain separate from primary totals. The paired
processes are to start only after both primary text runs finish, avoiding extra
API traffic during primary timing. No diagnostic API calls were made while
implementing this example.

The example requires fresh output, request-journal, and derived progress paths;
it never resumes or mixes artifacts. Progress records retain every completed
assignment. A normal error writes `status=failed` with the successful prefix;
a killed process leaves the initial `status=running`, never a false completion.
The final `status=complete` requires exactly the requested count and a successful
stream. `cost_complete` separately captures unknown attempt charges. Existing
provider retries and raw credential-free attempt journals are reused.

Provenance includes the exact JSONL-plus-local-image fingerprint (the same
versioned function shape as the primary CLI), raw JSONL hash, raw catalog hash,
full catalog definitions, runtime source commit, executable hash, and embedded
hashes for this example, provider, types, metrics, library module declarations,
Cargo manifest, and Cargo lockfile. Before any API call, these embedded bytes
must match both the committed HEAD versions and the working files. This requires
committing and rebuilding the example before execution. Ground-truth labels
remain output/evaluation data only; the unchanged provider excludes them from
all model evidence.

Initial behavioral Red:

```text
paging_preserves_ids_and_visits_every_page_until_match:
assertion `left == right` failed
  left: None
 right: Some(50)
other_requires_every_page_to_have_no_match:
assertion `left == right` failed
  left: 1
 right: 3
existing_artifact_is_refused_without_changing_contents:
existing evidence was silently replaced
partial_and_failed_runs_never_claim_complete:
assertion `left == right` failed
  left: "complete"
 right: "failed"
test result: FAILED. 0 passed; 4 failed
```

Temporarily restoring the one-page implementation reproduced the same missing
ID-50 failure (exit 101), then restoring the finished implementation returned
Green. Eight offline tests pin all-page traversal, early page stopping, Other,
artifact preservation and cleanup, failed-stream prefix retention, incomplete
status, and image-byte fingerprints. The focused example tests, example Clippy
with warnings denied, release example build with `--locked`, and Rust formatting
check passed. The original main executable retained SHA-256
`ef1d211d0808a688554f46995cd3370ee98d53b78760dff2fd2026c382c203ee`.
The simplification pass kept one paging function and reused the existing provider
and partition metrics; no dependencies, core source, runner, or primary artifacts
were changed.

Build after committing the example:

```sh
cargo test --example frozen_catalog
cargo clippy --example frozen_catalog -- -D warnings
cargo build --release --example frozen_catalog --locked
```

After primary completion, launch these two commands as paired processes:

```sh
target/release/examples/frozen_catalog \
  --input data/images.jsonl \
  --catalog runs/frozen-images-seed42/catalog.json \
  --mode llm --k 8 --expected 100 \
  --log runs/frozen-images-seed42/llm.calls.jsonl \
  --output runs/frozen-images-seed42/llm.json

target/release/examples/frozen_catalog \
  --input data/images.jsonl \
  --catalog runs/frozen-images-seed42/catalog.json \
  --mode ld --k 8 --expected 100 \
  --log runs/frozen-images-seed42/ld.calls.jsonl \
  --output runs/frozen-images-seed42/ld.json
```

Each final JSON contains `status`, `metadata` (IDs/hashes/configuration),
`processed_count`, `expected_count`, `wall_seconds`, `timing_complete`,
`other_count`, `coverage`, `measurement` (attempt counts, comparison counts,
request seconds, token categories, cost, completeness, journal hash),
`dataset_label_agreement`, ordered `assignments` (`id`, `cluster_id`, `label`),
`error`, and `progress_sha256`. Progress files derive from output names:
`llm.progress.jsonl` and `ld.progress.jsonl`. A first metadata record, one row
per completed point, and a terminal outcome support post-hoc auditing.
