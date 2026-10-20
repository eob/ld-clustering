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

## Completed image comparisons and interpretation

The first cohort's complete 100-point image pair is retained under
`experiments/2026-10-20-main-seed42/`. Its text reference stopped at 216/1,000
with pending reassignment after supervisor SIGTERM; the signal source is not
established. Its text LD run finished but contains one HTTP 503 attempt without
reported usage. Consequently that cohort is archived as interrupted and cannot
support a complete text comparison. The image replicate remains valid. The
replacement cohort is `runs/main-seed42-detached`, initially supervised by user
unit `ld-clustering-main-seed42-20261020.service`. Neither cohort changes frozen
runtime source, executable, data selection or order.

Both completed image pairs were independently checked by enumerating every
unordered point pair, with exact rational ARI arithmetic. Raw databases were
opened read-only; image bytes linked anonymized model requests back to persisted
points. Reconstructed first-cohort assignment histories equal the final states.
The frozen Rust `compare` command agrees with the independent metrics.

| Image cohort | Points/arm | ARI vs reference | Pair F1 | LD Other | Reference Other |
| --- | ---: | ---: | ---: | ---: | ---: |
| First, complete image replicate | 100 | 0.338363075 | 0.419853539 | 31 | 0 |
| Detached replacement, complete images | 100 | 0.173153868 | 0.256622517 | 37 | 0 |

The manager's initial requests are identical JSON within each pair and across
these image replicates: canonical SHA-256
`5eeee1f39b62b37683a82297b42ffbaf6bfe7a5ccc251915a540be5ac9c37105`.
Nevertheless, the first reference splits Sneakers/Boots/Sandals while first LD
starts with Footwear; in the replacement pair the reference starts with broad
Footwear and LD separates those types. These taxonomy differences arise before
the assignment backends receive their first point. Granularity is not an
intrinsic property of the decision backend inferred from these observations.

For the first image pair, 258 pairs are grouped by both systems, 302 only by LD,
411 only by the reference, and 3,979 by neither. Of the 302 extra LD grouped
pairs, 110 come from its broad Footwear group and 150 from Sweaters/sweatshirts.
Of the 411 missing reference pairs, 249 touch at least one LD Other point.
Actual review prefixes differ despite identical trigger rules: reference
20/45/70/95/100; LD 20/34/59/79/100. Reference maintenance creates Pants, Bras
and Skirts; LD creates Trousers and Underwear, retires an empty Handbags cluster,
then creates Bags/handbags. Neither image run merges or splits clusters.

Granularity does not explain every first-cohort assignment. All ten bag-labeled
images finish as seven Other plus three Trousers in LD; the reference puts seven
in Handbags, two in Pants and one in Shirts. The last LD review creates a broad
bag description, followed by 62 calls: 31 first pages and 31 bag-only second
pages, all returning Other. Three bags already in Trousers are not reconsidered
by a Create operation, which queues Other rather than unaffected named groups.
Manual inspection of eight original PNGs found visible bag bodies and handles
in IDs `d5e9d0e842219c35031a`, `93e1be08ebd0dd49a154` and
`0f7bc3589bcaf6a46799`, while some bags called Pants by the reference have
pouch-like silhouettes. This is a small, non-blind visual spot check, not human
validation of the full dataset. Those same three images land in Bags/purses in
replacement LD; seven bag-labeled images still remain Other.

In the replacement image pair, independent pair counts are TP 155, FP 198,
FN 700, TN 3,897; exact ARI is `10343/59733`. Rejection contributes 505 of the
700 missing reference grouped pairs. Its reference Footwear contains all 30
boot/sandal/sneaker-labeled images; replacement LD names only 16 of them and
rejects 14. This accounts for 315 missing pairs involving rejection and 59
further pairs separated among its named footwear types. A broad LD Shirts/tops
group contributes 179 of the 198 extra grouped pairs. Neither run reaches the
16-cluster cap, so rejection is not forced by catalog overflow.

Post hoc diagnostics change the population or taxonomy and never replace the
100-point headline:

| Diagnostic | First pair ARI / F1 | Replacement pair ARI / F1 |
| --- | --- | --- |
| Mutually covered points only | 0.404738 / 0.526531 (n=69) | 0.318273 / 0.440967 (n=63) |
| Merge finer footwear types to the other arm's broad group | 0.405677 / 0.490013 (n=100) | 0.254005 / 0.337806 (n=100) |
| Both transformations | 0.577048 / 0.675229 (n=69) | 0.456318 / 0.561680 (n=63) |

Neither reference is ground truth. Dataset-label ARI is 0.415459 versus 0.301902
for first reference/LD, and 0.444128 versus 0.213609 for replacement reference/LD.
These are descriptive results for the same small grayscale sample and intended
grouping task, not a universal model ranking. A frozen-catalog control is separate
work and must not be mixed with these independently evolving systems.

Replacement image timing is complete: 663.815 seconds reference and 223.233
seconds LD, with retry time included. Independently priced recorded usage splits
as follows: reference planner $0.051968 plus assignment/reassignment $0.219560,
total $0.271528; LD planner $0.077089 plus known assignment/reassignment
$0.0100359, total known $0.0871249. LD journal source JSONL lines 88 and 242
contain HTTP 503 attempts with no reported usage. Their costs are unknown, not
zero; an exact fully accounted cost ratio is therefore not established.

External text recovery must preserve its own timing distinction: after a clean
plan-validation rejection, SQLite `wall_ms` sums the measured active-loop
segments across restart. Manual pause and CLI validation are excluded. A true
`timing_complete` flag after graceful failure does not make that sum uninterrupted
start-to-finish elapsed time. Retain the external supervisor's resume history,
calendar duration, raw journal failures and all known charges separately.

## Preserved pre-amendment cohorts and archival handoff

Both original-protocol cohorts are interrupted text experiments. Their completed
100-point image pairs remain separately identified replicates; neither supplies a
full 1,000-point text headline. A new four-arm amended-protocol cohort is required.

The second terminal cohort was captured and independently verified at
`experiments/2026-10-20-main-seed42-detached`. Its immutable manifest SHA-256 is
`ae602400ee66cb701d1582f501eb861b0a35b9b55e1f540839ba6ba659e47035`.
Every raw SQLite state, request journal and process log was copied byte-for-byte
into timestamp-zero gzip, with original/decompressed hashes checked. SQLite
integrity and foreign keys pass; every persisted Item matches its pinned input
prefix. Shared inputs, licenses and pricing are byte-identical to the first
archive. Root separately compared all eight DB/journal raw byte hashes. The
original resume supervisor/history, process logs, and the unrun frozen-control
waiter/catalog are retained under `operational/`. Collected systemd unit results
remain unknown rather than being inferred successful.

The second text reference stopped at 397 persisted points with 19 pending
reassignments and possible unrecorded in-flight usage. Text LD stopped at 779
with no pending reassignments after one external graceful resume. The native
refusal is preserved at original journal physical line 9,582: HTTP 200,
`answer.type=refusal`, 15 input / 0 output tokens, independently priced known
charge $0.0000015. The input is classification evidence about a credit-card
question; no real credit-card action was requested. Text-LD missing usage remains
unknown at lines 4,674 and 8,295; image-LD unknown rows remain 88 and 242. Known
recorded totals are $1.1335695 text reference, $0.7203811 text LD,
$0.2715280 image reference and $0.0871249 image LD. These are not complete final
text costs, and unknown usage is never zero. Full text comparison was deliberately
not generated; complete image scores agree with independent exact-pair metrics.

Preserved original runtime is `59656c06db2e2ec8599b3bc31f90144a451e27b3`;
launch checkout is `bdee72c39faf99460b641b852859c8624ec42432`. The exact original
executable was copied outside live build paths to `/tmp/ld-clustering-v1-frozen`,
SHA-256 `ef1d211d0808a688554f46995cd3370ee98d53b78760dff2fd2026c382c203ee`.
The archive contains its hash and local-copy provenance, not executable bytes.
Later source changes do not alter these immutable manifests or raw records.

The original disposable complete-cohort helper and instructions are preserved as
`/tmp/ld-archive-final-v1.py` and `/tmp/ld-archive-final-v1.README.md`. The actual
second-cohort interrupted capture used `/tmp/ld-archive-interrupted-v1.py`, also
preserved in its archive. These tools make no API calls. The v1 complete-cohort
helper intentionally refuses the interrupted text and must not be used to claim
completion of either prior cohort.

The amended-protocol helper remains `/tmp/ld-archive-final.py`, with usage in
`/tmp/ld-archive-final.README.md`. It is being adapted for explicit new runtime,
launch and executable pins, the unchanged dataset pins, clean four-arm runs, and
mandatory external history whenever recovery is declared or observed. Persisted
run-start/finish and refusal events will be checked against complete counts and
raw charged attempts. The helper stays an operational verifier; Rust remains the
clusterer implementation. No new archive is run until root confirms all primary
and control processes terminal and supplies the final green runtime pins.


The amended helper now requires full explicit runtime/launch/executable pins and
uses ordered persisted run_start/run_finish events to prove fresh invocation
boundaries. It rejects an omitted observed recovery, nonempty unresolved queues,
and mismatched refusal flags/events; it independently prices every reported
charged attempt and preserves unknown usage. Nine focused offline checks pass.
Independent review caught a legitimate nullable transport-response shape that
would have blocked archival after an otherwise successful retry. The focused
check first failed with `AttributeError: 'NoneType' object has no attribute 'get'`;
response/array guards and nullable ledger usage access now pass a failed-null
attempt followed by same-body successful attempt2, retaining unknown physical
JSONL line2 rather than assigning zero cost. New executable full synthetic
creation/replay validation is pending the frozen amended runtime pins.
