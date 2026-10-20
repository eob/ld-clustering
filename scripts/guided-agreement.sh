#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: guided-agreement.sh catalog|controlled|repeat|review|diagnostics DATA_DIR RUN_DIR'
  echo 'Makes paid calls. Set LD_GUIDANCE_BINARY to the frozen guided_agreement executable.'
}

if [[ "${1:-}" == --help ]]; then usage; exit 0; fi
if [[ $# != 3 ]]; then usage >&2; exit 2; fi
stage="$1"
case "$stage" in catalog|controlled|repeat|review|diagnostics) ;; *) usage >&2; exit 2;; esac
cd "$(dirname "$0")/.."
data_dir="$(realpath "$2")"
run_dir="$(realpath -m "$3")"
binary="${LD_GUIDANCE_BINARY:-target/release/examples/guided_agreement}"
binary="$(realpath "$binary")"
test -x "$binary"
test -f "$data_dir/manifest.json"
test -n "${OPENAI_API_KEY:-}"
git diff --quiet -- src examples Cargo.toml Cargo.lock scripts/guided-agreement.sh
git diff --cached --quiet -- src examples Cargo.toml Cargo.lock scripts/guided-agreement.sh
mkdir -p "$run_dir"
stage_dir="$run_dir/$stage"
mkdir "$stage_dir"
git rev-parse HEAD > "$stage_dir/source-commit.txt"
sha256sum "$binary" > "$stage_dir/binary-sha256.txt"
sha256sum "$data_dir/manifest.json" > "$stage_dir/dataset-manifest-sha256.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$stage_dir/launched-at.txt"

pids=()
review_prefixes=()
cleanup() {
  for pid in $(jobs -pr); do kill "$pid" 2>/dev/null || true; done
  for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

catalog_pair() {
  local modality="$1" count="$2"
  local worker=''
  trap 'if [[ -n "$worker" ]]; then kill "$worker" 2>/dev/null || true; wait "$worker" 2>/dev/null || true; fi' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  "$binary" discover --input "$data_dir/discovery/$modality.jsonl" \
    --modality "$modality" --expected "$count" --max-clusters 16 \
    --log "$stage_dir/$modality-original.calls.jsonl" \
    --output "$stage_dir/$modality-original.json" &
  worker="$!"
  wait "$worker"
  worker=''
  "$binary" rewrite --input "$data_dir/discovery/$modality.jsonl" \
    --catalog "$stage_dir/$modality-original.json" \
    --modality "$modality" --expected "$count" \
    --log "$stage_dir/$modality-guided.calls.jsonl" \
    --output "$stage_dir/$modality-guided.json" &
  worker="$!"
  wait "$worker"
  worker=''
}

for modality in text images; do
  if [[ "$modality" == text ]]; then count=1000; discovery_count=200; repeat_count=100
  else count=100; discovery_count=60; repeat_count=25; fi
  if [[ "$stage" == catalog ]]; then
    catalog_pair "$modality" "$discovery_count" > "$stage_dir/$modality.process.log" 2>&1 &
    pids+=("$!")
    continue
  fi
  for condition in original guided; do
    catalog="$run_dir/catalog/$modality-$condition.json"
    test -f "$catalog"
    if [[ "$stage" == review ]]; then
      prefix="$stage_dir/$modality-$condition"
      "$binary" prepare-review --input "$data_dir/heldout/$modality.jsonl" \
        --catalog "$catalog" \
        --reference "$run_dir/controlled/$modality-$condition-llm.json" \
        --candidate "$run_dir/controlled/$modality-$condition-ld.json" \
        --cohort-id "$modality-$condition" --output "$prefix.bundle.json" \
        > "$prefix.prepare.log" 2>&1
      review_prefixes+=("$prefix")
      continue
    fi
    if [[ "$stage" == repeat ]]; then
      prefix="$stage_dir/$modality-$condition-llm"
      "$binary" repeat --input "$data_dir/repeat/$modality.jsonl" \
        --catalog "$catalog" --mode llm --expected "$repeat_count" --k 8 \
        --reference "$run_dir/controlled/$modality-$condition-llm.json" \
        --reference-input "$data_dir/heldout/$modality.jsonl" --repeat-index 1 \
        --log "$prefix.calls.jsonl" --output "$prefix.json" \
        > "$prefix.process.log" 2>&1 &
      pids+=("$!")
      continue
    fi
    if [[ "$stage" == diagnostics && "$condition" == original ]]; then continue; fi
    for mode in llm ld; do
      if [[ "$stage" == controlled ]]; then
        prefix="$stage_dir/$modality-$condition-$mode"
        "$binary" classify --input "$data_dir/heldout/$modality.jsonl" \
          --catalog "$catalog" --mode "$mode" --expected "$count" --k 8 \
          --log "$prefix.calls.jsonl" --output "$prefix.json" \
          > "$prefix.process.log" 2>&1 &
        pids+=("$!")
      else
        for policy in reverse one-page; do
          prefix="$stage_dir/$modality-$condition-$mode-$policy"
          options=(--diagnostic --k 16)
          if [[ "$policy" == reverse ]]; then options=(--diagnostic --k 8 --reverse-catalog-order); fi
          "$binary" repeat --input "$data_dir/repeat/$modality.jsonl" \
            --catalog "$catalog" --mode "$mode" --expected "$repeat_count" \
            --reference "$run_dir/controlled/$modality-$condition-$mode.json" \
            --reference-input "$data_dir/heldout/$modality.jsonl" \
            --repeat-index 2 \
            "${options[@]}" --log "$prefix.calls.jsonl" --output "$prefix.json" \
            > "$prefix.process.log" 2>&1 &
          pids+=("$!")
        done
      fi
    done
  done
done

for prefix in "${review_prefixes[@]}"; do
  "$binary" review --bundle "$prefix.bundle.json" \
    --log "$prefix.calls.jsonl" --output "$prefix.json" \
    > "$prefix.process.log" 2>&1 &
  pids+=("$!")
done

result=0
for pid in "${pids[@]}"; do wait "$pid" || result=1; done
pids=()
printf '%s\n' "$result" > "$stage_dir/supervisor-exit-code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$stage_dir/finished-at.txt"
exit "$result"
