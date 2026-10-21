#!/usr/bin/env python3
"""Export secondary diagnostics from a completed independent audit, without calls.

Usage: --run-root RUN --audit RUN/independent-audit.json --output FRESH.json
The report's source property is supplied separately by the caller.
"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

# Load the existing independent metric implementation without creating bytecache.
_verifier_path = Path(__file__).with_name("verify_guided_agreement.py")
_verifier = {"__name__": "guided_diagnostics_metrics", "__file__": str(_verifier_path)}
exec(compile(_verifier_path.read_bytes(), str(_verifier_path), "exec"), _verifier)
compare_assignments = _verifier["compare_assignments"]
require = _verifier["require"]

STAGES = ("catalog", "controlled", "repeat", "review", "diagnostics")
MEASUREMENT_FIELDS = (
    "cost_complete",
    "timing_complete",
    "cost_usd",
    "wall_seconds",
    "calls",
    "error_calls",
    "unknown_usage_calls",
    "unknown_pricing_calls",
    "assignment_refusal_calls",
)
COMPARISON_FIELDS = (
    "n",
    "direct_agreement_count",
    "direct_agreement",
    "named_id_agreement_count",
    "named_id_agreement",
    "reference_assigned_count",
    "candidate_assigned_count",
    "reference_coverage",
    "candidate_coverage",
    "reference_refused_points",
    "candidate_refused_points",
    "assigned_other",
    "jointly_named_agreement",
    "categories",
    "confusion",
    "partition",
)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def comparison(value):
    """Project the shared metric result onto the website's GuidanceComparison."""
    result = {key: value[key] for key in COMPARISON_FIELDS}
    result["categories"] = [
        {k: v for k, v in row.items() if k != "true_negative_count"}
        for row in value["categories"]
    ]
    result["partition"] = {k: v for k, v in value["partition"].items() if k != "n"}
    return result


def integer(value):
    require(type(value) is int and value >= 0, "invalid nonnegative attempt count")
    return value


def dollars(value):
    require(isinstance(value, str), "cost must remain an exact Decimal string")
    parsed = Decimal(value)
    require(parsed.is_finite() and parsed >= 0, "invalid Decimal cost")
    return value


def accounting(audit):
    summary = audit["cost_summary"]
    require(
        set(summary["by_stage"]) == set(STAGES),
        "audit cost scope must exclude future streams",
    )
    require(
        all(role.split("/", 1)[0] in STAGES for role in audit["costs"]),
        "unscoped cost ledger",
    )
    complete = summary["cost_complete"]
    require(type(complete) is bool, "missing overall cost completeness")
    total = summary["total_cost_usd"]
    require((total is not None) == complete, "incomplete cost must not claim a total")
    if total is not None:
        dollars(total)
    stages = []
    for stage in STAGES:
        saved = summary["by_stage"][stage]
        ledgers = [
            value
            for role, value in audit["costs"].items()
            if role.startswith(stage + "/")
        ]
        require(
            ledgers and type(saved["cost_complete"]) is bool,
            "missing stage cost evidence",
        )
        require(
            saved["calls"] == sum(integer(row["calls"]) for row in ledgers),
            "stage call count differs from audit ledgers",
        )
        require(
            not saved["cost_complete"]
            or saved["unknown_usage_calls"] == saved["unknown_pricing_calls"] == 0,
            "complete stage has unknown cost",
        )
        stages.append(
            {
                "stage": stage,
                "calls": integer(saved["calls"]),
                "known_cost_usd": dollars(saved["known_cost_usd"]),
                "cost_complete": saved["cost_complete"],
                "retry_attempts": sum(
                    integer(row["retry_attempts"]) for row in ledgers
                ),
                "error_calls": sum(integer(row["error_calls"]) for row in ledgers),
                "refusal_attempts": sum(
                    integer(row["raw_refusal_attempts"]) for row in ledgers
                ),
                "unknown_usage_calls": integer(saved["unknown_usage_calls"]),
                "unknown_pricing_calls": integer(saved["unknown_pricing_calls"]),
            }
        )
    require(
        complete == all(stage["cost_complete"] for stage in stages),
        "overall/stage cost completeness differs",
    )
    return {
        "total_cost_usd": total,
        "known_cost_usd": dollars(summary["known_cost_usd"]),
        "cost_complete": complete,
        "stages": stages,
    }


def export_diagnostics(run_root, audit_path, output):
    run, audit_path, output = Path(run_root).resolve(), Path(audit_path), Path(output)
    require(not output.exists(), "diagnostic output must be a fresh path")
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)
    require(
        audit.get("schema_version") == 1
        and audit.get("status") in ("verified", "verified_with_incomplete_review"),
        "completed verified audit required",
    )
    used = {}

    def raw(name, expected_hash):
        path = (run / name).resolve()
        require(run in path.parents, "raw path escapes run root")
        record = audit["evidence_files"][name]
        body = path.read_bytes()
        digest = sha(body)
        require(
            digest == record["sha256"] == expected_hash
            and len(body) == record["bytes"],
            "raw bytes/hash differ from verified audit: " + name,
        )
        value = json.loads(body)
        require(
            value.get("status") == "complete" and value.get("error") is None,
            "raw diagnostic/primary artifact is incomplete",
        )
        used[path] = digest
        return value

    analyzed = {row["modality"]: row for row in audit["analysis"]["modalities"]}
    require(
        set(analyzed) == {"text", "images"}
        and len(audit["analysis"]["modalities"]) == 2,
        "audit modalities differ",
    )
    result = {
        "schema_version": 1,
        "status": "complete",
        "audit_sha256": sha(audit_bytes),
        "modalities": [],
        "accounting": accounting(audit),
    }
    for modality, n in [("text", 100), ("images", 25)]:
        pins = analyzed[modality]["guided"]["artifact_sha256"]
        catalog = raw(f"catalog/{modality}-guided.json", pins["catalog"])["catalog"]
        primary, variants = {}, []
        for mode, role in [("llm", "baseline"), ("ld", "candidate")]:
            artifact = raw(f"controlled/{modality}-guided-{mode}.json", pins[role])
            rows = artifact["assignments"]
            primary[mode] = {row["id"]: row for row in rows}
            expected_count = 1000 if modality == "text" else 100
            require(
                len(primary[mode])
                == len(rows)
                == artifact["processed_count"]
                == artifact["expected_count"]
                == expected_count,
                "duplicate primary ID or incorrect full-cohort size",
            )
            expected = {
                "modality": modality,
                "condition": "guided",
                "mode": mode,
                "stage": "classify",
                "k": 8,
                "reverse_catalog_order": False,
                "catalog_sha256": pins["catalog"],
            }
            require(
                all(
                    artifact["metadata"].get(key) == value
                    for key, value in expected.items()
                ),
                "primary guided K8 binding differs",
            )
        require(
            primary["llm"].keys() == primary["ld"].keys(), "primary backend IDs differ"
        )
        selected_ids = None
        for policy in ["reverse", "one-page"]:
            k, reverse = (8, True) if policy == "reverse" else (16, False)
            assigned, stability, measurements, same_pages = {}, {}, {}, []
            for mode, role in [("llm", "baseline"), ("ld", "candidate")]:
                name = f"{modality}-guided-{mode}-{policy}"
                saved = audit["diagnostics"][name]
                artifact = raw(f"diagnostics/{name}.json", saved["artifact_sha256"])
                rows, metadata = artifact["assignments"], artifact["metadata"]
                ids = [row["id"] for row in rows]
                if selected_ids is None:
                    selected_ids = ids
                require(
                    len(ids) == len(set(ids)) == n
                    and ids == selected_ids
                    and set(ids) <= primary[mode].keys(),
                    "diagnostic ID/order/subset differs across variants",
                )
                require(
                    artifact["processed_count"] == artifact["expected_count"] == n,
                    "diagnostic sample count differs",
                )
                expected = {
                    "modality": modality,
                    "condition": "guided",
                    "mode": mode,
                    "stage": "diagnostic",
                    "k": k,
                    "reverse_catalog_order": reverse,
                    "catalog_sha256": pins["catalog"],
                    "reference_sha256": pins[role],
                }
                require(
                    all(metadata.get(key) == value for key, value in expected.items()),
                    "diagnostic policy/reference binding differs",
                )
                require(
                    saved["effective_request_policy"]
                    == {"k": k, "reverse_order": reverse},
                    "audited policy differs",
                )
                stable = saved["comparison_to_primary_subset"]
                require(stable["n"] == n, "stability denominator differs")
                assigned[mode], stability[mode] = rows, comparison(stable)
                measurements[mode] = {
                    key: artifact["measurement"][key] for key in MEASUREMENT_FIELDS
                }
                require(
                    measurements[mode]["timing_complete"] is True,
                    "diagnostic measured loop incomplete",
                )
                same_pages.append(saved["same_effective_page_content_as_primary"])
            require(
                type(same_pages[0]) is bool
                and type(same_pages[1]) is bool
                and same_pages[0]
                == same_pages[1]
                == (policy == "one-page" and len(catalog) <= 8),
                "same-page diagnostic flag differs",
            )
            variants.append(
                {
                    "policy": policy,
                    "k": k,
                    "reverse_order": reverse,
                    "comparison": comparison(
                        compare_assignments(assigned["llm"], assigned["ld"], catalog)
                    ),
                    "llm_stability": stability["llm"],
                    "ld_stability": stability["ld"],
                    "same_effective_page_content_as_primary": same_pages[0],
                    "measurements": measurements,
                }
            )
        subset = {
            mode: [primary[mode][point] for point in selected_ids]
            for mode in ["llm", "ld"]
        }
        result["modalities"].append(
            {
                "modality": modality,
                "n": n,
                "primary_subset": comparison(
                    compare_assignments(subset["llm"], subset["ld"], catalog)
                ),
                "variants": variants,
            }
        )
    require(
        sha(audit_path.read_bytes()) == result["audit_sha256"],
        "audit changed during export",
    )
    require(
        all(sha(path.read_bytes()) == digest for path, digest in used.items()),
        "raw evidence changed during export",
    )
    body = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as file:
        file.write(body)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-root", "audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        export_diagnostics(args.run_root, args.audit, args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
