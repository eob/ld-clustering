# Fixed-catalog membership-guidance experiment

This experiment compares short category descriptions with one jointly generated
rewrite containing membership guidance and neighboring-category boundaries.
`protocol.json` was committed before the first paid request. The primary
comparison freezes IDs, labels, category order, K=8 paging and the held-out items.
Both assignment backends receive the same catalog for each condition.

## Inputs and scope

Discovery uses 200 fresh CLINC150 text requests and 60 natural color photographs.
Evaluation uses disjoint 1,000-text and 100-photo samples. A further 1,000-text /
100-photo partition is reserved for the subsequent evolving-manager experiment.
Source labels and photo provenance are sampling/attribution metadata, excluded
from model inputs. Original means the new discovery-generated short catalog,
not a catalog reused from the earlier seed-42 experiment.

All 260 supplied photographs are RGB JPEGs with verified native long edge at
least 512 pixels and preserved aspect. The held-out supplied images have long
edges of 978–1,024 pixels; native originals range from 1,024 to 6,016 pixels.
Publisher metadata supplies original dimensions and licensing. Original-byte
hashes are available for 59/260 photos, not all of them. Exactly one oversized
source was downsampled to 1,024 pixels; its raw source is retained separately.
The input archive retains each photograph's author, source, license and changes.
Photos are CC BY 2.0, Open Images metadata CC BY 4.0, and CLINC150 CC BY 3.0.

## Primary results

| Modality | Held-out n | Original direct agreement | Guided direct agreement | Original / guided named matches | Both Other, original / guided |
| --- | ---: | ---: | ---: | ---: | ---: |
| Text | 1,000 | 820 / 1,000 | 522 / 1,000 | 809 / 511 | 11 / 11 |
| Natural photographs | 100 | 96 / 100 | 81 / 100 | 91 / 76 | 5 / 5 |

The tested rewrite reduces agreement. Equal shared-Other counts do not mean
identical rejected items. Named matches also fall, so rejection alone does not
explain the result. Agreement with Sol measures reproduction of that model's
choices, not human semantic accuracy. ARI and pair scores treat Other points as
separate singletons rather than one artificial rejection cluster.

Description wording and length change together: whitespace-delimited description
words grow 215→1,435 for text and 142→1,094 for photos. This is one generated
rewrite, not a length-matched or individual-cue ablation. No evaluation-guided
catalog retuning or favorable replacement run is part of the primary comparison.
New photo results are not a resolution-only comparison with Fashion-MNIST: the
dataset, taxonomy, prompt and discovery/evaluation protocol also differ.

The preselected LLM repeats match 97/100 original and 99/100 guided text IDs;
photo repeats match 23/25 and 24/25. These small consistency subsets are not
accuracy estimates or a theoretical ceiling on agreement. Anchoring both
conditions to original Sol assignments is a preplanned secondary diagnostic.
Reversed order and K=16 use the same preselected subsets and remain secondary.
The eight-category image catalog already fits on one K=8 page, so image K=16
is an extra pass with the same options rather than a pagination intervention.

## Blinded review and accounting

The reviewer sees the item, full applicable catalog and shuffled A/B assignments,
without backend identity, condition names or aggregate outcomes. Text review
uses fixed confusion-stratum quotas without reallocating shortfalls; all 100
photos are selected per condition. Report accepted, failed and not-attempted
counts rather than treating selection as completed review. Automated same-family
review is evidence to inspect, not human validation or population accuracy.

The original-photo review stops after 57 accepted judgments, one incomplete API
response and 42 unattempted cases. The failed response exhausts the fixed 8,192
output-token cap. Its $0.086291 known charge remains in the arm's $0.4766555
known subtotal. Recorded cost-history, cost and timing completeness flags remain
false. The missing review is not replaced by a clean rerun.

Discovery, rewriting, primary assignments, repeat passes, review and order/page
diagnostics have separate call journals and measurements. Token prices are
frozen in `preregistration/pricing.json`; estimates are not provider invoices.
Unknown usage or incomplete history never becomes a complete total. Concurrent
arm wall times must not be summed as an experiment's elapsed duration.

## Reproduction pins

- Controlled runtime: `9f80d8400ac23c70c9e5dd2e23c953cdee362410`.
- Controlled executable SHA-256: `9130b82079e107c282dea401261d0e993459126b51411fbe4a659226ac240dce`.
- Analyzer SHA-256: `9c886c11b2341c93bf7b3a8333b57ae05ec65d82a5da87a27863ad968138e719`.
- Dataset manifest SHA-256: `c61ce5b4703e98ae79581c73e492aece53196777ac7510f121bbced59ed752f4`.
- Registered protocol SHA-256: `894b0e577a0f6e778f09855ba676f614620b4992b3f013e8ee61477452181fbd`.
- Review-plan file SHA-256: `e61d2e1055478b90043d20a09319b0294e82bf5213add6f44f130ee896db9bf1`.
- Typed compact review-plan SHA-256: `5d1aa5e17d20991c477822c5c353a222b8d63e01b54dd995d00bb8abfa87391e`.

Offline analysis uses the corrected postprocessor at
`616b5d0d707b926db15e73cc43128fac09904e3c`, executable SHA-256
`f3599d59bca96919bc0dccd4c907b3605fc6169e2d58e3700db2846cf59b49ad`.
The original frozen analyzer fails exact sampling-key validation because its
JSON decoder changes some recorded probabilities by one floating-point ULP.
The correction enables round-trip-safe parsing and retains strict equality;
selections and paid artifacts remain unchanged. The two review-plan pins above
bind the formatted file bytes and typed compact serialization respectively.

Source and binary pins for later streaming stages are separate. Preserve the
controlled runtime and raw evidence when rebuilding or extending the clusterer.
The associated ticket records execution and validation; experiment artifacts
are the authority for measurements and completeness.

## Archived control evidence

`evidence/` contains the terminal control snapshot, including incomplete review
attempts, selected licensed inputs, raw requests/responses, analysis, independent
audit and exact offline helper copies. Verify it without credentials or builds:

```sh
python3 scripts/archive_guided_agreement.py verify \
  experiments/2026-10-20-guided-agreement-seed1042/evidence \
  --manifest-sha256 20d8a470bf9cfb63b5406b1b883f1f23199def56e9577928a8cc9dd9b908b1fa
```

The manifest indexes every original file and each ordered payload part. To
recover a payload, concatenate its parts in manifest order, xz-decompress, and
extract the resulting POSIX tar into a fresh directory. `inputs` and `run` use
separate roots. The readable summaries are byte-identical copies, not a
replacement for the complete raw payload. The manifest's primary runtime pin
refers to the paid control executable; the corrected analyzer has its separate
pin above. Executables and credentials are excluded.

## Reserved evolving streams

`streaming-protocol.json` registers the subsequent eight-arm comparison. It is
designed after interpreting the control, uses the disjoint reserved partition,
and compares the original manager against a combined compact contextual manager
and global reconsideration policy. Each backend evolves its own catalog, so
partition agreement and coverage apply; raw category IDs cannot be compared
across these catalogs. This is neither a confirmation of the negative control
nor an isolated test of description length.

The credential-free `inspect_guided_streaming` example checks actual bootstrap
requests and conservative maximum request sizes without dispatch. The launcher
has separate `plan` and paid `run` modes:

```sh
bash scripts/guided-streaming.sh plan \
  --data /absolute/selected-data \
  --run-root /absolute/experiment-run \
  --binary /absolute/frozen/ld-clustering \
  --protocol /absolute/streaming-protocol.json \
  --preflight /absolute/request-preflight.json
```

Paid execution requires committed runtime/protocol/context files, an immutable
hash-pinned binary and a fresh `streaming/` stage. Run the supervisor in a
service with `KillMode=control-group` so abrupt supervisor death also owns every
worker. Per-arm failures remain terminal evidence. Streaming results and their
raw evidence archive have separate runtime pins and do not modify `evidence/`.
