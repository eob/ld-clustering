# Contextual streaming: higher coverage with a text grouping tradeoff

All eight reserved streams completed: Original/Contextual × Sol/Decisions on
1,000 text requests and 100 natural photographs. Every worker exited zero with
its full input persisted and no pending reassignment work. The independent
audit is verified. These inputs are separate from discovery and the preceding
fixed-catalog evaluation.

The contextual policy combines concise membership guides, complete-catalog
management context, frozen findings from the earlier control, and global
reconsideration after catalog changes. Each arm learns its own evolving catalog.
This comparison therefore measures the combined policy and partition agreement;
category-ID equality across arms is inapplicable. It does not isolate wording,
length, remembered examples or reconsideration, and neither model is semantic
ground truth.

## Full reserved cohorts

| Cohort and policy | n | ARI | Pair precision | Pair recall | Pair F1 | Sol named | Decisions named |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Text Original | 1,000 | 0.538096 | 0.811199 | 0.453763 | 0.581982 | 994 | 708 |
| Text Contextual | 1,000 | 0.609758 | 0.682267 | 0.631516 | 0.655911 | 998 | 908 |
| Photos Original | 100 | 0.818656 | 0.905297 | 0.788811 | 0.843049 | 95 | 98 |
| Photos Contextual | 100 | 0.971144 | 0.957105 | 0.994429 | 0.975410 | 95 | 97 |

Pair precision and recall compare the two learned partitions; they are not
semantic classification precision or recall. Each Other item is treated as a
separate singleton in these primary pair metrics.

| Cohort and policy | Both named | Sol named / Decisions Other | Sol Other / Decisions named | Both Other |
| --- | --- | --- | --- | --- |
| Text Original | 707 | 287 | 1 | 5 |
| Text Contextual | 908 | 90 | 0 | 2 |
| Photos Original | 94 | 1 | 4 | 1 |
| Photos Contextual | 95 | 0 | 2 | 3 |

Text Decisions names 200 more items, while full-cohort ARI and pair F1 improve.
This is not a gain obtained by both methods rejecting more. A post hoc common
subset exposes a tradeoff that the full score alone conceals.

## Conditional common-named diagnostic

After observing all outcomes, retain only items named by both classifiers under
both policies. Use exactly the same retained item IDs for each policy. These
are conditional, selected diagnostics: they exclude rejection cases and do not
replace full-cohort results or provide a new confirmation experiment.

| Same common subset | n / full n | Original / contextual ARI | Original / contextual pair F1 |
| --- | --- | --- | --- |
| Text | 674 / 1,000 | 0.787131 / 0.721809 | 0.819144 / 0.760726 |
| Photos | 93 / 100 | 0.829953 / 0.977568 | 0.855835 / 0.981366 |

The text subset regresses while coverage rises on the full stream. The result
supports a measured coverage/grouping tradeoff, not a general claim of better
semantic classifications or proof that rejection alone causes the full-score
gain. The photo improvement persists on its common subset. One input order and
one independently learned catalog per arm do not establish population effects.

## Work and accounting

| Arm | API calls | Reevaluations | Recorded API cost |
| --- | --- | --- | --- |
| Text Original Sol | 1,606 | 300 | $2.296944 |
| Text Original Decisions | 9,690 | 6,441 | $0.7377214 |
| Text Contextual Sol | 8,131 | 5,964 | $10.6207179 |
| Text Contextual Decisions | 10,876 | 8,283 | $0.8146604 |
| Photos Original Sol | 152 | 51 | $0.7149612 |
| Photos Original Decisions | 138 | 35 | $0.1408902 |
| Photos Contextual Sol | 279 | 171 | $0.8107719 |
| Photos Contextual Decisions | 348 | 242 | $0.2926858 |

The complete streaming API ledger is **$16.4293528**, with 31,220 attempts,
two error attempts, two retries, no refusals, and no unknown usage or pricing.
These are frozen-price token estimates, not invoices. Coding and coding-harness
qualitative-review compute are outside this ledger. Contextual Sol text performs
far more work than Original; ID moves and reevaluations do not establish semantic
corrections. Concurrent loop times are not additive elapsed time or isolated
performance measurements.

The earlier fixed-catalog control remains unchanged: direct agreement fell
82.0%→52.2% on 1,000 requests and 96%→81% on 100 photos. Its original-photo
review remains 57 accepted / one failed / 42 unattempted, and its $7.7162398 known
subtotal is still incomplete. The complete streaming ledger does not repair
that separate accounting limitation.

## Qualitative evidence and algorithm artifacts

A blinded coding-harness review covers eleven reserved photos and 44 anonymous
assignments, including agreements. It distinguishes a vehicle-wreckage error,
reasonable Sports/People granularity, a persistent mannequin boundary, and
defensible Other for an uncovered cooking appliance. These selected judgments
are fallible, not population accuracy or independent human truth.

The historical contextual Sol text episode at 53 received items illustrates a
maintenance artifact: retiring all eight categories queues 53 reevaluations,
which produce Other without classifier requests because no candidates remain.
Forty-five previously named items temporarily become Other; the other eight
were already Other. Novelty management at 61 creates ten categories and queues
all 61 items again. The active-category cap did not require retirement, and the
raw plan gives no public rationale. This episode is retained rather than
interpreted as evidence of intent or semantic merit.

## Evidence and validation

- Frozen streaming source: `f78dcf91409e9b088e78f5995e2a488a0ad63bc8`.
- Executable SHA-256: `d16f7d289af670f7539f28ccec6474602e3735f54cfbafb24fff884cb627e603`.
- Registered protocol SHA-256: `65edc12008dd26404a52406a31f1c135e628642e4e8ac69e213882f8d60c0070`.
- Independent audit SHA-256: `a939309be01b79663ca6a517c021aaee459b1aa6a2365cfdcdcfb5a9886417fd`.
- Independent metric/checker SHA-256: `2c2b18777e1f1b799255d39f69b14838dbfa946f10f17ac36171a1ca0ddbb40d`.

Full comparison JSON and exact common-subset IDs are retained separately under
`runs/guided-agreement-seed1042/streaming/comparisons` and `posthoc`. The
independent checker binds source, binary, registered inputs/context, raw request
bodies, accepted replies, final SQLite assignments and Decimal all-attempt costs.
A separate read-only enumeration from terminal SQLite states reproduces all
four full comparisons and both same-item conditional diagnostics.

The checker does not prove the manager's exact historical example-selection,
maintenance-trigger cadence or queue membership, and it does not rebuild the
binary. Recorded validation is 115 offline Rust passes plus one ignored paid
test, 93 Python tests, rustfmt and Clippy. Streaming archive finalization is
separate from the immutable control archive; its external manifest anchor is
recorded after verification.

Streaming archive creation and separate anchored verification now pass for407
input/run files. Manifest SHA-256:
`75d694a497fdf0dfab14159b8f978606ce89eeb17efb646802fe2106fc79d9f4`.
The external receipt is `streaming-archive-verification.json` beside the archive.
The14MB independent audit is retained exactly inside the raw run payload;
smaller comparisons and conditional diagnostics have readable mirrors.
