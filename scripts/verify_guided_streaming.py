#!/usr/bin/env python3
"""Audit terminal reserved streams offline; never dispatch requests or build code.

--run-root names the streaming stage containing run-plan.json and eight arms.
--binary optionally supplies relocated bytes of the pinned executable; it is never run.
"""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import subprocess

_path = Path(__file__).with_name("verify_guided_agreement.py")
_shared = {"__name__": "streaming_audit_shared", "__file__": str(_path)}
exec(compile(_path.read_bytes(), str(_path), "exec"), _shared)
require = _shared["require"]
sha = _shared["sha"]
canonical = _shared["canonical"]
struct_json = _shared["struct_json"]
assert_tree = _shared["assert_tree"]
is_refusal = _shared["is_refusal"]
raw_record = _shared["raw_record"]
reprice = _shared["reprice"]
decimal_text = _shared["decimal_text"]
SOL, DECISIONS = _shared["SOL"], _shared["DECISIONS"]
EXPERIMENT = "experiments/2026-10-20-guided-agreement-seed1042"
SOURCE_FILES = (
    "Cargo.toml",
    "Cargo.lock",
    "src/main.rs",
    "src/engine.rs",
    "src/store.rs",
    "src/results.rs",
    "src/provider.rs",
    "src/types.rs",
    "src/metrics.rs",
    "src/lib.rs",
    "scripts/guided-streaming.sh",
)
CALL_FIELDS = ("phase", "model", "request", "response", "elapsed_ms", "usage")


def read(path):
    return json.loads(Path(path).read_bytes())


def file_pin(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def uint(value):
    return type(value) is int and 0 <= value <= 2**64 - 1


def partition(reference, candidate, singleton_other=True):
    """Enumerate pairs independently of Rust's contingency-table implementation."""
    require(
        len(reference) == len(candidate) and reference, "empty or mismatched partition"
    )
    tp = fp = fn = tn = 0
    for i in range(len(reference)):
        for j in range(i + 1, len(reference)):
            a = reference[i] == reference[j] and (
                not singleton_other or reference[i] is not None
            )
            b = candidate[i] == candidate[j] and (
                not singleton_other or candidate[i] is not None
            )
            if a and b:
                tp += 1
            elif a:
                fn += 1
            elif b:
                fp += 1
            else:
                tn += 1
    total, rp, cp = tp + fp + fn + tn, tp + fn, tp + fp
    expected = Fraction(rp * cp, total) if total else Fraction(0)
    denominator = Fraction(rp + cp, 2) - expected
    return {
        "n": len(reference),
        "adjusted_rand_index": (
            float((tp - expected) / denominator) if denominator else 1.0
        ),
        "pairwise_precision": tp / cp if cp else (1.0 if not rp else 0.0),
        "pairwise_recall": tp / rp if rp else (1.0 if not cp else 0.0),
        "pairwise_f1": 2 * tp / (rp + cp) if rp + cp else 1.0,
    }


def pair_comparison(left, right):
    require(
        [r[0]["id"] for r in left] == [r[0]["id"] for r in right],
        "comparison input IDs/order differ",
    )
    a, b = [r[1] for r in left], [r[1] for r in right]
    table = {
        "both_named": 0,
        "baseline_named_ld_other": 0,
        "baseline_other_ld_named": 0,
        "both_other": 0,
    }
    for x, y in zip(a, b):
        key = (
            "both_other"
            if x is None and y is None
            else (
                "baseline_other_ld_named"
                if x is None
                else "baseline_named_ld_other" if y is None else "both_named"
            )
        )
        table[key] += 1
    return {
        "agreement": partition(a, b),
        "shared_other_sensitivity": partition(a, b, False),
        "assigned_other": table,
    }


def call_key(row):
    return sha(canonical({key: row[key] for key in CALL_FIELDS if key != "phase"}))


def source_bytes(repo, commit, name):
    return subprocess.run(
        ["git", "show", f"{commit}:{name}"], cwd=repo, capture_output=True, check=True
    ).stdout


def source_literal(source, prefix):
    values = []
    for match in re.finditer(r'"(?:[^"\\]|\\.)*"', source.decode()):
        try:
            value = json.loads(match.group())
        except ValueError:
            continue
        if value.startswith(prefix):
            values.append(value)
    require(len(values) == 1, "cannot identify frozen source prompt: " + prefix)
    return values[0]


def render_source(template, **fields):
    # Substitute source placeholders once, without interpreting braces in evidence.
    return re.sub(r"\{([a-z_]*)\}", lambda match: str(fields[match[1]]), template)


def plan_schema():
    string, integer = {"type": "string"}, {"type": "integer"}
    definition = {
        "type": "object",
        "properties": {"name": string, "description": string},
        "required": ["name", "description"],
        "additionalProperties": False,
    }
    variants = []
    for op, fields in [
        ("create", {"name": string, "description": string}),
        ("rename", {"id": integer, "name": string, "description": string}),
        (
            "merge",
            {
                "ids": {"type": "array", "items": integer, "minItems": 2},
                "name": string,
                "description": string,
            },
        ),
        (
            "split",
            {
                "id": integer,
                "children": {"type": "array", "items": definition, "minItems": 2},
            },
        ),
        ("retire", {"id": integer}),
    ]:
        variants.append(
            {
                "type": "object",
                "properties": {"op": {"type": "string", "enum": [op]}, **fields},
                "required": ["op", *fields],
                "additionalProperties": False,
            }
        )
    return {
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "items": {"anyOf": variants},
                "maxItems": 16,
            }
        },
        "required": ["operations"],
        "additionalProperties": False,
    }


def verify_request(request, phase, backend, config, context, provider_source, evidence):
    require(
        len(canonical(request)) <= 32 * 1024 * 1024, "request exceeds frozen body limit"
    )
    if phase == "assign":
        user = request["input"][-1]
        require(
            user.get("role") == "user" and canonical(user["content"]) in evidence,
            "request contains unregistered text/image evidence",
        )
        item = evidence[canonical(user["content"])]
        if backend == "ld":
            choices = request["questions"][0]["choices"]
        else:
            prompt = request["input"][0]["content"]
            choices = json.loads(prompt.split("\nAvailable choices: ", 1)[1])
        require(
            2 <= len(choices) <= config["k"] + 1
            and choices[-1]
            == {
                "value": "other",
                "description": "The item does not fit any listed cluster.",
            },
            "assignment choices/page differ",
        )
        page = []
        for choice in choices[:-1]:
            value = choice["value"]
            require(
                isinstance(value, str)
                and value.isascii()
                and value.isdigit()
                and str(int(value)) == value
                and int(value) > 0,
                "invalid requested category ID",
            )
            name, description = choice["description"].split(": ", 1)
            page.append({"id": int(value), "name": name, "description": description})
        require(len({c["id"] for c in page}) == len(page), "duplicate page category")
        expected = _shared["assignment_request"](
            backend, config["task"], item, page, item.get("_image_bytes", {})
        )
        require(
            request == expected,
            "assignment request differs from frozen task/schema/evidence",
        )
        return {
            "page_choices": choices[:-1],
            "page_ids": [c["id"] for c in page],
            "item_id": item["id"],
        }
    require(phase == "plan", "unknown journal phase")
    prompt = request["input"][0]["content"]
    marker = "\nExisting clusters: "
    require(marker in prompt, "manager catalog missing")
    catalog, _ = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])
    require(
        isinstance(catalog, list) and len(catalog) <= config["max_clusters"],
        "manager catalog exceeds cap",
    )
    require(
        all(
            set(c) == {"id", "name", "description"}
            and type(c["id"]) is int
            and c["id"] > 0
            for c in catalog
        ),
        "manager catalog fields differ",
    )
    template = source_literal(
        provider_source, "You maintain a streaming semantic cluster catalog."
    )
    expected_prompt = render_source(
        template,
        task=config["task"],
        **{"": struct_json(catalog).decode()},
        max_clusters=config["max_clusters"],
    )
    if context is not None:
        contextual = source_literal(
            provider_source, "{original}\n\nContextual manager policy."
        )
        expected_prompt = render_source(
            contextual, original=expected_prompt, context=context
        )
    require(
        prompt == expected_prompt,
        "manager task/context/catalog prompt differs from frozen source",
    )
    parts = request["input"][1]["content"]
    position = examples = 0
    while position < len(parts):
        examples += 1
        require(
            set(parts[position]) == {"type", "text"}
            and parts[position].get("type") == "input_text"
            and re.fullmatch(
                rf"Example {examples}\. Current cluster: (other|[1-9][0-9]*)\.",
                parts[position].get("text", ""),
            ),
            "manager example marker differs",
        )
        position += 1
        end = position + 1
        if end < len(parts) and parts[end].get("type") == "input_image":
            end += 1
        require(
            canonical(parts[position:end]) in evidence,
            "manager example contains unregistered evidence",
        )
        current = parts[position - 1]["text"].split("Current cluster: ", 1)[1][:-1]
        require(
            current == "other" or int(current) in {c["id"] for c in catalog},
            "manager example references a category outside its catalog",
        )
        position = end
    require(examples <= 40, "too many manager examples")
    expected = _shared["sol_body"](
        [
            {"role": "developer", "content": expected_prompt},
            {"role": "user", "content": parts},
        ],
        "cluster_plan",
        plan_schema(),
    )
    require(
        request == expected, "manager request schema/options differ from frozen source"
    )
    return {"catalog": catalog}


def journal(
    path, backend, config, context, provider_source, evidence, terminal_success
):
    body = path.read_bytes()
    lines = body.splitlines(keepends=True)
    require(lines and lines[0].endswith(b"\n"), "journal header is truncated")
    header = json.loads(lines[0])
    require(
        set(header) == {"type", "schema_version", "run_id"}
        and header["type"] == "ld-clustering-journal"
        and header["schema_version"] == 1
        and isinstance(header["run_id"], str)
        and header["run_id"],
        "invalid journal identity",
    )
    truncated = bool(lines and not lines[-1].endswith(b"\n"))
    require(not terminal_success or not truncated, "successful journal is truncated")
    if truncated:
        lines.pop()
    counts = Counter(
        {
            key: 0
            for key in (
                "calls",
                "error_calls",
                "retry_attempts",
                "raw_refusal_attempts",
                "assignment_refusal_calls",
                "unknown_usage_calls",
                "unknown_pricing_calls",
                "assignment_calls",
                "maintenance_calls",
                "request_ms",
            )
        }
    )
    usage_total = Counter(
        {
            key: 0
            for key in (
                "input_tokens",
                "cached_tokens",
                "cache_write_tokens",
                "output_tokens",
            )
        }
    )
    known = Decimal(0)
    raw_cost = Decimal(0)
    successes = Counter()
    attempts = []
    replay_rows = []
    previous = None
    for physical, line in enumerate(lines[1:], 2):
        row, raw = raw_record(line)
        require(
            all(
                k in row
                for k in (
                    *CALL_FIELDS,
                    "error",
                    "attempt",
                    "http_status",
                    "usage_available",
                    "refusal",
                )
            ),
            "journal attempt fields missing",
        )
        phase, request, response = row["phase"], row["request"], row["response"]
        binding = verify_request(
            request, phase, backend, config, context, provider_source, evidence
        )
        require(
            raw["request"] == canonical(request),
            "journal request bytes differ from serialized wire body",
        )
        model = DECISIONS if phase == "assign" and backend == "ld" else SOL
        require(
            request["model"] == model
            and row["model"]
            == (response.get("model", model) if isinstance(response, dict) else model),
            "call/request model binding differs",
        )
        failed = row["error"] is not None
        require(
            not failed or isinstance(row["error"], str),
            "journal error is not nullable text",
        )
        require(
            uint(row["elapsed_ms"])
            and type(row["attempt"]) is int
            and 1 <= row["attempt"] <= 3,
            "invalid duration/attempt",
        )
        if row["attempt"] > 1:
            require(
                previous is not None
                and previous["error"] is not None
                and row["attempt"] == previous["attempt"] + 1
                and request == previous["request"]
                and phase == previous["phase"],
                "retry changed request or attempt sequence",
            )
            require(
                previous["http_status"] in (None, 429, 502, 503, 529)
                or (
                    phase == "plan"
                    and previous["http_status"] == 200
                    and isinstance(previous["response"], dict)
                    and previous["response"].get("status") == "completed"
                    and not is_refusal(previous["response"])
                ),
                "hard failure or planner refusal was retried",
            )
        refused = is_refusal(response)
        require(
            type(row["refusal"]) is bool and row["refusal"] == refused,
            "raw refusal flag differs",
        )
        cost, missing, usage = reprice(response, model)
        has_usage = (
            isinstance(response, dict)
            and isinstance(response.get("usage"), dict)
            and uint(response["usage"].get("input_tokens"))
            and uint(response["usage"].get("output_tokens"))
        )
        require(
            type(row["usage_available"]) is bool
            and row["usage_available"] == has_usage,
            "raw usage availability differs",
        )
        require(
            not has_usage or missing != "usage" or failed,
            "accepted provider cache usage is impossible",
        )
        saved_usage = row["usage"]
        expected_usage = usage or {
            k: 0
            for k in (
                "input_tokens",
                "cached_tokens",
                "cache_write_tokens",
                "output_tokens",
            )
        }
        assert_tree(expected_usage, saved_usage, "journal.usage")
        # Rust's persisted token estimate predates strict returned-tier pricing.
        token_cost = (
            reprice({**response, "model": model, "service_tier": "default"}, model)[0]
            if has_usage
            else Decimal(0)
        )
        if token_cost is None:
            require(failed, "accepted attempt has no valid token estimate")
            token_cost = Decimal(0)
        require(
            abs(Decimal(str(saved_usage["cost_usd"])) - token_cost) <= Decimal("1e-12"),
            "stored token estimate differs from raw usage",
        )
        raw_cost += token_cost
        if cost is not None:
            known += cost
        usage_total.update(expected_usage)
        counts.update(
            {
                "calls": 1,
                "error_calls": int(failed),
                "retry_attempts": int(row["attempt"] > 1),
                "raw_refusal_attempts": int(refused),
                "assignment_refusal_calls": int(
                    phase == "assign" and not failed and refused
                ),
                "unknown_usage_calls": int(missing == "usage"),
                "unknown_pricing_calls": int(missing == "pricing"),
                "assignment_calls": int(phase == "assign"),
                "maintenance_calls": int(phase == "plan"),
                "request_ms": row["elapsed_ms"],
            }
        )
        if not failed:
            require(
                type(row["http_status"]) is int
                and 200 <= row["http_status"] < 300
                and isinstance(response, dict)
                and response.get("model") == model
                and has_usage,
                "accepted journal attempt lacks valid response/status/usage",
            )
            require(
                model != SOL or response.get("service_tier") in (None, "default"),
                "accepted Sol tier differs",
            )
            successes[call_key(row)] += 1
            if phase == "assign":
                binding["outcome"] = _shared["response_assignment"](
                    response, backend, set(binding["page_ids"])
                )
            else:
                generated = _shared["response_json"](response)
                require(
                    isinstance(generated, dict)
                    and isinstance(generated.get("operations"), list),
                    "accepted planner response has no operations",
                )
                binding["plan"] = generated
        replay_rows.append(
            {"key": call_key(row), "phase": phase, "failed": failed, **binding}
        )
        attempts.append(
            {
                "physical_row": physical,
                "phase": phase,
                "model": model,
                "attempt": row["attempt"],
                "error": row["error"],
                "refusal": refused,
                "known_cost_usd": decimal_text(cost) if cost is not None else None,
                "unknown_reason": missing,
                "request_sha256": sha(raw["request"]),
                "response_sha256": sha(raw["response"]),
            }
        )
        previous = row
    return (
        {
            "run_id": header["run_id"],
            **dict(counts),
            "usage": dict(usage_total),
            "known_cost_usd": decimal_text(known),
            "reported_token_cost_usd": decimal_text(raw_cost),
            "journal_sha256": sha(body),
            "truncated_tail": truncated,
            "attempt_ledger": attempts,
        },
        successes,
        replay_rows,
    )


def apply_catalog(catalog, next_id, plan, cap):
    """Replay Store's ordered IDs and definitions without running Rust or writing SQLite."""
    active = {c["id"]: dict(c) for c in catalog}
    touched = set()

    def add(definition):
        nonlocal next_id
        require(
            all(
                isinstance(definition[k], str) and definition[k].strip()
                for k in ("name", "description")
            )
            and len(definition["name"].encode()) <= 500
            and len(definition["description"].encode()) <= 4000,
            "store-invalid catalog definition",
        )
        active[next_id] = {
            "id": next_id,
            "name": definition["name"],
            "description": definition["description"],
        }
        next_id += 1

    for operation in plan["operations"]:
        kind = operation["op"]
        sources = (
            operation["ids"]
            if kind == "merge"
            else [operation["id"]] if kind in ("rename", "split", "retire") else []
        )
        require(
            kind in ("create", "rename", "merge", "split", "retire")
            and all(
                type(i) is int and i in active and i not in touched for i in sources
            )
            and len(set(sources)) == len(sources),
            "catalog operation consumes unknown/duplicate source",
        )
        touched.update(sources)
        if kind == "create" or kind == "merge":
            require(kind != "merge" or len(sources) >= 2, "invalid merge arity")
            add(operation)
        elif kind == "rename":
            require(
                all(
                    isinstance(operation[k], str) and operation[k].strip()
                    for k in ("name", "description")
                )
                and len(operation["name"].encode()) <= 500
                and len(operation["description"].encode()) <= 4000,
                "store-invalid catalog definition",
            )
            active[operation["id"]] = {
                "id": operation["id"],
                "name": operation["name"],
                "description": operation["description"],
            }
        elif kind == "split":
            require(len(operation["children"]) >= 2, "invalid split arity")
            for child in operation["children"]:
                add(child)
        if kind != "rename":
            for source in sources:
                del active[source]
    require(len(active) <= cap, "catalog replay exceeds registered cap")
    return [active[i] for i in sorted(active)], next_id


def replay_catalog_requests(
    replay_rows,
    committed_calls,
    maintenance,
    updates,
    final_catalog,
    config,
    allow_failed_apply,
    final_assignments,
    reassignment_events,
):
    catalog, next_id, committed_index, applied = [], 1, 0, 0
    targets = dict.fromkeys(final_assignments)
    group = None
    reevaluated = 0
    for row in replay_rows:
        if row["phase"] == "plan":
            require(
                reevaluated == len(reassignment_events)
                or reassignment_events[reevaluated]["_catalog_epoch"] > applied,
                "manager request skipped committed reevaluation events from the current catalog",
            )
            require(
                group is None or allow_failed_apply,
                "manager call interrupted assignment paging",
            )
            group = None
            require(
                row["catalog"] == catalog,
                "manager request catalog differs from replayed current catalog",
            )
        else:
            pages = [
                [
                    {
                        "value": str(c["id"]),
                        "description": f'{c["name"]}: {c["description"]}',
                    }
                    for c in catalog[start : start + config["k"]]
                ]
                for start in range(0, len(catalog), config["k"])
            ]
            require(
                row["page_choices"] in pages,
                "assignment candidate IDs/definitions/order differ from replayed current catalog",
            )
            page = pages.index(row["page_choices"])
            require(
                (group is None and page == 0)
                or (
                    group is not None
                    and group[1] == row["item_id"]
                    and group[2] == page
                )
                or (allow_failed_apply and page == 0),
                "raw assignment attempt skipped first-match page order",
            )
        if row["failed"]:
            continue
        if committed_index >= len(committed_calls) or row["key"] != call_key(
            committed_calls[committed_index]
        ):
            continue
        call = committed_calls[committed_index]
        committed_index += 1
        require(
            (call["phase"] == "plan") == (row["phase"] == "plan"),
            "committed call phase differs from provider phase",
        )
        if row["phase"] != "plan":
            page = pages.index(row["page_choices"])
            identity = (call["phase"], row["item_id"])
            if group is not None and page == 0 and allow_failed_apply:
                group = None
            require(
                (group is None and page == 0)
                or (group is not None and group[:2] == identity and group[2] == page),
                "assignment did not follow first-match page order",
            )
            choice, refused = row["outcome"]
            done = choice is not None or refused or page == len(pages) - 1
            if not done:
                group = (*identity, page + 1)
                continue
            group = None
            if call["phase"] == "reassign":
                event = (
                    reassignment_events[reevaluated]
                    if reevaluated < len(reassignment_events)
                    else None
                )
                if (
                    event is not None
                    and event["_catalog_epoch"] == applied
                    and event["point_id"] == row["item_id"]
                    and event["cluster_id"] == choice
                ):
                    require(
                        row["item_id"] in targets
                        and event.get("interim_cluster_id") == targets[row["item_id"]],
                        "reassignment event interim state differs from replayed assignment",
                    )
                    targets[row["item_id"]] = choice
                    reevaluated += 1
                else:
                    require(
                        allow_failed_apply,
                        "reevaluation result lacks a matching committed reassignment event",
                    )
            elif row["item_id"] in targets:
                targets[row["item_id"]] = choice
            continue
        if applied < len(maintenance) and row["plan"] == maintenance[applied]:
            require(
                updates[applied]["before_sha256"] == sha(struct_json(catalog)),
                "catalog update does not bind its accepted plan input",
            )
            before = catalog
            catalog, next_id = apply_catalog(
                catalog, next_id, row["plan"], config["max_clusters"]
            )
            changes = sum(c not in catalog for c in before) + sum(
                not any(old["id"] == c["id"] for old in before) for c in catalog
            )
            require(
                updates[applied]["catalog_change_count"] == changes,
                "catalog change count differs from replayed definitions",
            )
            active_ids = {c["id"] for c in catalog}
            targets = {
                point: choice if choice in active_ids else None
                for point, choice in targets.items()
            }
            require(
                updates[applied]["after_sha256"] == sha(struct_json(catalog)),
                "catalog update does not bind its accepted plan output",
            )
            applied += 1
            if not catalog:
                # Empty catalogs perform a real Store::reassign(None) with no HTTP call.
                drained = set()
                while (
                    reevaluated < len(reassignment_events)
                    and reassignment_events[reevaluated]["_catalog_epoch"] == applied
                ):
                    event = reassignment_events[reevaluated]
                    point = event["point_id"]
                    require(
                        point in targets
                        and point not in drained
                        and event["cluster_id"] is None
                        and event.get("interim_cluster_id") is None
                        and targets[point] is None,
                        "empty-catalog reevaluation requires one null target/interim state per point",
                    )
                    drained.add(point)
                    reevaluated += 1
                require(
                    len(drained) <= updates[applied - 1]["pending_count"],
                    "empty-catalog reevaluations exceed the committed pending queue",
                )
                require(
                    allow_failed_apply
                    or len(drained) == updates[applied - 1]["pending_count"],
                    "complete empty-catalog drain is missing committed reevaluation events",
                )
        else:
            require(
                allow_failed_apply,
                "accepted SQLite planner call has no committed catalog application",
            )
    require(
        committed_index == len(committed_calls),
        "SQLite calls are not an ordered subsequence of accepted journal attempts",
    )
    require(
        applied == len(maintenance) and catalog == final_catalog,
        "accepted plan replay differs from final SQLite catalog",
    )
    require(
        reevaluated == len(reassignment_events),
        "committed reassignment event lacks a completed raw response",
    )
    require(
        targets == final_assignments,
        "SQLite final assignments differ from accepted response and retirement replay",
    )


def event_summaries(events, policy, catalog):
    reassignment = Counter(evaluations=0, id_moves=0, unchanged=0, origin_unknown=0)
    operations = Counter()
    updates = []
    maintenance = []
    for kind, value in events:
        if kind == "reassign":
            reassignment["evaluations"] += 1
            changed, known, before, after = (
                value.get("changed"),
                value.get("previous_assignment_known", False),
                value.get("previous_cluster_id"),
                value.get("cluster_id"),
            )
            require(after is None or type(after) is int, "invalid reassignment target")
            if changed is None:
                require(
                    known is False and before is None,
                    "unknown reassignment origin contradicts marker",
                )
                reassignment["origin_unknown"] += 1
            else:
                require(
                    type(changed) is bool
                    and known is True
                    and (before is None or type(before) is int)
                    and changed == (before != after),
                    "reassignment changed flag contradicts captured origin",
                )
                reassignment["id_moves" if changed else "unchanged"] += 1
        elif kind == "maintenance":
            maintenance.append(value)
            for op in value["operations"]:
                require(
                    op["op"] in ("create", "rename", "merge", "split", "retire"),
                    "unknown committed catalog operation",
                )
                operations[op["op"]] += 1
        elif kind == "catalog_update":
            require(
                value["policy"] == policy
                and type(value["catalog_changed"]) is bool
                and value["catalog_changed"]
                == (value["before_sha256"] != value["after_sha256"]),
                "catalog update policy/change marker differs",
            )
            require(
                value["global_reconsideration"]
                is (policy == "contextual" and value["catalog_changed"]),
                "global reconsideration marker differs",
            )
            require(
                all(
                    uint(value[k])
                    for k in ("catalog_change_count", "newly_queued", "pending_count")
                )
                and value["newly_queued"] <= value["pending_count"],
                "invalid catalog queue counts",
            )
            require(
                not updates or updates[-1]["after_sha256"] == value["before_sha256"],
                "catalog update hash chain differs",
            )
            updates.append(value)
    require(
        len(updates) == len(maintenance),
        "maintenance/catalog update event counts differ",
    )
    if updates:
        require(
            updates[0]["before_sha256"] == sha(struct_json([]))
            and updates[-1]["after_sha256"] == sha(struct_json(catalog)),
            "catalog update chain does not bind final catalog",
        )
    else:
        require(not catalog, "catalog exists without committed maintenance")
    return {
        "reassignment": dict(reassignment),
        "maintenance_events": len(maintenance),
        "operations": dict(operations),
        "catalog_updates": updates,
        "note": "Committed reevaluations and ID moves can be mechanical after merge/retire; they do not establish semantic correction.",
    }, maintenance


def read_arm(directory, arm, rows, protocol, context, provider_source, evidence):
    exit_code = int((directory / "exit-code.txt").read_text().strip())
    require(
        (directory / "finished-at.txt").is_file(), "arm has no terminal finish marker"
    )
    database, log = directory / "state.sqlite", directory / "calls.jsonl"
    success = exit_code == 0
    if not database.exists() or not log.exists():
        require(not success, "missing database/journal evidence")
        require(
            not database.exists() and not log.exists(),
            "unpaired database/journal evidence cannot be audited without losing known state or charges",
        )
        return (
            {
                "complete": False,
                "exit_code": exit_code,
                "persisted_count": None,
                "expected_count": arm["expected_count"],
                "coverage": None,
                "catalog": None,
                "cost_complete": False,
                "cost_history_complete": False,
                "known_cost_usd": "0",
                "total_cost_usd": None,
                "measurement": None,
                "unknown_dispatch_history": True,
                "available_artifacts": {
                    path.name: file_pin(path)
                    for path in (database, log)
                    if path.is_file()
                },
                "reason": "Terminal worker lacks a complete database/journal pair; persisted state and dispatch history cannot be verified.",
            },
            [],
            None,
        )
    require(
        not any(
            p.exists() and p.stat().st_size
            for p in (Path(str(database) + "-wal"), Path(str(database) + "-journal"))
        ),
        "terminal SQLite has a nonempty recovery sidecar; snapshot it consistently before auditing",
    )
    config = protocol["modalities"][arm["modality"]]["config"]
    ledger, successes, replay_rows = journal(
        log, arm["backend"], config, context, provider_source, evidence, success
    )
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        require(
            db.execute("PRAGMA integrity_check").fetchone() == ("ok",),
            "SQLite integrity failure",
        )
        require(
            not db.execute("PRAGMA foreign_key_check").fetchall(),
            "SQLite foreign key failure",
        )
        meta = dict(db.execute("SELECT key,value FROM meta"))
        require(
            json.loads(meta["config"]) == config
            and meta["backend"] == arm["backend"]
            and json.loads(meta["manager_descriptor"]) == arm["manager_descriptor"]
            and meta["input_sha256"] == arm["input_sha256"],
            "SQLite config/backend/manager/input binding differs",
        )
        require(
            meta["journal_run_id"] == ledger["run_id"]
            and Path(meta["journal_path"]).name == "calls.jsonl"
            and Path(meta["journal_path"]).parent.name == arm["name"]
            and meta["journal_initialized"] == "1",
            "SQLite journal binding differs",
        )
        points = db.execute(
            "SELECT id,ordinal,payload FROM points ORDER BY ordinal"
        ).fetchall()
        require(
            [r[1] for r in points] == list(range(len(points))),
            "SQLite ordinal prefix differs",
        )
        items = [json.loads(r[2]) for r in points]
        require(
            items == rows[: len(items)]
            and [p[0] for p in points] == [p["id"] for p in items],
            "SQLite points differ from registered input prefix",
        )
        assignments = dict(db.execute("SELECT point_id,cluster_id FROM assignments"))
        require(
            set(assignments) == {p["id"] for p in items},
            "SQLite assignment set differs from persisted points",
        )
        catalog = [
            {"id": r[0], "name": r[1], "description": r[2]}
            for r in db.execute(
                "SELECT id,name,description FROM clusters WHERE active=1 ORDER BY id"
            )
        ]
        require(
            len(catalog) <= config["max_clusters"]
            and all(c["name"].strip() and c["description"].strip() for c in catalog),
            "invalid final catalog",
        )
        allowed = {c["id"] for c in catalog}
        require(
            all(
                choice is None or type(choice) is int and choice in allowed
                for choice in assignments.values()
            ),
            "assignment references an inactive/unknown category",
        )
        pending = db.execute(
            "SELECT point_id,previous_cluster_id,previous_assignment_known FROM reassignment ORDER BY point_id"
        ).fetchall()
        require(
            all(
                p[0] in assignments and p[2] in (0, 1) and (p[2] or p[1] is None)
                for p in pending
            ),
            "pending reassignment origin differs",
        )
        committed = 0
        committed_calls = []
        plans = Counter()
        committed_refusals = 0
        for (payload,) in db.execute("SELECT payload FROM calls ORDER BY id"):
            call = json.loads(payload)
            committed_calls.append(call)
            require(
                call["phase"] in ("assign", "reassign", "plan"),
                "unknown committed call phase",
            )
            key = call_key(call)
            require(
                successes[key] > 0,
                "SQLite call lacks a matching accepted journal attempt",
            )
            successes[key] -= 1
            committed += 1
            if call["phase"] == "plan":
                plans[canonical(_shared["response_json"](call["response"]))] += 1
            elif is_refusal(call["response"]):
                committed_refusals += 1
        events = [
            (kind, json.loads(payload))
            for kind, payload in db.execute(
                "SELECT kind,payload FROM events ORDER BY id"
            )
        ]
        summary, maintenance = event_summaries(events, arm["policy"], catalog)
        epoch = 0
        reevaluation_events = []
        for kind, value in events:
            if kind == "catalog_update":
                epoch += 1
            elif kind == "reassign":
                reevaluation_events.append({**value, "_catalog_epoch": epoch})
        replay_catalog_requests(
            replay_rows,
            committed_calls,
            maintenance,
            summary["catalog_updates"],
            catalog,
            config,
            not success or meta.get("cost_history_complete") == "false",
            assignments,
            reevaluation_events,
        )
        for plan in maintenance:
            key = canonical(plan)
            require(
                plans[key] > 0, "committed maintenance lacks accepted SQLite plan call"
            )
            plans[key] -= 1
        refusal_events = [
            value for kind, value in events if kind == "assignment_refusal"
        ]
        require(
            len(refusal_events) <= committed_refusals
            and all(
                v["point_id"] in {r["id"] for r in rows}
                and v["phase"] in ("assign", "reassign")
                for v in refusal_events
            ),
            "assignment refusal event binding differs",
        )
        starts = [v for kind, v in events if kind == "run_start"]
        finishes = [v for kind, v in events if kind == "run_finish"]
        prior = starts[0].get("prior_wall_ms", 0) if starts else 0
        require(uint(prior), "invalid prior loop duration")
        recorded = prior
        history = len(starts) == len(finishes)
        for index, (start, finish) in enumerate(zip(starts, finishes), 1):
            history &= (
                start.get("session") == index
                and finish.get("session") == index
                and start.get("prior_wall_ms") == recorded
                and uint(finish.get("elapsed_ms"))
            )
            recorded += finish.get("elapsed_ms", 0)
        wall = int(meta.get("wall_ms", "0"))
        require(wall >= 0, "negative active loop duration")
        if starts:
            history &= (
                recorded == wall
                and bool(finishes)
                and finishes[-1].get("success") is True
            )
        timing = (
            meta.get("timing_complete") == "true"
            and meta.get("run_in_progress") == "0"
            and history
            and bool(starts)
            and starts[0].get("saved_count") == 0
            and starts[0].get("prior_wall_ms") == 0
        )
        complete = (
            success
            and len(items) == arm["expected_count"]
            and meta.get("completed_count") == str(arm["expected_count"])
            and not pending
        )
        require(
            not success or complete,
            "successful arm is not complete at registered count",
        )
        if complete:
            require(
                len(refusal_events) == committed_refusals and starts and finishes,
                "complete run lacks committed refusal/session evidence",
            )
        require(
            not timing or wall >= ledger["request_ms"],
            "active loop duration excludes recorded serial requests",
        )
        cost_history = (
            success
            and timing
            and meta.get("cost_history_complete") != "false"
            and not ledger["truncated_tail"]
        )
        complete_cost = (
            cost_history
            and not ledger.get("unknown_usage_calls", 0)
            and not ledger.get("unknown_pricing_calls", 0)
        )
        data = [(item, assignments[item["id"]]) for item in items]
        other = sum(choice is None for _, choice in data)
        moves = summary["reassignment"]
        measured = {
            "sample_count": arm["expected_count"],
            "reassignment_evaluations": moves["evaluations"],
            "reassignment_id_moves": moves["id_moves"],
            "reassignment_unchanged": moves["unchanged"],
            "reassignment_origin_unknown": moves["origin_unknown"],
            "wall_seconds": wall / 1000,
            "timing_complete": timing,
            "cost_usd": float(ledger["reported_token_cost_usd"]),
            "cost_complete": timing
            and meta.get("cost_history_complete") != "false"
            and not ledger.get("unknown_usage_calls", 0),
            "calls": ledger.get("calls", 0),
            "committed_success_calls": committed,
            "uncommitted_success_calls": sum(successes.values()),
            "assignment_calls": ledger.get("assignment_calls", 0),
            "assignment_refusal_calls": ledger.get("assignment_refusal_calls", 0),
            "run_sessions": len(starts),
            "timing_scope": (
                "cumulative_active_loops"
                if len(starts) > 1
                or starts
                and (starts[0].get("saved_count", 0) > 0 or prior > 0)
                else "uninterrupted_loop"
            ),
            "maintenance_calls": ledger.get("maintenance_calls", 0),
            **{
                k: ledger["usage"].get(k, 0)
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cached_tokens",
                    "cache_write_tokens",
                )
            },
            "request_seconds": ledger.get("request_ms", 0) / 1000,
            "error_calls": ledger.get("error_calls", 0),
            "unknown_usage_calls": ledger.get("unknown_usage_calls", 0),
            "cluster_count": len(catalog),
            "other_count": other,
            "coverage": 1 - other / arm["expected_count"],
            "assignment_model": DECISIONS if arm["backend"] == "ld" else SOL,
            "planner_model": SOL,
            "sol_reasoning_effort": "high",
            "journal_run_id": ledger["run_id"],
            "journal_sha256": ledger["journal_sha256"],
        }
        result = {
            "complete": complete,
            "exit_code": exit_code,
            "persisted_count": len(items),
            "expected_count": arm["expected_count"],
            "pending_reassignments": len(pending),
            "catalog": catalog,
            "coverage": measured["coverage"] if complete else None,
            "coverage_of_persisted_points": 1 - other / len(items) if items else None,
            "measurement": measured,
            **ledger,
            **summary,
            "cost_complete": bool(complete_cost),
            "cost_history_complete": bool(cost_history),
            "total_cost_usd": ledger["known_cost_usd"] if complete_cost else None,
        }
        return result, data, measured


def terminal_guard(stage, binaries):
    require(
        (stage / "supervisor-exit-code.txt").is_file()
        and (stage / "finished-at.txt").is_file(),
        "streaming supervisor is not terminal",
    )
    require(
        (stage / "supervisor-exit-code.txt").read_text().strip() in ("0", "1"),
        "invalid supervisor exit marker",
    )
    namespace = {
        "__name__": "streaming_archive_guard",
        "__file__": str(Path(__file__).with_name("archive_guided_agreement.py")),
    }
    helper = Path(namespace["__file__"])
    exec(compile(helper.read_bytes(), str(helper), "exec"), namespace)
    require(
        not namespace["active_workers"](stage, binaries=binaries),
        "streaming workers remain active",
    )


def inventory(stage):
    return {
        str(path.relative_to(stage)): file_pin(path)
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    }


def audit_streaming(run_root, data_root, source_repo, binary=None):
    stage, data, repo = (
        Path(run_root).resolve(),
        Path(data_root).resolve(),
        Path(source_repo).resolve(),
    )
    plan = read(stage / "run-plan.json")
    receipt = (stage / "binary-sha256.txt").read_text().strip().split(maxsplit=1)
    executable = (
        Path(binary).resolve() if binary is not None else Path(receipt[1].lstrip("*"))
    )
    terminal_guard(stage, [executable])
    before = inventory(stage)
    require(
        plan["schema_version"] == 1 and len(plan["arms"]) == 8,
        "expected eight registered streaming arms",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", plan["source_commit"]) is not None
        and (stage / "source-commit.txt").read_text().strip() == plan["source_commit"],
        "source receipt differs",
    )
    require(
        receipt[0] == plan["binary_sha256"] == file_pin(executable)["sha256"],
        "executable bytes differ from frozen pin",
    )
    protocol_path = stage / "preregistration/protocol.json"
    protocol, preflight = read(protocol_path), read(
        stage / "preregistration/request-preflight.json"
    )
    require(
        file_pin(protocol_path)["sha256"] == plan["protocol_sha256"]
        and file_pin(stage / "preregistration/request-preflight.json")["sha256"]
        == plan["preflight_sha256"]
        == protocol["offline_preflight"]["artifact_sha256"],
        "protocol/preflight byte pins differ",
    )
    require(
        preflight["status"] == "offline_preflight_passed"
        and preflight["api_calls"] == 0,
        "registered offline preflight did not pass",
    )
    pricing = json.loads(
        (stage / "preregistration/pricing.json").read_bytes(), parse_float=Decimal
    )
    prices = pricing["per_million_tokens"]
    require(
        {k: Decimal(str(v)) for k, v in prices[SOL].items()}
        == {
            "uncached_input": Decimal(2),
            "cached_input": Decimal(".1"),
            "cache_write_input": Decimal("2.5"),
            "output_including_reasoning": Decimal(10),
        },
        "Sol pricing snapshot differs",
    )
    require(
        {k: Decimal(str(v)) for k, v in prices["gpt-6-luna_decisions"].items()}
        == {"all_input": Decimal(".1"), "output": Decimal(0)},
        "Decisions pricing snapshot differs",
    )
    require(
        pricing["long_context"]["input_token_threshold_exclusive"] == 272000
        and Decimal(str(pricing["long_context"]["input_rate_multiplier"])) == 2
        and Decimal(str(pricing["long_context"]["output_rate_multiplier"]))
        == Decimal("1.5"),
        "long-context pricing snapshot differs",
    )
    source = {
        name: source_bytes(repo, plan["source_commit"], name) for name in SOURCE_FILES
    }
    require(
        source_bytes(
            repo, plan["source_commit"], EXPERIMENT + "/streaming-protocol.json"
        )
        == protocol_path.read_bytes(),
        "protocol differs from frozen Git source",
    )
    manifest = read(data / "manifest.json")
    require(
        file_pin(data / "manifest.json")["sha256"]
        == plan["dataset_manifest_sha256"]
        == protocol["dataset_manifest_sha256"]
        == preflight["dataset_manifest_sha256"]
        == (stage / "dataset-manifest-sha256.txt").read_text().strip(),
        "dataset manifest pin differs",
    )
    data_pins = {"manifest.json": file_pin(data / "manifest.json")}
    inputs, contexts, evidence_by_modality = {}, {}, {}
    for modality in ("text", "images"):
        registered = protocol["modalities"][modality]
        spec = manifest["partitions"]["streaming"][modality]
        path = data / "streaming" / (modality + ".jsonl")
        body = path.read_bytes()
        rows = [json.loads(line) for line in body.splitlines() if line.strip()]
        require(
            len(rows)
            == registered["expected_count"]
            == spec["count"]
            == (1000 if modality == "text" else 100),
            "registered reserved count differs",
        )
        require(
            [r["id"] for r in rows] == spec["ordered_ids"]
            and len({r["id"] for r in rows}) == len(rows),
            "reserved input order/IDs differ",
        )
        require(
            sha(body) == registered["jsonl_sha256"]
            and sha(struct_json(rows)) == spec["payload_sha256"]
            and sha(struct_json([r["id"] for r in rows])) == spec["order_sha256"],
            "reserved input byte/payload pins differ",
        )
        excluded = {
            point
            for split in ("discovery", "heldout")
            for point in manifest["partitions"][split][modality]["ordered_ids"]
        }
        require(
            not excluded.intersection(r["id"] for r in rows),
            "reserved IDs overlap discovery/heldout",
        )
        digest = hashlib.sha256(
            b"ld-clustering-input-v1\0" + struct.pack("<Q", len(body)) + body
        )
        images = {}
        hashes = []
        for item in rows:
            require(
                isinstance(item["text"], str) and bool(item["id"]),
                "invalid reserved item",
            )
            if modality == "images":
                require(
                    item["text"] == "Photograph."
                    and item.get("label") is None
                    and item.get("image") == f'../images/{item["id"]}.jpg',
                    "nonneutral image input",
                )
                image_path = (path.parent / item["image"]).resolve()
                require(data in image_path.parents, "image path escapes data root")
                image = image_path.read_bytes()
                require(
                    sha(image) == manifest["photos"][item["id"]]["supplied_sha256"],
                    "reserved supplied image differs",
                )
                images[item["id"]] = image
                hashes.append({"id": item["id"], "sha256": sha(image)})
                data_pins[str(image_path.relative_to(data))] = file_pin(image_path)
                digest.update(b"local-image\0" + struct.pack("<Q", len(image)) + image)
            else:
                require(item.get("image") is None, "text input contains an image")
        require(
            hashes == spec["ordered_image_hashes"]
            and sha(struct_json(hashes)) == spec["ordered_image_content_sha256"],
            "ordered image pins differ",
        )
        require(
            digest.hexdigest() == registered["input_sha256"],
            "reserved input fingerprint differs",
        )
        inspected = next(
            row for row in preflight["modalities"] if row["modality"] == modality
        )
        require(
            all(
                inspected[k] == v
                for k, v in {
                    "count": len(rows),
                    "config": registered["config"],
                    "input_sha256": registered["input_sha256"],
                    "jsonl_sha256": registered["jsonl_sha256"],
                }.items()
            ),
            "preflight/input configuration differs",
        )
        context_record = protocol["manager"]["contexts"][modality]
        context_path = stage / "preregistration" / context_record["file"]
        require(
            context_path.parent == stage / "preregistration",
            "context path escapes preregistration",
        )
        context_body = context_path.read_bytes()
        require(
            0 < len(context_body) <= 32768
            and context_body.decode().strip()
            and sha(context_body)
            == context_record["sha256"]
            == inspected["context_sha256"],
            "context byte pin differs",
        )
        require(
            source_bytes(
                repo, plan["source_commit"], EXPERIMENT + "/" + context_record["file"]
            )
            == context_body,
            "context differs from frozen Git source",
        )
        expected_descriptors = [
            protocol["policies"]["original"]["descriptor"],
            {
                "policy": "contextual",
                "context_sha256": context_record["sha256"],
                "prompt_revision": protocol["policies"]["contextual"][
                    "prompt_revision"
                ],
            },
        ]
        require(
            [row["manager_descriptor"] for row in inspected["policies"]]
            == expected_descriptors,
            "preflight manager descriptors differ",
        )
        inputs[modality], contexts[modality] = rows, context_body.decode()
        evidence = {}
        for item in rows:
            evidence[canonical(_shared["evidence_parts"](item, images))] = {
                **item,
                "_image_bytes": images,
            }
        require(
            len(evidence) == len(rows),
            "duplicate provider evidence makes raw request identity ambiguous",
        )
        evidence_by_modality[modality] = evidence
        data_pins[str(path.relative_to(data))] = file_pin(path)
    expected_names = {
        f"{modality}-{policy}-{backend}"
        for modality in ("text", "images")
        for policy in ("original", "contextual")
        for backend in ("llm", "ld")
    }
    require(
        {a["name"] for a in plan["arms"]} == expected_names
        and len(plan["arms"]) == len(expected_names),
        "streaming matrix differs",
    )
    arms, tables, measures = {}, {}, {}
    for arm in plan["arms"]:
        modality, policy, backend = arm["modality"], arm["policy"], arm["backend"]
        name = f"{modality}-{policy}-{backend}"
        require(arm["name"] == name and name in expected_names, "arm identity differs")
        directory = stage / name
        require(
            (directory / "source-commit.txt").read_text().strip()
            == plan["source_commit"]
            and (directory / "binary-sha256.txt").read_text().strip().split(maxsplit=1)
            == receipt,
            "arm source/binary receipt differs",
        )
        record = protocol["manager"]["contexts"][modality]
        descriptor = (
            protocol["policies"]["original"]["descriptor"]
            if policy == "original"
            else {
                "policy": "contextual",
                "context_sha256": record["sha256"],
                "prompt_revision": protocol["policies"]["contextual"][
                    "prompt_revision"
                ],
            }
        )
        require(
            arm["manager_descriptor"]
            == read(directory / "manager-descriptor.json")
            == descriptor
            and (directory / "input-sha256.txt").read_text().strip()
            == arm["input_sha256"]
            == protocol["modalities"][modality]["input_sha256"],
            "arm manager/input receipt differs",
        )
        config = protocol["modalities"][modality]["config"]
        argv = arm["argv"]
        require(
            argv[:2] == [receipt[1].lstrip("*"), "run"] and len(argv[2:]) % 2 == 0,
            "unexpected launch command",
        )
        options = dict(zip(argv[2::2], argv[3::2]))
        historical = Path(arm["directory"])
        expected = {
            "--input": str(Path(arm["cwd"]) / (modality + ".jsonl")),
            "--database": str(historical / "state.sqlite"),
            "--log": str(historical / "calls.jsonl"),
            "--mode": backend,
            "--task": config["task"],
            "--k": str(config["k"]),
            "--max-clusters": str(config["max_clusters"]),
            "--bootstrap": str(config["bootstrap_size"]),
            "--novelty": str(config["novelty_trigger"]),
            "--maintenance-interval": str(config["maintenance_interval"]),
            "--manager-policy": policy,
        }
        if policy == "contextual":
            expected["--manager-context"] = str(
                historical.parent / "preregistration" / record["file"]
            )
        require(
            options == expected
            and len(options) * 2 == len(argv[2:])
            and historical.name == name
            and Path(arm["cwd"]).name == "streaming"
            and arm["expected_count"] == len(inputs[modality]),
            "launch argument/config/path binding differs",
        )
        arms[name], tables[name], measures[name] = read_arm(
            directory,
            arm,
            inputs[modality],
            protocol,
            contexts[modality] if policy == "contextual" else None,
            source["src/provider.rs"],
            evidence_by_modality[modality],
        )
    complete = all(a["complete"] for a in arms.values())
    require(
        (stage / "supervisor-exit-code.txt").read_text().strip()
        == ("0" if all(a["exit_code"] == 0 for a in arms.values()) else "1"),
        "supervisor/arm exit status differs",
    )
    comparisons = []
    for modality in ("text", "images"):
        for policy in ("original", "contextual"):
            left, right = f"{modality}-{policy}-llm", f"{modality}-{policy}-ld"
            paired_complete = arms[left]["complete"] and arms[right]["complete"]
            entry = {
                "modality": modality,
                "policy": policy,
                "complete": paired_complete,
                "comparison": None,
            }
            if paired_complete:
                compared = pair_comparison(tables[left], tables[right])
                saved_path = stage / "comparisons" / f"{modality}-{policy}.json"
                require(
                    saved_path.is_file(),
                    "complete pair requires frozen CLI comparison artifact",
                )
                saved = read(saved_path)
                expected = {
                    "status": "complete",
                    "expected_count": len(inputs[modality]),
                    "config": protocol["modalities"][modality]["config"],
                    "manager_descriptor": read(
                        stage / left / "manager-descriptor.json"
                    ),
                    "input_sha256": protocol["modalities"][modality]["input_sha256"],
                    "baseline": measures[left],
                    "ld": measures[right],
                    **compared,
                }
                assert_tree(expected, saved, "saved comparison")
                entry.update(
                    comparison=compared, saved_sha256=file_pin(saved_path)["sha256"]
                )
            comparisons.append(entry)
    terminal_guard(stage, [executable])
    require(before == inventory(stage), "streaming evidence changed during audit")
    require(
        all(file_pin(data / name) == pin for name, pin in data_pins.items()),
        "registered input bytes changed during audit",
    )
    known = sum((Decimal(a["known_cost_usd"]) for a in arms.values()), Decimal(0))
    cost_complete = all(a["cost_complete"] for a in arms.values())
    return {
        "schema_version": 1,
        "status": "verified" if complete else "verified_with_partial_streams",
        "scope": "Terminal eight-arm reserved streams only; independent pair enumeration and all physical recorded attempts. No semantic-correction claim and no summing overlapping arm wall times.",
        "assurance": "Binds frozen source/binary/protocol/input receipts, exact request bodies and supplied evidence, accepted response values, current catalog/page order, successful SQLite calls, committed reevaluation targets and final assignments. Replays catalog operations and compares independent pair scores with frozen CLI artifacts.",
        "limitations": [
            "Does not reproduce the manager's deterministic example-selection algorithm, maintenance-trigger cadence or historical queue membership; selected examples must be registered input evidence and reference an active category or Other.",
            "Independent catalog IDs do not share semantic meaning across backends. Partition agreement, ID moves and automated catalog changes do not establish correctness.",
            "A missing database/journal pair is explicitly unverifiable; an unpaired available database or journal is refused rather than dropping state or known charges. Nonempty SQLite recovery sidecars require a consistent terminal snapshot.",
            "The binary hash and immutable Git source receipt are verified without rebuilding or proving a reproducible build.",
        ],
        "source_commit": plan["source_commit"],
        "source_files": {name: sha(body) for name, body in source.items()},
        "binary": file_pin(executable),
        "arms": arms,
        "comparisons": comparisons,
        "cost_summary": {
            "known_cost_usd": decimal_text(known),
            "cost_complete": cost_complete,
            "total_cost_usd": decimal_text(known) if cost_complete else None,
            **{
                key: sum(arm.get(key, 0) for arm in arms.values())
                for key in (
                    "calls",
                    "retry_attempts",
                    "error_calls",
                    "raw_refusal_attempts",
                    "assignment_refusal_calls",
                    "unknown_usage_calls",
                    "unknown_pricing_calls",
                )
            },
            "interpretation": "Recorded token estimates are not invoices. Unknown or potentially unrecorded dispatches contribute no invented dollars. Refusal counters count requests, including reevaluation requests, not unique points.",
        },
        "evidence_files": before,
        "input_files": data_pins,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-root", "data-root", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument(
        "--source-repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), "audit output must be a fresh path")
    result = audit_streaming(
        args.run_root, args.data_root, args.source_repo, args.binary
    )
    body = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as file:
        file.write(body)


if __name__ == "__main__":
    main()
