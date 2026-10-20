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
Dataset, controlled-harness and metrics/review lanes are delegated. No new paid
model calls have been made. Dataset feasibility, review sample allocation and
the final protocol pins remain to be frozen before execution.

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
