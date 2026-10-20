# Preserve accounting uncertainty after a request-journal I/O failure

Status: Considering
Created: 2026-10-20
Type: Bug
Area: Provider journaling and resumed cost accounting
Reporter: Codex
Owner: Unassigned
Implementation branch: Not started
PR: None
Reviewed source: c1c77c0a69707bdb49de5cb35ba548971e2861bd
Amended source reviewed: 9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c
Evidence: Code review only; no observed benchmark impact established
Release scope: Follow-up; do not change the current frozen experiment

## Problem and evidence

`src/provider.rs:97` dispatches inference before `src/provider.rs:164` writes the
attempt to the journal. `journal` can fail while serializing, writing the newline,
or flushing (`src/provider.rs:76`). The request may already have completed and
incurred a charge, yet an I/O failure can leave no complete attempt row.

That error returns normally through `Clusterer::run`. `src/engine.rs:136` saves
its measured loop duration and clears `run_in_progress` at line 141 for a normal
error return. Consequently, a subsequent successful resume may retain clean
history markers and complete usage for every remaining recorded row even though
one dispatched request was never recorded. Matching SQLite calls to existing
journal rows cannot discover that omitted request.

This is a source-level failure mechanism, not an observed cohort failure. No
journal I/O error was found in the reviewed benchmark artifacts. The separate
conservative treatment of unclean interrupted history does not by itself cover
this cleanly returned logging error.

## Proposed scope

Persist or preserve accounting uncertainty when journaling fails after dispatch,
and prevent later resume/summary logic from silently converting it to a complete
cost claim. Choose a minimal explicit failure/continuity mechanism; retain known
usage and its subtotal rather than inventing a charge. If durable storage itself
cannot record uncertainty, stop without asserting that the ledger is complete.

Documentation must describe current accounting as verification of observed
records and clean-history markers. It must not promise a complete billing ledger
under disk or journal-storage failure. Preserve the current frozen executable
and all original experiment evidence.

## Acceptance criteria

- An offline fake transport can complete a request with reported usage while an
  injected journal writer fails before recording a complete row.
- A normal error exit followed by resume cannot claim complete accounting for
  that history; known recorded costs remain available as a subtotal.
- Missing-usage counters count observed rows without usage, not an invented
  number of requests potentially lost during a storage failure.
- A failed frozen-catalog control cannot label its recorded subtotal complete
  after a dispatched request fails to reach the journal. Preserve its failed
  status, completed assignment prefix, and known recorded usage.
- A successful complete control with all reported usage retains its complete
  flag; a missing-usage count of zero alone never proves continuity after an
  unrecorded request.
- Point/assignment conservation and safe refusal of malformed journals remain
  intact.
- Tests assert writer outcomes, durable markers, and dispatch/record counts;
  they use no wall-clock completion threshold and make no paid API calls.
- A focused regression fails before the fix and passes afterward; existing
  offline tests, formatting, and Clippy remain green.

## Non-goals

Do not redesign all persistence, claim any observed cohort impact, reconstruct
unreported charges, alter the frozen control, or expand the current release.
Decide implementation in a separate branch.

## Current state

The amended feature runtime now conservatively persists
`cost_history_complete=false` on any terminal invocation error, before clearing
its in-progress marker. Its verifier preserves that uncertainty after a later
resume, and run-start/finish events provide invocation evidence. A regression
simulating a completed request followed by a journal error proves that generic
continuity guard; causal reversion loses the marker. The remaining follow-up is
explicit provider-writer fault injection and clearer storage-error context,
rather than the original unmarked normal-error path. No actual benchmark
journal-storage failure has been observed.

## Remaining failed-control summary path

The amended primary engine's terminal-error guard does not cover the separate
frozen-catalog example. In the reviewed amended source,
`examples/frozen_catalog.rs:239` initializes `journal_summary`'s cost flag to true
and line 274 only combines the usage flags of rows that exist. At line 384 an
assignment error becomes the final output's error, but a successful journal
summary at line 386 is retained unchanged in `measurement` at line 432.

The provider can receive a charged response and then return a journal-write
error through `src/provider.rs:167`. If that writer fails before appending any
bytes, the earlier journal prefix can remain valid and contain only known-usage
rows. The control then correctly writes `status=failed` and incomplete timing,
but can still write `measurement.cost_complete=true` for that earlier subtotal.
Its `unknown_usage_calls` may be zero because the missing request has no row.
This is code-review evidence; this control writer failure has not been injected
or observed in an experiment.

Extend the proposed offline writer-injection check to this example: retain a
known-usage prefix, complete the next fake request, fail its journal write before
the next row, and require a failed output with incomplete cost continuity and
the preserved known subtotal. Assert dispatch/record counts and flags, with no
timing threshold or paid API request. The exact mechanism can conservatively
invalidate cost continuity on terminal control errors, consistent with the
primary engine; it must not fabricate a charge or missing-request count.

There is no established impact on the mandatory single-fresh v2 primary archive
or complete-control publication. The primary has its terminal-error guard;
the control archiver/publication path requires `status=complete`, 100 assignments,
and raw journal/progress replay, so a failed control is not publishable as a
complete diagnostic. Keep this follow-up outside the frozen runtime and do not
rewrite original artifacts.
