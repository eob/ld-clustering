"""Synthetic sealed reviews only; no actual confirmation outcomes or model calls."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_auto_research_review.py"
exporter = types.ModuleType("export_auto_research_review")
exporter.__file__ = str(SCRIPT)
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), "exec"), exporter.__dict__)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def rank(modality, stratum, point):
    return hashlib.sha256(
        (
            "auto-research-review-v1\0"
            + "2043\0confirmation\0"
            + modality
            + "\0"
            + stratum
            + "\0"
            + point
        ).encode()
    ).digest()


def fake_jpeg(width=800, height=600):
    return (
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )


class Fixture:
    def __init__(self, root):
        self.run, self.data, self.assets = root / "run", root / "data", root / "assets"
        self.run.mkdir()
        self.data.mkdir()
        self.output = self.run / "report/review-publication.json"
        self.source = dict(
            commit="a" * 40,
            executable_sha256="b" * 64,
            committed_sources_verified=True,
            embedded_file_sha256={"src/auto_research.rs": "c" * 64},
        )
        self.audit = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            status="verified",
            source=self.source,
            comparisons={},
            request_response_bindings={},
            evidence_files={},
        )
        self.selected = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            frozen_at_utc="2026-10-21T01:00:00Z",
            modalities={},
        )
        self.curation = dict(
            schema_version=1,
            selection_note="Synthetic explicitly selected illustrations, not an accuracy sample.",
            asset_url_prefix="/goofing/ld-clustering/auto-research",
            cases=[],
        )
        self.protocol = dict(
            schema_version=1,
            experiment="guidance-auto-research",
            data=dict(
                partitions=dict(
                    confirmation={
                        modality: dict(count=2) for modality in ["text", "images"]
                    }
                )
            ),
        )
        write(self.run / "preregistration/protocol.json", self.protocol)
        self.audit["protocol_sha256"] = sha(
            (self.run / "preregistration/protocol.json").read_bytes()
        )
        self.selected["protocol_sha256"] = self.audit["protocol_sha256"]
        self.instruction = "Synthetic instruction: evaluate visible evidence against each own catalog.\n"
        (self.run / "prompts").mkdir()
        (self.run / "prompts/blinded-review.md").write_text(self.instruction)
        self.protocol["fixed_fixture_sha256"] = {
            "prompts/blinded-review.md": sha(self.instruction.encode())
        }
        write(self.run / "preregistration/protocol.json", self.protocol)
        self.audit["protocol_sha256"] = sha(
            (self.run / "preregistration/protocol.json").read_bytes()
        )
        self.selected["protocol_sha256"] = self.audit["protocol_sha256"]
        self.photo = dict(
            supplied_sha256=sha(fake_jpeg()),
            source_sha256=sha(fake_jpeg()),
            supplied_width=800,
            supplied_height=600,
            native_width=1600,
            native_height=1200,
            inspection="natural_color_photograph",
            transform="Exact supplied JPEG; no crop, resize or re-encoding.",
            archived_source_file="sources/photo.jpg",
            metadata=dict(
                Author="Synthetic Author",
                AuthorProfileURL="https://example.com/author",
                OriginalLandingURL="https://example.com/photo",
                License="https://creativecommons.org/licenses/by/2.0/",
                Title="Synthetic photo credit only",
            ),
        )
        self.dataset = dict(
            schema_version=3,
            experiment="guidance-auto-research",
            photos={"images-0": self.photo, "images-1": copy.deepcopy(self.photo)},
            partitions=dict(confirmation={}),
        )
        for modality in ["text", "images"]:
            rows = [
                dict(
                    id=f"{modality}-{i}",
                    text=(
                        "Photograph."
                        if modality == "images"
                        else f"Literal synthetic request {i}."
                    ),
                    image=(
                        f"../images/{modality}-{i}.jpg"
                        if modality == "images"
                        else None
                    ),
                    label="HIDDEN_SOURCE_LABEL",
                )
                for i in range(2)
            ]
            raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
            for base, relative in [
                (self.run, f"inputs/confirmation/{modality}.jsonl"),
                (self.data, f"confirmation/{modality}.jsonl"),
            ]:
                (base / relative).parent.mkdir(parents=True, exist_ok=True)
                (base / relative).write_bytes(raw)
            self.dataset["partitions"]["confirmation"][modality] = dict(
                file=f"confirmation/{modality}.jsonl",
                count=2,
                ordered_ids=[row["id"] for row in rows],
                jsonl_sha256=sha(raw),
            )
            if modality == "images":
                for i in range(2):
                    for path in [
                        self.run / f"inputs/images/images-{i}.jpg",
                        self.data / f"images/images-{i}.jpg",
                        self.data / "sources/photo.jpg",
                    ]:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(fake_jpeg())
            catalogs = {}
            for variant in ["baseline", "challenger"]:
                definitions = [
                    dict(
                        id=1,
                        name="Group One",
                        description=f"Synthetic {variant} scope one.",
                    ),
                    dict(
                        id=2,
                        name="Group Two",
                        description=f"Synthetic {variant} scope two.",
                    ),
                ]
                design = dict(
                    schema_version=1,
                    modality=modality,
                    task="Synthetic subject classification.",
                    definitions=definitions,
                    provenance=dict(evidence_ids=["discovery-only"]),
                )
                path = f"catalogs/{variant}-{modality}.json"
                write(self.run / path, design)
                catalogs[variant] = definitions
                for mode in ["llm", "ld"]:
                    stem = f"confirmation-{modality}-{variant}"
                    choices = (
                        [1 if mode == "llm" else 2, None]
                        if modality == "text"
                        else [None if variant == "baseline" or mode == "ld" else 1, 2]
                    )
                    assignments = [
                        dict(
                            id=row["id"],
                            cluster_id=choice,
                            refused=False,
                            label="HIDDEN_SOURCE_LABEL",
                        )
                        for row, choice in zip(rows, choices)
                    ]
                    write(
                        self.run / f"confirmation/{stem}-{mode}.json",
                        dict(
                            schema_version=1,
                            status="complete",
                            error=None,
                            processed_count=2,
                            expected_count=2,
                            metadata=dict(
                                experiment="guidance-auto-research",
                                stage="confirmation",
                                modality=modality,
                                mode=mode,
                                source=self.source,
                                protocol_sha256=self.audit["protocol_sha256"],
                                catalog_sha256=sha((self.run / path).read_bytes()),
                                definitions=definitions,
                                task=design["task"],
                                ordered_ids=[row["id"] for row in rows],
                                expected_count=2,
                                input_jsonl_sha256=sha(raw),
                            ),
                            assignments=assignments,
                        ),
                    )
                    self.audit["request_response_bindings"][stem + "-" + mode] = dict(
                        complete=True, expected_count=2, processed_count=2
                    )
                self.audit["comparisons"][f"confirmation-{modality}-{variant}"] = dict(
                    n=2
                )
            self.selected["modalities"][modality] = dict(
                status="NOT_ADOPTED",
                adopted="baseline",
                challenger="compact",
                original_catalog=dict(
                    path=f"catalogs/baseline-{modality}.json",
                    sha256=sha(
                        (self.run / f"catalogs/baseline-{modality}.json").read_bytes()
                    ),
                ),
                challenger_catalog=dict(
                    path=f"catalogs/challenger-{modality}.json",
                    sha256=sha(
                        (self.run / f"catalogs/challenger-{modality}.json").read_bytes()
                    ),
                ),
            )
            cases, keys, judgments = [], [], []
            folder = self.run / f"qualitative/confirmation/{modality}"
            for row in rows:
                point = row["id"]
                cid = rank(modality, "case", point).hex()[:24]
                case = dict(
                    case_id=cid,
                    text=row["text"],
                    catalog=catalogs["challenger"],
                    pairs=[],
                )
                key = dict(case_id=cid, item_id=point, stratum="synthetic", pairs=[])
                judgment = dict(case_id=cid, pairs=[])
                if modality == "images":
                    path = f"qualitative/confirmation/images/images/{cid}.jpg"
                    (self.run / path).parent.mkdir(parents=True, exist_ok=True)
                    (self.run / path).write_bytes(fake_jpeg())
                    case.update(image=path, image_sha256=sha(fake_jpeg()))
                for index, (role, variant) in enumerate(
                    [("challenger-pair", "challenger"), ("original-pair", "baseline")],
                    1,
                ):
                    swap = rank(modality, "blind:" + role, point)[0] >= 128
                    mapping = dict(A="ld" if swap else "llm", B="llm" if swap else "ld")
                    choices = {}
                    for label, mode in mapping.items():
                        arm = json.loads(
                            (
                                self.run
                                / f"confirmation/confirmation-{modality}-{variant}-{mode}.json"
                            ).read_bytes()
                        )
                        choices[label] = next(
                            record["cluster_id"]
                            for record in arm["assignments"]
                            if record["id"] == point
                        )
                    case["pairs"].append(
                        dict(
                            pair_id=index,
                            catalog=catalogs[variant],
                            assignments=choices,
                        )
                    )
                    key["pairs"].append(dict(role=role, **mapping))
                    judgment["pairs"].append(
                        dict(
                            pair_id=index,
                            assignments={
                                label: dict(
                                    fit="plausible",
                                    evidence="Literal synthetic visible evidence.",
                                    severity="minor",
                                )
                                for label in ["A", "B"]
                            },
                            verdict="both_reasonable",
                            themes=["reasonable boundary"],
                            boundary_note="Synthetic granularity uncertainty.",
                        )
                    )
                cases.append(case)
                keys.append(key)
                judgments.append(judgment)
            write(
                folder / "packet.json",
                dict(
                    schema_version=1,
                    phase="confirmation",
                    modality=modality,
                    instruction=self.instruction,
                    cases=cases,
                ),
            )
            write(
                folder / "key.json",
                dict(
                    schema_version=1,
                    phase="confirmation",
                    modality=modality,
                    counts={},
                    keys=keys,
                    audit_comparison=f"confirmation-{modality}-challenger",
                ),
            )
            write(
                folder / "judgments.json",
                dict(
                    schema_version=1,
                    phase="confirmation",
                    modality=modality,
                    packet_sha256=sha((folder / "packet.json").read_bytes()),
                    reviewer=dict(
                        kind="coding harness",
                        model="unknown",
                        compute_accounting="Outside API ledger.",
                    ),
                    judgments=judgments,
                    failed=[],
                ),
            )
            self.seal(modality)
            self.curation["cases"].append(
                dict(
                    modality=modality,
                    case_id=cases[0]["case_id"],
                    summary="Synthetic illustration; either assignment may be reasonable.",
                    **(
                        dict(alt="Literal synthetic visible evidence.")
                        if modality == "images"
                        else {}
                    ),
                )
            )
        write(self.data / "manifest.json", self.dataset)
        write(self.run / "preregistration/dataset-manifest.json", self.dataset)
        self.audit["dataset_manifest_sha256"] = sha(
            (self.data / "manifest.json").read_bytes()
        )
        self.selected["dataset_manifest_sha256"] = self.audit["dataset_manifest_sha256"]
        self.refresh()

    def seal(self, modality):
        folder = self.run / f"qualitative/confirmation/{modality}"
        custom_path = folder / "reviewer-instructions.md"
        if not custom_path.exists():
            custom_path.write_text(
                "Synthetic frozen harness instructions and output schema, distinct from base prompt.\n"
            )
        write(
            folder / "review-registration.json",
            dict(
                phase="confirmation",
                modality=modality,
                registered_at_utc="2026-10-21T01:30:00Z",
                packet_sha256=sha((folder / "packet.json").read_bytes()),
                instructions_sha256=sha(custom_path.read_bytes()),
                expected_cases=2,
                reviewer_compute="Outside API ledger.",
            ),
        )
        packet = json.loads((folder / "packet.json").read_bytes())
        judgments = json.loads((folder / "judgments.json").read_bytes())
        judgments["packet_sha256"] = sha((folder / "packet.json").read_bytes())
        write(folder / "judgments.json", judgments)
        accepted = {row["case_id"] for row in judgments["judgments"]}
        failed = {row["case_id"] for row in judgments["failed"]}
        missing = sorted(
            {row["case_id"] for row in packet["cases"]} - accepted - failed
        )
        write(
            folder / "review-seal.json",
            dict(
                schema_version=1,
                phase="confirmation",
                modality=modality,
                sealed_at_utc="2026-10-21T02:00:00Z",
                packet_sha256=sha((folder / "packet.json").read_bytes()),
                judgments_sha256=sha((folder / "judgments.json").read_bytes()),
                reviewer_instructions_sha256=sha(custom_path.read_bytes()),
                expected_count=len(packet["cases"]),
                accepted_count=len(accepted),
                failed_count=len(failed),
                not_attempted_count=len(missing),
                not_attempted_case_ids=missing,
                blinding="Synthetic sealed before unblinding.",
            ),
        )
        write(
            folder / "unblinding.json",
            dict(
                unblinded_at_utc="2026-10-21T03:00:00Z",
                review_seal_sha256=sha((folder / "review-seal.json").read_bytes()),
                key_sha256=sha((folder / "key.json").read_bytes()),
            ),
        )

    def refresh(self):
        write(self.run / "selection/selection.json", self.selected)
        write(self.run / "report/review-selection.json", self.curation)
        self.audit["evidence_files"] = {
            path.relative_to(self.run).as_posix(): sha(path.read_bytes())
            for path in self.run.rglob("*")
            if path.is_file() and path.name != "final-independent-audit.json"
        }
        write(self.run / "validation/final-independent-audit.json", self.audit)

    def export(self):
        return exporter.export_review(
            self.run,
            self.run / "validation/final-independent-audit.json",
            self.run / "selection/selection.json",
            self.run / "report/review-selection.json",
            self.data,
            self.assets,
            self.output,
        )

    def change(self, relative, change, seal=None):
        path = self.run / relative
        value = json.loads(path.read_bytes())
        change(value)
        write(path, value)
        if seal:
            self.seal(seal)
        self.refresh()

    def change_photo(self, change):
        change(self.photo)
        write(self.data / "manifest.json", self.dataset)
        write(self.run / "preregistration/dataset-manifest.json", self.dataset)
        self.audit["dataset_manifest_sha256"] = sha(
            (self.data / "manifest.json").read_bytes()
        )
        self.selected["dataset_manifest_sha256"] = self.audit["dataset_manifest_sha256"]
        self.refresh()


class ReviewExportTests(unittest.TestCase):
    def assert_clean_rejection(self, fixture, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            fixture.export()
        self.assertFalse(fixture.output.exists())
        self.assertFalse(fixture.assets.exists())

    def test_sealed_own_catalog_choices_and_literal_judgments_copy_without_truth_claims(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            result = fixture.export()
            self.assertEqual(len(result["examples"]), 2)
            self.assertIsNone(result["source"]["commit"])
            self.assertIsNone(result["source"]["manifest_sha256"])
            self.assertEqual(
                result["reviewer"], "unknown (coding harness; outside API ledger)"
            )
            text, image = result["examples"]
            self.assertEqual(text["text"], "Literal synthetic request 0.")
            self.assertEqual(
                {(r["design"], r["backend"]) for r in text["assignments"]},
                {
                    (d, b)
                    for d in ["Original", "Challenger"]
                    for b in ["Sol", "Decisions"]
                },
            )
            self.assertTrue(
                all(
                    r["fit"] == "plausible"
                    and r["severity"] == "minor"
                    and r["evidence"] == "Literal synthetic visible evidence."
                    for r in text["assignments"]
                )
            )
            self.assertEqual(
                {
                    (row["pair_id"], row["anonymous_label"])
                    for row in text["assignments"]
                },
                {(pair, label) for pair in (1, 2) for label in ("A", "B")},
            )
            self.assertEqual(
                image["image"]["alt"], "Literal synthetic visible evidence."
            )
            self.assertEqual(
                (image["image"]["width"], image["image"]["height"]), (800, 600)
            )
            self.assertEqual(
                (fixture.assets / Path(image["image"]["src"]).name).read_bytes(),
                fake_jpeg(),
            )
            self.assertTrue(
                any(
                    r["category"] == "Other" and r["fit"] == "plausible"
                    for r in image["assignments"]
                )
            )
            self.assertNotIn("HIDDEN_SOURCE_LABEL", json.dumps(result))
            self.assertIn(
                "Synthetic Author", (fixture.assets / "ATTRIBUTION.txt").read_text()
            )
            self.assertEqual(json.loads(fixture.output.read_bytes()), result)

    def test_literal_pair_notes_and_all_required_raw_provenance_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            result = fixture.export()
            raw = json.loads(
                (
                    fixture.run / "qualitative/confirmation/text/judgments.json"
                ).read_bytes()
            )
            for shown, original in zip(
                result["examples"][0]["pair_reviews"], raw["judgments"][0]["pairs"]
            ):
                for key in ["verdict", "themes", "boundary_note"]:
                    self.assertEqual(shown[key], original[key])
            for name in [
                "validation/final-independent-audit.json",
                "selection/selection.json",
                "report/review-selection.json",
                "preregistration/dataset-manifest.json",
                "qualitative/confirmation/images/review-seal.json",
                "qualitative/confirmation/images/review-registration.json",
                "qualitative/confirmation/images/reviewer-instructions.md",
                "prompts/blinded-review.md",
                "qualitative/confirmation/images/unblinding.json",
                "qualitative/confirmation/images/packet.json",
                "qualitative/confirmation/images/key.json",
                "qualitative/confirmation/images/judgments.json",
                "confirmation/confirmation-text-baseline-llm.json",
                "catalogs/challenger-images.json",
            ]:
                self.assertEqual(
                    result["provenance_files"][name],
                    sha((fixture.run / name).read_bytes()),
                )

    def test_post_seal_packet_or_judgment_changes_cannot_be_published(self):
        for artifact in ["packet", "judgments"]:
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                path = fixture.run / f"qualitative/confirmation/text/{artifact}.json"
                path.write_bytes(path.read_bytes() + b"\n")
                fixture.refresh()
                self.assert_clean_rejection(
                    fixture, "sealed review packet/judgments hash"
                )

    def test_unblinding_requires_unchanged_seal_key_and_recorded_chronology(self):
        for field, value in [
            ("review_seal_sha256", "0" * 64),
            ("key_sha256", "0" * 64),
            ("unblinded_at_utc", "2026-10-21T01:59:59Z"),
        ]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                fixture.change(
                    "qualitative/confirmation/text/unblinding.json",
                    lambda row: row.update({field: value}),
                )
                self.assert_clean_rejection(fixture, "unblinding (receipt|chronology)")

    def test_resealed_key_swap_still_fails_canonical_blinding(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))

            def swap(value):
                pair = value["keys"][0]["pairs"][0]
                pair["A"], pair["B"] = pair["B"], pair["A"]

            fixture.change("qualitative/confirmation/text/key.json", swap, seal="text")
            self.assert_clean_rejection(fixture, "canonical blind mapping")

    def test_custom_review_registration_binds_packet_instructions_and_preseal_time(
        self,
    ):
        for field, value in [
            ("packet_sha256", "0" * 64),
            ("instructions_sha256", "0" * 64),
            ("expected_cases", 99),
            ("registered_at_utc", "2026-10-21T02:01:00Z"),
        ]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                fixture.change(
                    "qualitative/confirmation/text/review-registration.json",
                    lambda row: row.update({field: value}),
                )
                self.assert_clean_rejection(
                    fixture, "registered custom|unblinding chronology"
                )

    def test_false_review_denominators_and_identity_leaks_are_rejected_after_resealing(
        self,
    ):
        for mutation in ["denominator", "identity"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                if mutation == "denominator":
                    fixture.change(
                        "qualitative/confirmation/text/review-seal.json",
                        lambda row: row.update(accepted_count=99),
                    )
                    receipt = json.loads(
                        (
                            fixture.run
                            / "qualitative/confirmation/text/unblinding.json"
                        ).read_bytes()
                    )
                    receipt["review_seal_sha256"] = sha(
                        (
                            fixture.run
                            / "qualitative/confirmation/text/review-seal.json"
                        ).read_bytes()
                    )
                    write(
                        fixture.run / "qualitative/confirmation/text/unblinding.json",
                        receipt,
                    )
                    fixture.refresh()
                else:
                    fixture.change(
                        "qualitative/confirmation/text/packet.json",
                        lambda row: row["cases"][0]["pairs"][0].update(backend="Sol"),
                        seal="text",
                    )
                self.assert_clean_rejection(
                    fixture, "denominators|canonical blind mapping"
                )

    def test_resealed_packet_choice_must_match_actual_audited_assignment(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))

            def change_choice(value):
                pair = value["cases"][0]["pairs"][0]
                pair["assignments"]["A"] = 2 if pair["assignments"]["A"] == 1 else 1

            fixture.change(
                "qualitative/confirmation/text/packet.json", change_choice, seal="text"
            )
            self.assert_clean_rejection(fixture, "actual audited assignments")

    def test_whole_own_catalog_description_is_checked_even_when_id_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.change(
                "qualitative/confirmation/text/packet.json",
                lambda row: row["cases"][0]["pairs"][1]["catalog"][0].update(
                    description="Changed scope under same ID."
                ),
                seal="text",
            )
            self.assert_clean_rejection(fixture, "own full catalog")

    def test_partial_or_unaudited_raw_arm_never_supplies_examples(self):
        for mutation in ["partial", "raw"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                if mutation == "partial":
                    fixture.audit["request_response_bindings"][
                        "confirmation-text-baseline-ld"
                    ]["complete"] = False
                    fixture.refresh()
                else:
                    path = (
                        fixture.run / "confirmation/confirmation-text-baseline-ld.json"
                    )
                    path.write_bytes(path.read_bytes() + b"\n")
                self.assert_clean_rejection(
                    fixture, "incomplete audited|raw bytes differ"
                )

    def test_failed_unselected_case_stays_failed_without_invalidating_accepted_examples(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))

            def fail_second(value):
                failed = value["judgments"].pop()
                value["failed"].append(
                    dict(
                        case_id=failed["case_id"],
                        error="Synthetic parser failure; no rerun.",
                    )
                )

            fixture.change(
                "qualitative/confirmation/text/judgments.json", fail_second, seal="text"
            )
            result = fixture.export()
            self.assertEqual(
                result["review_accounting"]["text"],
                dict(
                    expected_count=2,
                    accepted_count=1,
                    failed_count=1,
                    not_attempted_count=0,
                ),
            )

    def test_uncurated_sealed_modality_keeps_all_review_failure_denominators(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.curation["cases"] = fixture.curation["cases"][:1]

            def fail_second(value):
                failed = value["judgments"].pop()
                value["failed"].append(
                    dict(
                        case_id=failed["case_id"],
                        error="Synthetic failed uncurated image review.",
                    )
                )

            fixture.change(
                "qualitative/confirmation/images/judgments.json",
                fail_second,
                seal="images",
            )
            result = fixture.export()
            self.assertEqual(len(result["examples"]), 1)
            self.assertEqual(
                result["review_accounting"].get("images"),
                dict(
                    expected_count=2,
                    accepted_count=1,
                    failed_count=1,
                    not_attempted_count=0,
                ),
            )

    def test_selected_failed_case_cannot_be_replaced_with_an_unreviewed_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))

            def fail_first(value):
                failed = value["judgments"].pop(0)
                value["failed"].append(
                    dict(case_id=failed["case_id"], error="Synthetic failed review.")
                )

            fixture.change(
                "qualitative/confirmation/text/judgments.json", fail_first, seal="text"
            )
            self.assert_clean_rejection(fixture, "no accepted sealed judgment")

    def test_missing_review_denominators_are_preserved_not_counted_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.change(
                "qualitative/confirmation/text/judgments.json",
                lambda row: row["judgments"].pop(),
                seal="text",
            )
            result = fixture.export()
            self.assertEqual(
                result["review_accounting"]["text"]["not_attempted_count"], 1
            )
            self.assertEqual(result["review_accounting"]["text"]["accepted_count"], 1)

    def test_refusal_remains_other_with_its_point_level_refused_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.change(
                "confirmation/confirmation-images-baseline-llm.json",
                lambda row: row["assignments"][0].update(refused=True),
            )
            result = fixture.export()
            photo = result["examples"][1]
            choice = next(
                row
                for row in photo["assignments"]
                if row["design"] == "Original" and row["backend"] == "Sol"
            )
            self.assertIsNone(choice["cluster_id"])
            self.assertEqual(choice["category"], "Other")
            self.assertTrue(choice["refused"])

    def test_invalid_photo_source_aspect_native_size_or_license_is_rejected(self):
        for mutation in ["source", "aspect", "native", "license"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                if mutation == "source":
                    (fixture.data / "sources/photo.jpg").write_bytes(
                        fake_jpeg() + b"modified"
                    )
                elif mutation == "aspect":
                    fixture.change_photo(
                        lambda row: row.update(native_width=1600, native_height=1600)
                    )
                elif mutation == "native":
                    fixture.change_photo(
                        lambda row: row.update(native_width=400, native_height=300)
                    )
                else:
                    fixture.change_photo(
                        lambda row: row["metadata"].update(
                            License="https://example.com/not-licensed"
                        )
                    )
                self.assert_clean_rejection(fixture, "JPEG|aspect|upscaling|license")

    def test_frozen_prompt_pin_is_required_even_when_prompt_is_not_in_arm_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.audit["evidence_files"].pop("prompts/blinded-review.md")
            write(
                fixture.run / "validation/final-independent-audit.json", fixture.audit
            )
            self.assertEqual(len(fixture.export()["examples"]), 2)

    def test_custom_registered_reviewer_instructions_are_distinct_from_base_prompt(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            folder = fixture.run / "qualitative/confirmation/text"
            custom = b"Synthetic frozen harness instructions and output schema; not the base prompt.\n"
            (folder / "reviewer-instructions.md").write_bytes(custom)
            write(
                folder / "review-registration.json",
                dict(
                    phase="confirmation",
                    modality="text",
                    registered_at_utc="2026-10-21T01:30:00Z",
                    packet_sha256=sha((folder / "packet.json").read_bytes()),
                    instructions_sha256=sha(custom),
                    expected_cases=2,
                    reviewer_compute="Outside API ledger.",
                ),
            )
            seal = json.loads((folder / "review-seal.json").read_bytes())
            seal["reviewer_instructions_sha256"] = sha(custom)
            write(folder / "review-seal.json", seal)
            receipt = json.loads((folder / "unblinding.json").read_bytes())
            receipt["review_seal_sha256"] = sha(
                (folder / "review-seal.json").read_bytes()
            )
            write(folder / "unblinding.json", receipt)
            fixture.refresh()
            self.assertEqual(len(fixture.export()["examples"]), 2)

    def test_optional_seal_registration_hash_binds_exact_bytes_and_keeps_legacy_seals(
        self,
    ):
        for variant in ("legacy", "valid", "extra_metadata", "valid_timestamp"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp:
                fixture = Fixture(Path(temp))
                folder = fixture.run / "qualitative/confirmation/text"
                if variant != "legacy":
                    seal = json.loads((folder / "review-seal.json").read_bytes())
                    seal["reviewer_registration_sha256"] = sha(
                        (folder / "review-registration.json").read_bytes()
                    )
                    write(folder / "review-seal.json", seal)
                    receipt = json.loads((folder / "unblinding.json").read_bytes())
                    receipt["review_seal_sha256"] = sha(
                        (folder / "review-seal.json").read_bytes()
                    )
                    write(folder / "unblinding.json", receipt)
                if variant in ("extra_metadata", "valid_timestamp"):
                    registration = json.loads(
                        (folder / "review-registration.json").read_bytes()
                    )
                    if variant == "extra_metadata":
                        registration["extra_note"] = (
                            "Changed after sealing; semantic packet/instruction fields unchanged."
                        )
                    else:
                        registration["registered_at_utc"] = "2026-10-21T01:31:00Z"
                    write(folder / "review-registration.json", registration)
                fixture.refresh()
                if variant in ("legacy", "valid"):
                    self.assertEqual(len(fixture.export()["examples"]), 2)
                else:
                    self.assert_clean_rejection(
                        fixture, "sealed reviewer registration hash"
                    )

    def test_output_collision_preserves_existing_bytes_and_fresh_asset_write_failure_cleans_up(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            fixture.output.parent.mkdir(parents=True, exist_ok=True)
            fixture.output.write_bytes(b"keep-existing")
            with self.assertRaisesRegex(ValueError, "fresh"):
                fixture.export()
            self.assertEqual(fixture.output.read_bytes(), b"keep-existing")
            self.assertFalse(fixture.assets.exists())
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp))
            original = Path.write_bytes

            def fail_copy(path, body):
                if path.parent == fixture.assets and path.suffix == ".jpg":
                    raise OSError("Synthetic asset-write failure")
                return original(path, body)

            with patch.object(Path, "write_bytes", fail_copy):
                with self.assertRaisesRegex(OSError, "Synthetic asset-write"):
                    fixture.export()
            self.assertFalse(fixture.assets.exists())
            self.assertFalse(fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
