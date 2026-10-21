import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    path = ROOT / "scripts" / (name + ".py")
    result = types.ModuleType(name)
    result.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


exporter = module("export_guided_diagnostics")
verify = module("verify_guided_agreement")
CATALOG = [
    {"id": 1, "name": "One", "description": "First"},
    {"id": 2, "name": "Two", "description": "Second"},
]
STAGES = ("catalog", "controlled", "repeat", "review", "diagnostics")


class Fixture:
    def __init__(self, root):
        self.root = root
        self.audit = {
            "schema_version": 1,
            "status": "verified_with_incomplete_review",
            "evidence_files": {},
            "analysis": {"modalities": []},
            "diagnostics": {},
            "costs": {},
            "cost_summary": {
                "known_cost_usd": "0.780000",
                "total_cost_usd": None,
                "cost_complete": False,
                "by_stage": {},
            },
        }
        for stage, dollars in zip(
            STAGES, ["0.1000", "0.2000", "0.0300", "0.4000", "0.0500"]
        ):
            complete = stage != "review"
            self.audit["cost_summary"]["by_stage"][stage] = {
                "calls": 2,
                "known_cost_usd": dollars,
                "cost_complete": complete,
                "unknown_usage_calls": 0,
                "unknown_pricing_calls": 0,
            }
            self.audit["costs"][stage + "/synthetic"] = {
                "calls": 2,
                "known_cost_usd": dollars,
                "cost_complete": complete,
                "retry_attempts": 1,
                "error_calls": 1,
                "raw_refusal_attempts": 1,
                "unknown_usage_calls": 0,
                "unknown_pricing_calls": 0,
            }
        for modality, full_count, n in [("text", 1000, 100), ("images", 100, 25)]:
            catalog_hash = self.raw(
                f"catalog/{modality}-guided.json",
                {"catalog": CATALOG, "status": "complete", "error": None},
            )
            ids = [f"{modality}-{i * 3}" for i in range(n)]
            primary = {}
            hashes = {"catalog": catalog_hash}
            for mode, pattern in [("llm", [1, 1, None]), ("ld", [1, None, None])]:
                selected = {point: pattern[i % 3] for i, point in enumerate(ids)}
                rows = [
                    self.row(f"{modality}-{i}", selected.get(f"{modality}-{i}", 2))
                    for i in range(full_count)
                ]
                primary[mode] = [self.row(point, selected[point]) for point in ids]
                artifact = self.artifact(
                    rows, modality, mode, "classify", catalog_hash, 8, False
                )
                hashes["baseline" if mode == "llm" else "candidate"] = self.raw(
                    f"controlled/{modality}-guided-{mode}.json", artifact
                )
            self.audit["analysis"]["modalities"].append(
                {"modality": modality, "guided": {"artifact_sha256": hashes}}
            )
            for policy in ["reverse", "one-page"]:
                for mode, pattern in [("llm", [None, None, 2]), ("ld", [1, None, 2])]:
                    rows = [
                        self.row(point, pattern[i % 3]) for i, point in enumerate(ids)
                    ]
                    name = f"{modality}-guided-{mode}-{policy}"
                    artifact = self.artifact(
                        rows,
                        modality,
                        mode,
                        "diagnostic",
                        catalog_hash,
                        16 if policy == "one-page" else 8,
                        policy == "reverse",
                    )
                    artifact["metadata"]["reference_sha256"] = hashes[
                        "baseline" if mode == "llm" else "candidate"
                    ]
                    digest = self.raw(f"diagnostics/{name}.json", artifact)
                    self.audit["diagnostics"][name] = {
                        "artifact_sha256": digest,
                        "comparison_to_primary_subset": verify.compare_assignments(
                            primary[mode], rows, CATALOG
                        ),
                        "effective_request_policy": {
                            "k": 16 if policy == "one-page" else 8,
                            "reverse_order": policy == "reverse",
                        },
                        "same_effective_page_content_as_primary": policy == "one-page",
                    }
        self.save()

    @staticmethod
    def row(point, choice):
        return {"id": point, "cluster_id": choice, "refused": False, "label": None}

    @staticmethod
    def artifact(rows, modality, mode, stage, catalog_hash, k, reverse):
        return {
            "schema_version": 1,
            "status": "complete",
            "error": None,
            "processed_count": len(rows),
            "expected_count": len(rows),
            "assignments": rows,
            "metadata": {
                "modality": modality,
                "condition": "guided",
                "mode": mode,
                "stage": stage,
                "k": k,
                "reverse_catalog_order": reverse,
                "catalog_sha256": catalog_hash,
            },
            "measurement": {
                "calls": len(rows),
                "cost_complete": True,
                "timing_complete": True,
                "cost_usd": 0,
                "wall_seconds": 0,
                "error_calls": 0,
                "unknown_usage_calls": 0,
                "unknown_pricing_calls": 0,
                "assignment_refusal_calls": 0,
            },
        }

    def raw(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(value).encode()
        path.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        self.audit["evidence_files"][name] = {"bytes": len(body), "sha256": digest}
        return digest

    def save(self):
        self.path = self.root / "independent-audit.json"
        self.path.write_text(json.dumps(self.audit))

    def export(self):
        return exporter.export_diagnostics(
            self.root, self.path, self.root / "diagnostics-publication.json"
        )


class DiagnosticsExportTests(unittest.TestCase):
    def test_variant_agreement_and_own_backend_stability_have_distinct_orientation(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            result = fixture.export()
            text = result["modalities"][0]
            self.assertEqual(text["n"], 100)
            self.assertEqual(text["primary_subset"]["direct_agreement_count"], 67)
            reverse = text["variants"][0]
            self.assertEqual(reverse["comparison"]["direct_agreement_count"], 66)
            self.assertEqual(reverse["comparison"]["named_id_agreement_count"], 33)
            self.assertEqual(reverse["llm_stability"]["reference_assigned_count"], 67)
            self.assertEqual(reverse["llm_stability"]["candidate_assigned_count"], 33)
            self.assertEqual(
                reverse["llm_stability"]["assigned_other"][
                    "reference_named_candidate_other"
                ],
                67,
            )
            self.assertEqual(reverse["ld_stability"]["direct_agreement_count"], 67)
            self.assertEqual(
                result["audit_sha256"],
                hashlib.sha256(fixture.path.read_bytes()).hexdigest(),
            )
            self.assertNotIn("source", result)

    def test_incomplete_cost_and_exact_decimal_strings_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            result = Fixture(Path(directory)).export()
            accounting = result["accounting"]
            self.assertIsNone(accounting["total_cost_usd"])
            self.assertEqual(accounting["known_cost_usd"], "0.780000")
            self.assertFalse(accounting["cost_complete"])
            self.assertEqual(accounting["stages"][3]["known_cost_usd"], "0.4000")
            self.assertEqual(accounting["stages"][3]["refusal_attempts"], 1)
            self.assertFalse(accounting["stages"][3]["cost_complete"])

    def test_foreign_diagnostic_id_fails_even_with_updated_audit_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            name = "diagnostics/text-guided-ld-one-page.json"
            value = json.loads((fixture.root / name).read_bytes())
            value["assignments"][0]["id"] = "foreign"
            fixture.audit["diagnostics"]["text-guided-ld-one-page"][
                "artifact_sha256"
            ] = fixture.raw(name, value)
            fixture.save()
            with self.assertRaisesRegex(ValueError, "ID|order|subset"):
                fixture.export()

    def test_raw_hash_change_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            path = fixture.root / "controlled/text-guided-llm.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "hash|bytes"):
                fixture.export()
            self.assertFalse((fixture.root / "diagnostics-publication.json").exists())

    def test_existing_output_is_preserved_and_unverified_audit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = fixture.root / "diagnostics-publication.json"
            output.write_text("keep")
            with self.assertRaisesRegex(ValueError, "fresh"):
                fixture.export()
            self.assertEqual(output.read_text(), "keep")
            output.unlink()
            fixture.audit["status"] = "running"
            fixture.save()
            with self.assertRaisesRegex(ValueError, "verified"):
                fixture.export()


if __name__ == "__main__":
    unittest.main()
