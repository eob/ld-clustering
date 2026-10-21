# Measure whether contextual category guidance improves LLM–Decisions agreement

**Status:** In Review
**Type:** Investigation
**Filed:** 2026-10-20
**Branch:** feat-guided-agreement-experiment
**Pull request:** https://github.com/eob/ld-clustering/pull/3 (draft; experiment in progress)

## Goal / failure mode

Implement and run a controlled comparison of original category descriptions and
jointly rewritten membership guidance. Measure agreement between Sol assignments
and native Decisions assignments without letting increased rejection masquerade
as improvement. Explain remaining disagreements with blinded LLM review and
concrete examples, then test the improved manager in the evolving stream system.
Publish the findings in the existing illustrated report.

## Evidence and reproduction

The published v2 experiment uses independently evolving catalogs and CLINC150
text plus 28×28 Fashion-MNIST. Its image fixed-catalog diagnostic reuses the
baseline's evaluation images for catalog construction. Neither comparison
isolates description quality on fresh held-out examples. Immutable baseline
evidence remains in `experiments/2026-10-20-main-v2-seed42/` and
`experiments/2026-10-20-frozen-images-v2-seed42/`; measured runtime is
`9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c`.

Current assignment prompts receive the broad clustering task as well as the
instruction to select existing categories. Store maintenance revisits affected
members and Other, so creating a new competing category need not revisit an
earlier named assignment. These mechanisms require separate controlled and
streaming checks; old anecdotal errors are hypotheses, not new observations.

## Context / research brief

Question: with category IDs, labels, order, data and paging fixed, does explicit
membership and neighboring-category guidance improve LLM–LD agreement while
preserving useful named-category coverage? The audience is a reader deciding
whether shared catalog design, rejection policy, or streaming maintenance is the
next useful intervention. This is one case study, not a universal accuracy claim.

Hypotheses: (1) guidance resolves implicit context and overlap; (2) apparent gains
come from both methods choosing Other; (3) agreement remains limited by reference
instability, reasonable interpretations, paging or the decision model itself.
The semantic quality of both methods is distinct from reproducing Sol.

## Plan

1. Freeze fresh, disjoint discovery, controlled-evaluation and reserved-stream
   partitions, licenses, hashes and protocol before paid calls. Select natural
   color photographs with native long edge ≥512, preserving original aspect and
   image bytes; inspect actual inputs. Target discovery 200 text/60 images,
   controlled 1,000 text/100 images, reserved stream 1,000 text/100 images.
2. Implement offline-tested Rust catalog, evaluation, repeat, review and metrics
   tooling. Generate one discovery-only catalog per modality. Freeze structure;
   jointly rewrite descriptions using the full catalog and discovery evidence.
3. Run original/guided × LLM/LD on identical held-out items and category order,
   K=8 plus Other, stable first-match paging. Use the same clean assignment-only
   objective in every new controlled arm. Preselect repeat subsets of 100 text
   and 25 images per description condition before observing results.
4. Measure direct IDs, coverage, assigned/Other cross-tab, confusion, per-category
   disagreement, ARI and pair metrics, conditional jointly assigned agreement,
   paired gains/losses and LLM repeat consistency. Account for all calls,
   retries, refusals, usage, cost and elapsed time; unknown usage stays unknown.
5. Review disagreements and sampled agreements with backend identity hidden,
   shuffled candidate identities, full applicable catalogs, evidence and
   severity. Inspect high-resolution image examples and page/order traces.
6. Interpret the controlled comparison before changing the streaming manager.
   Test contextual manager guidance and reconsideration of earlier assignments
   on the separately reserved stream. Report independent-catalog confounding.
7. Archive auditable selected inputs and raw evidence; update README and the
   existing website report, preserving the dated v2 results. Deliver through PRs.

## Acceptance criteria

- Discovery/evaluation/reserved inputs are disjoint; no upstream labels leak
  into prompts. No tiny-image upscaling is counted as a larger dataset.
- Original and guided fixed catalogs have identical IDs, labels, order/count.
  Both backends use the same condition's descriptions and paging policy.
- New runs preserve exact source/binary/input/catalog/prompt pins, complete
  attempts, model IDs, usage and timing; incomplete runs cannot appear complete.
- Primary agreement includes Other, accompanied by named-ID agreement and full
  coverage cross-tabs. Subset and post hoc results are explicitly labeled.
- Concrete blinded reviews consider shared errors and reference-model errors;
  no held-out description tuning or cherry-picked reruns.
- Offline tests, formatting and Clippy pass; report visual inspection and local
  CI preflight pass before publication. Prior evidence remains unchanged.

## Current state

The controlled experiment is complete and independently verified with an
incomplete original-photo review. Original→guided direct agreement is
820→522 / 1,000 text items and 96→81 / 100 photographs. Matching named IDs
also fall, while joint-Other counts stay 11 and 5. One generated rewrite
changes content and length together; semantic correctness is separate from
reproduction of Sol. The automated reviews expose clear Decisions errors,
reference errors and reasonable alternatives. Full findings and reproduction
pins are in the experiment README and immutable archived evidence.

All controlled paid stages terminated by 2026-10-21 00:07:08 UTC. The frozen
runtime is `9f80d8400ac23c70c9e5dd2e23c953cdee362410`; the separately corrected
offline analyzer is `616b5d0d707b926db15e73cc43128fac09904e3c`. Independent
verification reconstructs 6,439 observed attempts and $7.7162398 known cost.
The failed original-photo review remains 57 accepted / 1 failed / 42 unattempted,
with incomplete accounting flags preserved. Control archive manifest is
`20d8a470bf9cfb63b5406b1b883f1f23199def56e9577928a8cc9dd9b908b1fa`.

The adaptive eight-arm reserved-stream follow-up launched at
**2026-10-21 00:45:43 UTC** under `ld-guidance-streaming-1042.service` after
interpreting the control. All eight fresh databases began with the registered
24-item bootstrap. Each modality uses the same reserved order and schedule
across Original/Contextual × Sol/Decisions. Contextual combines compact catalog
guidance, frozen prior findings and global reconsideration; the catalogs evolve
independently, so partition agreement and coverage are primary. **All eight arms
are terminal with exit zero, complete 1,000-text or 100-photo inputs, and no
pending reassignment work.** Independent full-stream verification passes with
audit SHA-256
`a939309be01b79663ca6a517c021aaee459b1aa6a2365cfdcdcfb5a9886417fd`.

Full text ARI improves 0.538096→0.609758 and pair F1 0.581982→0.655911;
Decisions coverage rises 70.8%→90.8% and Sol coverage 99.4%→99.8%. The same
674 items named by all four text arms give the opposite post hoc grouping
diagnostic: ARI 0.787131→0.721809 and F1 0.819144→0.760726. This is a
coverage/grouping tradeoff, not a clean semantic-accuracy improvement. Full
photo ARI improves 0.818656→0.971144 and pair F1 0.843049→0.975410;
Sol coverage stays 95%, Decisions coverage is 98%→97%, and the common-named
93-photo diagnostic also improves. Conditional subsets never replace the full
primary cohorts. The combined intervention and independently evolving catalogs
prevent attribution to description quality alone.

The streaming API ledger is complete at $16.4293528 across 31,220 recorded
attempts, including two errors and two retries, with no refusals or unknown
usage/pricing. Contextual Sol text accounts for $10.6207179, 8,131 calls and
5,964 reevaluations versus Original Sol text $2.296944, 1,606 calls and 300
reevaluations. Coding-harness review compute is outside the ledger; queue
evaluations and ID moves do not establish semantic corrections.

Streaming runtime is frozen at `f78dcf91409e9b088e78f5995e2a488a0ad63bc8`,
release binary SHA-256
`d16f7d289af670f7539f28ccec6474602e3735f54cfbafb24fff884cb627e603`.
The release inspector exactly reproduces the registered request preflight.
Recorded final local gates passed 115 offline Rust tests (one paid ignored),
93 Python helper tests, rustfmt and Clippy. Both graceful SIGTERM and violent
supervisor SIGKILL lifecycle checks cleaned up all eight workers and their
eight descendants with zero API calls. Real report data and licensed photo
examples are exported and being integrated. Separate streaming archive
finalization, report validation and publication remain; the immutable control
archive and its incomplete original-photo review are unchanged. Completed
streaming findings are recorded in
`experiments/2026-10-20-guided-agreement-seed1042/STREAMING-RESULTS.md`.

Source base is main `1fd37ebb28e956a380ba8587815d4aa738719510`. The source and
report draft PRs retain the active work until all requested evidence is ready.

## Decisions and durable findings

- Description quality is the first intervention: no taxonomy restructuring in
  the controlled comparison, and assignment-role cleanup is shared across arms.
- Dataset labels aid sampling only; they are not semantic ground truth.
- The reserved streaming sample prevents the controlled review from shaping
  evaluation of the subsequent manager change.
- Full raw image journals may require lossless compressed archives; decompressed
  byte hashes must remain independently verifiable.
- Source and report use separate clean worktrees. Website ticket:
  `eob/kaya-web:tickets/open/feature-ld-guided-agreement-report.md`.
- The official Open Images mirror alone is insufficient proof of native
  resolution: initial checks found mirror dimensions exceeding some fetched
  originals. Require independently verified original dimensions at least as
  large as supplied dimensions (accounting for rotation), matching aspect ratio,
  and native long edge ≥512. Retain original byte hashes when available and
  explicitly mark unavailable original bytes; do not invent a source hash.
- Preplanned order/page diagnostics use the same guided repeat subset: reverse
  order at K=8 and all categories on one page at K=16. These are secondary
  sensitivity checks, separate from the fixed-order K=8 primary comparison.
- Actual text catalogs span two K=8 pages; images fit on one page. Therefore
  multi-page routing cannot explain primary fixed-image disagreements, and image
  K=16 produces identical request bodies: it is an extra repeat, not a page-count
  intervention. The preplanned reverse-order comparison still changes choice
  order within the page. No categories were added to manufacture pagination.

### Reserved-stream design

Keep Original behavior and legacy saved configurations compatible. Bind a
separate manager-policy/context descriptor, and compare matching descriptors.
For the contextual policy, an actual catalog change should transactionally
reconsider all persisted points; exact no-op plans should not add that work.
Capture previous category IDs when queueing, before merge/split/retire sets
assignments to interim Other. Count reevaluations separately from actual ID
moves, and mark legacy pending origins unknown. Run reserved photographs from
the stream-input directory with absolute command paths, preserving existing
CWD-relative image semantics. Freeze the precise contextual prompt and evidence
only after the controlled comparison and review are understood.

### Completed primary arms

The 100 held-out image pairs are complete. Short descriptions produce 96/100
matching IDs (91 matching named IDs); the jointly rewritten guides produce
81/100 (76 matching named IDs). Paired changes are 0 gains and 15 losses. Both
conditions have 5 shared-Other items, so rejection does not explain this loss.
Sol coverage changes 95→94 and Decisions coverage 92→90. Nine guided disagreements
are People versus Food; three are Electronics versus Buildings. All 200 raw
Decisions image payloads match the selected JPEG bytes. Example raw response
`48599a29fabce63c6bc1` changes from choice `4` to choice `5`, with the correct
stable choice IDs in both requests. This excludes a local label-mapping error
for that case; it does not establish the model's causal failure mechanism.

The primary text comparison is now complete: direct agreement falls 820→522
out of 1,000; matching named IDs fall 809→511. Sol coverage changes 977→974 and
Decisions coverage 935→906. Both conditions have 11 joint-Other items (counts,
not necessarily the same identities). Paired changes are 64 gains and 362 losses;
Sol changes 77 IDs and Decisions 432. ARI falls 0.718→0.633 and pairwise F1
0.751→0.675. The independently recomputed primary metrics are preserved in
`runs/guided-agreement-seed1042/primary-comparison.json`.

Do not describe the controlled comparison as the completed two-phase experiment,
retune held-out guides,
or infer that longer guidance generally hurts all workloads. The tested rewrite
changes wording and length together: image descriptions grow from 142 to 1,094
whitespace-delimited words, text from 215 to 1,435. This is one generated rewrite,
not a length-matched or cross-reference ablation. A supplemental
25-case anonymous visual inspection is separate from the registered image
review census and cannot support a population-accuracy estimate.

## Validation evidence

Base: `1fd37ebb28e956a380ba8587815d4aa738719510`.
Compiling fixed-ID metrics stubs established this behavioral Red witness:

```text
running 6 tests
Error: fixed-ID agreement metrics are not implemented
Error: paired fixed-ID gains are not implemented
Error: predeclared repeat consistency is not implemented
test result: FAILED. 1 passed; 5 failed; 0 ignored; 0 measured; 50 filtered out
```

Launcher feature check before implementation:

```text
$ bash scripts/guided-agreement.sh --help
bash: scripts/guided-agreement.sh: No such file or directory
```

The implemented launcher passes `bash -n` and its help check. Rust behavioral
Green and causal reversions now pass. The final source gate is 72 library tests,
3 CLI tests, 2 offline analyzer tests and 11 frozen-catalog example tests;
one paid-live test is explicitly ignored. `cargo fmt --check`,
`cargo clippy --locked --all-targets -- -D warnings` and `git diff --check` pass.

Dataset Red command:
`cargo test --locked agreement_data::tests::text_partitions_exclude_prior_normalized_duplicates_and_each_other -- --exact`.

```text
running 1 test
test agreement_data::tests::text_partitions_exclude_prior_normalized_duplicates_and_each_other ... FAILED
---- agreement_data::tests::text_partitions_exclude_prior_normalized_duplicates_and_each_other stdout ----
Error: disjoint partition selection not implemented
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 55 filtered out; finished in 0.01s
```

Compiling provider/catalog/paging tests also established these causal failures:

```text
provider::successful_reply_from_unrequested_model_is_rejected_and_charged
a successful HTTP reply from another model must fail the experiment
agreement::rewrite_preserves_exact_ids_names_order_count
rewrite mutation0 must be rejected
agreement::paging_visits_later_candidates_and_records_each_page
Other must advance to every later page
left: Other
right: Cluster(11)
```

Metrics/review causal reversions reproduced the original fixed-ID error and
`parsed judgment must stay bound to preserved generated response`, then restored
Green. A malformed nullable alternative also failed before the fix with
`a missing alternative cluster ID must not silently propose Other`; explicit
null remains the valid Other representation.

Independent launcher review found diagnostics used `classify` while the harness
requires a primary-bound repeat. The actual offline CLI reproduced:

```text
Error: pagination diagnostics require the guided repeat subset
```

The launcher now uses `repeat` with the matching backend's primary reference,
original held-out input and a positive repeat index. All eight modality × backend
× diagnostic-policy dry runs pass without an API key or paid artifacts. This
scoped sibling check found no other command-family mismatch.

| Gate | Source base | Result |
| --- | --- | --- |
| `cargo test --locked --all-targets` | `fa20a5920cc81bffc12af12206fe016f7d5525b9` + experiment changes | 88 offline passed; 1 paid ignored |
| `cargo fmt --check` | same | pass |
| `cargo clippy --locked --all-targets -- -D warnings` | same | pass |
| Dataset unit tests / causal reversion | same | 4 Green; expected missing-selection Red restored |
| Independent dataset and relocated request audit | frozen dataset `c61ce5b…` | pass; identical byte/content pins |
| Diagnostic CLI matrix | same | 8 dry runs passed; key absent; zero paid artifacts |
| Report baseline `bun run ci:preflight` | product base `36eb004ae` | all fast lanes passed, including 4 WASM byte checks and 117 native parity tests |

### Review execution and additional diagnostics

The original-image review stopped after 58/100 attempted cases: 57 accepted, one
failed and 42 not attempted. The HTTP 200 response had status `incomplete` and
reason `max_output_tokens` at the fixed 8,192-output-token limit; no refusal. Its
known charge is $0.086291, included in the arm's $0.4766555 known subtotal. Keep
the recorded cost-history, cost and timing completeness flags false. Preserve
this terminal arm rather than rerunning it to complete the review census. The
other three review arms subsequently completed 100 accepted judgments each. All
eight diagnostics completed under the unchanged runtime. The failed review is
retained as a terminal/incomplete arm; no paid stage was repeated.

A post hoc confusion diagnostic finds that different-named assignments often
move to the next catalog entry: 339/380 guided text disagreements and 12/13
guided image disagreements. This is an association, not a proven off-by-one or
model mechanism. Raw request choice IDs and response values agree with the
stored assignments. Reversed choice order and page-size diagnostics remain
necessary; do not shift IDs or retune the frozen descriptions.

### Completed diagnostic subsets and review interpretation

On the preselected 100-text guided subset, matched Sol–Decisions direct agreement
is 49/100 at primary K8, 61/100 with reversed order and 34/100 with all ten
categories on one K16 page. Named matches are 47, 58 and 33; joint-Other counts
are 2, 3 and 1. Reversal changes 57 Decisions IDs versus four Sol IDs; K16 changes
28 Decisions and two Sol IDs. Reversal changes page composition as well as
order. K16 changes candidate availability and is another stochastic pass; neither
is a pure causal ablation. On the 25-photo subset, direct agreement is 21/25
primary, 22/25 reversed and 22/25 K16. K16 Decisions repeats all 25 IDs; Sol changes
one. These are secondary subsets, separate from the full primary comparison.

The completed guided-photo reviewer prefers Sol in 16/19 disagreements, Decisions
in two and finds both reasonable in one. It identifies clear People→Food errors,
unjustified rejection of visible electronics, but reasonable stove/courtyard
boundaries and insufficient evidence for the granular close-up. The guided-text
review also rejects Sol's Other for clear instructional requests; one case
(“search information on how to apply foundation”) supports neither Sol Other nor
Decisions Cars and proposes Knowledge. All 30 sampled guided-text agreements
are supported by that reviewer; 80/81 photo agreements are supported and one
shared rejection is unclear. These are same-family automated assessments, not
human truth or a population accuracy estimate. Text strata are deliberately
balanced, so unweighted review preferences are not overall accuracy.

### Offline analyzer numeric parsing defect

The first actual frozen-analyzer invocation rejects a review key before writing
analysis.json: `Error: frozen review identity/selection key differs`. Instrumented
reproduction isolates one JSON-decoding ULP: saved 2/11 parses as
0.18181818181818185 while the rebuilt rational is 0.18181818181818182. All IDs,
order, strata, choices, A/B flags, denominators and payload hashes match. An
independent probe linked to the frozen release parser finds 21 original-text
and 12 guided-text keys affected by ±1 ULP, and zero photo keys.

A focused failing test pins exact probability round trips, including every
affected ratio. Enable serde_json's float_roundtrip feature, retain strict
identity/equality checks, and pin the corrected offline analyzer separately.
The paid runtime, catalogs, raw responses and selections remain unchanged.
Full Rust gates pass 89 offline tests (one paid ignored), formatting and Clippy.
Causal feature removal reproduces the failure; restoration passes. The full
independent artifact audit still follows successful analyzer regeneration.

The stream readiness audit additionally requires atomic descriptor binding at
both apply entry points, a genuine empty-history check for contextual adoption,
real pending origins before reassignment events, and a documented no-downgrade
boundary for migrated queues. Keep Original requests and Config/Model APIs
compatible; record the actual stream source and binary separately from 9f80.

### Verified control evidence and reserved-stream implementation

Independent verification passes with status `verified_with_incomplete_review`:
6,439 observed attempts across 28 roles, all exact request/page/image bindings,
metrics, sampling and Decimal charges. Audit SHA-256 is
`cdc396040c19737c6e8029083fec2355c82616ac43c8d1bf08bac8cbdd548fe7`; analysis
SHA-256 is `006202236b702a79dce31dfcb40bf1628d9d5902edcdaeb5d5fc65b10e6f1f7a`.
Known subtotal is $7.7162398; total remains unavailable under the preserved
failed-review cost-history flag. All observed usage/pricing is known. There is
one review error, zero retries, and one native refusal in the reversed-text
diagnostic (none in primary).

A checker defect initially confused the formatted review-plan file hash with
its typed compact hash. Strict tests now validate both distinct domains and
exact object equality; the raw evidence and protocol were untouched. Corrected
verifier/exporter tests retain deliberate corruption negatives for each domain.

The terminal control snapshot is archived separately before the reserved phase,
so later source/stream work cannot change it. Its manifest SHA-256 is
`20d8a470bf9cfb63b5406b1b883f1f23199def56e9577928a8cc9dd9b908b1fa`;
externally anchored verification passes all 521 files. It contains frozen selected
inputs, raw calls, failed/accepted reviews, analysis, audit and exact corrected
offline helper copies. Runtime binaries and later stream receipts are excluded.
The later stream will have its own evidence snapshot and runtime/source pins.

The reserved implementation now includes descriptor/context binding, compact
provider guidance, transactional global reconsideration and durable old origins,
matching-descriptor comparison and all-item assigned/Other counts. Original
planning and assignment request builders retain their exact original bodies.
Focused causal reversions cover global queueing, old origins, empty-history
binding, drain ordering, exact contexts, result counters and launcher option
handling. Main/results peer review also found and fixed a strict-reader gap where
a contradictory known-origin event could hide a move as unknown.

Full integration gates pass 115 offline Rust tests (one paid ignored), 58 Python
helper tests, formatting, Clippy and diff checks. Pure maximum-request preflight
passes both modalities with zero calls: the image contextual bound is 31,309,089
bytes below the 33,554,432-byte cap, including 40 largest selected photos and 16
maximum-byte definitions. Its input fingerprints match the independent reserved
data check. Protocol and per-modality control-context files are written before
new paid calls. Launcher review, fresh-binary/source freeze and lifecycle checks
were subsequently completed before the reserved launch recorded above.

The final pre-freeze wording explicitly preserves conversational feedback as a
valid practical subject. Its focused regression and causal reversion pass;
21 provider tests pass (one paid ignored). Regenerated pure preflight is byte
repeatable, SHA-256 `ecbb7447d9222f953d8605419093c24d57fd956af71724cb5d9fb1d0a5ea99ec`;
registered streaming protocol is `65edc12008dd26404a52406a31f1c135e628642e4e8ac69e213882f8d60c0070`.
Original planning and assignment request pins remain unchanged. Independent
launcher, process-ownership and scientific preflight reviews found no remaining
blocker; zero-API lifecycle validation precedes the reserved launch.

### Completed reserved-stream audit and interpretation

The independent checker passes 20 synthetic tests, with raw request/context/
image/page/current-catalog/response/final-state binding, independent pair
enumeration and Decimal all-attempt accounting. Final helper SHA-256 is
`2c2b18777e1f1b799255d39f69b14838dbfa946f10f17ac36171a1ca0ddbb40d`.
It explicitly handles empty-catalog reevaluations with no provider request.
The completed all-eight-arm audit is verified: all persisted input counts are
complete and all queues drained. A separate read-only check independently
enumerated unordered pairs from the terminal SQLite assignments, reproducing
all four full comparisons and both common-named diagnostics. It also verified
the exact common item IDs and the Decimal sum of all eight API arm costs.

| Cohort | Full Original / contextual ARI | Full Original / contextual pair F1 | Common-named diagnostic n | Conditional Original / contextual ARI | Conditional Original / contextual pair F1 |
| --- | --- | --- | --- | --- | --- |
| Text | 0.538096 / 0.609758 | 0.581982 / 0.655911 | 674 of 1,000 | 0.787131 / 0.721809 | 0.819144 / 0.760726 |
| Natural photographs | 0.818656 / 0.971144 | 0.843049 / 0.975410 | 93 of 100 | 0.829953 / 0.977568 | 0.855835 / 0.981366 |

Full assigned/Other text counts change from 707 both named / 287 Sol-only named /
one Decisions-only named / five both Other to 908 / 90 / zero / two. Photos
change from 94 / one / four / one to 95 / zero / two / three. Neither a shared
rejection count nor a conditional subset alone explains the complete result.
The text coverage improvement coexists with weaker grouping agreement among
the items all methods already named. This is one stream order and a combined
manager intervention, not semantic ground truth or a component ablation.

The post hoc common-named diagnostics retain the same items for both policies,
selected only after observing final outcomes. They exclude rejection cases and
are neither primary results nor independent confirmations. Exact code, selected
IDs and the frozen metric-helper hash are retained under streaming/reproduction
and streaming/posthoc. Full-cohort metrics are checked against the frozen CLI
first; the immutable control evidence remains separate.

A separate blinded coding-harness review inspects eleven reserved photos and
44 anonymous assignments, including disagreements, shared rejection and four
seed-selected jointly named agreements. Qualitative judgments are sealed before
unblinding, exclude source metadata and are not human truth or accuracy rates.
Examples distinguish a vehicle-wreckage error, a reasonable Sports/People
granularity difference, a persistent mannequin boundary and defensible shared
Other for a cooking-appliance catalog gap. Four illustrative cases are curated
for the report; coding-harness review compute is outside the API ledger.

A bounded historical text episode is independently captured: at 53 received
items the contextual Sol manager retires all eight categories, queuing 53.
Those commit zero-request Other reevaluations (45 previously named, eight
previously Other) because there are no candidate pages. Eight subsequent inputs
trigger novelty management at 61 and ten categories are created, queuing all61.
The active-category cap16 did not require retirement. The raw plans provide no
public rationale, so no intent or semantic-merit claim is inferred. Episode
JSON/Markdown retain event IDs, selected row/call hashes and runtime pins.

The final all-target Rust receipt sums to 115 offline passes (94 library, seven
CLI, three analyzer and 11 frozen-catalog example tests), plus one ignored paid
test and zero doctests. Earlier prose counted 117; this corrects the count
without changing runtime or experiment evidence. All 93 Python tests now pass,
including 20 independent stream-verifier and 15 stream-publication tests.

Streaming archive creation and separate anchored verification now pass for407
input/run files. Manifest SHA-256:
`75d694a497fdf0dfab14159b8f978606ce89eeb17efb646802fe2106fc79d9f4`.
The external receipt is `streaming-archive-verification.json` beside the archive.
The14MB independent audit is retained exactly inside the raw run payload;
smaller comparisons and conditional diagnostics have readable mirrors.
