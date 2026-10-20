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
are implemented. No new paid model calls have been made. Final full gates pass
88 offline tests (one paid test ignored), formatting and all-target Clippy with
warnings denied. Dataset manifest is
`c61ce5b4703e98ae79581c73e492aece53196777ac7510f121bbced59ed752f4`;
independent Python/Pillow verification passes all partition/order/payload/image
hashes, 2,460 distinct new non-repeat IDs, 260 unique supplied JPEGs and exact
100/25 repeat-subset evidence. Relocated inputs produce identical fingerprints
and the identical 28,731,011-byte discovery request below the 32 MiB local cap.
The registered protocol and review plan live in
`experiments/2026-10-20-guided-agreement-seed1042/`. Source commit, release
executable and all stage launch receipts will be pinned before the first call.

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
