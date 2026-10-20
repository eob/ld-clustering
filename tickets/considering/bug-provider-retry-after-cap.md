# Respect the minimum delay in Retry-After responses

Status: Considering
Created: 2026-10-20
Type: Bug
Area: OpenAI provider retry policy
Reporter: Codex
Owner: Unassigned
Implementation branch: Not started
PR: None
Reviewed source: c1c77c0a69707bdb49de5cb35ba548971e2861bd
Evidence: Code review only; no observed benchmark impact established
Release scope: Follow-up; do not change the current frozen experiment

## Problem and evidence

`src/provider.rs:108` reads integer `Retry-After` seconds, but
`src/provider.rs:177` applies:

```rust
retry_after.unwrap_or(1 << (attempt - 1)).min(30)
```

A valid server minimum of 60 seconds therefore becomes 30 seconds. The caller
retries sooner than requested. The official OpenAI rate-limit guidance says to
wait at least the valid server delay; when that delay exceeds a configured retry
budget, stop or defer instead of retrying early:
https://developers.openai.com/api/docs/guides/rate-limits

This finding follows directly from the reviewed code. No archived response
headers establish that a long Retry-After hint occurred in either benchmark
cohort. This ticket does not claim that observed costs, outcomes, or timing were
affected.

## Proposed scope

Keep bounded retry attempts. Treat a valid Retry-After value as a minimum. Either
honor it or return a clearly deferred failure when it exceeds the retry budget.
Keep fallback backoff for missing or invalid hints. Preserve every existing
request-attempt journal record and avoid hidden retries or model fallback.
Do not change the frozen cohort's executable, requests, or artifacts.

## Acceptance criteria

- A valid hint above 30 seconds is never shortened below the server minimum.
- The client honors that delay or stops before dispatching another attempt.
- Missing/invalid hints still use bounded fallback backoff.
- Tests use an injectable wait recorder or virtual clock to verify selected
  durations and dispatch counts; no assertion depends on finishing within a
  wall-clock threshold.
- A focused regression fails before the fix and passes afterward.
- Existing offline provider tests, formatting, and Clippy remain green.

## Non-goals

No new retry family, broad backoff redesign, retrospective benchmark adjustment,
or extra API experiment is required. Decide implementation in a separate branch.
