# LD Clustering

A Rust stream clusterer that uses an LLM to create and maintain clusters, and
either an LLM or a decision model to assign points. State lives in one SQLite
file. Clusters can change: maintenance can merge, split, rename or retire them
and reassign older points.

The comparison uses **GPT-6.1 Sol with high reasoning** for management in both
arms. Ordinary assignments use the same Sol model in `llm` mode and the native
**GPT-6 Luna Decisions API** in `ld` mode. There are no embeddings, trained local
classifiers or labels standing in for either model.

Code is BSD-3-Clause. Benchmark inputs retain their upstream licenses. Measured
agreement with an LLM reference is separate from ground-truth accuracy.

[Illustrated technical report](https://edwardbenson.com/goofing/ld-clustering)
· [Primary results](#primary-results)
· [Recorded evidence](experiments/2026-10-20-main-v2-seed42/)

## Run

Install current stable Rust and set `OPENAI_API_KEY` in your environment. The
key is read at runtime and is never written to the database or request journal.
Run the offline tests for all targets and build both executables before starting
any paid stream:

```sh
cargo test --locked --all-targets
cargo build --release --locked --bin ld-clustering --example frozen_catalog
target/release/ld-clustering prepare --output data --seed 42
bash scripts/benchmark.sh runs/main-v2-seed42
```

The last command makes paid API calls. It starts four independent sequential
streams: text/image × LLM/LD. Each stream has concurrency one; the four arms
overlap. Logs, SQLite state and process output are separate. Measured time covers
the clustering loop, including bootstrap, model calls, management, reassignment
and persistence. Dataset preparation and CLI input validation are excluded.

For another execution, choose unused state, journal and output paths. The seed
repeats dataset selection and order; it does not make the model calls
deterministic. Repeating the paid procedure can produce different descriptions,
assignments, costs and times. Preserved SQLite snapshots and request journals can
be inspected without making new model calls.

To process your own newline-delimited JSON:

```sh
target/release/ld-clustering run \
  --input examples.jsonl --database state.sqlite --log requests.jsonl \
  --mode ld --task 'Group requests by their broad practical subject' \
  --k 8 --max-clusters 16 --bootstrap 24 --novelty 8 \
  --maintenance-interval 100
```

Each line has this shape; `image` and `label` are optional:

```json
{"id":"point-1","text":"Can you explain this charge?","image":null,"label":null}
```

An image item uses a local PNG, JPEG or WebP path, or an inline image data URL.
The provider sends text and image bytes only: original item IDs, filenames and
evaluation labels do not enter model prompts. `label` exists solely for
post-run evaluation. Input IDs must be unique. The runner verifies the saved
stream prefix, configuration, backend, evidence hash and journal when resuming.

## Algorithm

1. Store the received prefix in Other until the bootstrap size is reached.
2. Ask Sol to propose useful named clusters with membership descriptions from
   that prefix. There is no preset category list or target cluster count.
3. For each new point, traverse active clusters in stable ID order, in pages of
   at most K clusters. Every call also offers Other. A selected cluster ends the
   search; Other advances to the next page. If every page returns Other, keep
   the point in Other. A model refusal stops paging immediately and leaves the
   point unassigned in Other, with a separate refusal event. Refusals are not
   retried or forced into a cluster. No eligible cluster is silently truncated.
4. Ask Sol for maintenance when either the interval expires or enough **new**
   Other assignments accumulate. Persistent outliers alone do not repeatedly
   trigger management. Give it at most 40 representative examples, with up to
   two from each cluster and extra examples from Other.
5. Apply a valid plan in one SQLite transaction, enforcing the active-cluster
   cap. Queue points in changed clusters and Other for reassignment through the
   arm's assignment backend. Unaffected cluster assignments remain intact.
6. Give the final stream a maintenance opportunity, then drain its queue before
   marking the run complete.

A completed manager response with an invalid plan may retry within the same
maximum of three request attempts used for transient transport/server retries.
Every failed reply and its known usage remains in the journal. Planner refusals
and incomplete responses stop the run. There is no model or prompt fallback.
Assignment refusals are accepted non-assignment outcomes for both backends;
`assignment_refusal_calls` counts those requests separately from ordinary Other
choices. Reassignment can revisit an unassigned point, so refusal-call counts
are not counts of distinct points.

Each assignment request contains at most K cluster choices **plus Other**; K
and the maximum active-cluster count are separate settings. The API permits
at most 254 cluster alternatives plus Other. Stable first-match paging is
simple and bounded, but can favor earlier clusters when descriptions overlap.
Both arms use exactly the same paging procedure.

The database contains `points`, `clusters`, `assignments`, `events`, `calls`,
`reassignment` and `meta`. Retired cluster rows and management events preserve
history. Each run invocation records paired `run_start`/`run_finish` events;
new uninterrupted benchmark arms require one successful pair starting from empty
state. Terminal invocation errors conservatively mark cost continuity incomplete,
because a charged request could be missing after a journal-write failure.
Assignment updates and queue removal are atomic. On restart, pending
reassignments finish before new stream points. Invalid or conflicting plans
roll back without dropping points. Other is represented by a null cluster ID,
so it never depends on an ordinary cluster surviving maintenance.

## Experiments and evidence

`prepare` downloads immutable, checksum-verified source files and records the
selected item IDs, their order, seed, image hashes and upstream notices:

| Input | Size | Sampling | License |
| --- | ---: | --- | --- |
| [CLINC150](https://github.com/clinc/oos-eval) test requests | 1,000 | 90 from each of 10 broad domains, plus 100 original out-of-scope requests | CC BY 3.0 |
| [Fashion-MNIST](https://github.com/zalandoresearch/fashion-mnist) test images | 100 | 10 from each of 10 classes | MIT |

Domain/class labels control deterministic sampling and secondary evaluation;
they are hidden from model calls. Fashion-MNIST retains its original 28×28
grayscale pixels. These inputs do not establish performance on general photos
or arbitrary document collections. Original CLINC out-of-scope labels also do
not imply that every such request is semantically unclusterable.

The main experiment ran independent mutable catalogs with identical stream
order, settings, task wording and management model. Only the assignment backend
was deliberately changed. Independent management calls could also vary, so final
partition disagreement includes both local assignment differences and later
catalog divergence. One stream order is a case study, not a statistical claim
about all orders or all workloads.

Two earlier attempts are retained under `experiments/2026-10-20-main-seed42/`
and `experiments/2026-10-20-main-seed42-detached/`. Their image pairs completed,
but their text comparisons did not. The second exposed an invalid maintenance
plan and then an assignment refusal; the amended runtime handles those cases
explicitly. The matched v2 cohort restarted all four arms from empty state with
one frozen amended executable. All four primary streams completed: 1,000 text
and 100 image points per arm, empty reassignment queues and one successful fresh
session each. Earlier prefixes were not continued under changed semantics or
mixed into these primary results.

To compare saved streams after a new execution finishes:

```sh
target/release/ld-clustering compare \
  --baseline runs/main-v2-seed42/text-llm.sqlite \
  --baseline-log runs/main-v2-seed42/text-llm.calls.jsonl \
  --ld runs/main-v2-seed42/text-ld.sqlite \
  --ld-log runs/main-v2-seed42/text-ld.calls.jsonl \
  --expected 1000 --output runs/main-v2-seed42/text-results.json
```

Repeat for `images`, with `--expected 100`. Comparison requires complete runs,
matching inputs/configurations and a matching request journal. It reports:

- Adjusted Rand index (ARI) against the LLM partition, independent of names.
- Positive-pair precision, recall and F1, avoiding misleading agreement from
  the many pairs separated by both methods.
- Coverage and active cluster counts. Other points receive distinct singleton
  labels in the main score; a shared-Other sensitivity score is also retained.
- Secondary agreement with dataset labels, clearly separate from the reference.
- Total measured wall time and token-priced API cost, including initial cluster
  creation, management, reassignment and recorded retries.

The credential-free append-only API journal retains exact requests/responses,
returned models, raw usage, request durations, timestamps and errors. Successful
calls also appear in SQLite. Unknown usage means unknown cost, never free
inference. Unclean interrupted timing is flagged instead of presented as a
complete end-to-end measurement. Token-priced cost estimates are not invoices.

Clean resumes accumulate each invocation's measured loop duration and exclude
manual pauses. Present that total as cumulative processing seconds and record
failure/restart timestamps separately. A complete timing flag does not imply
one uninterrupted invocation.

Price baseline, checked 2026-10-20, USD per million tokens:

| Endpoint/model | Ordinary input | Cache read | Cache write | Output |
| --- | ---: | ---: | ---: | ---: |
| Responses / GPT-6.1 Sol | $2.00 | $0.10 | $2.50 | $10.00 |
| Decisions / GPT-6 Luna | $0.10 | $0 | $0 | $0 |

Sol output usage already includes reasoning tokens. Rates are pinned from the
[Sol model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
and [Decisions guide](https://developers.openai.com/api/docs/guides/decisions).
The standard processing tier is used; no Batch or Flex pricing is assumed.

## Primary results

The completed v2 experiment used the frozen Rust runtime
[`9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c`](https://github.com/eob/ld-clustering/tree/9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c).
The measured main executable SHA-256 was
`8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160`.
Each arm processed its full requested sample in one uninterrupted clustering
loop. The four arms overlapped in real time, with one request at a time per arm.

| Input | Arm | Token-priced API cost (USD) | Loop seconds | Named points | Active/nonempty clusters | API attempts |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Text | LLM | $3.7861672 | 7065.888 | 970/1,000 (97.0%) | 16/16 | 2,893 |
| Text | LD | $0.5510947 known subtotal | 1328.795 | 836/1,000 (83.6%) | 15/15 | 6,274 |
| Images | LLM | $0.2851850 | 669.490 | 100/100 (100.0%) | 13/12 | 139 |
| Images | LD | $0.0939411 | 277.269 | 66/100 (66.0%) | 11/8 | 352 |

The text LD known subtotal excludes the unknown charges for two retried HTTP 503
attempts that did not report token usage. Their costs are unknown, not zero;
there is no complete text cost-reduction ratio. The image costs have complete
recorded usage. Costs include bootstrap, cluster management, assignment,
reassignment and recorded retries, rather than assignment alone.

Known cost splits show the shared LLM overhead. Planning includes bootstrap and
later reviews; assignment includes maintenance reassignment. Fractions below use
known recorded usage, so unknown text-LD charges can change its full-cost share.

| Input / arm | Planning USD | Assignment and reassignment USD | Planning share of known cost |
| --- | ---: | ---: | ---: |
| Text / LLM | $0.1642532 | $3.6219140 | 4.3% |
| Text / LD | $0.2800086 | $0.2710861 | 50.8% |
| Images / LLM | $0.0586930 | $0.2264920 | 20.6% |
| Images / LD | $0.0808265 | $0.0131146 | 86.0% |

Agreement is measured against the LLM arm's final partition:

| Input | ARI | Pair precision | Pair recall | Pair F1 | Shared-Other ARI |
| --- | ---: | ---: | ---: | ---: | ---: |
| Text | 0.682958 | 0.781581 | 0.662884 | 0.717356 | 0.609829 |
| Images | 0.328782 | 0.374815 | 0.455856 | 0.411382 | 0.227790 |

Primary ARI and pair scores treat each Other point as a separate singleton.
The last column instead groups Other together as a sensitivity check. LD left
164 text points and 34 images in Other, versus 30 text points and no images for
the LLM baseline. All four primary arms recorded zero accepted assignment
refusals. Refusal calls and ordinary Other outcomes are measured separately.

The baseline/LD processing-time ratios were 5.32× for text and
2.41× for images. For images, the complete token-priced cost ratio was
3.04×. These are measurements of this cohort, under shared API and machine
conditions. They accompany lower LD coverage and different final partitions;
they do not establish equal-quality clustering or a general model speedup.

Each manager also made independent stochastic decisions. Planning request counts
were 21 versus 36 for text and 5 versus 6 for images (LLM versus LD). The totals
therefore include different catalogs and amounts of review/reassignment work;
they do not isolate assignment under one common taxonomy. The LLM baseline is a
reference, not a human-validated answer key. Secondary dataset-label scores are
retained in the comparison artifacts. These primary runs applied creation,
renaming and retirement operations; no merge or split was applied. Both operations
are implemented and tested offline, and the report's maintenance animation is an
illustration rather than a replay of these runs.

The primary manifest SHA-256 is
`95c7c86d5174256e1f1882873534e94f808f7c1b8b2dfce02b0c15919ccbaaff`.
The [primary archive](experiments/2026-10-20-main-v2-seed42/) contains the raw
SQLite states and request journals, selected inputs and licenses, model prices,
[manifest](experiments/2026-10-20-main-v2-seed42/manifest.json),
[text comparison](experiments/2026-10-20-main-v2-seed42/text-results.json),
[image comparison](experiments/2026-10-20-main-v2-seed42/images-results.json),
[cost split](experiments/2026-10-20-main-v2-seed42/cost-split.json) and
[independent verification](experiments/2026-10-20-main-v2-seed42/independent-verification.json).
These records can be inspected without new model calls. Repeating the paid
procedure preserves inputs and settings, but stochastic model calls need not
reproduce these exact catalogs, assignments, costs or times.

## Frozen-catalog image diagnostic

Both control arms completed all 100 images after the primary streams finished.
Their verified assignment-only measurements remain separate from the primary
tables above.

A separate post-hoc control measures assignment behavior after removing the
independent managers' catalog differences. Its catalog is the **11 active
clusters discovered by the completed first-cohort LLM image run**, with original
IDs, names, descriptions and ordering preserved. Eleven is an observed result,
not a preset taxonomy or a target count. The catalog was learned from those
same image inputs, so this control isolates local choices; it is not another
independent streaming evaluation or a held-out generalization test.

| Control arm | Token-priced API cost (USD) | Loop seconds | Named points | API attempts |
| --- | ---: | ---: | ---: | ---: |
| LLM | $0.2090700 | 491.777 | 98/100 (98.0%) | 114 |
| LD | $0.0054936 | 18.703 | 67/100 (67.0%) | 137 |

Direct cluster-ID agreement was 47/100 (47%), including one point that both
arms placed in Other. Singleton-Other ARI was 0.385518, pairwise precision
0.526627, recall 0.403323 and F1 0.456801. Grouping Other together instead
gave ARI 0.263767. Both arms reported complete usage, with no failed requests or
accepted assignment refusals. Baseline/LD cost and processing-time ratios were
38.06× and 26.29× respectively, for assignment only.

The large assignment-only efficiency ratios accompany substantial disagreement
and lower LD coverage. Holding this catalog fixed did not make the backends
interchangeable. This post-hoc, baseline-derived catalog was learned from these
same images in an earlier run; the control is not a held-out evaluation and
does not quantify how much of the primary disagreement came from management.
Its costs exclude the earlier work that produced the catalog.

The [control archive](experiments/2026-10-20-frozen-images-v2-seed42/) preserves
[independent request replay and results](experiments/2026-10-20-frozen-images-v2-seed42/independent-results.json),
[the frozen catalog](experiments/2026-10-20-frozen-images-v2-seed42/catalog.json)
and all raw requests, progress, outputs, inputs and notices. Its manifest SHA-256 is
`514bdadfe78b3469d744e3348484000357c4e444cfa3bf04f0db0dbe9ac1cf1a`.

Commit the source before measured API calls. The Run sequence above builds
both the main and separate control executables before the primary streams start.
Use that same build for the control.

Record the source, executable, input and catalog hashes, and keep those
executables unchanged through the primary run and its control. For the v2
cohort, both executables were frozen before the primary launch, and the control
started with that existing build after all four primary streams were verified
complete with matching counts and empty reassignment queues. For another
execution, use the same ordering.

Both control processes use the same 100 images, frozen catalog, task, K=8 and
first-matching-page/Other policy. They make no management calls. This is a
separate post-hoc assignment diagnostic; its costs and times exclude catalog
creation and maintenance. For a new paid execution, build before starting the
measured calls, then run the command below once with each mode after the primary
streams finish, launching the two modes together with separate fresh paths:

```sh
target/release/examples/frozen_catalog \
  --input data/images.jsonl \
  --catalog experiments/2026-10-20-frozen-images-v2-seed42/catalog.json \
  --mode llm --k 8 --expected 100 \
  --log runs/frozen-images-replay-seed42/llm.calls.jsonl \
  --output runs/frozen-images-replay-seed42/llm.json
```

For the second process use `--mode ld`, `ld.calls.jsonl` and `ld.json`.
The tracked catalog file is a JSON array of `{ "id": 1, "name": "...",
"description": "..." }` objects exported from the original first-cohort LLM
baseline's active clusters in ascending ID order. A fresh clone can inspect or
reuse these preselected definitions; no new catalog-generation calls are needed.
Preserve its IDs and ordering, including any gaps. Use new log, output and
progress paths for another paid run; the example records the catalog's exact
hash and full contents.

Each arm writes its credential-free API journal, an ordered assignment list,
`llm.progress.jsonl` or `ld.progress.jsonl`, and a final JSON containing source,
executable, input/image and catalog hashes, counts, measured time, token usage,
cost and completeness flags. Existing artifact paths are refused. Normal
failures preserve the completed prefix as `status=failed`; interruption leaves
`status=running`, and this small control has no resume mode.

Keep these costs and times separate from the mutable-catalog primary results.
Only compare complete 100-point arms with matching evidence/catalog hashes.
Check `measurement.cost_complete` and `timing_complete` before making cost or
time claims: a numerical cost can be only a known subtotal. In primary comparison
output, `unknown_usage_calls` counts recorded requests without usage, while an
unclean history can make cost incomplete even when that recorded count is zero.

## Related work

[Text Clustering as Classification with LLMs](https://arxiv.org/html/2410.00927v1)
separates label generation, label merging and assignment. This project builds
on that decomposition; its experiment is replacing repeated assignment-time
generation with native typed decisions while retaining a mutable catalog.
[ClusterLLM](https://aclanthology.org/2023.emnlp-main.858/) studies comparison
queries and clustering granularity, and
[Large Language Models Enable Few-Shot Clustering](https://aclanthology.org/2024.tacl-1.18/)
studies instruction-guided clustering and quality/cost tradeoffs. Their results
are prior work, not reproduced measurements of this implementation.
