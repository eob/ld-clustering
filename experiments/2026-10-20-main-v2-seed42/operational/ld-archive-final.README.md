# Offline amended-cohort archiver

Script: `/tmp/ld-archive-final.py`. Its creation mode requires explicit full
runtime commit, launch checkout and executable SHA-256 pins. Dataset pins remain
unchanged. It makes no API calls and never writes live state or source. Root owns
execution, review, archive commit and immutable publication links.

Run only after all four primary arms are terminal. Replace the three uppercase
pins and exact primary systemd unit with the green launch provenance:

```sh
python3 /tmp/ld-archive-final.py \
  --repo /mnt/disks/data/ld-clustering \
  --run runs/main-v2-seed42 \
  --output experiments/2026-10-20-main-v2-seed42 \
  --runtime-source RUNTIME_COMMIT \
  --launch-head LAUNCH_CHECKOUT_COMMIT \
  --binary-sha256 EXECUTABLE_SHA256 \
  --service PRIMARY_SYSTEMD_UNIT
```

`--binary` defaults to `target/release/ld-clustering`; point it at a saved exact
copy if the working build changes. Creation refuses a different binary, source
content mismatch against the pinned runtime, existing output, matching live
`/proc` run processes, live primary/resume service, incomplete 1000/100 counts,
pending reassignments, bad SQLite/foreign keys or nonmatching pinned input bytes.
Collected/not-found systemd units have unknown terminal Result. That does not
mean successful service exit; persisted run boundaries independently prove arm
completion. No model name, price or missing charge is inferred from service state.

For a clean cohort no resume history is required. Each arm must have exactly one
ordered run_start/run_finish pair, saved_count=0, prior_wall_ms=0 and successful
finish; summed event milliseconds must equal SQLite wall_ms. The helper detects
additional invocations, resume-named files and declared resume units. Any such
recovery requires explicit byte-preserved `--resume-history PATH` and (when
applicable) `--resume-service UNIT`. Both options repeat. Empty, stop-only,
unfinished, wrong-role or omitted history is rejected. This bounded helper handles
one external recovery per role; another recovery needs an explicit history-chain
verifier. Recovered roles report cumulative measured active loops and retain
external calendar/downtime records; they must never be called uninterrupted runs.

`--operational PATH` repeats to retain additional credential-free supervisor,
waiter, service definition or log files. All auxiliary regular files already in
the run directory are retained automatically. The exact configured credential is
checked against evidence before copying; request bodies contain no auth headers.
Keep source, build and operational provenance unchanged while the helper runs.

Output contains timestamp-zero gzip copies of each raw SQLite state, call journal
and process log; copied pinned inputs, PNGs, licenses and pricing; full frozen
Rust text/image comparisons; readable cluster definitions, assignments, dataset
labels and every maintenance/run/refusal event; independent exact-pair agreement;
full charged-attempt ledger with original physical JSONL line indices, unknown
usage and planner/assignment cost split; explicit resume/session/refusal evidence;
and runtime/launch/archive checkout pins. Refusal count is per accepted request,
not per point or final Other assignment. Typed assignment refusal maps to Other;
planner refusal remains a failed attempt. Every retry must retain the exact body
and increment a preceding failure's attempt number within three total attempts.

All selected input Item payloads are bound to the original archived JSONL bytes,
ordered IDs and each PNG hash. Frozen Rust comparison outputs must replay exactly
from decompressed relocated copies. Independent verification enumerates every
unordered pair and prices raw reported usage using Decimal. Other is a unique
singleton for each point in headline metrics; shared-Other sensitivity and
mutually-covered scores remain separately identified diagnostics. Missing usage
and possible unrecorded calls are never priced at zero. The helper atomically
installs output only after the staged archive passes verification.

Repeat read-only verification with the exact measured binary:

```sh
python3 /tmp/ld-archive-final.py \
  --repo /mnt/disks/data/ld-clustering \
  --binary /path/to/exact/measured/ld-clustering \
  --verify-only experiments/2026-10-20-main-v2-seed42
```

Verification mode takes pins from the immutable manifest; optional explicit pins
must agree. It verifies hashes/decompression, pinned inputs, DB integrity, raw
refusal flags/counters, run events, all-pair metrics, Decimal pricing and relocated
Rust outputs. Publish source and archive links by immutable Git commits.

Both earlier cohorts remain unchanged. Their text streams are interrupted and
cannot provide the full headline comparison. Original helper/instructions:
`/tmp/ld-archive-final-v1.py`, `/tmp/ld-archive-final-v1.README.md`; original exact
executable: `/tmp/ld-clustering-v1-frozen`. Second interrupted archive:
`experiments/2026-10-20-main-seed42-detached`, manifest SHA-256
`ae602400ee66cb701d1582f501eb861b0a35b9b55e1f540839ba6ba659e47035`.

Validated so far: Python compile/help, nine focused offline checks covering
clean/resumed history, invalid history rejection, native/Sol raw refusal flags,
known refusal charge vs unknown failed usage, nullable transport responses with unknown cost retained, exact session elapsed sum, persisted
refusal membership, explicit full pins and same-body bounded retries. Full amended-binary creation and relocated verify-only replay passed against
runtime/launch commit `9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c` and main executable
SHA-256 `8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160`: 35 archived
payloads in an automatically removed synthetic repository/run/archive. The end-to-end
fixture is `/tmp/ld-archive-v2-full-fixture.py`. Synthetic fixture
outputs are disposable and never experimental evidence. No final live archive or
paid call has been run by this helper.
