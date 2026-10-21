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

Source branch starts from main `1fd37ebb28e956a380ba8587815d4aa738719510`.
The controlled harness, dataset preparation, metrics and blinded review tooling
are implemented. Preregistration and all offline gates completed before paid
calls began on 2026-10-20 at 22:49:43 UTC. Final full gates pass
88 offline tests (one paid test ignored), formatting and all-target Clippy with
warnings denied. Dataset manifest is
`c61ce5b4703e98ae79581c73e492aece53196777ac7510f121bbced59ed752f4`;
independent Python/Pillow verification passes all partition/order/payload/image
hashes, 2,460 distinct new non-repeat IDs, 260 unique supplied JPEGs and exact
100/25 repeat-subset evidence. Relocated inputs produce identical fingerprints
and the identical 28,731,011-byte discovery request below the 32 MiB local cap.
The registered protocol and review plan live in
`experiments/2026-10-20-guided-agreement-seed1042/`. Source commit, release
executable and all stage launch receipts were pinned before the first call:
source `9f80d8400ac23c70c9e5dd2e23c953cdee362410`, classifier binary
`9130b82079e107c282dea401261d0e993459126b51411fbe4a659226ac240dce`, analyzer
`9c886c11b2341c93bf7b3a8333b57ae05ec65d82a5da87a27863ad968138e719` and protocol
`894b0e577a0f6e778f09855ba676f614620b4992b3f013e8ee61477452181fbd`.

The catalog stage completed four successful calls by 22:52:13 UTC, with 10 text
categories and 8 image categories. Each guided rewrite preserves original IDs,
names, order and count. All eight held-out dry runs passed before launching the
primary stage at 22:53:49 UTC under `ld-guidance-controlled-1042.service`.
Runtime sources/executables and catalogs remain frozen through the controlled
stages. Primary artifacts live under `runs/guided-agreement-seed1042/controlled/`.
All eight primary arms completed at 23:35:48 UTC with 5,240 recorded attempts,
zero errors, zero assignment refusals and no missing usage reported. The repeat
stage started at 23:35:49 UTC and all four repeat arms completed: text consistency
is 97/100 original and 99/100 guided; images 23/25 and 24/25. These are small
repeat subsets, not semantic accuracy or an agreement ceiling. All controlled paid stages terminated by 2026-10-21 at 00:07:08 UTC. Three
review arms completed 100 judgments each; the original-photo review remains
terminal/incomplete (57 accepted, one failed, 42 unattempted). All eight planned
order/page diagnostic arms completed. Independent evidence verification and the
reserved-stream implementation remain pending.

Protocol choices frozen before outcomes: dataset seed 1042; review seed 2042.
All 100 held-out images are reviewed for each description condition. For each
text condition, review quotas are 30 different-named disagreements, 30 Sol-named /
LD-Other, 10 Sol-Other / LD-named, 20 equal-named agreements and 10 both-Other.
Select all available cases in an undersized stratum; do not reallocate spare
quota. Report sampled denominators. Backend identities, condition names and
aggregate results are hidden from the reviewer; candidate A/B order is shuffled
and preserved separately for later unblinding. Automated reviewer judgments are
not human ground truth. The anchored-original-reference paired comparison is a
preplanned secondary diagnostic; the primary uses matched descriptions.

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

### Reserved-stream design review (not implemented yet)

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

### Completed primary arms (other stages pending)

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
