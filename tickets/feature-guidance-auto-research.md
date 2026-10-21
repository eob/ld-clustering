# Improve shared-catalog agreement through bounded adaptive experiments

**Status:** In Progress
**Type:** Investigation
**Filed:** 2026-10-21
**Branch:** feat-guidance-auto-research
**Pull request:** not opened

## Goal / failure mode

Run a few focused follow-up rounds to improve Sol–Decisions agreement while
preserving named coverage and checking semantic quality. Preserve every design,
regression, failed attempt and selection decision in a permanent Auto research
log in the existing LD Clustering report. Agreement is distinct from accuracy.

## Evidence and reproduction

The preceding frozen control reduced direct agreement from 82.0% to 52.2% for
1,000 text requests and 96% to 81% for 100 natural photographs. These are new
shared-catalog baselines, not the earlier independently evolving v2 catalogs.
Different-named guided disagreements often select the next canonical entry:
339/380 text and 12/13 photographs. Raw choice values map correctly to saved
IDs; an upstream mechanism has not been established. Reversed text K8 changes
order and page composition together, so it is not a pure position experiment.

The earlier experiment and its independent audit/archive remain immutable in
`experiments/2026-10-20-guided-agreement-seed1042/`. Its reserved contextual Sol
text worker is still running under frozen runtime f78dcf9. The other seven
arms have succeeded. No ongoing worker, source file, context or executable is
changed by this follow-up.

## Context / research brief

Question: can compact category membership rules and explicit neighboring
boundaries improve direct category-ID agreement on fresh examples without
gaining only through Other or narrowing coverage? First isolate whether the
observed position association survives simple, unambiguous choices and changes
in description length/order. Later choose a candidate on development evidence
and test that choice once against the original baseline on untouched data.

Leading alternatives: richer descriptions cause semantic interference;
position or option encoding affects native decisions; the categories overlap;
Sol and Decisions make reasonable different interpretations; apparent gains
are sampling noise, reference instability or increased rejection.

## Plan

1. Freeze the protocol and dataset identities before paid follow-up calls.
   Inspect the existing request schema against current official Decisions
   documentation. Preserve the same models, reasoning, retry/refusal behavior
   and raw attempt accounting. Use new, honestly named Rust experiment tooling;
   do not bypass or relabel the preceding registered harness's guardrails.
2. Freeze fresh development and confirmation partitions, disjoint from all
   previous text/photo inputs and each other. The pinned CLINC test/oos_test
   sources have enough unused normalized texts for 200 development and 1,000
   confirmation items. Determine and freeze feasible new photo counts before
   launch. Native dimensions, RGB content, aspect, source bytes and individual
   licensing follow the preceding verified policy; no tiny-image upscaling.
3. Round 1: bounded synthetic calibration with known constructed answers,
   stable nonconsecutive IDs, one page, counterbalanced option positions and
   concise versus boundary-heavy definitions. Record exact request/response
   choices and probabilities. This is a mechanism probe, not natural-data
   accuracy. Freeze its exact cases and all requested conditions before launch.
4. Round 2: jointly generate compact, self-contained positive membership
   descriptions from the original full catalog and discovery evidence. Preserve
   IDs, names, order, count and semantic scope. Compare against the original
   descriptions on the same development cohort under identical K8 conditions.
5. Round 3: use the full catalog, discovery members and bounded blinded
   development disagreement evidence to repair neighboring boundaries. Freeze
   the precise revision and its rationale before evaluating it on that same
   development cohort. Reused development outcomes are adaptive evidence.
6. Freeze a selection rule and the final candidate per modality before opening
   confirmation outcomes. Prefer higher matching named-ID agreement, retain
   direct agreement and coverage checks, and keep Original on ties. Do not
   select on joint-Other gains alone. Complete the exact eligibility/ranking
   rule in the protocol before any development classification.
7. Run original and the selected candidate once on the untouched confirmation
   data. Report paired gains/losses, confusion, per-category errors, Other2x2,
   ARI/pair metrics, reference repeats, all attempts/charges/times and blinded
   disagreements plus agreements. Do not retune on confirmation or hide a
   failed or unfavorable result. State automated-review limitations.
8. Independently reconstruct raw evidence, archive it separately from earlier
   experiments, and add every design/decision to the report's Auto research
   log. Validate source, actual imported data and useful browser viewports;
   deliver through PRs and the existing authorized publication workflow.

## Acceptance criteria

- The earlier study/ongoing streams remain untouched and are fully delivered.
- The protocol defines all initial probes, sample counts, comparison conditions,
  adaptive boundaries, selection rule and stopping condition before paid calls.
- Stop after these three rounds and one frozen confirmation comparison;
  additional redesign requires a new recorded research decision, not hidden
  favorable reruns. A negative answer is valid.
- Catalog versions and API encoding have explicit identities; no new design is
  disguised as an original registered condition.
- No evaluated confirmation item or outcome is used to rewrite or choose the
  candidate. Development reuse and inspected examples are labeled nearby.
- Gains include named matches and full coverage/rejection accounting, with
  semantic review distinct from reference reproduction.
- Every attempt, failure and incomplete cost remains visible. Every scientific
  claim traces to frozen raw evidence, not a report-only recomputation.
- The permanent log distinguishes direct ID agreement, ARI and semantic review,
  including historical/superseded/partial designs without invented numbers.

## Current state

Accepted by the user on 2026-10-21. Protocol/data feasibility and minimal Rust
runner design are in progress; no follow-up paid calls have started. This clean
worktree was created from origin/main and fast-forwarded to the accepted f78dcf9
dependency. The earlier experiment's worktree remains frozen. Its PR #3 must
land before this dependent PR is finalized against refreshed main.

## Decisions and durable findings

- Preserve the first controlled comparison as originally reported. Follow-up
  development and final confirmation are new experiments, not replacements.
- Keep taxonomy structure fixed for the first compact/boundary comparisons;
  avoid attributing differently broad catalogs to improved classification.
- The API reference supports string choice values with descriptions and
  returns explicit choice values and per-value probabilities. Current evidence
  does not establish a request-schema defect. Official sources checked
  2026-10-21: https://developers.openai.com/api/reference/resources/decisions/methods/create
  and https://developers.openai.com/api/docs/guides/decisions .
- Website planning continues in
  `eob/kaya-web:tickets/open/feature-ld-guided-agreement-report.md` and PR #2226.
