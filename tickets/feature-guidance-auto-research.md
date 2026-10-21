# Improve shared-catalog agreement through bounded adaptive experiments

**Status:** In Review
**Type:** Investigation
**Filed:** 2026-10-21
**Branch:** feat-guidance-auto-research
**Pull request:** https://github.com/eob/ld-clustering/pull/4

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
`experiments/2026-10-20-guided-agreement-seed1042/`. At the follow-up's start,
its reserved contextual Sol text worker was still running under frozen runtime
f78dcf9, with the other seven arms complete. All eight subsequently finished
and passed independent verification; PR #3 merged the separate streaming
evidence. This follow-up changed no active worker, source, context or executable.

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

Accepted by the user on 2026-10-21. The separate Rust runner and frozen protocol
completed all 52 registered paid invocations from source
`a3b38d7f9e535f300ac783b3aa4abeb77b17a54f` and frozen
binary `2eed0a941e5f8e292940c0fd2f72d2432409c0456d3acb2a9314bdc2920f9f20`.
The final independent audit verifies 22 comparisons and complete experiment API
cost $6.5893167. Fresh confirmation did not reproduce the development photo
gain, and text also failed to improve. Preselected repeats and all 61 selected
blinded confirmation cases are complete; no confirmation-driven rewrite,
replacement judgment, or favorable rerun was performed.

The leading method-comparison matrix is complete: nine explicitly scoped groups
and 18 method rows, with per-backend audited classification costs and measured
loop times. Combined offline validation passed 211 Python tests; the frozen
runtime passed 136 Rust tests with one paid test ignored. The evidence archive
passed separate externally anchored verification. Source PR review is separate
from final report import and browser/publication validation in eob/kaya-web
PR #2226. This worktree was created from
origin/main and fast-forwarded to the accepted f78dcf9 dependency. The earlier
eight-arm stream completed, independently verified and archived; PR #3 merged
at `48d62670de7b5201e2e7b5464e9c5505c2ebe7eb`. This feature incorporated that
main change with a merge into the feature branch, preserving runtime ancestry.

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

### Fresh text selection witness

The focused preparation test first fails with
`Error: fresh auto research partition selection is not implemented`. The
implemented deterministic selector then passes, preserving domain quotas and
excluding prior normalized content and duplicates across both fresh partitions.
The actual selected text manifest SHA-256 is
`2712312223ad68fa98dd01add1343c784e3ca71348aab69b44ab1535d76c2e9f`:
200 development and 1,000 untouched confirmation items from the same pinned
test/oos_test sources, plus a preselected 100-item confirmation repeat.
At that preparation freeze, no classifier outcomes had been requested for these
partitions.

### Frozen follow-up design and dataset

Protocol `0c84dbe330d8dcb433ddd6ceb62dede41fd71ecae328669eddcef99525fc3b65`
binds all 52 allowed invocations: 24 synthetic calibration arms, four one-shot
joint rewrites, 12 development arms, eight fresh confirmation arms, and four
reference repeats. Description structure remains fixed. Compact and boundary
candidates must improve named matches over all items, retain direct matches,
and lose no more than two percentage points of either method's coverage before
adoption. Candidate choice freezes before one confirmation comparison; retain
negative candidates and all costs. Conditions SHA-256 is
`a22381595393f3980fbb271b896359508d3dca553be7c1e3b58e017bfe931d22`.

Dataset manifest `add80aa99c9b8015ad69ff76d9ba98c01f7ce2724ff32a9c84081e8b08d7c2d1`
contains 200 development / 1,000 confirmation texts and 40 / 100 photographs,
with preselected 100-text / 25-photo confirmation repeats. All 140 new supplied
JPEGs preserve source bytes and aspect ratio; native long edges are at least
1,024 pixels. Original-byte verification is available for 99, unavailable for
41; publisher dimension/license evidence is retained for all. The dataset
independent gate passed with receipt SHA-256
`d72f1175670539a4ea7585eb9ef5e9722ef6007eb4e1bc0295e2f036bcd75518`.

Before freeze, peer review caught two provenance gaps: omission of the complete
500-candidate acquisition ledger and comparing RGB hashes from different JPEG
decoders. The archive now includes the complete ledger and correct curation
helper. Prior photo bytes are redecoded using the same Rust image decoder as
new photos; Pillow hashes retain their separate decoder identity. Four focused
preparation tests pass, including old manifests without precomputed pixel hashes.

Zero-API inspection of 2,739 earlier primary native responses found every
returned value in its recorded probability argmax set, exact option-value order,
and no invalid or duplicate IDs. Fifteen were tied. This excludes that observed
local mapping failure; it does not establish an API mechanism or semantic truth.

### Interim controlled development evidence

All 480 calibration decisions matched the constructed key: 20 distinct cases
repeated across three styles, four orders and two backends. Both models were
stable across all four orders for every case. Complete experiment API cost:
$0.33382. This did not reproduce the earlier position association. Four named
options with nonconsecutive IDs differ from the natural eight/ten-category
setting; this is not evidence of natural-data accuracy or a universal absence
of cardinality/encoding/semantic effects.

The two compact rewrites completed once, without regeneration, for $0.1685345.
Actual description totals are text 215→221 words and photographs 142→140;
the intervention is positive membership guidance under a word budget, not a
pure length reduction. All original IDs, names, order and counts are preserved.

On the fresh development cohort, Original→compact gives:

| Cohort | Direct matches | Named matches / all items | Sol named | Native named | Both Other |
| --- | --- | --- | --- | --- | --- |
| Text, n=200 | 172→166 | 169→166 | 197→200 | 189→187 | 3→0 |
| Photos, n=40 | 35→37 | 32→33 | 36→36 | 35→35 | 3→4 |

The photo direct gain is two items, including one shared-Other match; coverage
does not change. Text regresses. These are development scores, not confirmation
or semantic accuracy. Through calibration, generation and development the
independent known and complete API subtotal is $1.4295474. Its dependency union
contains 34 invocations and 16 full within-condition comparisons.

The bounded blinded development review selected 14 text cases and seven photos
without reallocating short stratum quotas, including agreements and Other.
Every selected case has an accepted judgment, no failures. Judgments and actual
boundary instructions were sealed before key parsing/unblinding; all notes and
all selected input items are retained. Review is coding-harness qualitative
compute outside the experiment API ledger, with exact backend model identity
unavailable and possible shared-family biases. It is not a population accuracy
sample. The boundary rewrites use the original discovery plus exactly those
14/7 development items, never confirmation data.

An actual zero-API launch check caught the legacy schema2 manifest's missing
`jsonl_sha256` field before paid dispatch. The corrected launcher verifies its
recorded payload/order/image hashes, enforces optional raw hashes when present,
and pins actual staged JSONL bytes. Twelve focused launcher tests include that
real legacy shape, altered content rejection, process-tree containment and
terminal accounting. Reverting the legacy fix reproduces the original KeyError.


### Boundary development and frozen selection

The one-shot boundary rewrites completed from discovery plus all 14 text /
seven photo blinded development cases. Description totals are 257 text and
165 photo words; all individual guides meet the recorded word budgets.

| Development cohort | Original direct / named | Compact direct / named | Boundary direct / named | Boundary Sol / native named | Boundary both Other |
| --- | --- | --- | --- | --- | --- |
| Text, n=200 | 172 / 169 | 166 / 166 | 168 / 168 | 200 / 191 | 0 |
| Photos, n=40 | 35 / 32 | 37 / 33 | 37 / 34 | 36 / 36 | 3 |

Boundary photos pass the exact development rule and outrank compact by named
matches. Neither text challenger passes: boundary is the highest complete
challenger but remains `NOT_ADOPTED`; Original remains the text policy. The
selection was frozen at 2026-10-21T04:06:43.997181+00:00 before any confirmation
classification. Both frozen challengers subsequently received the single
recorded fresh confirmation comparison, preserving the negative text result. Through
all development stages the independent audit verifies 40 invocations,
18 comparisons, and complete API cost $2.1590464. No confirmation outcome
can trigger another rewrite or favorable rerun in this study.


### Fresh confirmation did not reproduce the development gain

The full independent confirmation audit verifies 48 completed invocations and
22 comparisons. On the untouched cohorts, Original→Boundary gives:

| Cohort | Direct matches | Named matches / all items | Sol named | Native named | Both Other |
| --- | --- | --- | --- | --- | --- |
| Text, n=1,000 | 824→808 | 809→796 | 970→982 | 940→925 | 15→12 |
| Photos, n=100 | 98→95 | 87→85 | 89→88 | 88→88 | 11→10 |

Text ARI is 0.706956→0.688243 and pair F1 0.741564→0.725860; photo ARI is
0.963675→0.934134 and pair F1 0.968304→0.942323. Named agreement also declines,
so shared rejection alone does not explain the result. The three-item photo
direct difference is a small single-cohort observation, not a universal or
human-accuracy claim. The development selection stays frozen and visible:
image Boundary was ADOPTED for confirmation, while text Boundary remained
NOT_ADOPTED. Neither fresh comparison establishes an improvement.

At the primary-confirmation checkpoint the complete experiment API subtotal was
$6.2481214, before the four preselected repeat invocations. Coding-harness
qualitative review is outside that ledger. Review packets contain 46 text
cases and 15 photographs, with short strata left short; Original is shown
alongside the challenger using its own catalog. Fresh blinded reviewers received
no backend key or aggregate scores; all selected cases were subsequently sealed
and accepted. No further rewrite or favorable rerun is part of this frozen study.

An independent primary replay adds an important interpretation: photo native
assignments are identical across Original and Boundary (0/100 changes). Sol
changes three assignments, and all three lose agreement, with no gains. The
photo drop therefore comes from reference movement rather than a change in
native photo outputs. The completed blinded own-catalog review and repeats
provide context without establishing semantic truth. Text has 57 Sol and 133 native changes, with
65 direct-agreement gains/81 losses and 59 named gains/72 losses.

### Final repeats and complete experiment accounting

The final independent audit is `verified`: 52/52 registered invocations complete,
22 full comparisons, no failed conditions, and 7,608 recorded API attempts.
It records zero retries, API error calls and assignment refusals. Known and
complete API cost are both $6.5893167; coding and coding-harness review compute
are outside this experiment ledger. No unknown-usage cost was imputed.

The preselected Sol repeat subsets give Original→Boundary consistency of
96/100→98/100 text requests and 25/25→24/25 photographs. These are repeat
agreement with the same Sol classifier, not semantic accuracy or full-cohort
classification agreement. They do not reverse the fresh negative primary
result or change the frozen development decisions: text `NOT_ADOPTED` with
Original retained, photographs `ADOPTED` on development before confirmation.

Reproduction anchors under `runs/auto-research-seed2043/`:

- `validation/final-independent-audit.json`, SHA-256
  `2f720fac520610a592cab7662e5e3526cd749b99e4a3688be72e41fef5f07c1f`.
- `analysis/confirmation-diagnostics.json`, SHA-256
  `1a5de02b75499b25959df7b7f5c874fe8827dc6b5b321f362088f126a9eabbf7`.
- `qualitative/confirmation/summary.json`, SHA-256
  `f089dfad89903e34a90f25e254cbefdfbe25d0d6025d9478a782400e0eb9b029`.
- `readiness/confirmation-review-summary-independent-check.json`, SHA-256
  `9c0d14e0bf59800c86bacb31b4fe978bf043f521d39e2b78f8a5f74bf21f58b6`.

### Blinded confirmation review and remaining semantic uncertainty

All 46 text and 15 photo cases have accepted sealed judgments: no failed or
unattempted selected cases and no replacement review. Independent checks bind
the deterministic challenger-based sampling, both own catalogs, anonymous
assignments, instructions, registration, seals and unblinding chronology to
the raw primary results. Original uses the same challenger-selected cases;
cross-design fit counts are therefore asymmetric, not representative accuracy
estimates. Exact reviewer model identity is unavailable, shared-family bias
is possible, and no independent human truth is supplied.

For challenger text pairs, the reviewer preferred Sol in 17 cases, Decisions
in eight, and considered both reasonable in 21. Concrete findings span both
methods: Decisions rejects “hola!” despite the challenger's explicit social
conversation scope, while Sol misroutes “how might i say hello if i were
scottish” as assistant interaction rather than linguistic instruction.
“what do i do now that my battery is dead” reasonably permits a vehicle-care
interpretation or Other because the battery's owner is unstated. Retirement
rollovers also overlap financial transfers and employment benefits. Agreement
and clear errors coexist with scope, granularity and missing-context questions.

All 60 photo assignment judgments across both designs were supported or
plausible. The selected set includes every changed Sol photo assignment:
the reviewer preferred unchanged Decisions People for the sand sculptor and
Other for the industrial compressor, while considering the engine-trailer
difference reasonable. None of these selected photo choices was marked
unsupported. Together with unchanged native outputs on all 100 photos, this
prevents interpreting the three-point agreement drop as demonstrated loss of
native semantic accuracy.

One sealed challenger text judgment for “should i run every day” (case
`908df5ebe9ab02f861f6d40d`) appears to swap the two evidence rationales.
Its two plausible fits, both-reasonable verdict and all counts remain untouched;
the inconsistency is flagged and the case excluded from curated illustrations.
No hidden repair or replacement judgment was used. Neither these selected
reviews nor the repeats overturn the negative full-cohort confirmation result.

### Validation and delivery limits

Offline source checks passed: 136 Rust tests, one explicitly ignored paid test,
`cargo fmt --check`, and `cargo clippy --all-targets -- -D warnings`. The original
follow-up Python checkpoint passed 162 tests plus seven separate blinded-review
reproduction helper tests. After incorporating the preceding streaming tools
and final matrix exporter, the complete repository Python suite passed 211 tests.
Receipts are `readiness/source-offline-validation.json`,
`readiness/final-offline-python-validation.json` and
`readiness/method-matrix-full-python-tests.json`; runtime source identity stayed
frozen throughout paid classification. Raw API replay verifies accounting and
assignment binding, not human accuracy or a provider/pagination mechanism.
The final report/publication checks remain delivery work in the report repository.

### Post hoc residual text concentration

Source-bound page replay finds total text disagreements176→192 while unmatched
Decisions Knowledge choices fall89→62. Boundary Assistant→Other45 and Personal
Organization→Assistant32 account for77/192 differences; all32 latter cases stop
on page1, including the exact held-out reminder-list example. These were
post hoc, hash-selected illustrations without a new semantic review. Late
Knowledge choices require page1Other by construction, so the association cannot
establish a paging defect or identify the correct model. Full per-category,
confusion and page cross-tabs are in `analysis/text-paging-posthoc.json`, with
reproduction/source-guard receipt `readiness/text-paging-posthoc-check.json`.
No new paid calls, selection or tuning followed this analysis.

### Leading comparison matrix

The report leads with a nine-column grouped matrix: method, then cost, time,
LLM–Decisions agreement and ARI for text and images. Rows distinguish datasets,
development/confirmation and post hoc diagnostics. Natural-data agreement is
not labeled semantic accuracy. Per-backend costs and measured loop times remain
separate; missing/incomplete measurements remain explicit. Calibration repeats
retain their dependent denominator and time-sum scope; independent catalogs
have no direct-ID agreement. Shared generation/review/repeat accounting stays
in the chronological research log. All values derive from pinned prior
publication artifacts or independently audited fresh runs, never manual scores.

### Final source evidence archive

`experiments/2026-10-21-auto-research-seed2043/evidence/manifest.json` is anchored
by SHA-256 `74a0d9fca1fe95f63c7a5e11054aa33fd34871cc82f60afed5ee34aab95ced07`.
Creation and a separate verification with that literal external anchor passed,
binding all 397 selected dataset files and 1,054 run files. The exact final
matrix and all raw attempts, terminal registrations, catalog versions, reviews,
provenance and reproduction helpers are archived. No RUN bytes changed after
the snapshot. The external `EVIDENCE-VERIFICATION.json` receipt records the
command, runtime/data/audit/matrix pins and validation receipts. Preregistered
fixture bytes and their original checksums remain unchanged; final findings
are documented in `RESULTS.md` and the repository README. Review and website
publication remain distinct from successful source archive verification.
