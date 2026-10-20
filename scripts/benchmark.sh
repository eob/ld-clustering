#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

run_dir="${1:-runs/main-seed42}"
mkdir -p "$run_dir"
binary="${LD_CLUSTERING_BINARY:-target/release/ld-clustering}"
test -x "$binary"
test -f data/manifest.json
git diff --exit-code -- src Cargo.toml Cargo.lock
git diff --cached --exit-code -- src Cargo.toml Cargo.lock
git rev-parse HEAD >"$run_dir/source-commit.txt"
sha256sum "$binary" >"$run_dir/binary-sha256.txt"
cp data/manifest.json "$run_dir/dataset-manifest.json"
date -u +%Y-%m-%dT%H:%M:%SZ >"$run_dir/launched-at.txt"

# One sequential stream per arm. The four independent arms overlap in real time.
pids=()
cleanup() {
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for dataset in text images; do
  if [[ "$dataset" == text ]]; then
    bootstrap=24
    interval=100
    task='Group customer requests by broad practical subject or service domain, rather than fine-grained intent or wording. Create coherent reusable groups from the observed evidence. Keep unrelated requests in Other when no group fits. Do not force every request into an existing group.'
  else
    bootstrap=20
    interval=25
    task='Group clothing images by the visible kind of garment, footwear, or accessory, rather than color, style, orientation, or background. Create coherent reusable groups from observed evidence. Keep unclear or unrelated images in Other when no group fits.'
  fi
  for mode in llm ld; do
    "$binary" run --input "data/$dataset.jsonl" \
      --database "$run_dir/$dataset-$mode.sqlite" \
      --log "$run_dir/$dataset-$mode.calls.jsonl" \
      --mode "$mode" --task "$task" --k 8 --max-clusters 16 \
      --bootstrap "$bootstrap" --novelty 8 --maintenance-interval "$interval" \
      >"$run_dir/$dataset-$mode.process.log" 2>&1 &
    pids+=("$!")
    printf '%s %s pid=%s\n' "$dataset" "$mode" "$!"
  done
done

result=0
for pid in "${pids[@]}"; do
  wait "$pid" || result=1
done
exit "$result"
