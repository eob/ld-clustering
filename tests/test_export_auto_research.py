"""Synthetic frozen archives only; no model calls or actual experiment outputs."""

import copy
from decimal import Decimal
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_auto_research.py"
exporter = types.ModuleType("export_auto_research")
exporter.__file__ = str(SCRIPT)
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), "exec"), exporter.__dict__)
archive = exporter.archive
STYLES = ["short", "redundant-positive", "negative-boundaries"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    )


def score(n, value):
    direct = int(n * value)
    named = min(direct, int(n * max(0, value - 0.1)))
    other = direct - named
    assigned = n - other
    return dict(
        n=n,
        direct_agreement_count=direct,
        named_id_agreement_count=named,
        reference_assigned_count=assigned,
        candidate_assigned_count=assigned,
        direct_agreement=direct / n,
        named_id_agreement=named / n,
        reference_coverage=assigned / n,
        candidate_coverage=assigned / n,
        assigned_other=dict(
            both_other=other,
            both_named=assigned,
            reference_named_candidate_other=0,
            reference_other_candidate_named=0,
        ),
        partition=dict(n=n, adjusted_rand_index=value - 0.4, pairwise_f1=value),
    )


class Fixture:
    def __init__(self, root):
        self.root = root
        self.run = root / "run"
        self.data = root / "data"
        self.out = root / "archive"
        self.output = root / "publication.json"
        self.run.mkdir()
        self.data.mkdir()
        self.binary = root / "frozen-runtime"
        self.binary.write_bytes(b"\x7fELFsynthetic-runtime")
        self.source = dict(
            commit="a" * 40,
            executable_sha256=sha(self.binary),
            committed_sources_verified=True,
            embedded_file_sha256={"src/runtime.rs": "c" * 64},
        )
        write(self.run / "preregistration/runtime-source-pins.json", self.source)
        history = dict(
            schema_version=1,
            updated_at="2026-10-20",
            objective="Synthetic objective; preserve the original history.",
            rounds=[],
        )
        for index in range(6):
            history["rounds"].append(
                dict(
                    id=f"historical-{index}",
                    title="Synthetic historical design",
                    phase="historical",
                    status="superseded" if index == 0 else "complete",
                    design="Synthetic earlier design.",
                    hypothesis="Earlier synthetic hypothesis.",
                    conditions=["Frozen earlier evidence."],
                    dataset="Synthetic prior cohort.",
                    timestamps=None,
                    measurements=None,
                    accounting=None,
                    decision="Retain earlier record.",
                    next_question=None,
                    limits=["Synthetic fixture only."],
                    evidence=[
                        dict(
                            label="Earlier immutable evidence",
                            url="https://github.com/example/evidence",
                        )
                    ],
                )
            )
        write(self.run / "report/history-log.json", history)
        self.conditions = []
        self.comparisons = []
        self.metrics = {}
        self.costs = {}
        self.bindings = {}
        self.calib = {}
        self.grouped = []
        for style in STYLES:
            for order in range(4):
                stem = f"r1-{style}-o{order}"
                for mode in ["llm", "ld"]:
                    self.arm(
                        stem + "-" + mode,
                        "calibration",
                        mode,
                        2,
                        "text",
                        description_style=style,
                        cyclic_order=order,
                    )
                    self.calib[stem + "-" + mode] = dict(
                        status="complete",
                        style=style,
                        cyclic_order=order,
                        mode=mode,
                        n=2,
                        correct=2 if mode == "llm" else 1,
                        accuracy=1.0 if mode == "llm" else 0.5,
                        rows=[],
                    )
                self.pair(stem, stem + "-llm", stem + "-ld", score(2, 0.5))
            for mode in ["llm", "ld"]:
                self.grouped.append(
                    dict(
                        style=style,
                        mode=mode,
                        status="complete",
                        n=8,
                        correct=8 if mode == "llm" else 4,
                        accuracy=1.0 if mode == "llm" else 0.5,
                        same_choice_in_all_four_orders=2,
                        distinct_cases=2,
                    )
                )
        for modality, n in [("text", 4), ("images", 3)]:
            for variant, round_id, value in [
                ("baseline", "r2", 0.75),
                ("compact", "r2", 0.5),
                ("boundary", "r3", 0.25),
            ]:
                if variant != "baseline":
                    self.arm(
                        f"{round_id}-{modality}-{variant}-generation",
                        ("round2" if round_id == "r2" else "round3") + "-generation",
                        "llm",
                        2,
                        modality,
                        kind="custom_rewrite",
                    )
                stem = f"{round_id}-{modality}-{variant}"
                for mode in ["llm", "ld"]:
                    self.arm(
                        stem + "-" + mode,
                        ("round2" if round_id == "r2" else "round3") + "-development",
                        mode,
                        n,
                        modality,
                    )
                self.pair(stem, stem + "-llm", stem + "-ld", score(n, value))
            for variant, value in [("baseline", 0.5), ("challenger", 0.9)]:
                stem = f"confirmation-{modality}-{variant}"
                for mode in ["llm", "ld"]:
                    self.arm(stem + "-" + mode, "confirmation", mode, n + 2, modality)
                self.pair(stem, stem + "-llm", stem + "-ld", score(n + 2, value))
                self.arm(
                    f"repeat-{modality}-{variant}-llm", "repeats", "llm", 2, modality
                )
        dataset = dict(
            schema_version=3,
            experiment="guidance-auto-research",
            archival_files=["manifest.json"]
            + [f"provenance/{i}.bin" for i in range(396)],
        )
        for name in dataset["archival_files"][1:]:
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        write(self.data / "manifest.json", dataset)
        write(self.run / "preregistration/dataset-manifest.json", dataset)
        self.protocol = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            data=dict(
                dataset_manifest_sha256=sha(self.data / "manifest.json"),
                text="Synthetic text data.",
                photos="Synthetic image data.",
                partitions=dict(
                    development=dict(text=dict(count=4), images=dict(count=3)),
                    confirmation=dict(text=dict(count=6), images=dict(count=5)),
                    repeat=dict(text=dict(count=2), images=dict(count=2)),
                ),
            ),
            round1=dict(
                name="Synthetic calibration",
                items=2,
                styles=STYLES,
                stable_ids=dict(Banking=11, Cooking=29, Weather=43, Transportation=71),
                interpretation="Four dependent orders; not natural-data accuracy.",
            ),
            round2=dict(name="One compact joint rewrite per modality"),
            round3=dict(name="One bounded refinement"),
            hypotheses=dict(
                mechanism="A synthetic mechanism hypothesis.",
                compact="Compact may improve agreement.",
                boundary="Boundary may improve agreement.",
            ),
            question="Does a frozen challenger transfer?",
            scope="Synthetic frozen scope.",
        )
        write(self.run / "preregistration/protocol.json", self.protocol)
        write(
            self.run / "preregistration/conditions.json",
            dict(
                schema_version=1,
                experiment="guidance-auto-research",
                conditions=self.conditions,
                comparisons=self.comparisons,
            ),
        )
        self.protocol["conditions_sha256"] = sha(
            self.run / "preregistration/conditions.json"
        )
        write(self.run / "preregistration/protocol.json", self.protocol)
        base = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            status="verified",
            protocol_sha256=sha(self.run / "preregistration/protocol.json"),
            dataset_manifest_sha256=sha(self.data / "manifest.json"),
            source=self.source,
            comparisons=self.metrics,
            costs=self.costs,
            request_response_bindings=self.bindings,
        )
        subset = {
            **base,
            "comparisons": {
                name: value
                for name, value in self.metrics.items()
                if not name.startswith("confirmation-")
            },
            "evidence_files": {},
        }
        write(self.run / "validation/development-independent-audit.json", subset)
        self.selection = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            frozen_at_utc="2026-10-21T00:00:00Z",
            audit_sha256=sha(
                self.run / "validation/development-independent-audit.json"
            ),
            protocol_sha256=base["protocol_sha256"],
            dataset_manifest_sha256=base["dataset_manifest_sha256"],
            modalities={},
        )
        for modality in ["text", "images"]:
            baseline = self.metrics[f"r2-{modality}-baseline"]
            ranking = []
            for name, round_id in [("compact", "r2"), ("boundary", "r3")]:
                metrics = self.metrics[f"{round_id}-{modality}-{name}"]
                checks = dict(
                    named_improved=metrics["named_id_agreement_count"]
                    > baseline["named_id_agreement_count"],
                    direct_retained=metrics["direct_agreement_count"]
                    >= baseline["direct_agreement_count"],
                    reference_coverage_retained=100
                    * (
                        baseline["reference_assigned_count"]
                        - metrics["reference_assigned_count"]
                    )
                    <= 2 * baseline["n"],
                    candidate_coverage_retained=100
                    * (
                        baseline["candidate_assigned_count"]
                        - metrics["candidate_assigned_count"]
                    )
                    <= 2 * baseline["n"],
                )
                ranking.append(
                    dict(
                        name=name,
                        eligible=all(checks.values()),
                        checks=checks,
                        metrics=metrics,
                    )
                )
            self.selection["modalities"][modality] = dict(
                status="NOT_ADOPTED",
                adopted="baseline",
                challenger="compact",
                baseline=baseline,
                ranking=ranking,
            )
        write(self.run / "selection/selection.json", self.selection)
        calibration = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            scope="Synthetic exact-key tests only.",
            protocol_sha256=base["protocol_sha256"],
            audit_sha256=sha(
                self.run / "validation/development-independent-audit.json"
            ),
            conditions=self.calib,
            grouped=self.grouped,
            within_condition_comparisons={
                name: value
                for name, value in self.metrics.items()
                if name.startswith("r1-")
            },
        )
        write(self.run / "analysis/calibration-analysis.json", calibration)
        self.audit = {
            **base,
            "evidence_files": {
                str(path.relative_to(self.run)): sha(path)
                for path in self.run.rglob("*")
                if path.is_file()
            },
        }
        write(self.run / "validation/final-independent-audit.json", self.audit)
        inventory = {name: sha(self.data / name) for name in dataset["archival_files"]}
        gate = dict(
            schema_version=1,
            status="passed",
            manifest_sha256=sha(self.data / "manifest.json"),
            archival_file_count=397,
            artifact_sha256=inventory,
            artifact_inventory=[
                dict(file=name, sha256=digest, bytes=(self.data / name).stat().st_size)
                for name, digest in inventory.items()
            ],
        )
        write(self.run / "validation/dataset-independent-audit.json", gate)
        (self.run / "dispatcher.lock").write_bytes(b"")
        registration = dict(
            conditions=[dict(id=condition["id"]) for condition in self.conditions]
        )
        write(self.run / "registrations/synthetic/registration.json", registration)
        write(
            self.run / "registrations/synthetic/supervisor-start.json",
            dict(containment=dict(unit="synthetic-only")),
        )
        write(
            self.run / "registrations/synthetic/supervisor-terminal.json",
            dict(
                status="complete",
                registration_sha256=sha(
                    self.run / "registrations/synthetic/registration.json"
                ),
                containment=dict(unit="synthetic-only"),
                conditions=[
                    dict(id=condition["id"], successful=True)
                    for condition in self.conditions
                ],
                not_started=[],
            ),
        )
        self.pack()

    def arm(self, id, phase, mode, n, modality, kind="classify", **extra):
        if phase == "calibration":
            prefix = "calibration/results"
        elif phase.endswith("-generation"):
            prefix = "catalogs"
        elif phase == "repeats":
            prefix = "repeat"
        elif phase == "confirmation":
            prefix = "confirmation"
        else:
            prefix = "development"
        output = prefix + "/" + id + ".json"
        self.conditions.append(
            dict(
                id=id,
                kind="classification" if kind == "classify" else "rewrite",
                phase=phase,
                stage=(
                    "custom_rewrite"
                    if kind != "classify"
                    else (
                        "calibration"
                        if phase == "calibration"
                        else (
                            "confirmation"
                            if phase in ["confirmation", "repeats"]
                            else "development"
                        )
                    )
                ),
                mode=mode,
                modality=modality,
                expected_count=n,
                output=output,
                **extra,
            )
        )
        self.costs[id] = dict(
            known_cost_usd="0.000000000000000001",
            cost_complete=True,
            cost_history_complete=True,
            calls=1,
            error_calls=0,
            unknown_usage_calls=0,
            unknown_pricing_calls=0,
            assignment_refusal_calls=0,
            retry_attempts=0,
        )
        self.bindings[id] = dict(complete=True, expected_count=n, processed_count=n)
        write(
            self.run / output,
            dict(
                schema_version=1,
                experiment="guidance-auto-research",
                status="complete",
                metadata=dict(source=self.source),
                processed_count=n,
                expected_count=n,
            ),
        )

    def pair(self, id, reference, candidate, metrics):
        output = "comparisons/" + id + ".json"
        self.comparisons.append(
            dict(id=id, reference=reference, candidate=candidate, output=output)
        )
        self.metrics[id] = metrics
        write(
            self.run / output,
            dict(
                schema_version=1,
                experiment="guidance-auto-research",
                status="complete",
                comparison=metrics,
            ),
        )

    def pack(self):
        with patch.object(archive, "active_workers", return_value=[]):
            archive.create_archive(
                self.run,
                self.data,
                self.out,
                dataset_manifest_sha256=sha(self.data / "manifest.json"),
                dataset_gate="validation/dataset-independent-audit.json",
                dataset_gate_sha256=sha(
                    self.run / "validation/dataset-independent-audit.json"
                ),
                source_commit=self.source["commit"],
                binary=self.binary,
                binary_sha256=sha(self.binary),
            )
        self.anchor = sha(self.out / "manifest.json")

    def refresh(self):
        subset = json.loads(
            (self.run / "validation/development-independent-audit.json").read_bytes()
        )
        subset["comparisons"] = {
            name: value
            for name, value in self.audit["comparisons"].items()
            if not name.startswith("confirmation-")
        }
        write(self.run / "validation/development-independent-audit.json", subset)
        calibration = json.loads(
            (self.run / "analysis/calibration-analysis.json").read_bytes()
        )
        calibration["audit_sha256"] = sha(
            self.run / "validation/development-independent-audit.json"
        )
        calibration["within_condition_comparisons"] = {
            name: value
            for name, value in self.audit["comparisons"].items()
            if name.startswith("r1-")
        }
        write(self.run / "analysis/calibration-analysis.json", calibration)
        self.selection["audit_sha256"] = sha(
            self.run / "validation/development-independent-audit.json"
        )
        write(self.run / "selection/selection.json", self.selection)
        final = self.run / "validation/final-independent-audit.json"
        self.audit["evidence_files"] = {
            str(path.relative_to(self.run)): sha(path)
            for path in self.run.rglob("*")
            if path.is_file() and path != final
        }
        write(final, self.audit)
        shutil.rmtree(self.out)
        self.pack()

    def add_review(self):
        write(
            self.run / "qualitative/review.json",
            dict(judgment="Synthetic literal evidence; not actual research."),
        )
        self.review = dict(
            schema_version=1,
            source=dict(
                repository=exporter.REPOSITORY,
                run_path=exporter.PUBLIC_ARCHIVE,
                commit=None,
                manifest_sha256=None,
            ),
            provenance_files={
                "qualitative/review.json": sha(self.run / "qualitative/review.json")
            },
            selection_note="Synthetic selected case only.",
            reviewer="Synthetic reviewer fixture",
            examples=[
                dict(
                    case_id="synthetic-only",
                    text="Literal synthetic request.",
                    image=None,
                    summary="Synthetic outcome.",
                    themes=["uncertain"],
                    assignments=[],
                )
            ],
        )
        write(self.run / "report/review-publication.json", self.review)
        self.refresh()

    def export(self, review_publication=None):
        return exporter.export_publication(
            self.run,
            self.run / "validation/final-independent-audit.json",
            self.run / "report/history-log.json",
            self.run / "analysis/calibration-analysis.json",
            self.run / "selection/selection.json",
            self.out,
            self.anchor,
            "b" * 40,
            self.output,
            review_publication=review_publication,
        )


class ExportTests(unittest.TestCase):
    def test_history_and_all_new_designs_are_preserved_with_distinct_metric_denominators(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            publication = fixture.export()
            history = json.loads((fixture.run / "report/history-log.json").read_bytes())
            self.assertEqual(publication["rounds"][:6], history["rounds"])
            self.assertEqual(len(publication["rounds"]), 12)
            self.assertEqual(
                publication["rounds"][6]["measurements"][0]["metric"],
                "constructed_key_accuracy",
            )
            self.assertEqual(publication["rounds"][6]["measurements"][0]["n"], 8)
            calibration_limits = " ".join(publication["rounds"][6]["limits"])
            self.assertIn("four named options plus Other", calibration_limits)
            self.assertIn("11, 29, 43, 71", calibration_limits)
            self.assertIn("not held constant", calibration_limits)
            compact = next(
                row for row in publication["rounds"] if row["id"] == "auto-r2-compact"
            )
            named = next(
                row
                for row in compact["measurements"]
                if row["metric"] == "named_id_agreement" and row["n"] == 4
            )
            self.assertEqual(named["conditions"][1]["value"], 0.25)
            pair_f1 = next(
                row
                for row in compact["measurements"]
                if row["metric"] == "pairwise_f1" and row["n"] == 4
            )
            self.assertEqual(
                pair_f1["conditions"][1]["value"],
                fixture.metrics["r2-text-compact"]["partition"]["pairwise_f1"],
            )

    def test_negative_results_and_not_adopted_decision_are_not_replaced_by_confirmation(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            publication = fixture.export()
            compact = next(
                row for row in publication["rounds"] if row["id"] == "auto-r2-compact"
            )
            direct = next(
                row
                for row in compact["measurements"]
                if row["metric"] == "direct_id_agreement" and row["n"] == 4
            )
            self.assertEqual(
                [condition["value"] for condition in direct["conditions"]], [0.75, 0.5]
            )
            confirmation = next(
                row for row in publication["rounds"] if row["phase"] == "confirmation"
            )
            self.assertIn("NOT_ADOPTED", confirmation["decision"])
            self.assertIn("adopted: baseline", confirmation["decision"])
            self.assertEqual(
                confirmation["measurements"][0]["conditions"][1]["value"],
                fixture.metrics["confirmation-text-challenger"]["direct_agreement"],
            )
            self.assertIn(
                "/blob/"
                + "b" * 40
                + "/experiments/2026-10-21-auto-research-seed2043/evidence/readable/",
                confirmation["evidence"][0]["url"],
            )

    def test_each_new_api_stage_is_charged_once_with_exact_decimal_strings(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            publication = fixture.export()
            expected = sum(
                Decimal(row["known_cost_usd"])
                for row in fixture.audit["costs"].values()
            )
            observed = sum(
                Decimal(row["accounting"]["known_cost_usd"])
                for row in publication["rounds"][6:]
            )
            self.assertEqual(expected, observed)
            self.assertEqual(len(fixture.conditions), 52)
            for row in publication["rounds"][6:]:
                self.assertEqual(
                    row["accounting"]["known_cost_usd"],
                    row["accounting"]["total_cost_usd"],
                )
                self.assertNotIn("e", row["accounting"]["known_cost_usd"])
            boundary = next(
                row for row in publication["rounds"] if row["id"] == "auto-r3-boundary"
            )
            self.assertIn(
                "0.000000000000000006", boundary["accounting"]["known_cost_usd"]
            )
            self.assertIn("reused", " ".join(boundary["conditions"]))

    def test_compact_round_decision_precedes_final_boundary_adoption(self):
        for incomplete in (False, True):
            with self.subTest(incomplete=incomplete), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                selected = fixture.selection["modalities"]["text"]
                metrics = score(4, 1.0)
                fixture.metrics["r3-text-boundary"] = metrics
                selected["ranking"][1].update(
                    metrics=metrics,
                    eligible=True,
                    checks=dict(
                        named_improved=True,
                        direct_retained=True,
                        reference_coverage_retained=True,
                        candidate_coverage_retained=True,
                    ),
                )
                selected["ranking"].reverse()
                selected.update(status="ADOPTED", adopted="boundary", challenger="boundary")
                if incomplete:
                    name = "r2-text-compact-ld"
                    fixture.audit["request_response_bindings"][name]["complete"] = False
                    fixture.audit["costs"][name].update(
                        cost_complete=False, cost_history_complete=False
                    )
                    fixture.audit["comparisons"].pop("r2-text-compact")
                    selected["ranking"] = selected["ranking"][:1]
                fixture.refresh()
                publication = fixture.export()
                rounds = {row["id"]: row for row in publication["rounds"]}
                compact = rounds["auto-r2-compact"]
                self.assertNotIn("ADOPTED", compact["decision"])
                self.assertNotIn("adopted: boundary", compact["decision"])
                if incomplete:
                    self.assertEqual(compact["status"], "incomplete")
                    self.assertIn("incomplete candidate", compact["decision"])
                    self.assertIn("available complete candidates", compact["decision"])
                else:
                    self.assertIn("one registered boundary revision", compact["decision"])
                boundary = rounds["auto-r3-boundary"]
                confirmation = rounds["auto-r4-confirmation"]
                self.assertIn("Final development selection:", boundary["decision"])
                self.assertIn("adopted: boundary", boundary["decision"])
                self.assertIn("Frozen before confirmation:", confirmation["decision"])
                self.assertIn("adopted: boundary", confirmation["decision"])

    def test_unknown_usage_retains_valid_scores_and_only_a_known_subtotal(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            cost = fixture.audit["costs"]["r2-text-compact-ld"]
            cost.update(
                cost_complete=False, cost_history_complete=True, unknown_usage_calls=1
            )
            fixture.refresh()
            publication = fixture.export()
            compact = next(
                row for row in publication["rounds"] if row["id"] == "auto-r2-compact"
            )
            self.assertEqual(compact["status"], "complete")
            self.assertFalse(compact["accounting"]["cost_complete"])
            self.assertIsNone(compact["accounting"]["total_cost_usd"])
            self.assertEqual(compact["measurements"][0]["conditions"][1]["value"], 0.5)

    def test_incomplete_confirmation_never_turns_missing_metrics_into_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            name = "confirmation-text-challenger-ld"
            fixture.audit["request_response_bindings"][name]["complete"] = False
            fixture.audit["costs"][name].update(
                cost_complete=False, cost_history_complete=False
            )
            fixture.audit["comparisons"].pop("confirmation-text-challenger")
            fixture.refresh()
            publication = fixture.export()
            confirmation = next(
                row for row in publication["rounds"] if row["phase"] == "confirmation"
            )
            self.assertEqual(confirmation["status"], "incomplete")
            measurement = next(
                row
                for row in confirmation["measurements"]
                if row["metric"] == "direct_id_agreement" and row["n"] == 6
            )
            self.assertEqual(measurement["conditions"][0]["value"], 0.5)
            for key in ["value", "llm_coverage", "ld_coverage", "both_other"]:
                self.assertIsNone(measurement["conditions"][1][key])
            self.assertIsNone(confirmation["accounting"]["total_cost_usd"])

    def test_stale_calibration_group_value_is_withheld_for_an_incomplete_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            name = "r1-short-o0-ld"
            fixture.audit["request_response_bindings"][name]["complete"] = False
            fixture.audit["costs"][name].update(
                cost_complete=False, cost_history_complete=False
            )
            fixture.audit["comparisons"].pop("r1-short-o0")
            fixture.refresh()
            publication = fixture.export()
            row = next(
                row for row in publication["rounds"] if row["id"] == "auto-r1-short"
            )
            self.assertEqual(row["status"], "incomplete")
            self.assertEqual(row["measurements"][0]["n"], 8)
            self.assertEqual(row["measurements"][0]["conditions"][0]["value"], 1.0)
            self.assertIsNone(row["measurements"][0]["conditions"][1]["value"])

    def test_bad_archive_anchor_and_raw_or_readable_tampering_fail_before_output(self):
        for corruption in ["anchor", "raw", "readable"]:
            with self.subTest(
                corruption=corruption
            ), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                if corruption == "anchor":
                    fixture.anchor = "0" * 64
                elif corruption == "raw":
                    path = fixture.run / "selection/selection.json"
                    path.write_bytes(path.read_bytes() + b"\n")
                else:
                    path = fixture.out / "readable/selection/selection.json"
                    path.write_bytes(path.read_bytes() + b"\n")
                with self.assertRaises(ValueError):
                    fixture.export()
                self.assertFalse(fixture.output.exists())

    def test_selection_metrics_must_match_the_audited_design_not_a_stale_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.selection["modalities"]["text"]["ranking"][0]["metrics"] = (
                copy.deepcopy(fixture.metrics["r2-text-compact"])
            )
            fixture.selection["modalities"]["text"]["ranking"][0]["metrics"][
                "direct_agreement"
            ] = 1.0
            fixture.refresh()
            with self.assertRaisesRegex(ValueError, "candidate differs"):
                fixture.export()
            self.assertFalse(fixture.output.exists())

    def test_adoption_cannot_flip_when_audited_candidates_are_ineligible(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            selected = fixture.selection["modalities"]["text"]
            selected.update(status="ADOPTED", adopted="compact")
            fixture.refresh()
            with self.assertRaisesRegex(ValueError, "selection eligibility"):
                fixture.export()
            self.assertFalse(fixture.output.exists())

    def test_eligible_audited_adoption_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            selected = fixture.selection["modalities"]["text"]
            metrics = score(4, 1.0)
            fixture.metrics["r2-text-compact"] = metrics
            selected["ranking"][0].update(
                metrics=metrics,
                eligible=True,
                checks=dict(
                    named_improved=True,
                    direct_retained=True,
                    reference_coverage_retained=True,
                    candidate_coverage_retained=True,
                ),
            )
            selected.update(status="ADOPTED", adopted="compact")
            fixture.refresh()
            publication = fixture.export()
            confirmation = next(
                row for row in publication["rounds"] if row["phase"] == "confirmation"
            )
            self.assertIn(
                "Text selection: ADOPTED; adopted: compact", confirmation["decision"]
            )

    def test_exact_development_tie_keeps_registered_compact_preference(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            selected = fixture.selection["modalities"]["text"]
            metrics = copy.deepcopy(fixture.metrics["r2-text-compact"])
            fixture.metrics["r3-text-boundary"] = metrics
            selected["ranking"][1].update(
                metrics=metrics,
                checks=copy.deepcopy(selected["ranking"][0]["checks"]),
            )
            selected["ranking"].reverse()
            selected["challenger"] = "boundary"
            fixture.refresh()
            with self.assertRaisesRegex(ValueError, "selection eligibility/ranking"):
                fixture.export()
            self.assertFalse(fixture.output.exists())

    def test_anchored_review_preserves_examples_and_enriches_only_forward_source_pins(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.add_review()
            publication = fixture.export("report/review-publication.json")
            expected = copy.deepcopy(fixture.review)
            expected["source"].update(commit="b" * 40, manifest_sha256=fixture.anchor)
            self.assertEqual(publication["review"], expected)
            self.assertIsNone(
                json.loads(
                    (fixture.run / "report/review-publication.json").read_bytes()
                )["source"]["commit"]
            )
            self.assertIn(
                "sealed evidence", " ".join(publication["rounds"][-1]["limits"])
            )

    def test_review_forward_pins_and_unanchored_provenance_are_rejected(self):
        for mutation in ["commit", "manifest_sha256", "repository", "provenance"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                fixture.add_review()
                if mutation == "provenance":
                    fixture.review["provenance_files"]["qualitative/review.json"] = (
                        "0" * 64
                    )
                else:
                    fixture.review["source"][mutation] = "contradictory-forward-pin"
                write(fixture.run / "report/review-publication.json", fixture.review)
                fixture.refresh()
                with self.assertRaisesRegex(ValueError, "review (source|provenance)"):
                    fixture.export("report/review-publication.json")
                self.assertFalse(fixture.output.exists())

    def test_analysis_dependency_audit_and_existing_output_are_not_silently_replaced(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            calibration = json.loads(
                (fixture.run / "analysis/calibration-analysis.json").read_bytes()
            )
            calibration["audit_sha256"] = "0" * 64
            write(fixture.run / "analysis/calibration-analysis.json", calibration)
            fixture.audit["evidence_files"]["analysis/calibration-analysis.json"] = sha(
                fixture.run / "analysis/calibration-analysis.json"
            )
            write(
                fixture.run / "validation/final-independent-audit.json", fixture.audit
            )
            shutil.rmtree(fixture.out)
            fixture.pack()
            with self.assertRaisesRegex(ValueError, "dependency audit"):
                fixture.export()
            fixture.output.write_bytes(b"preserve existing output")
            with self.assertRaisesRegex(ValueError, "fresh"):
                fixture.export()
            self.assertEqual(fixture.output.read_bytes(), b"preserve existing output")
