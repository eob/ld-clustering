# Provider evidence

Status: Implemented and verified

## Behavioral red evidence

Before implementing request construction, response decoding, or pricing, `cargo test provider::tests -- --nocapture` produced:

```text
assignment_wire_hides_evaluation_label_and_uses_native_decisions:
evaluation label leaked into request: {"input":{"clusters":[{"description":"Invoices and payment questions","id":7,"name":"Payments"}],"item":{"id":"a","label":"SECRET_GROUND_TRUTH","text":"My invoice is incorrect"},"task":"Group support messages"},"model":"ld"}
cache_reads_writes_and_reasoning_output_have_distinct_prices:
assertion `left == right` failed
  left: 0
 right: 1000
native_choice_is_decoded_and_unknown_choice_is_refused:
called `Result::unwrap()` on an `Err` value: typed assignment decoding is not implemented
test result: FAILED. 0 passed; 3 failed; 0 ignored
```

## Protocol and price pins

Retrieved 2026-10-20 from official OpenAI documentation:

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/guides/decisions
- https://developers.openai.com/api/reference/resources/decisions/methods/create
- https://developers.openai.com/api/docs/guides/structured-outputs

Use `gpt-6.1-sol` and `reasoning.effort=high` for LLM assignment and planning.
Use `gpt-6-luna` only through `/v1/decisions` for LD assignment.
Standard Sol rates per million tokens: input $2, cached reads $0.10,
cache writes $2.50, output $10. Output already includes reasoning tokens;
never add reasoning tokens a second time.
Decisions input costs $0.10 per million tokens; the endpoint has no
cache-read, cache-write, or output-token charges. All experiments remain
below the >272K-input long-context price boundary and use standard processing.
Prices are estimates from recorded provider usage, not reconciled invoices.
Requests above 272K input apply 2x input/cache and 1.5x output rates;
regression tests pin this boundary even though these experiments stay below it.

Authenticated GET `/v1/models` returned HTTP 200 and listed both model IDs.
Credentials were not printed. Model listing alone is not inference verification.

## Recovery and retry policy

Every dispatched HTTP attempt is flushed to append-only JSONL, including failed
responses and semantic refusals. Journal rows retain the exact credential-free
request, response, usage, elapsed time, status, attempt index, and error.
The SQLite call record contains the final successful attempt; account for retries
from JSONL when computing complete experimental cost.

Up to three attempts are permitted for HTTP 429/502/503/529 and connection
establishment failures. Other transport failures and HTTP 500/504 may have
completed upstream; retain the attempt and fail rather than retry automatically.
No provider error or refusal silently changes models, picks Other, or returns an
unmeasured fabricated result.

## Verification

| Gate | Result |
| --- | --- |
| Initial behavioral Red | 3 focused tests failed for label leakage, absent typed decode, and zero token usage |
| Reversion check | Restoring the original request construction reproduced the same label-leak failure (exit 101); restored implementation passed |
| `cargo test --lib provider::tests -- --nocapture` | 9 passed, 0 failed; 1 paid live test ignored |
| `cargo clippy --lib --tests -- -D warnings` | Passed |
| Explicit `live_text_image_provider_smoke` | 6 live calls passed; labels absent from all logged requests |

The new repository has no base commit yet. Provider source was reviewed with
`simplifyfu`: one HTTP path serves assignments and plans, and shared pure helpers
cover evidence serialization, response decoding, pricing, and plan invariants.
No SDK or Kaya dependency was introduced.

Live smoke command:

```sh
LD_SMOKE_LOG=/tmp/ld-provider-smoke-20261020.jsonl cargo test provider::tests::live_text_image_provider_smoke -- --ignored --nocapture
```

| Call | Model | Elapsed ms | Estimated USD |
| --- | --- | ---: | ---: |
| Text assignment, LLM | gpt-6.1-sol high | 2993 | 0.00062800 |
| Image assignment, LLM | gpt-6.1-sol high | 2222 | 0.00060200 |
| Text assignment, LD | gpt-6-luna Decisions | 513 | 0.00001890 |
| Image assignment, LD | gpt-6-luna Decisions | 114 | 0.00001860 |
| Text planning | gpt-6.1-sol high | 4675 | 0.00242400 |
| Image planning | gpt-6.1-sol high | 3987 | 0.00186400 |

These six synthetic protocol probes are not benchmark observations. Every call
returned HTTP 200, usage, the expected assignment or a valid plan, and no retry.
The benchmark must measure full workflows independently.

All provider requests exclude `Item.label`, original IDs, and image paths; image
bytes are encoded inline. The task and current cluster descriptions are the only
category guidance. The permanent Other choice is always last. Native Decisions
needs at least one existing cluster, because its choice schema requires two
options including Other; the engine bootstraps before model assignment.

`usage_available=false` identifies failed attempts without reported usage. Their
zero-valued `Usage` does not prove no charge. Do not report a complete known cost
when such potentially dispatched failures remain unresolved. SQLite successful
call rows alone omit failed/retried attempts; the JSONL journal is authoritative
for full experiment provider costs. Workflow wall time includes retry backoff.

## Journal binding and measurement audit follow-up

Independent review reproduced a false completion: two completed databases with
no calls could be compared against the same unrelated one-row log, yielding
`status=complete`, `cost_complete=true`, and an invented tiny measured cost.
The committed regression initially failed with:

```text
complete_databases_reject_one_unrelated_shared_journal:
a wrong shared log was accepted as complete measured evidence
test result: FAILED. 0 passed; 1 failed
```

CLI runs now bind a random run ID in SQLite to a first-line JSONL header and
the canonical request-log path. A fresh database refuses a nonempty existing
log. Resume checks every committed SQLite call against a journal success before
spending, ignoring only the engine's later `assign` to `reassign` phase change.
Comparison repeats this coverage check, rejects wrong/truncated logs and
tampered usage/cost/model fields, recomputes token charges from raw responses,
and includes any bound-log successful calls that were not committed to SQLite
as `uncommitted_success_calls`. Such orphan calls are billed rather than hidden.
Copied database/log evidence remains comparable by run ID; resuming execution
requires the original canonical log path.

`timing_complete` comes from the engine's clean-run markers; missing metadata or
an interrupted session makes timing explicitly incomplete. Assignment completion
alone does not establish cost/timing completeness for publication.

Input fingerprints now include raw JSONL bytes and the ordered local image bytes
with domain separation and length prefixes. Changing an image at the same path
changes the run identity. The reproducible CLI rejects HTTP image URLs with an
instruction to download the file; direct provider protocols still support them.

Verification added five result audit tests and three CLI binding/hash tests.
The full offline suite passed (31 library tests plus 3 CLI tests; one paid live
provider test ignored), as did formatting and all-target Clippy.
