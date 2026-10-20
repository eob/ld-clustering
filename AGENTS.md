# LD Clustering

Use Rust. Code is BSD-3-Clause; downloaded datasets retain their own licenses.
Keep credentials and bulk source downloads out of Git. Selected licensed
benchmark inputs and model-call evidence may be archived under experiments/
with upstream notices. Never invent benchmark results.
Preserve model IDs, API usage, measured elapsed time, prices and dataset hashes.

Work on a feat-* branch and deliver through a GitHub PR. Planning and durable
experimental findings belong in tickets/. Run cargo test, cargo fmt --check and
cargo clippy --all-targets -- -D warnings before handoff. Tests must be offline
unless explicitly marked as live experiments. No wall-clock threshold assertions.
