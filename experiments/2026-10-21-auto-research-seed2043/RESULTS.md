# Compact category guidance: development gains did not confirm

The bounded follow-up completed all 52 registered invocations and 22 comparisons.
The frozen Boundary challenger did not improve agreement in either modality
on fresh confirmation. Original descriptions remain the stronger measured
confirmation baseline in this study.
Agreement with Sol is distinct from semantic accuracy.

The frozen runtime was `a3b38d7f9e535f300ac783b3aa4abeb77b17a54f`, executable
SHA-256 `2eed0a941e5f8e292940c0fd2f72d2432409c0456d3acb2a9314bdc2920f9f20`.
The protocol and dataset were registered before paid calls; adaptive generation
and selection were registered before dependent calls. No description was tuned
after confirmation and no unfavorable result was replaced by another run.

## Every design

| Stage | Text direct / named matches | Photo direct / named matches | Decision |
| --- | --- | --- | --- |
| Calibration: short | Sol and Decisions each 80/80 against the constructed key | Not an image test | Retain evidence; no natural-data selection |
| Calibration: redundant positive | Both 80/80 | Not an image test | No position association reproduced here |
| Calibration: negative boundaries | Both 80/80 | Not an image test | This simple probe does not rule out effects in larger natural catalogs |
| Development: Original | 172/200; 169/200 | 35/40; 32/40 | Baseline |
| Development: Compact | 166/200; 166/200 | 37/40; 33/40 | Keep unfavorable text and favorable photo results |
| Development: Boundary | 168/200; 168/200 | 37/40; 34/40 | Text NOT_ADOPTED; photo ADOPTED on development |
| Fresh confirmation: Original | 824/1,000; 809/1,000 | 98/100; 87/100 | Stronger measured confirmation baseline |
| Fresh confirmation: frozen Boundary challenger | 808/1,000; 796/1,000 | 95/100; 85/100 | Development photo gain did not reproduce |

Direct agreement includes shared Other. Named matches use all items as their
denominator and exclude shared Other. Calibration rotates the same 20 cases
through four orders; 80 dependent assignments are not 80 distinct cases.
Development reused 200 requests and 40 photos for both revisions; confirmation
used separate 1,000-request and 100-photo partitions. Category IDs, names, order,
structure and K8 first-match paging were held fixed across natural comparisons.

Compact means a positive membership budget, not necessarily shorter than
Original. Total description words were Original/Compact/Boundary 215/221/257
for text and 142/140/165 for photos. Wording and length were not independently
randomized. The simple calibration has four nonconsecutive named IDs plus Other;
it does not isolate the mechanism of an earlier larger-catalog association.

## Coverage, rejection and grouping

| Fresh condition | Sol named | Decisions named | Both named | Sol only | Decisions only | Both Other | ARI | Pairwise F1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Text Original | 970 | 940 | 925 | 45 | 15 | 15 | 0.706956 | 0.741564 |
| Text Boundary | 982 | 925 | 919 | 63 | 6 | 12 | 0.688243 | 0.725860 |
| Photos Original | 89 | 88 | 88 | 1 | 0 | 11 | 0.963675 | 0.968304 |
| Photos Boundary | 88 | 88 | 86 | 2 | 2 | 10 | 0.934134 | 0.942323 |

There is no apparent gain manufactured by shared rejection: direct and named
agreement both decline, and shared Other also declines. ARI and pair scores
treat each Other item as a separate singleton. Full confusion matrices,
per-category counts, pair precision/recall and conditional jointly assigned
agreement are preserved in the comparison JSON files and independent audit.

Decisions photo labels are identical for all 100 items across the two guides.
Sol changes three photo labels and all three lose agreement. This is reference
movement, not evidence that Decisions photo semantic accuracy worsened. Text
has 57 Sol and 133 Decisions changes, with 65 direct-agreement gains and 81 losses.
Anchoring both conditions to Original Sol is a secondary diagnostic, not the
primary result or semantic ground truth.

## Repeats and blinded review

On preselected subsets, Original→Boundary Sol label consistency was
96/100→98/100 text and 25/25→24/25 photos. The industrial-compressor photo changed
from category 6 to Other under an identical serialized request on repeat. Its
primary answer remains unchanged in every primary metric. Photo repeat ARI can
equal 1 despite that label change because the singleton partition is unchanged.

Fresh coding-harness reviewers accepted all 46 text and 15 photo cases, with
zero failed or unattempted selected cases. They saw anonymous assignments and
each pair's own full catalog; notes were sealed before unblinding. The sample
was stratified by challenger outcomes, with no quota reallocation, and includes
agreements. Original uses the same selected cases. Review counts cannot estimate
population accuracy or fairly rank designs. Exact reviewer model identity is
unknown; judgments may share model-family biases and are not independent human
truth. Their compute is outside the experiment API ledger.

Concrete examples include Decisions rejecting “hola!” despite explicit social
conversation scope, Sol treating a question about Scottish greetings as direct
assistant interaction, overlapping 401k financial/employee-benefit categories,
and an ambiguous dead battery. All three changed Sol photos were reviewed:
the reviewer preferred unchanged Decisions on the sand sculptor and industrial
compressor and considered the engine-trailer difference reasonable. No selected
photo assignment was judged unsupported. A volcanic landscape illustrates a
legitimate shared Other where the catalog lacks a landscape category.

One sealed text case (“should i run every day”) appears to transpose its two
rationales. Its original bytes and counts are preserved and flagged; it is
excluded from the curated gallery, with no replacement review.

## Post hoc concentration and page boundaries

Text disagreements increased from 176 to 192, but unmatched Decisions choices
of Knowledge & Learning fell from 89 to 62. Under Boundary, the largest cells
were Sol Assistant versus Decisions Other (45) and Sol Personal Organization
versus Decisions Assistant (32): 77/192 disagreements, or 40.1%. All 32 latter
cases stop on the same first page. An exact example is “read my list of
reminders,” with Sol choosing category 7 and Decisions category 8.

All Decisions Knowledge choices follow first-page Other, as the algorithm
requires; this prerequisite is not independent evidence of a pagination defect.
For Boundary, 53/141 such choices occur where Sol accepted a first-page named
category. Category semantics, position and page context are confounded. The
source-bound `analysis/text-paging-posthoc.json` preserves full per-category
counts, largest confusion cells, page cross-tabs and hash-selected examples.
This analysis was designed after confirmation. The reminder example has no new
blinded semantic judgment, and these counts neither identify the correct model
nor establish a causal paging effect.

## Accounting and reproduction

The experiment API ledger is complete: **$6.5893167**, 7,608 recorded attempts,
zero errors, retries, refusals or unknown-usage calls. This excludes coding and
coding-harness qualitative review. Stage loops overlapped with one another and
the preceding streaming study; their elapsed times are not additive wall time
or isolated performance measurements.

The evidence archive contains the raw model records, registration/terminal
receipts, exact selected input bytes and individual licensing/provenance,
generated catalogs, immutable reviews, reproduction tools and offline validation.
No tiny image was upscaled: the 140 fresh development/confirmation photos have
supplied long edges of 768–1,024 pixels and documented native long edges of at
least 1,024. They are disjoint from all 260 previously used photos by the recorded
identity/source/content checks. Original bytes were verified for 99; the other
41 retain documented native dimensions and licenses without claiming retrieved
original-byte verification.

Start with the externally anchored archive manifest and `evidence/README.md`.
After restoring the run payload, consult `reproduction/README.md`. The independent final audit is
SHA-256 `2f720fac520610a592cab7662e5e3526cd749b99e4a3688be72e41fef5f07c1f`;
repeat diagnostics are
`1a5de02b75499b25959df7b7f5c874fe8827dc6b5b321f362088f126a9eabbf7`.
The illustrated report and permanent research log are at
<https://edwardbenson.com/goofing/ld-clustering>.

The archive manifest SHA-256 is
`74a0d9fca1fe95f63c7a5e11054aa33fd34871cc82f60afed5ee34aab95ced07`.
[EVIDENCE-VERIFICATION.json](EVIDENCE-VERIFICATION.json) records a separate
verification against that literal external anchor: 397 selected dataset files
and 1,054 raw run files, including the final nine-group/18-row method matrix.
All 211 repository Python tests and 136 offline Rust tests passed; one explicitly
paid Rust test was ignored. The original preregistration README and fixture
checksums remain unchanged.

From this experiment directory, verify without model calls:

```sh
python3 evidence/archive_auto_research.py verify evidence --manifest-sha256 74a0d9fca1fe95f63c7a5e11054aa33fd34871cc82f60afed5ee34aab95ced07
```
