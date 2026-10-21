import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve()
HELPER = (
    HERE.with_name("verify_guided_agreement.py")
    if HERE.with_name("verify_guided_agreement.py").exists()
    else HERE.parents[1] / "scripts/verify_guided_agreement.py"
)
spec = importlib.util.spec_from_file_location("verify_guided_agreement", HELPER)
verify = importlib.util.module_from_spec(spec)
exec(compile(HELPER.read_bytes(), str(HELPER), "exec"), verify.__dict__)

CATALOG = [
    {"id": i, "name": f"Group{i}", "description": f"Criteria{i}"} for i in range(1, 4)
]


def rows(values):
    return [
        {"id": str(i), "cluster_id": value, "refused": False, "label": None}
        for i, value in enumerate(values)
    ]


def call(
    tokens=100, cached=0, write=0, output=0, model="gpt-6.1-sol", error=None, attempt=1
):
    return {
        "phase": "assign",
        "request": {"model": model},
        "response": {
            "model": model,
            "service_tier": "default",
            "usage": {
                "input_tokens": tokens,
                "output_tokens": output,
                "input_tokens_details": {
                    "cached_tokens": cached,
                    "cache_write_tokens": write,
                },
            },
        },
        "error": error,
        "http_status": 200,
        "attempt": attempt,
        "elapsed_ms": 3,
        "refusal": False,
    }


class MetricTests(unittest.TestCase):
    def test_explicit_pair_enumeration_crossed_partitions(self):
        score = verify.compare_assignments(
            rows([1, 1, 2, 2]), rows([1, 2, 1, 2]), CATALOG
        )
        self.assertEqual(score["direct_agreement_count"], 2)
        self.assertEqual(score["partition"]["adjusted_rand_index"], -0.5)
        self.assertEqual(score["partition"]["pairwise_f1"], 0)
        self.assertEqual(
            score["independent_pair_confusion"],
            {
                "both_same": 0,
                "reference_same_only": 2,
                "candidate_same_only": 2,
                "both_different": 2,
                "all_unordered_pairs": 6,
            },
        )

    def test_partition_is_permutation_invariant_but_ids_are_not(self):
        score = verify.compare_assignments(rows([1, 1, 2]), rows([2, 2, 1]), CATALOG)
        self.assertEqual(score["direct_agreement_count"], 0)
        self.assertEqual(score["partition"]["adjusted_rand_index"], 1)

    def test_other_points_are_singletons_but_both_other_is_direct_agreement(self):
        score = verify.compare_assignments(
            rows([None, None, None]), rows([None, None, None]), CATALOG
        )
        self.assertEqual(score["direct_agreement"], 1)
        self.assertEqual(score["named_id_agreement"], 0)
        self.assertIsNone(score["jointly_named_agreement"])
        self.assertEqual(score["partition"]["pairwise_f1"], 1)

    def test_mixed_coverage_and_pair_scores(self):
        score = verify.compare_assignments(
            rows([1, 1, 2, 2, None, None]), rows([1, 1, None, 3, 2, None]), CATALOG
        )
        self.assertEqual(
            score["assigned_other"],
            {
                "both_named": 3,
                "reference_named_candidate_other": 1,
                "reference_other_candidate_named": 1,
                "both_other": 1,
            },
        )
        self.assertAlmostEqual(score["partition"]["adjusted_rand_index"], 26 / 41)
        self.assertEqual(score["partition"]["pairwise_precision"], 1)
        self.assertEqual(score["partition"]["pairwise_recall"], 0.5)

    def test_duplicate_unknown_and_refused_named_rows_fail(self):
        for invalid in [
            [{"id": "0", "cluster_id": 1}, {"id": "0", "cluster_id": None}],
            rows([99]),
            [{"id": "0", "cluster_id": 1, "refused": True}],
        ]:
            with self.assertRaises(ValueError):
                verify.compare_assignments(rows([1]), invalid, CATALOG)

    def test_paired_gain_loss_exposes_reference_drift(self):
        gain = verify.paired_gain_loss(
            rows([1, 1, None, 2]),
            rows([2, 1, None, 2]),
            rows([2, 1, None, 2]),
            rows([2, 3, None, 2]),
            CATALOG,
        )
        self.assertEqual(gain["condition_matched_direct"]["gained_agreement"], 1)
        self.assertEqual(gain["condition_matched_direct"]["lost_agreement"], 1)
        self.assertEqual(
            gain["original_reference_anchored_direct"]["gained_agreement"], 0
        )
        self.assertEqual(gain["reference_id_changes"], 1)


class AccountingTests(unittest.TestCase):
    def run_journal(self, calls):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "calls.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "type": "ld-clustering-guided-journal",
                        "schema_version": 1,
                        "run_id": "r",
                        "stage": "classify",
                    }
                )
                + "\n"
                + "".join(json.dumps(row) + "\n" for row in calls)
            )
            return verify.price_journal(path, "r", True)

    def test_decimal_cache_writes_and_long_context_rates(self):
        score = self.run_journal([call(300000, 100000, 50000, 1000)])
        self.assertEqual(score["known_cost_usd"], "0.885")
        score = self.run_journal(
            [call(300000, 100000, 50000, 1000, model="gpt-6-luna")]
        )
        self.assertEqual(score["known_cost_usd"], "0.06")

    def test_every_attempt_is_charged_and_unknown_usage_remains_unknown(self):
        failed = call(100, error="temporary", attempt=1)
        failed["http_status"] = 503
        unknown = call()
        unknown.update(response=None, error="HTTP503", http_status=503)
        score = self.run_journal([failed, unknown, call(100, attempt=2)])
        self.assertEqual(score["known_cost_usd"], "0.0004")
        self.assertEqual(score["calls"], 3)
        self.assertEqual(score["unknown_usage_calls"], 1)
        self.assertFalse(score["cost_complete"])
        self.assertEqual(score["unknown_usage_physical_rows"], [3])

    def test_unknown_model_tier_is_not_falsely_priced(self):
        unknown = call()
        unknown["response"]["service_tier"] = "priority"
        score = self.run_journal([unknown])
        self.assertEqual(score["unknown_pricing_calls"], 1)
        self.assertFalse(score["cost_complete"])
        self.assertEqual(score["known_cost_usd"], "0")

    def test_raw_response_hash_uses_original_numeric_lexemes(self):
        row, raw = verify.raw_record(
            b'{"request":{"model":"x"},"response":{"prob":1e-9},"usage":null}'
        )
        self.assertEqual(raw["response"], b'{"prob":1e-9}')
        self.assertNotEqual(
            raw["response"], json.dumps(row["response"], separators=(",", ":")).encode()
        )


class TraceTests(unittest.TestCase):
    def fixture(self, root, refusal=False):
        import hashlib

        catalog = [
            {"id": i, "name": f"Group{i}", "description": f"Criteria{i}"}
            for i in range(1, 11)
        ]
        item = {
            "id": "PRIVATE_ID",
            "text": "a neutral request",
            "label": "PRIVATE_LABEL",
        }
        metadata = {"run_id": "r", "task": verify.TEXT_TASK}
        artifact = {
            "metadata": metadata,
            "assignments": [
                {
                    "id": item["id"],
                    "cluster_id": None if refusal else 9,
                    "refused": refusal,
                    "label": item["label"],
                }
            ],
        }
        calls = []
        events = [{"type": "metadata", "metadata": metadata}]
        for page_index, page in enumerate(
            [catalog[:8]] if refusal else [catalog[:8], catalog[8:]]
        ):
            request = verify.assignment_request("ld", verify.TEXT_TASK, item, page, {})
            answer = (
                {"name": "cluster", "type": "refusal"}
                if refusal
                else {
                    "name": "cluster",
                    "type": "choice",
                    "choice": "other" if page_index == 0 else "9",
                }
            )
            response = {
                "model": verify.DECISIONS,
                "usage": {"input_tokens": 100, "output_tokens": 0},
                "answers": [answer],
            }
            row = call(model=verify.DECISIONS)
            row.update(request=request, response=response, refusal=refusal)
            calls.append(row)
            events.append(
                {
                    "type": "page",
                    "ordinal": 0,
                    "id": item["id"],
                    "page": {
                        "page_index": page_index,
                        "candidate_ids": [c["id"] for c in page],
                        "cluster_id": None if refusal or page_index == 0 else 9,
                        "refused": refusal,
                        "request_sha256": hashlib.sha256(
                            verify.canonical(request)
                        ).hexdigest(),
                        "response_sha256": hashlib.sha256(
                            verify.canonical(response)
                        ).hexdigest(),
                    },
                }
            )
        events.extend(
            [
                {
                    "type": "assignment",
                    "ordinal": 0,
                    "id": item["id"],
                    "cluster_id": None if refusal else 9,
                    "refused": refusal,
                },
                {
                    "type": "terminal",
                    "status": "complete",
                    "processed_count": 1,
                    "expected_count": 1,
                    "error": None,
                },
            ]
        )
        journal = root / "calls.jsonl"
        journal.write_bytes(
            verify.canonical(
                {
                    "type": "ld-clustering-guided-journal",
                    "schema_version": 1,
                    "run_id": "r",
                    "stage": "classify",
                }
            )
            + b"\n"
            + b"".join(verify.canonical(r) + b"\n" for r in calls)
        )
        progress = root / "progress.jsonl"
        progress.write_bytes(b"".join(verify.canonical(r) + b"\n" for r in events))
        artifact["progress_sha256"] = hashlib.sha256(progress.read_bytes()).hexdigest()
        return artifact, item, catalog, journal, progress, events

    def test_raw_pages_reconstruct_first_match_and_hide_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact, item, catalog, journal, progress, events = self.fixture(Path(tmp))
            traces = verify.replay_assignments(
                journal, progress, artifact, [item], catalog, "ld", 8, "classify", {}
            )
            self.assertEqual(len(traces), 2)
            self.assertNotIn("PRIVATE_LABEL", journal.read_text())
            self.assertNotIn("PRIVATE_ID", journal.read_text())

    def test_native_refusal_stops_paging(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact, item, catalog, journal, progress, events = self.fixture(
                Path(tmp), True
            )
            self.assertEqual(
                len(
                    verify.replay_assignments(
                        journal,
                        progress,
                        artifact,
                        [item],
                        catalog,
                        "ld",
                        8,
                        "classify",
                        {},
                    )
                ),
                1,
            )

    def test_self_consistent_progress_hash_cannot_hide_wrong_response_binding(self):
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            artifact, item, catalog, journal, progress, events = self.fixture(Path(tmp))
            events[1]["page"]["response_sha256"] = "f" * 64
            progress.write_bytes(b"".join(verify.canonical(r) + b"\n" for r in events))
            artifact["progress_sha256"] = hashlib.sha256(
                progress.read_bytes()
            ).hexdigest()
            with self.assertRaises(ValueError):
                verify.replay_assignments(
                    journal,
                    progress,
                    artifact,
                    [item],
                    catalog,
                    "ld",
                    8,
                    "classify",
                    {},
                )


class ReviewTests(unittest.TestCase):
    def plan(self):
        return {
            "schema_version": 1,
            "seed": 2042,
            "text_quotas": {
                "different_named": 3,
                "reference_named_candidate_other": 3,
                "reference_other_candidate_named": 2,
                "equal_named": 2,
                "both_other": 1,
            },
            "images_census": True,
            "shortfall_policy": "no reallocation",
            "sampling_method": "ranked cell balancing",
            "interpretation": "selected cases only",
        }

    def test_strata_balance_shortfall_and_seeded_order_are_stable(self):
        left = [1] * 5 + [2] * 5 + [1, None, 2, None]
        right = [2] * 5 + [1] * 5 + [None, 2, 2, None]
        items = [{"id": str(i), "text": str(i)} for i in range(len(left))]
        a, b = rows(left), rows(right)
        keys, strata = verify.review_selection(
            self.plan(), "text-original", "text", items, a, b
        )
        by = {s["stratum"]: s for s in strata}
        self.assertEqual(len(keys), 7)
        self.assertEqual(by["different_named"]["selected_count"], 3)
        self.assertEqual(
            sorted(c["selected_count"] for c in by["different_named"]["cells"]), [1, 2]
        )
        self.assertEqual(by["reference_named_candidate_other"]["selected_count"], 1)
        self.assertEqual(by["equal_named"]["selected_count"], 1)
        self.assertEqual(
            (keys, strata),
            verify.review_selection(
                self.plan(),
                "text-original",
                "text",
                list(reversed(items)),
                list(reversed(a)),
                b,
            ),
        )
        self.assertEqual(len({k["item_id"] for k in keys}), 7)
        self.assertTrue(
            all(k["inclusion_probability_within_cell"] in [0.2, 0.4, 1] for k in keys)
        )
        self.assertTrue(any(k["a_is_reference"] for k in keys))
        self.assertTrue(any(not k["a_is_reference"] for k in keys))

    def test_image_census_includes_agreements_and_rejection(self):
        a, b = rows([1, None, 1, 2]), rows([1, None, 2, None])
        items = [{"id": str(i), "text": "Photograph."} for i in range(4)]
        keys, strata = verify.review_selection(
            self.plan(), "images-original", "images", items, a, b
        )
        self.assertEqual(len(keys), 4)
        self.assertTrue(all(k["inclusion_probability_within_cell"] == 1 for k in keys))
        self.assertEqual(
            {k["stratum"] for k in keys},
            {
                "equal_named",
                "both_other",
                "different_named",
                "reference_named_candidate_other",
            },
        )

    def fixture(self):
        case = {
            "case_id": "blind",
            "task": "Classify",
            "item": {"text": "Evidence", "image": None},
            "catalog": CATALOG,
            "choice_a": 1,
            "choice_b": 2,
        }
        key = {
            "case_id": "blind",
            "item_id": "private",
            "stratum": "different_named",
            "a_is_reference": False,
        }
        bundle = {
            "plan_sha256": "p",
            "cases": [case],
            "audit": {
                "cohort_id": "c",
                "keys": [key],
                "strata": [{"stratum": "different_named"}],
            },
            "sampling_plan": {"interpretation": "selected only"},
        }
        judgment = {
            "case_id": "blind",
            "a_fit": "supported",
            "b_fit": "unsupported",
            "verdict": "a_better",
            "severity": "major",
            "themes": ["wrong_named_category"],
            "evidence": ["Subject fits A"],
            "explanation": "A fits; B does not.",
            "proposed_alternative": None,
        }
        return bundle, judgment

    def test_unblinding_allows_reference_error_and_preserves_raw_judgment(self):
        bundle, judgment = self.fixture()
        outcome = {
            "case_id": "blind",
            "judgment": judgment,
            "raw_response": judgment,
            "error": None,
        }
        aggregate = verify.aggregate_reviews(bundle, [outcome])
        self.assertEqual(aggregate["totals"]["candidate_preferred_count"], 1)
        self.assertEqual(aggregate["totals"]["reference_preferred_count"], 0)
        self.assertEqual(aggregate["totals"]["reviewer_reference_unsupported_count"], 1)
        outcome["raw_response"] = {**judgment, "explanation": "changed"}
        with self.assertRaisesRegex(ValueError, "parsed review differs"):
            verify.aggregate_reviews(bundle, [outcome])

    def test_failed_and_unattempted_reviews_remain_distinct(self):
        bundle, judgment = self.fixture()
        self.assertEqual(
            verify.aggregate_reviews(bundle, [])["totals"]["not_attempted_count"], 1
        )
        failed = {
            "case_id": "blind",
            "judgment": None,
            "raw_response": {"invalid": True},
            "error": "rejected",
        }
        score = verify.aggregate_reviews(bundle, [failed])
        self.assertEqual(score["totals"]["failed_count"], 1)
        self.assertEqual(score["totals"]["accepted_count"], 0)
        self.assertEqual(score["totals"]["not_attempted_count"], 0)

    def test_invalid_identical_choice_judgment_is_rejected(self):
        bundle, judgment = self.fixture()
        bundle["cases"][0]["choice_b"] = 1
        with self.assertRaisesRegex(ValueError, "identical choices"):
            verify.validate_judgment(bundle["cases"][0], judgment)

    def test_relocated_review_evidence_hash_binds_actual_bytes(self):
        self.assertEqual(
            verify.review_evidence_hash("Photograph.", b"jpeg"),
            verify.review_evidence_hash("Photograph.", b"jpeg"),
        )
        self.assertNotEqual(
            verify.review_evidence_hash("Photograph.", b"jpeg"),
            verify.review_evidence_hash("Photograph.", b"other"),
        )


class GuardTests(unittest.TestCase):
    def test_missing_terminal_marker_fails_before_any_live_artifact_is_read(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            verify, "Audit", side_effect=AssertionError("must not read cohort")
        ):
            with self.assertRaisesRegex(ValueError, "terminal supervisor"):
                verify.audit_complete(
                    Path(tmp), Path(tmp), Path(tmp) / "analysis.json", Path(tmp)
                )

    def test_cli_refuses_existing_output_without_inspecting_cohort(self):
        import subprocess, sys

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing.json"
            output.write_text("unchanged")
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "--run-root",
                    tmp,
                    "--data-root",
                    tmp,
                    "--analysis",
                    tmp,
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fresh path", result.stderr)
            self.assertEqual(output.read_text(), "unchanged")

    def test_repeat_scores_use_frozen_subset_and_exact_ids(self):
        primary = rows([1, 2, None, 1])
        again = [rows([1, 2, None, 1])[i] for i in [0, 2]]
        score = verify.repeat_score(primary, again, CATALOG, ["0", "2"])
        self.assertEqual(score["n"], 2)
        self.assertEqual(score["direct_agreement"], 1)
        with self.assertRaisesRegex(ValueError, "repeat order"):
            verify.repeat_score(primary, list(reversed(again)), CATALOG, ["0", "2"])


class CompleteFixture:
    """Tiny synthetic evidence bytes at the registered 1000/100 sample counts."""

    def __init__(self, root, failed_review=False, leaked_review=False):
        import subprocess

        self.root = root
        self.run = root / "runs/guided"
        self.data = root / "data/guidance"
        self.run.mkdir(parents=True)
        self.data.mkdir(parents=True)
        self.images = {}
        self.inputs = {}
        self.catalogs = {}
        self.arms = {}
        self.source_repo = HERE.parents[1]
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.source_repo, text=True
        ).strip()
        names = [
            "src/agreement.rs",
            "src/agreement_metrics.rs",
            "src/agreement_review.rs",
            "src/provider.rs",
            "src/types.rs",
            "src/lib.rs",
            "examples/guided_agreement.rs",
            "Cargo.toml",
            "Cargo.lock",
        ]
        self.source = {
            "commit": commit,
            "executable_sha256": "e" * 64,
            "embedded_file_sha256": {
                n: verify.sha(
                    subprocess.check_output(
                        ["git", "show", f"{commit}:{n}"], cwd=self.source_repo
                    )
                )
                for n in names
            },
        }
        plan_bytes = subprocess.check_output(
            [
                "git",
                "show",
                f"{commit}:experiments/2026-10-20-guided-agreement-seed1042/review-plan.json",
            ],
            cwd=self.source_repo,
        )
        plan = json.loads(plan_bytes)
        partitions = {}
        photos = {}
        for split, text_count, image_count in [
            ("discovery", 200, 60),
            ("heldout", 1000, 100),
            ("streaming", 1000, 100),
            ("repeat", 100, 25),
        ]:
            partitions[split] = {}
            for modality, count in [("text", text_count), ("images", image_count)]:
                if split == "repeat":
                    items = self.inputs[("heldout", modality)][:count]
                else:
                    items = []
                    for i in range(count):
                        point = f"{modality}-{split}-{i}"
                        item = {
                            "id": point,
                            "text": (
                                f"{split} neutral request {i}"
                                if modality == "text"
                                else "Photograph."
                            ),
                        }
                        if modality == "text":
                            item["label"] = "private label"
                        else:
                            item["image"] = f"../images/{point}.jpg"
                            body = b"\xff\xd8\xff" + point.encode()
                            self.images[point] = body
                            self.write_bytes(self.data / f"images/{point}.jpg", body)
                            photos[point] = {"supplied_sha256": verify.sha(body)}
                        items.append(item)
                self.inputs[(split, modality)] = items
                self.jsonl(self.data / f"{split}/{modality}.jsonl", items)
                image_hashes = [
                    {"id": item["id"], "sha256": verify.sha(self.images[item["id"]])}
                    for item in items
                    if item.get("image")
                ]
                partitions[split][modality] = {
                    "file": f"{split}/{modality}.jsonl",
                    "count": count,
                    "ordered_ids": [item["id"] for item in items],
                    "order_sha256": verify.sha(
                        verify.struct_json([item["id"] for item in items])
                    ),
                    "payload_sha256": verify.sha(verify.struct_json(items)),
                    "ordered_image_hashes": image_hashes,
                    "ordered_image_content_sha256": verify.sha(
                        verify.struct_json(image_hashes)
                    ),
                }
        dataset = {"photos": photos, "partitions": partitions}
        self.write(self.data / "manifest.json", dataset)
        protocol = {
            "dataset_manifest_sha256": verify.sha(
                (self.data / "manifest.json").read_bytes()
            ),
            "partitions": partitions,
            "review_plan": plan,
            "review_plan_sha256": verify.sha(plan_bytes),
        }
        self.write(self.run / "preregistration/protocol.json", protocol)
        self.write_bytes(self.run / "preregistration/review-plan.json", plan_bytes)
        self.write(
            self.run / "preregistration/runtime.json",
            {
                "source_commit": commit,
                "protocol_sha256": verify.sha(
                    (self.run / "preregistration/protocol.json").read_bytes()
                ),
                "dataset_manifest_sha256": protocol["dataset_manifest_sha256"],
                "classification_executable_sha256": "e" * 64,
                "analysis_executable_sha256": "a" * 64,
            },
        )
        self.write(
            self.run / "preregistration/pricing.json",
            {
                "per_million_tokens": {
                    verify.SOL: {
                        "uncached_input": 2,
                        "cached_input": 0.1,
                        "cache_write_input": 2.5,
                        "output_including_reasoning": 10,
                    },
                    "gpt-6-luna_decisions": {"all_input": 0.1, "output": 0},
                },
                "long_context": {
                    "input_token_threshold_exclusive": 272000,
                    "input_rate_multiplier": 2,
                    "output_rate_multiplier": 1.5,
                },
            },
        )
        for stage in verify.STAGES:
            self.write_bytes(self.run / stage / "supervisor-exit-code.txt", b"0\n")
            self.write_bytes(self.run / stage / "source-commit.txt", commit.encode())
            self.write_bytes(
                self.run / stage / "binary-sha256.txt",
                b"e" * 64 + b"  /unavailable/frozen/guided_agreement\n",
            )
            self.write_bytes(
                self.run / stage / "dataset-manifest-sha256.txt",
                protocol["dataset_manifest_sha256"].encode(),
            )
        self.audit = verify.Audit(self.run, self.data, self.source_repo)
        self.plan = plan
        for modality in ["text", "images"]:
            for condition in ["original", "guided"]:
                self.make_catalog(modality, condition)
            for condition in ["original", "guided"]:
                for mode in ["llm", "ld"]:
                    self.make_classification(modality, condition, mode, "controlled")
                self.make_classification(modality, condition, "llm", "repeat")
                self.make_review(
                    modality,
                    condition,
                    failed_review and modality == "text" and condition == "original",
                    leaked_review and modality == "text" and condition == "original",
                )
            for mode in ["llm", "ld"]:
                for policy in ["reverse", "one-page"]:
                    self.make_classification(
                        modality, "guided", mode, "diagnostics", policy
                    )
        self.make_analysis()

    def write_bytes(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def write(self, path, value):
        self.write_bytes(path, verify.struct_json(value) + b"\n")
        return verify.sha(path.read_bytes())

    def jsonl(self, path, values):
        self.write_bytes(
            path, b"".join(verify.canonical(value) + b"\n" for value in values)
        )

    def response(self, value):
        return {
            "model": verify.SOL,
            "service_tier": "default",
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": verify.struct_json(value).decode(),
                        }
                    ],
                }
            ],
        }

    def row(self, phase, request, response, error=None, attempt=1, status=200):
        return {
            "phase": phase,
            "request": request,
            "response": response,
            "error": error,
            "http_status": status,
            "attempt": attempt,
            "elapsed_ms": 3,
            "refusal": verify.is_refusal(response),
        }

    def journal(self, prefix, phase, calls):
        run_id = prefix
        self.jsonl(
            self.run / (prefix + ".calls.jsonl"),
            [
                {
                    "type": "ld-clustering-guided-journal",
                    "schema_version": 1,
                    "run_id": run_id,
                    "stage": phase,
                }
            ]
            + calls,
        )
        return run_id

    def measurement(self, prefix, success=True):
        ledger = verify.price_journal(
            self.run / (prefix + ".calls.jsonl"), prefix, success
        )
        cost = float(ledger["known_cost_usd"])
        usage = {**ledger["usage"], "cost_usd": cost}
        wall = ledger["calls"] * 3 + 1
        return {
            k: ledger[k]
            for k in [
                "calls",
                "error_calls",
                "unknown_usage_calls",
                "unknown_pricing_calls",
                "assignment_refusal_calls",
                "cost_complete",
                "cost_history_complete",
                "phase_calls",
                "journal_sha256",
            ]
        } | {
            "usage": usage,
            "cost_usd": cost,
            "request_seconds": float(ledger["request_seconds"]),
            "timing_complete": success,
            "wall_ms": wall,
            "wall_seconds": wall / 1000,
        }

    def make_catalog(self, modality, condition):
        discovery = self.audit.inputs[("discovery", modality)]
        task = verify.TEXT_TASK if modality == "text" else verify.IMAGE_TASK
        catalog = [
            {"id": i, "name": f"Group{i}", "description": f"{condition} criteria {i}"}
            for i in [1, 2]
        ]
        original = self.catalogs.get((modality, "original"))
        phase = "catalog_discovery" if condition == "original" else "catalog_rewrite"
        if original is None:
            prompt = (
                self.audit.source_literal(
                    "src/agreement.rs",
                    "You maintain a semantic cluster catalog. Classification objective:",
                )
                .replace("{}", task, 1)
                .replace("{}", "16", 1)
            )
        else:
            prompt = (
                self.audit.source_literal(
                    "src/agreement.rs",
                    "You are jointly clarifying an immutable classification catalog.",
                )
                .replace("{task}", task)
                .replace("{}", verify.struct_json(original["catalog"]).decode(), 1)
            )
        properties = {"name": {"type": "string"}, "description": {"type": "string"}}
        required = ["name", "description"]
        if original is not None:
            properties["id"] = {"type": "integer"}
            required.append("id")
        schema = {
            "type": "object",
            "properties": {
                "clusters": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2 if original else 16,
                    "items": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["clusters"],
            "additionalProperties": False,
        }
        request = verify.structured_request(
            phase, prompt, discovery["rows"], schema, self.images
        )
        generated = {
            "clusters": (
                catalog
                if original
                else [{k: c[k] for k in ["name", "description"]} for c in catalog]
            )
        }
        prefix = f"catalog/{modality}-{condition}"
        self.journal(
            prefix, phase, [self.row(phase, request, self.response(generated))]
        )
        artifact = {
            "schema_version": 1,
            "run_id": prefix,
            "source": self.source,
            "status": "complete",
            "error": None,
            "modality": modality,
            "stage": condition,
            "task": task,
            "discovery_count": len(discovery["rows"]),
            "discovery_ids": [r["id"] for r in discovery["rows"]],
            "discovery_sha256": discovery["fingerprint"],
            "discovery_jsonl_sha256": discovery["jsonl_sha256"],
            "discovery_item_sha256": [
                verify.item_hash(r, self.images) for r in discovery["rows"]
            ],
            "max_clusters": 16,
            "parent_catalog_sha256": original["hash"] if original else None,
            "catalog": catalog,
            "request_sha256": verify.sha(verify.canonical(request)),
            "request_bytes": len(verify.canonical(request)),
            "measurement": self.measurement(prefix),
        }
        digest = self.write(self.run / (prefix + ".json"), artifact)
        self.jsonl(
            self.run / (prefix + ".progress.jsonl"),
            [
                {
                    "type": "metadata",
                    "run_id": prefix,
                    "stage": condition,
                    "discovery_sha256": discovery["fingerprint"],
                },
                {
                    "type": "terminal",
                    "status": "complete",
                    "catalog_sha256": verify.sha(verify.struct_json(catalog)),
                    "error": None,
                },
            ],
        )
        self.catalogs[(modality, condition)] = {
            "catalog": catalog,
            "hash": digest,
            "task": task,
        }

    def make_classification(self, modality, condition, mode, stage, policy=None):
        prefix = f"{stage}/{modality}-{condition}-{mode}" + (
            f"-{policy}" if policy else ""
        )
        catalog = self.catalogs[(modality, condition)]
        split = "heldout" if stage == "controlled" else "repeat"
        input_ = self.audit.inputs[(split, modality)]
        items = input_["rows"]
        ordered = (
            list(reversed(catalog["catalog"]))
            if policy == "reverse"
            else catalog["catalog"]
        )
        effective_order = [c["id"] for c in ordered]
        k = 16 if policy == "one-page" else 8
        actual_stage = (
            "classify"
            if stage == "controlled"
            else "repeat" if stage == "repeat" else "diagnostic"
        )
        primary = self.arms.get((modality, condition, mode, "controlled", None))
        metadata = {
            "experiment": "guided-agreement",
            "stage": actual_stage,
            "run_id": prefix,
            "source": self.source,
            "modality": modality,
            "condition": condition,
            "mode": mode,
            "task": catalog["task"],
            "k": k,
            "reverse_catalog_order": policy == "reverse",
            "diagnostic": stage == "diagnostics",
            "expected_count": len(items),
            "input_sha256": input_["fingerprint"],
            "input_jsonl_sha256": input_["jsonl_sha256"],
            "ordered_ids": [r["id"] for r in items],
            "catalog_sha256": catalog["hash"],
            "catalog": catalog["catalog"],
            "effective_catalog_sha256": verify.sha(verify.struct_json(ordered)),
            "effective_order": effective_order,
            "effective_order_sha256": verify.sha(verify.struct_json(effective_order)),
            "reference_sha256": primary["hash"] if stage != "controlled" else None,
            "repeat_index": (
                2 if stage == "diagnostics" else 1 if stage == "repeat" else None
            ),
            "assignment_model": verify.DECISIONS if mode == "ld" else verify.SOL,
            "sol_reasoning_effort": "high",
            "management_calls": 0,
        }
        requests = [
            verify.assignment_request(mode, catalog["task"], item, ordered, self.images)
            for item in items
        ]
        metadata["maximum_request_bytes"] = max(
            len(verify.canonical(r)) for r in requests
        )
        calls = []
        events = [{"type": "metadata", "metadata": metadata}]
        assignments = []
        patterns = {
            ("original", "llm"): [1, 1, 2, 2, None, None, 1, 2, None, 1],
            ("original", "ld"): [1, 2, 2, None, None, 1, 2, 2, None, 1],
            ("guided", "llm"): [1, 1, 2, 2, None, 1, 1, 2, None, 1],
            ("guided", "ld"): [1, 1, 2, 2, None, 1, 2, 2, 2, 1],
        }
        for ordinal, (item, request) in enumerate(zip(items, requests)):
            choice = patterns[(condition, mode)][ordinal % 10]
            refused = ordinal == 3 and mode == "ld"
            choice = None if refused else choice
            if mode == "ld":
                response = {
                    "model": verify.DECISIONS,
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                    "answers": [
                        (
                            {"name": "cluster", "type": "refusal"}
                            if refused
                            else {
                                "name": "cluster",
                                "type": "choice",
                                "choice": str(choice) if choice else "other",
                            }
                        )
                    ],
                }
            else:
                response = self.response(
                    {"cluster_id": str(choice) if choice else "other"}
                )
            retry = (
                stage == "controlled"
                and modality == "text"
                and condition == "original"
                and mode == "ld"
                and ordinal == 0
            )
            if retry:
                calls.append(self.row("assign", request, None, "HTTP503", 1, 503))
            calls.append(
                self.row("assign", request, response, attempt=2 if retry else 1)
            )
            record = {
                "id": item["id"],
                "cluster_id": choice,
                "refused": refused,
                "label": item.get("label"),
            }
            assignments.append(record)
            events.extend(
                [
                    {
                        "type": "page",
                        "ordinal": ordinal,
                        "id": item["id"],
                        "page": {
                            "page_index": 0,
                            "candidate_ids": effective_order,
                            "cluster_id": choice,
                            "refused": refused,
                            "request_sha256": verify.sha(verify.canonical(request)),
                            "response_sha256": verify.sha(verify.canonical(response)),
                        },
                    },
                    {
                        "type": "assignment",
                        "ordinal": ordinal,
                        "id": item["id"],
                        "cluster_id": choice,
                        "refused": refused,
                    },
                ]
            )
        self.journal(prefix, actual_stage, calls)
        events.append(
            {
                "type": "terminal",
                "status": "complete",
                "processed_count": len(items),
                "expected_count": len(items),
                "error": None,
            }
        )
        self.jsonl(self.run / (prefix + ".progress.jsonl"), events)
        artifact = {
            "schema_version": 1,
            "status": "complete",
            "error": None,
            "metadata": metadata,
            "processed_count": len(items),
            "expected_count": len(items),
            "assignments": assignments,
            "progress_sha256": verify.sha(
                (self.run / (prefix + ".progress.jsonl")).read_bytes()
            ),
            "measurement": self.measurement(prefix),
        }
        digest = self.write(self.run / (prefix + ".json"), artifact)
        self.arms[(modality, condition, mode, stage, policy)] = {
            "artifact": artifact,
            "hash": digest,
            "assignments": assignments,
        }

    def make_review(self, modality, condition, failed, leaked=False):
        prefix = f"review/{modality}-{condition}"
        items = self.inputs[("heldout", modality)]
        catalog = self.catalogs[(modality, condition)]
        baseline = self.arms[(modality, condition, "llm", "controlled", None)]
        candidate = self.arms[(modality, condition, "ld", "controlled", None)]
        keys, strata = verify.review_selection(
            self.plan,
            f"{modality}-{condition}",
            modality,
            items,
            baseline["assignments"],
            candidate["assignments"],
        )
        item_map = {r["id"]: r for r in items}
        cases = []
        evidence = {}
        for key in keys:
            item = item_map[key["item_id"]]
            a, b = key["reference_cluster_id"], key["candidate_cluster_id"]
            a, b = (a, b) if key["a_is_reference"] else (b, a)
            case = {
                "case_id": key["case_id"],
                "task": catalog["task"],
                "item": {
                    "text": item["text"],
                    "image": (
                        f'/unavailable/historical/{item["id"]}.jpg'
                        if modality == "images"
                        else None
                    ),
                },
                "catalog": catalog["catalog"],
                "choice_a": a,
                "choice_b": b,
            }
            if leaked:
                case["a_is_reference"] = key["a_is_reference"]
            cases.append(case)
            key["payload_sha256"] = verify.sha(verify.struct_json(case))
            evidence[case["case_id"]] = verify.review_evidence_hash(
                item["text"], self.images.get(item["id"])
            )
        historical = [
            verify.input_item(item, f'/unavailable/historical/{item["id"]}.jpg')
            for item in items
        ]
        bundle = {
            "schema_version": 1,
            "sampling_plan": self.plan,
            "plan_sha256": verify.sha(verify.struct_json(self.plan)),
            "audit": {
                "cohort_id": f"{modality}-{condition}",
                "modality": modality,
                "total_input_count": len(items),
                "catalog_sha256": verify.sha(verify.struct_json(catalog["catalog"])),
                "items_sha256": verify.sha(verify.struct_json(historical)),
                "reference_assignments_sha256": verify.sha(
                    verify.struct_json(verify.assignment_rows(baseline["assignments"]))
                ),
                "candidate_assignments_sha256": verify.sha(
                    verify.struct_json(verify.assignment_rows(candidate["assignments"]))
                ),
                "strata": strata,
                "keys": keys,
            },
            "cases": cases,
            "evidence_sha256": evidence,
        }
        bundle_hash = self.write(self.run / (prefix + ".bundle.json"), bundle)
        instructions = self.audit.source_literal(
            "src/agreement_review.rs", "Evaluate two anonymous classification choices"
        )
        requests = []
        for case, key in zip(cases, keys):
            visible = {k: v for k, v in case.items() if k != "item"}
            requests.append(
                verify.structured_request(
                    "blinded_review",
                    instructions
                    + "\nBlinded case: "
                    + verify.canonical(visible).decode(),
                    [item_map[key["item_id"]]],
                    verify.review_schema(case["case_id"]),
                    self.images,
                )
            )
        metadata = {
            "experiment": "guided-agreement",
            "stage": "blinded_review",
            "run_id": prefix,
            "source": self.source,
            "bundle_sha256": bundle_hash,
            "plan_sha256": bundle["plan_sha256"],
            "selected_count": len(keys),
            "model": verify.SOL,
            "reasoning_effort": "high",
            "maximum_request_bytes": max(len(verify.canonical(r)) for r in requests),
            "automated_review": True,
        }
        calls = []
        outcomes = []
        error = "completed semantic review rejection" if failed else None
        for i, (case, request) in enumerate(zip(cases, requests)):
            same = case["choice_a"] == case["choice_b"]
            judgment = {
                "case_id": case["case_id"],
                "a_fit": "supported",
                "b_fit": "supported" if same else "unsupported",
                "verdict": "both_reasonable" if same else "a_better",
                "severity": "none" if same else "major",
                "themes": ["reasonable_alternative"],
                "evidence": ["Visible source evidence"],
                "explanation": "Synthetic judgment.",
                "proposed_alternative": None,
            }
            if failed and i == 1:
                judgment["case_id"] = "wrong-case"
                calls.append(
                    self.row("blinded_review", request, self.response(judgment), error)
                )
                outcomes.append(
                    {
                        "case_id": case["case_id"],
                        "raw_response": None,
                        "judgment": None,
                        "error": error,
                    }
                )
                break
            calls.append(self.row("blinded_review", request, self.response(judgment)))
            outcomes.append(
                {
                    "case_id": case["case_id"],
                    "raw_response": judgment,
                    "judgment": judgment,
                    "error": None,
                }
            )
        self.journal(prefix, "blinded_review", calls)
        status = "failed" if failed else "complete"
        events = (
            [{"type": "metadata", "metadata": metadata}]
            + [{"type": "review", "outcome": outcome} for outcome in outcomes]
            + [
                {
                    "type": "terminal",
                    "status": status,
                    "attempted_count": len(outcomes),
                    "selected_count": len(keys),
                    "error": error,
                }
            ]
        )
        self.jsonl(self.run / (prefix + ".progress.jsonl"), events)
        aggregate = verify.aggregate_reviews(bundle, outcomes)
        artifact = {
            "status": status,
            "error": error,
            "metadata": metadata,
            "outcomes": outcomes,
            "aggregate": aggregate,
            "measurement": self.measurement(prefix, not failed),
            "progress_sha256": verify.sha(
                (self.run / (prefix + ".progress.jsonl")).read_bytes()
            ),
        }
        self.write(self.run / (prefix + ".json"), artifact)
        if failed:
            self.write_bytes(self.run / "review/supervisor-exit-code.txt", b"1\n")

    def make_analysis(self):
        mapping = {
            "schema_version": 1,
            "review_plan": "preregistration/review-plan.json",
            "cohorts": [],
        }
        report = {
            "schema_version": 1,
            "status": "complete",
            "review_plan": self.plan,
            "review_plan_sha256": verify.sha(verify.struct_json(self.plan)),
            "review_plan_file_sha256": verify.sha(
                (self.run / "preregistration/review-plan.json").read_bytes()
            ),
            "modalities": [],
        }
        for modality in ["text", "images"]:
            cohort = {
                "modality": modality,
                "items": f"../../data/guidance/heldout/{modality}.jsonl",
                "repeat_input": f"../../data/guidance/repeat/{modality}.jsonl",
            }
            row = {
                "modality": modality,
                "heldout_count": len(self.inputs[("heldout", modality)]),
                "repeat_count": len(self.inputs[("repeat", modality)]),
            }
            for condition in ["original", "guided"]:
                cohort[condition] = {
                    "catalog": f"catalog/{modality}-{condition}.json",
                    "baseline": f"controlled/{modality}-{condition}-llm.json",
                    "candidate": f"controlled/{modality}-{condition}-ld.json",
                    "baseline_repeat": f"repeat/{modality}-{condition}-llm.json",
                    "candidate_repeat": None,
                    "review_bundle": f"review/{modality}-{condition}.bundle.json",
                    "review_output": f"review/{modality}-{condition}.json",
                }
                baseline = self.arms[(modality, condition, "llm", "controlled", None)]
                candidate = self.arms[(modality, condition, "ld", "controlled", None)]
                again = self.arms[(modality, condition, "llm", "repeat", None)]
                catalog = self.catalogs[(modality, condition)]
                review_path = self.run / f"review/{modality}-{condition}.json"
                review = verify.read_json(review_path)
                bundle_path = self.run / f"review/{modality}-{condition}.bundle.json"
                bundle = verify.read_json(bundle_path)
                if review["status"] != "complete":
                    report["status"] = "reviews_incomplete"
                row[condition] = {
                    "artifact_sha256": {
                        "catalog": catalog["hash"],
                        "baseline": baseline["hash"],
                        "candidate": candidate["hash"],
                        "baseline_repeat": again["hash"],
                        "candidate_repeat": None,
                    },
                    "comparison": verify.compare_assignments(
                        baseline["assignments"],
                        candidate["assignments"],
                        catalog["catalog"],
                    ),
                    "baseline_repeat": verify.repeat_score(
                        baseline["assignments"],
                        again["assignments"],
                        catalog["catalog"],
                        [r["id"] for r in self.inputs[("repeat", modality)]],
                    ),
                    "candidate_repeat": None,
                    "measurements": {
                        "baseline": baseline["artifact"]["measurement"],
                        "candidate": candidate["artifact"]["measurement"],
                        "baseline_repeat": again["artifact"]["measurement"],
                        "candidate_repeat": None,
                    },
                    "review": {
                        "bundle_sha256": verify.sha(bundle_path.read_bytes()),
                        "selected_count": len(bundle["cases"]),
                        "complete": review["status"] == "complete",
                        "output_sha256": verify.sha(review_path.read_bytes()),
                        "aggregate": review["aggregate"],
                        "measurement": review["measurement"],
                    },
                }
            arms = lambda c, m: self.arms[(modality, c, m, "controlled", None)][
                "assignments"
            ]
            row["paired"] = verify.paired_gain_loss(
                arms("original", "llm"),
                arms("original", "ld"),
                arms("guided", "llm"),
                arms("guided", "ld"),
                self.catalogs[(modality, "original")]["catalog"],
            )
            mapping["cohorts"].append(cohort)
            report["modalities"].append(row)
        report["manifest_sha256"] = self.write(
            self.run / "analysis-input.json", mapping
        )
        self.write(self.run / "analysis.json", report)


class CompleteAuditTests(unittest.TestCase):
    def test_actual_raw_file_and_typed_plan_hashes_are_distinct_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CompleteFixture(Path(tmp))
            protocol = verify.read_json(fixture.run / "preregistration/protocol.json")
            bundle = verify.read_json(fixture.run / "review/text-original.bundle.json")
            analysis = verify.read_json(fixture.run / "analysis.json")
            self.assertEqual(
                protocol["review_plan_sha256"],
                "e61d2e1055478b90043d20a09319b0294e82bf5213add6f44f130ee896db9bf1",
            )
            self.assertEqual(
                bundle["plan_sha256"],
                "5d1aa5e17d20991c477822c5c353a222b8d63e01b54dd995d00bb8abfa87391e",
            )
            self.assertEqual(analysis["review_plan_sha256"], bundle["plan_sha256"])
            self.assertEqual(
                analysis["review_plan_file_sha256"], protocol["review_plan_sha256"]
            )
            result = verify.audit_complete(
                fixture.run,
                fixture.data,
                fixture.run / "analysis.json",
                fixture.source_repo,
            )
            self.assertEqual(result["status"], "verified")

    def test_raw_plan_pin_and_plan_object_corruption_are_independently_rejected(self):
        for corruption in ("raw_pin", "plan_object"):
            with self.subTest(
                corruption=corruption
            ), tempfile.TemporaryDirectory() as tmp:
                fixture = CompleteFixture(Path(tmp))
                path = fixture.run / "preregistration/protocol.json"
                protocol = verify.read_json(path)
                if corruption == "raw_pin":
                    protocol["review_plan_sha256"] = "0" * 64
                else:
                    protocol["review_plan"]["text_quotas"]["different_named"] -= 1
                digest = fixture.write(path, protocol)
                runtime_path = fixture.run / "preregistration/runtime.json"
                runtime = verify.read_json(runtime_path)
                runtime["protocol_sha256"] = digest
                fixture.write(runtime_path, runtime)
                with self.assertRaisesRegex(
                    ValueError,
                    (
                        "raw review plan file"
                        if corruption == "raw_pin"
                        else "review plan object"
                    ),
                ):
                    verify.audit_complete(
                        fixture.run,
                        fixture.data,
                        fixture.run / "analysis.json",
                        fixture.source_repo,
                    )

    def test_typed_plan_pins_in_bundle_and_analysis_are_independently_rejected(self):
        for artifact in ("review/text-original.bundle.json", "analysis.json"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as tmp:
                fixture = CompleteFixture(Path(tmp))
                path = fixture.run / artifact
                value = verify.read_json(path)
                value[
                    (
                        "plan_sha256"
                        if artifact.endswith("bundle.json")
                        else "review_plan_sha256"
                    )
                ] = ("0" * 64)
                fixture.write(path, value)
                with self.assertRaisesRegex(
                    ValueError, "review plan differs|review_plan_sha256"
                ):
                    verify.audit_complete(
                        fixture.run,
                        fixture.data,
                        fixture.run / "analysis.json",
                        fixture.source_repo,
                    )

    def test_self_consistent_backend_leak_in_reviewer_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CompleteFixture(Path(tmp), leaked_review=True)
            with self.assertRaisesRegex(ValueError, "unregistered fields"):
                verify.audit_complete(
                    fixture.run,
                    fixture.data,
                    fixture.run / "analysis.json",
                    fixture.source_repo,
                )

    def test_full_synthetic_evidence_relocates_and_keeps_unknown_cost_unknown(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as relocated:
            fixture = CompleteFixture(Path(tmp))
            shutil.copytree(fixture.root, Path(relocated) / "copy")
            root = Path(relocated) / "copy"
            result = verify.audit_complete(
                root / "runs/guided",
                root / "data/guidance",
                root / "runs/guided/analysis.json",
                fixture.source_repo,
            )
            self.assertEqual(result["status"], "verified")
            self.assertEqual(len(result["costs"]), 28)
            self.assertEqual(result["cost_summary"]["unknown_usage_calls"], 1)
            self.assertFalse(result["cost_summary"]["cost_complete"])
            self.assertIsNone(result["cost_summary"]["total_cost_usd"])
            self.assertEqual(result["analysis"]["modalities"][0]["heldout_count"], 1000)
            self.assertTrue(
                result["diagnostics"]["images-guided-ld-one-page"][
                    "same_effective_page_content_as_primary"
                ]
            )
            report = verify.read_json(root / "runs/guided/analysis.json")
            report["modalities"][0]["original"]["comparison"][
                "direct_agreement_count"
            ] += 1
            fixture.write(root / "runs/guided/analysis.json", report)
            with self.assertRaisesRegex(ValueError, "direct_agreement_count"):
                verify.audit_complete(
                    root / "runs/guided",
                    root / "data/guidance",
                    root / "runs/guided/analysis.json",
                    fixture.source_repo,
                )

    def test_terminal_semantic_review_rejection_is_audited_without_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CompleteFixture(Path(tmp), failed_review=True)
            result = verify.audit_complete(
                fixture.run,
                fixture.data,
                fixture.run / "analysis.json",
                fixture.source_repo,
            )
            self.assertEqual(result["status"], "verified_with_incomplete_review")
            self.assertEqual(result["analysis"]["status"], "reviews_incomplete")
            review = result["analysis"]["modalities"][0]["original"]["review"]
            self.assertFalse(review["complete"])
            self.assertEqual(review["aggregate"]["totals"]["accepted_count"], 1)
            self.assertEqual(review["aggregate"]["totals"]["failed_count"], 1)
            self.assertGreater(review["aggregate"]["totals"]["not_attempted_count"], 0)
            self.assertFalse(
                result["costs"]["review/text-original"]["cost_history_complete"]
            )
            self.assertEqual(len(review["independent_failures"]), 1)


if __name__ == "__main__":
    unittest.main()
