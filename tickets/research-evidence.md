# Dataset, metric and prior-art evidence

Status: In Progress
Branch: feat-stream-clustering
Parent ticket: feature-stream-clustering.md
Evidence checked: 2026-10-20

## Question and scope

Choose reproducible public inputs and a comparison method that isolates the
assignment backend without pretending agreement with an LLM is ground truth.
Scope: 1,000 short English texts and 100 clothing images, independent streaming
arms, bounded cluster choices, shared LLM management policy. No trained classifier
substitutes for the decision-model API.

## Plan

- [x] Verify original dataset files, license notices and primary-source literature.
- [x] Establish failing deterministic selection and partition-comparison tests.
- [x] Implement pinned downloads, neutral image paths and provenance manifest.
- [x] Implement permutation-invariant ARI and positive-pair precision/recall/F1.
- [x] Run offline gates, a causal reversion check and live dataset preparation.

## Red evidence

The repository initially contains no dataset or metric implementation. A test run
against explicit placeholder failures (`cargo test --lib`, initial source
repository with no implementation commit) produced:

```text
---- metrics::tests::partition_agreement_ignores_cluster_names stdout ----
Error: agreement is not implemented

---- metrics::tests::crossed_partitions_have_negative_ari stdout ----
Error: agreement is not implemented

---- metrics::tests::splitting_and_merging_exchange_precision_and_recall stdout ----
Error: agreement is not implemented

---- metrics::tests::degenerate_partitions_and_invalid_lengths_are_defined stdout ----
Error: agreement is not implemented

---- datasets::tests::text_selection_has_exact_counts_hidden_labels_and_reproducible_order stdout ----
Error: text selection is not implemented
```

Parallel provider and persistence work had its own expected failing scaffolds in
the same run; these are outside this lane.

The added image and integrity tests also failed against their placeholders:

```text
---- datasets::tests::hashes_reject_different_source_bytes stdout ----
Error: checksum verification is not implemented

---- datasets::tests::image_selection_preserves_pixels_and_balances_classes stdout ----
Error: image selection is not implemented

test result: FAILED. 0 passed; 3 failed; 0 ignored; 0 measured; 11 filtered out; finished in 0.00s
```

## Validation

The initial repository has no implementation commit; these gates run on the
shared `feat-stream-clustering` source tree before its first feature commit.

| Gate | Result |
| --- | --- |
| `cargo test --lib datasets::tests` | 3 passed: quotas/order/hidden labels, exact pixels/IDX rejection, checksum mismatch |
| `cargo test --lib metrics::tests` | 4 passed: relabeling, negative ARI, splits/merges, degenerate partitions/invalid sizes |
| Controlled temporary reversion of `compare` and `select_text` | Both anchor tests reproduced their original `is not implemented` failures; implementation restored immediately |
| `cargo test --lib` after restoration | 24 passed, 0 failed, 1 explicitly paid live test ignored |
| `cargo clippy --all-targets -- -D warnings` | Passed |
| Root CLI live dataset preparation, seed 42; independent read-only audit | 1,000 texts, 100 images; all quotas, every PNG hash and dimensions, unique IDs and ordered-ID hashes verified |

The audit found 90 texts in each domain plus 100 OOS requests, and 10 images in
each class. Manifest JSON contains no absolute path. Ordered IDs are hashed as
compact JSON, so relocation does not alter order evidence; image bytes have
separate SHA-256 records. Actual seed-42 order fingerprints:

- Text: `a9c9e70ab35d25f27f9d76be9315fd222a5ead33261b0988d07db61d765086f0`
- Images: `37c854ecc3b6b19379b099baf19fde564efa2c7a60441a9da0f2291a4c7f1bf0`

Simplification review retained only helpers that isolate tested parsing,
integrity, hashing or output behavior. No dataset or benchmark claims depend on
downloaded filenames carrying evaluation categories. The downloaded license
notices and attribution are written beside the data; the source manifest records
all six immutable URLs and their verified SHA-256 hashes.

## Verified sources and decisions

- [CLINC150 original repository](https://github.com/clinc/oos-eval), revision
  `828f8093932c8fe6ca7936c3d2e52903b1c523de` (2021-06-01), supplies 4,500 test
  requests, 150 intents and a mapping to 10 broad domains. Direct decoding found
  450 test requests per domain and no duplicate text in either test or OOS test.
  Its [original license](https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/LICENSE)
  is CC BY 3.0. Select 90/domain plus 100 OOS; labels remain evaluation metadata.
- [Fashion-MNIST original repository](https://github.com/zalandoresearch/fashion-mnist),
  revision `b2617bb6d3ffa2e429640350f613e3291e10b141` (2022-03-21), explicitly
  declares MIT licensing. Direct IDX decoding found 10,000 28x28 grayscale test
  images, exactly 1,000/class. Select 10/class. PNG conversion preserves pixels;
  paths and text contain no class names. This is not evidence about natural-photo
  workloads. Retain the dataset's notice independently of the code's BSD license.
- Huang and He,
  [Text Clustering as Classification with LLMs](https://arxiv.org/html/2410.00927v1)
  (2024-09-30), separates generating labels, merging similar labels and assigning
  items. It identifies ambiguity and fragmentation as limits. This is close
  prior art for the management/assignment separation, not a novelty proof for
  the present implementation.
- Zhang et al., [ClusterLLM](https://aclanthology.org/2023.emnlp-main.858/)
  (EMNLP 2023), uses triplet comparisons to establish clustering perspective and
  pairwise questions to choose granularity within bounds. Its embedder training
  is not part of this implementation.
- Viswanathan et al.,
  [Large Language Models Enable Few-Shot Clustering](https://aclanthology.org/2024.tacl-1.18/)
  (TACL 2024), studies LLM guidance before, during and after clustering and
  cost/quality tradeoffs. Explicit grouping instructions are appropriate; the
  desired partition cannot be inferred uniquely from an unlabeled collection.
- [scikit-learn ARI documentation](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html)
  and [pair confusion matrix](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cluster.pair_confusion_matrix.html)
  define label-invariant partition and pair counting metrics. Positive-pair
  precision/recall expose merges and splits that raw pairwise accuracy can hide.

## Method recommendations

Use two independent mutable states with identical item order, bounds, prompts,
management model and maintenance schedule. Replaying one arm's actual management
decisions into both suppresses propagation of assignment errors; a frozen-catalog
replay is a separate local-choice control. Bootstrap from the received prefix
only. Record lineage and reassignment after merges/splits/retirement.

The comparison limit K and maximum active cluster count are distinct. Every
assignment request includes Other and at most K alternatives. Any tournament or
shortlist policy must be identical across arms and recorded. Report comparisons
as well as requests.

Primary metrics compare final partitions to the LLM reference. Each rejected
point is a distinct singleton, so a large common Other bucket cannot create
spurious positive pairs. Report Other rates separately. Ground-truth labels are
supplementary, and OOS labels do not define a universally correct Other policy.
Empty comparisons are invalid; identical singleton or one-cluster partitions
score 1, while merging/splitting no-positive-pair partitions has pair F1 0.

Timing and cost include creation, maintenance, reassignment and retries. Preserve
returned model IDs, request/response hashes, token categories and pricing date.
Use equal concurrency. Distinguish live calls from cache replay. Dollar savings
remain unknown if the decision-model price is unavailable. Several fixed stream
orders are needed for an order-sensitivity claim; one run remains a case study.

## Maintenance sampling correction before the primary runs

Independent review found that the 40-example review budget could hide the newest
novelty. The original code computed evenly spaced Other indices using a desired
quota of 24, then stopped as soon as named-cluster examples consumed the overall
budget. With 16 populated clusters supplying two examples each, only eight Other
examples fit. Among 100 Other points those offsets were 0, 4, 8, 12, 17, 21, 25
and 30: the latest 69 points were never shown, even when they triggered review.
The invalid assumption was that each group's desired quota equaled its actual
share of the global budget.

A regression with 16 two-point named clusters and 100 Other points failed before
the fix:

```text
---- store::tests::crowded_review_samples_include_the_oldest_and_newest_other stdout ----
novelty-triggered review must see the newest Other point even when named clusters consume most slots
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 27 filtered out; finished in 0.01s
```

`Store::examples` now allocates actual quotas across groups first, retaining the
same round-robin limits of two per named cluster and up to 24 Other examples.
Each group's chosen points then span its full history using its allocated quota.
Two or more slots include oldest and newest; one slot selects newest. A zero
budget returns no examples. These are deterministic bounded samples, not claims
that every member or every semantic subtopic was examined.

Scoped sibling checks cover the crowded catalog, one-slot novelty and zero
budget. Six store tests pass. Temporarily restoring the original index expression
in a disposable source copy reproduced the same missing-newest regression.
That check reused the development target directory and briefly displaced its
cached test binary; forcing recompilation of the unchanged working source
removed the stale artifact. Final `cargo test --lib` from the actual repository
passed 32 tests, with 0 failures and one paid live test explicitly ignored.
`cargo clippy --all-targets -- -D warnings` also passed after the sampling fix.

No further conservation, restart or bounded-choice blocker was found in the
engine/store review. Transactions preserve points and pending work across
maintenance, resume verifies the persisted stream prefix, and assignment calls
only receive their bounded page. Paging deliberately returns the first matching
cluster; its ordering bias remains a reported limitation. Rename operations also
reassign affected members because their membership descriptions may change.
