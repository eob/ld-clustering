# Offline final-cohort archive helper

Script: `/tmp/ld-archive-final.py`. Run from any directory only after root confirms
all primary and resume processes are terminal. It makes no API calls, edits no
source/database/journal, and refuses an existing archive destination.

For the currently known single text-LD recovery:

```sh
python3 /tmp/ld-archive-final.py \
  --repo /mnt/disks/data/ld-clustering \
  --run runs/main-seed42-detached \
  --output experiments/2026-10-20-main-seed42-detached \
  --resume-history runs/main-seed42-detached/text-ld-resume-history.json \
  --resume-service ld-clustering-text-ld-resume1-20261020.service \
  --operational runs/frozen-images-seed42/after-main.py
```

The original service is checked by default. A collected/not-found systemd unit
has unknown terminal Result, never inferred success. Independent guards require
no matching `/proc` primary/resume CLI process, exactly 1000/100 persisted points
and assignments, completed markers, empty queues, valid SQLite integrity/foreign
keys, and terminal successful resume history. The helper currently supports the
one explicitly recorded text-LD resume; another recovery needs a deliberate
history/schema update, not silently dropping history.

The original unit can have exited 1 after its original LD child failed, while the
separate resumed arm later finishes. The original return code is preserved.
`wall_seconds` remains the frozen Rust output unchanged. For text LD it is summed
active-loop duration, excludes manual downtime/CLI validation, and must not be
called uninterrupted elapsed time. External calendar duration, original wall_ms,
error row boundary and resume timestamps are retained separately.

Provenance is deliberately split:

- Runtime source: `59656c06db2e2ec8599b3bc31f90144a451e27b3`.
- Launch checkout: `bdee72c39faf99460b641b852859c8624ec42432`.
- Archive checkout: whatever documentation commit root has when archiving.
- Runtime, binary and input pins are independently checked. Keep the frozen
  main binary and runtime files unchanged until primary/control archives verify;
  only then apply the held results accounting patch.

The helper creates a sibling staging directory, preserves raw DB/log bytes in
mtime-zero gzip, verifies shared inputs/licenses/pricing against the immutable
first archive, binds both DB Item payloads and input fingerprints to those pinned
inputs (including every PNG hash), generates frozen Rust comparisons, independently
enumerates every pair, independently prices recorded usage with Decimal, retains
all attempt/error source row indices and unknown charges, and replays comparisons
from decompressed relocated copies. It atomically installs the destination only
after verification succeeds. Operational supervisors/waiters and this verifier
are retained under `operational/`, separately from the frozen Rust runtime.

After creation, repeat the read-only archive verification:

```sh
python3 /tmp/ld-archive-final.py \
  --repo /mnt/disks/data/ld-clustering \
  --verify-only experiments/2026-10-20-main-seed42-detached
```

Validation already performed without archiving the live cohort:

- Python compilation and CLI help.
- Exact-pair metric anchors and degenerate cases.
- Read-only completed replacement image pair: independent metric/cost agreement;
  LD missing usage correctly identified at source JSONL lines 88 and 242.
- Deterministic gzip roundtrip and timestamp-zero check.
- Full synthetic four-arm archive fixture with real pinned input payloads but
  deliberately artificial assignments: checksums, decompression, relocated frozen
  comparisons and independent metrics all pass. This fixture is NOT experiment
  evidence and is deleted automatically.
- Missing/collected unit handling and live `/proc` process detection.

No live final archive has been created by this helper. Root owns its execution,
publication and immutable commit links. The separate frozen-catalog control needs
its own archive and must not be folded into the primary measurements.
