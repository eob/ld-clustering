# Interrupted first cohort, seed 42

Status: interrupted. Both image arms completed. The LLM text arm stopped at
216 points after the supervisor received SIGTERM. The LD text arm completed
1,000 points, but one HTTP 503 response omitted usage. A fresh complete cohort
is running at `runs/main-seed42-detached`. The signal source is not established.
These incomplete text results are excluded from the full primary comparison.
All observed costs and uncertainty are retained in `attempt-outcome.json`; a
request in flight when the LLM arm stopped may be absent from its journal.

The main experiment uses 1,000 CLINC requests and 100 Fashion-MNIST images, each
processed by independent mutable LLM and LD clusterers. Source, binary, input
order and data hashes are pinned in the accompanying files. Image measurements
include cluster creation, assignments, management, reassignment and persistence;
common preparation and CLI input validation are excluded. Both arms use one
outstanding API request at a time. Four main arms were launched together.

The image result shows 4.575× lower token-priced cost and 4.408× lower elapsed time
for LD, together with ARI 0.33836 and 31 Other points versus none in the reference.
This is a speed/cost tradeoff with substantial partition disagreement. It is not
evidence of a quality-preserving replacement. The small 28×28 grayscale clothing
task does not establish performance on general photographs.

Raw SQLite and API journals are archived unchanged with gzip timestamps fixed
to zero. Dataset licenses and attribution accompany selected inputs and calls;
BSD applies to code, not to the upstream dataset material. Input JSONL bytes retain
original execution-machine image paths for auditing. To run on another machine,
use `prepare` to regenerate paths; selected IDs/order/pixels remain reproducible.

## Recompute without API calls

Decompress the two image databases and journals into a temporary directory, then
run the committed Rust `compare` command with `--expected 100`. It opens state
read-only, verifies run identity and every committed successful call against the
journal, recomputes token-priced costs and calculates partition metrics. It does
not resolve the original image paths when comparing completed evidence. Compare
the recomputed JSON semantically with `images-results.json`.

```sh
verify_dir=$(mktemp -d)
for arm in llm ld; do
  gzip -dc images-$arm.sqlite.gz > "$verify_dir/images-$arm.sqlite"
  gzip -dc images-$arm.calls.jsonl.gz > "$verify_dir/images-$arm.calls.jsonl"
done
../../target/release/ld-clustering compare \
  --baseline "$verify_dir/images-llm.sqlite" \
  --baseline-log "$verify_dir/images-llm.calls.jsonl" \
  --ld "$verify_dir/images-ld.sqlite" \
  --ld-log "$verify_dir/images-ld.calls.jsonl" \
  --expected 100 --output "$verify_dir/images-recomputed.json"
```

Use `sha256sum -c SHA256SUMS` to verify committed files. `manifest.json` records
both compressed and original hashes. `images-partitions.json` provides readable
cluster definitions, sizes and point assignments.

The completed image pair remains a valid first observation. `image-analysis.json`
independently enumerates all 4,950 point pairs and records supplementary
diagnostics. The identical bootstrap requests produced different catalogs
before either assignment backend ran, so these full-system figures cannot
isolate the assignment model alone. A separately reported frozen-catalog
diagnostic addresses that question.
