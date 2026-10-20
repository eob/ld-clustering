# Require invocation evidence before classifying legacy timing as uninterrupted

Status: Considering
Created: 2026-10-20
Type: Bug
Area: Comparison timing and cost provenance
Reporter: Codex
Owner: Unassigned
Implementation branch: Not started
PR: None
Reviewed source: 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c
Evidence: Code review only; no observed v2 benchmark impact established
Release scope: Follow-up; do not change the current frozen experiment

## Problem and evidence

`src/results.rs:274` initializes session completeness with
`starts.len() == finishes.len()`. A compatible legacy database with no
`run_start` or `run_finish` events therefore begins with a true result. The loop
has no rows, and the elapsed-sum/final-success check at line 282 only runs when
`run_sessions > 0`.

For such a database, `timing_complete=true` and `run_in_progress=0` metadata can
make the reported timing complete at lines 286-288. `cumulative` is false at
lines 265-269 because there is no first session, so line 292 reports
`timing_scope=uninterrupted_loop`. With reported usage for every journal row and
no false cost-history marker, line 290 can also retain `cost_complete=true`.
The absence of invocation records does not prove that the legacy run used one
uninterrupted loop or retained every potentially charged request.

This follows from the current boolean branches; no running database was read,
fixture executed, or benchmark result generated for this review. An offline
reproduction should use a complete compatible legacy fixture with zero session
events, a positive saved wall duration, those metadata flags, and known usage.
The current branch classifies that history as uninterrupted without proof.

## Proposed scope

Keep compatible legacy assignments and known recorded costs readable, but
represent unsupported timing/continuity as unknown or incomplete. Do not infer
an uninterrupted invocation from two empty event lists. If explicit external
proof is supported, distinguish it from an inference based only on legacy
metadata. Preserve existing valid fresh and cumulative-session semantics.

## Acceptance criteria

- A focused regression first reproduces the zero-session legacy classification
  above, then requires incomplete/unknown timing instead of an uninterrupted
  claim; unsupported cost continuity remains incomplete with its known subtotal.
- A zero unknown-usage-row count alone does not restore complete continuity.
- A valid fresh start/finish pair beginning at zero retains complete
  uninterrupted timing, provided the other existing checks pass.
- Multiple valid pairs remain cumulative processing intervals, while unmatched
  or malformed session histories remain incomplete.
- Checks are offline and assert events, flags and accumulated work; they use no
  wall-clock threshold or paid API call. Retain original legacy artifacts and
  their measured runtime pins.

## Current experiment impact and non-goals

No impact is established on the mandatory single-fresh v2 primary archive or
complete-control publication. The v2 archive verifier independently requires
ordered run-start/finish provenance beginning from empty state; the fresh arms
have that provenance. The separate complete-control verifier requires fresh
artifacts, 100 assignments and raw journal/progress replay. Earlier archives
retain their original executable and provenance rather than being silently
reclassified by the amended comparator.

Do not alter frozen runtime files, rerun paid streams, rewrite archived results,
invent prior session counts, or broaden this into a persistence redesign.
Decide implementation on a separate branch.
