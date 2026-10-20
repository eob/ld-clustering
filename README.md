# LD Clustering

A Rust stream clusterer that uses an LLM to create and maintain clusters, and
either an LLM or a decision model to assign points. State lives in one SQLite
file. Clusters can change: maintenance can merge, split, rename or retire them
and reassign older points.

The comparison uses **GPT-6.1 Sol with high reasoning** for management in both
arms. Ordinary assignments use the same Sol model in `llm` mode and the native
**GPT-6 Luna Decisions API** in `ld` mode. There are no embeddings, trained local
classifiers or labels standing in for either model.

Code is BSD-3-Clause. Benchmark inputs retain their upstream licenses. This is
experimental software; the report will distinguish measured agreement with a
reference run from ground-truth accuracy.

## Run

Install current stable Rust and set `OPENAI_API_KEY` in your environment. The
key is read at runtime and is never written to the database or request journal.

```sh
cargo test --locked
cargo build --release --locked
target/release/ld-clustering prepare --output data --seed 42
bash scripts/benchmark.sh runs/main-seed42
```

The last command makes paid API calls. It starts four independent sequential
streams: text/image × LLM/LD. Each stream has concurrency one; the four arms
overlap. Logs, SQLite state and process output are separate. Dataset download
and preparation are common setup and excluded from measured clustering time.

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
   the point in Other. No eligible cluster is silently truncated.
4. Ask Sol for maintenance when either the interval expires or enough **new**
   Other assignments accumulate. Persistent outliers alone do not repeatedly
   trigger management. Give it at most 40 representative examples, with up to
   two from each cluster and extra examples from Other.
5. Apply a valid plan in one SQLite transaction, enforcing the active-cluster
   cap. Queue points in changed clusters and Other for reassignment through the
   arm's assignment backend. Unaffected cluster assignments remain intact.
6. Give the final stream a maintenance opportunity, then drain its queue before
   marking the run complete.

Each assignment request contains at most K cluster choices **plus Other**; K
and the maximum active-cluster count are separate settings. The API permits
at most 254 cluster alternatives plus Other. Stable first-match paging is
simple and bounded, but can favor earlier clusters when descriptions overlap.
Both arms use exactly the same paging procedure.

The database contains `points`, `clusters`, `assignments`, `events`, `calls`,
`reassignment` and `meta`. Retired cluster rows and management events preserve
history. Assignment updates and queue removal are atomic. On restart, pending
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

The main experiment runs independent mutable catalogs with identical stream
order, settings, task wording and management model. Only the assignment backend
is deliberately changed. Independent management calls can also vary, so final
partition disagreement includes both local assignment differences and later
catalog divergence. One stream order is a case study, not a statistical claim
about all orders or all workloads.

After all four streams finish:

```sh
target/release/ld-clustering compare \
  --baseline runs/main-seed42/text-llm.sqlite \
  --baseline-log runs/main-seed42/text-llm.calls.jsonl \
  --ld runs/main-seed42/text-ld.sqlite \
  --ld-log runs/main-seed42/text-ld.calls.jsonl \
  --expected 1000 --output runs/main-seed42/text-results.json
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

Price baseline, checked 2026-10-20, USD per million tokens:

| Endpoint/model | Ordinary input | Cache read | Cache write | Output |
| --- | ---: | ---: | ---: | ---: |
| Responses / GPT-6.1 Sol | $2.00 | $0.10 | $2.50 | $10.00 |
| Decisions / GPT-6 Luna | $0.10 | $0 | $0 | $0 |

Sol output usage already includes reasoning tokens. Rates are pinned from the
[Sol model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
and [Decisions guide](https://developers.openai.com/api/docs/guides/decisions).
The standard processing tier is used; no Batch or Flex pricing is assumed.

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
