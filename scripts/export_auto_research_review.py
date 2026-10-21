#!/usr/bin/env python3
"""Bind sealed confirmation reviews to audited classifications and copy a gallery.

Offline only. Curation declares selection_note, asset_url_prefix and explicit
cases [{modality, case_id, summary, alt?}]. Sealed judgments are copied verbatim.
Final commit/manifest pins remain null until the separately anchored log export.
"""

import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import types

HELPER = Path(__file__).with_name("export_guided_agreement.py")
images = types.ModuleType("guided_photo_copy")
images.__file__ = str(HELPER)
exec(compile(HELPER.read_bytes(), str(HELPER), "exec"), images.__dict__)
EXPERIMENT = "guidance-auto-research"
REPOSITORY = "https://github.com/eob/ld-clustering"
RUN_PATH = "experiments/2026-10-21-auto-research-seed2043/evidence"
FIT = {"supported", "plausible", "unsupported", "insufficient_evidence"}
VERDICTS = {
    "prefer_a",
    "prefer_b",
    "both_reasonable",
    "neither_fits",
    "insufficient_evidence",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "review timestamps require a timezone")
    return result


def rank(modality, stratum, item_id):
    return hashlib.sha256(
        (
            "auto-research-review-v1\0"
            + "2043\0confirmation\0"
            + modality
            + "\0"
            + stratum
            + "\0"
            + item_id
        ).encode()
    ).digest()


def member(root, name):
    path = Path(name)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    require(path.is_relative_to(root), "review input escapes its evidence root")
    require(path.is_file(), "review input is missing: " + str(path))
    return path


def indexed(rows, key):
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "duplicate review or assignment identity")
    return result


class Review:
    def __init__(self, run_root, audit, selection, report_selection, data_root):
        self.run, self.data = Path(run_root).resolve(), Path(data_root).resolve()
        self.provenance = {}
        self.audit = self.read(audit)
        require(
            self.audit.get("schema_version") == 1
            and self.audit.get("experiment") == EXPERIMENT
            and self.audit.get("status")
            in ("verified", "verified_with_failed_conditions"),
            "final independent audit required",
        )
        self.protocol = self.read("preregistration/protocol.json", audited=True)
        require(
            self.protocol.get("experiment") == EXPERIMENT
            and self.hash("preregistration/protocol.json")
            == self.audit["protocol_sha256"],
            "review protocol differs from final audit",
        )
        self.selection = self.read(selection)
        require(
            self.selection.get("schema_version") == 1
            and self.selection.get("experiment") == EXPERIMENT
            and self.selection["protocol_sha256"] == self.audit["protocol_sha256"]
            and self.selection["dataset_manifest_sha256"]
            == self.audit["dataset_manifest_sha256"],
            "review selection differs from final audit",
        )
        self.curation = self.read(report_selection)
        require(
            self.curation.get("schema_version") == 1
            and nonempty(self.curation.get("selection_note"))
            and isinstance(self.curation.get("cases"), list)
            and 1 <= len(self.curation["cases"]) <= 16,
            "explicit small report selection required",
        )
        prefix = self.curation["asset_url_prefix"]
        require(
            isinstance(prefix, str)
            and prefix.startswith("/")
            and not prefix.startswith("//")
            and ".." not in PurePosixPath(prefix).parts
            and not any(c in prefix for c in ("?", "#", "\\")),
            "invalid photo asset URL prefix",
        )
        self.prefix = prefix.rstrip("/")
        raw = self.bytes("preregistration/dataset-manifest.json", audited=True)
        require(
            sha(raw) == self.audit["dataset_manifest_sha256"]
            and (self.data / "manifest.json").read_bytes() == raw,
            "raw dataset manifest differs from final audit",
        )
        self.dataset = json.loads(raw)
        require(
            self.dataset.get("schema_version") == 3
            and self.dataset.get("experiment") == EXPERIMENT,
            "wrong review dataset",
        )
        self.cache = {}

    def bytes(self, name, audited=False):
        path = member(self.run, name)
        name = path.relative_to(self.run).as_posix()
        body = path.read_bytes()
        digest = sha(body)
        if audited:
            require(
                self.audit["evidence_files"].get(name) == digest,
                "review raw bytes differ from independent audit: " + name,
            )
        require(
            self.provenance.get(name, digest) == digest,
            "review source changed during export",
        )
        self.provenance[name] = digest
        return body

    def read(self, name, audited=False):
        return json.loads(self.bytes(name, audited))

    def hash(self, name):
        return sha(self.bytes(name))

    def catalog(self, modality, variant):
        path = f"catalogs/{variant}-{modality}.json"
        raw = self.bytes(path, audited=True)
        selected = self.selection["modalities"][modality]
        key = "original_catalog" if variant == "baseline" else "challenger_catalog"
        pin = selected[key]
        require(
            member(self.run, pin["path"]) == member(self.run, path)
            and pin["sha256"] == sha(raw),
            "selected own catalog byte pin differs",
        )
        value = json.loads(raw)
        if "design" in value:
            require(
                value.get("experiment") == EXPERIMENT
                and value.get("stage") == "custom_rewrite"
                and value.get("status") == "complete"
                and value.get("error") is None,
                "incomplete selected catalog",
            )
            value = value["design"]
        require(
            value.get("schema_version") == 1
            and value.get("modality") == modality
            and nonempty(value.get("task")),
            "own catalog identity differs",
        )
        definitions = value["definitions"]
        ids = [row["id"] for row in definitions]
        require(
            1 <= len(ids) <= 16
            and all(type(i) is int and i > 0 for i in ids)
            and ids == sorted(set(ids))
            and all(
                set(row) == {"id", "name", "description"}
                and nonempty(row["name"])
                and nonempty(row["description"])
                for row in definitions
            ),
            "invalid canonical own catalog",
        )
        return path, value

    def cohort(self, modality):
        path = f"inputs/confirmation/{modality}.jsonl"
        raw = self.bytes(path, audited=True)
        spec = self.dataset["partitions"]["confirmation"][modality]
        require(
            sha(raw) == spec["jsonl_sha256"]
            and member(self.data, spec["file"]).read_bytes() == raw,
            "review input differs from frozen dataset",
        )
        rows = [json.loads(line) for line in raw.splitlines() if line]
        ids = [row["id"] for row in rows]
        n = self.protocol["data"]["partitions"]["confirmation"][modality]["count"]
        require(
            len(rows) == n == spec["count"] and ids == spec["ordered_ids"],
            "review full cohort denominator/order differs",
        )
        return path, indexed(rows, "id"), ids

    def arms(self, modality, ids):
        result = {}
        for variant in ("challenger", "baseline"):
            catalog_path, catalog = self.catalog(modality, variant)
            definitions = catalog["definitions"]
            allowed = {row["id"] for row in definitions}
            stem = f"confirmation-{modality}-{variant}"
            require(
                self.audit["comparisons"].get(stem, {}).get("n") == len(ids),
                "full audited own-catalog comparison required",
            )
            for mode in ("llm", "ld"):
                name = stem + "-" + mode
                binding = self.audit["request_response_bindings"].get(name, {})
                require(
                    binding.get("complete") is True
                    and binding.get("processed_count")
                    == binding.get("expected_count")
                    == len(ids),
                    "incomplete audited confirmation arm",
                )
                arm = self.read(f"confirmation/{name}.json", audited=True)
                metadata = arm["metadata"]
                records = arm["assignments"]
                require(
                    arm.get("status") == "complete"
                    and arm.get("error") is None
                    and arm["processed_count"] == arm["expected_count"] == len(ids)
                    and [row["id"] for row in records] == ids,
                    "partial or reordered confirmation assignments",
                )
                require(
                    metadata.get("experiment") == EXPERIMENT
                    and metadata.get("stage") == "confirmation"
                    and metadata.get("modality") == modality
                    and metadata.get("mode") == mode
                    and metadata.get("source") == self.audit["source"]
                    and metadata.get("protocol_sha256") == self.audit["protocol_sha256"]
                    and metadata.get("catalog_sha256") == self.hash(catalog_path)
                    and metadata.get("definitions") == definitions
                    and metadata.get("task") == catalog["task"]
                    and metadata.get("ordered_ids") == ids,
                    "confirmation metadata/own catalog differs",
                )
                for row in records:
                    cid = row["cluster_id"]
                    require(
                        (cid is None or type(cid) is int and cid in allowed)
                        and type(row["refused"]) is bool
                        and (not row["refused"] or cid is None),
                        "invalid own-catalog assignment/refusal",
                    )
                result[(variant, mode)] = indexed(records, "id")
            result[(variant, "catalog")] = definitions
        return result

    def review(self, modality):
        if modality in self.cache:
            return self.cache[modality]
        require(modality in ("text", "images"), "unknown review modality")
        folder = f"qualitative/confirmation/{modality}"
        packet = self.read(folder + "/packet.json")
        judgments = self.read(folder + "/judgments.json")
        seal = self.read(folder + "/review-seal.json")
        receipt = self.read(folder + "/unblinding.json")
        registration = self.read(folder + "/review-registration.json")
        for artifact in (packet, judgments, seal):
            require(
                artifact.get("schema_version") == 1
                and artifact.get("phase") == "confirmation"
                and artifact.get("modality") == modality,
                "confirmation review identity differs",
            )
        require(
            seal["packet_sha256"]
            == judgments["packet_sha256"]
            == self.hash(folder + "/packet.json")
            and seal["judgments_sha256"] == self.hash(folder + "/judgments.json"),
            "sealed review packet/judgments hash differs",
        )
        instruction = self.bytes("prompts/blinded-review.md")
        require(
            packet["instruction"].encode() == instruction,
            "packet base reviewer instruction differs",
        )
        require(
            sha(instruction)
            == self.protocol["fixed_fixture_sha256"]["prompts/blinded-review.md"],
            "reviewer instruction differs from frozen protocol",
        )
        custom = self.bytes(folder + "/reviewer-instructions.md")
        require(
            custom.strip()
            and registration.get("phase") == "confirmation"
            and registration.get("modality") == modality
            and registration["packet_sha256"] == self.hash(folder + "/packet.json")
            and registration["expected_cases"] == len(packet["cases"])
            and registration["instructions_sha256"]
            == seal["reviewer_instructions_sha256"]
            == sha(custom),
            "registered custom reviewer instruction/packet differs",
        )
        if "reviewer_registration_sha256" in seal:
            require(
                seal["reviewer_registration_sha256"]
                == self.hash(folder + "/review-registration.json"),
                "sealed reviewer registration hash differs",
            )
        require(
            receipt["review_seal_sha256"] == self.hash(folder + "/review-seal.json")
            and receipt["key_sha256"] == self.hash(folder + "/key.json"),
            "unblinding receipt differs from sealed bytes",
        )
        require(
            timestamp(self.selection["frozen_at_utc"])
            <= timestamp(registration["registered_at_utc"])
            <= timestamp(seal["sealed_at_utc"])
            <= timestamp(receipt["unblinded_at_utc"]),
            "unblinding chronology precedes selection/review seal",
        )
        key = self.read(folder + "/key.json")
        require(
            key.get("schema_version") == 1
            and key.get("phase") == "confirmation"
            and key.get("modality") == modality
            and key.get("audit_comparison") == f"confirmation-{modality}-challenger",
            "unblinding key identity differs",
        )
        cases = indexed(packet["cases"], "case_id")
        keys = indexed(key["keys"], "case_id")
        accepted = indexed(judgments["judgments"], "case_id")
        failed = indexed(judgments["failed"], "case_id")
        missing = set(cases) - set(accepted) - set(failed)
        require(
            set(keys) == set(cases)
            and set(accepted) <= set(cases)
            and set(failed) <= set(cases)
            and not set(accepted) & set(failed),
            "review case/accounting identities differ",
        )
        require(
            (
                seal["expected_count"],
                seal["accepted_count"],
                seal["failed_count"],
                seal["not_attempted_count"],
            )
            == (len(cases), len(accepted), len(failed), len(missing))
            and len(seal["not_attempted_case_ids"]) == len(missing)
            and set(seal["not_attempted_case_ids"]) == missing,
            "sealed review accepted/failed/missing denominators differ",
        )
        path, items, ids = self.cohort(modality)
        arms = self.arms(modality, ids)
        require(
            nonempty(judgments["reviewer"].get("model")),
            "reviewer model must be recorded, including explicit unknown",
        )
        for cid, case in cases.items():
            point = keys[cid]["item_id"]
            require(
                point in items
                and cid == rank(modality, "case", point).hex()[:24]
                and case["text"] == items[point]["text"],
                "review case differs from canonical frozen input",
            )
            require(
                set(case)
                <= {"case_id", "text", "catalog", "pairs", "image", "image_sha256"}
                and case["catalog"] == arms[("challenger", "catalog")],
                "review packet contains unexpected identity/evidence or catalog",
            )
            require(
                len(case["pairs"]) == len(keys[cid]["pairs"]) == 2,
                "confirmation review requires both own-catalog pairs",
            )
            for index, (role, variant) in enumerate(
                (("challenger-pair", "challenger"), ("original-pair", "baseline"))
            ):
                pair, blind = case["pairs"][index], keys[cid]["pairs"][index]
                swap = rank(modality, "blind:" + role, point)[0] >= 128
                expected = dict(
                    role=role, A="ld" if swap else "llm", B="llm" if swap else "ld"
                )
                require(
                    blind == expected
                    and pair["pair_id"] == index + 1
                    and set(pair) == {"pair_id", "catalog", "assignments"}
                    and pair["catalog"] == arms[(variant, "catalog")]
                    and set(pair["assignments"]) == {"A", "B"},
                    "canonical blind mapping or own full catalog differs",
                )
                require(
                    all(
                        pair["assignments"][label]
                        == arms[(variant, blind[label])][point]["cluster_id"]
                        for label in ("A", "B")
                    ),
                    "blinded choices differ from actual audited assignments",
                )
            if cid in accepted:
                self.judgment(case, accepted[cid])
        result = dict(
            cases=cases,
            keys=keys,
            accepted=accepted,
            arms=arms,
            items=items,
            input_path=path,
            reviewer=judgments["reviewer"],
            accounting={
                name: seal[name]
                for name in (
                    "expected_count",
                    "accepted_count",
                    "failed_count",
                    "not_attempted_count",
                )
            },
        )
        self.cache[modality] = result
        return result

    def judgment(self, case, judgment):
        require(
            [row["pair_id"] for row in judgment["pairs"]] == [1, 2],
            "accepted judgment omits a confirmation pair",
        )
        for pair, choice in zip(judgment["pairs"], case["pairs"]):
            require(
                set(pair["assignments"]) == {"A", "B"}
                and pair["verdict"] in VERDICTS
                and isinstance(pair["themes"], list)
                and all(nonempty(theme) for theme in pair["themes"])
                and isinstance(pair["boundary_note"], str),
                "invalid accepted pair judgment",
            )
            if choice["assignments"]["A"] == choice["assignments"]["B"]:
                require(
                    pair["verdict"] not in ("prefer_a", "prefer_b"),
                    "identical choices cannot prefer one anonymous identity",
                )
            require(
                all(
                    set(row) == {"fit", "evidence", "severity"}
                    and row["fit"] in FIT
                    and nonempty(row["evidence"])
                    and nonempty(row["severity"])
                    for row in pair["assignments"].values()
                ),
                "invalid accepted assignment judgment",
            )

    def photo(self, study, case, selected):
        point = study["keys"][case["case_id"]]["item_id"]
        item = study["items"][point]
        photo = self.dataset["photos"][point]
        body = self.bytes(case["image"])
        original = member(self.run, study["input_path"]).parent / item["image"]
        supplied = self.bytes(original, audited=True)
        source = (
            member(
                self.data, self.dataset["partitions"]["confirmation"]["images"]["file"]
            ).parent
            / item["image"]
        )
        require(
            body
            == supplied
            == member(self.data, source).read_bytes()
            == member(self.data, photo["archived_source_file"]).read_bytes()
            and sha(body)
            == case["image_sha256"]
            == photo["supplied_sha256"]
            == photo["source_sha256"],
            "review photo differs from exact supplied/source JPEG",
        )
        width, height = images.jpeg_dimensions(body)
        require(
            all(
                type(n) is int and n > 0
                for n in (width, height, photo["native_width"], photo["native_height"])
            )
            and abs(width / height - photo["native_width"] / photo["native_height"])
            <= 0.01,
            "review photo native aspect differs",
        )
        require(
            nonempty(selected.get("alt")),
            "selected photo requires literal supplied alt text",
        )
        require(
            nonempty(photo.get("transform")), "selected photo changes must be recorded"
        )
        filename = case["case_id"] + ".jpg"
        return (
            images.example_image(body, photo, filename, self.prefix, selected["alt"]),
            body,
            filename,
        )

    def build(self):
        for modality in ("text", "images"):
            if (
                self.run / f"qualitative/confirmation/{modality}/review-seal.json"
            ).is_file():
                self.review(modality)
        examples, files = [], {}
        seen = set()
        for selected in self.curation["cases"]:
            modality, cid = selected["modality"], selected["case_id"]
            require(
                (modality, cid) not in seen and nonempty(selected["summary"]),
                "duplicate/empty curated review case",
            )
            seen.add((modality, cid))
            study = self.review(modality)
            require(
                cid in study["accepted"],
                "curated review case has no accepted sealed judgment",
            )
            case, key, judgment = (
                study["cases"][cid],
                study["keys"][cid],
                study["accepted"][cid],
            )
            assignments, pair_reviews, themes = [], [], []
            for index, variant in enumerate(("challenger", "baseline")):
                design = "Challenger" if variant == "challenger" else "Original"
                pair = judgment["pairs"][index]
                definitions = indexed(study["arms"][(variant, "catalog")], "id")
                for label in ("A", "B"):
                    mode = key["pairs"][index][label]
                    record = study["arms"][(variant, mode)][key["item_id"]]
                    category = definitions.get(record["cluster_id"])
                    assignments.append(
                        dict(
                            design=design,
                            pair_id=pair["pair_id"],
                            anonymous_label=label,
                            backend="Sol" if mode == "llm" else "Decisions",
                            cluster_id=record["cluster_id"],
                            category=category["name"] if category else "Other",
                            description=category["description"] if category else None,
                            refused=record["refused"],
                            **copy.deepcopy(pair["assignments"][label]),
                        )
                    )
                pair_reviews.append(
                    dict(
                        design=design,
                        verdict=pair["verdict"],
                        themes=copy.deepcopy(pair["themes"]),
                        boundary_note=pair["boundary_note"],
                    )
                )
                themes.extend(theme for theme in pair["themes"] if theme not in themes)
            example = dict(
                case_id=cid,
                text=case["text"] if modality == "text" else None,
                image=None,
                summary=selected["summary"],
                themes=themes,
                assignments=assignments,
                pair_reviews=pair_reviews,
            )
            if modality == "images":
                example["image"], body, filename = self.photo(study, case, selected)
                require(filename not in files, "duplicate selected photo filename")
                files[filename] = body
            examples.append(example)
        reviewers = list(
            dict.fromkeys(study["reviewer"]["model"] for study in self.cache.values())
        )
        result = dict(
            schema_version=1,
            source=dict(
                repository=REPOSITORY,
                run_path=RUN_PATH,
                commit=None,
                manifest_sha256=None,
            ),
            selection_note=self.curation["selection_note"],
            reviewer=" / ".join(reviewers) + " (coding harness; outside API ledger)",
            provenance_files=dict(self.provenance),
            examples=examples,
            review_accounting={
                name: self.cache[name]["accounting"] if name in self.cache else None
                for name in ("text", "images")
            },
            reviewer_metadata={
                name: (
                    copy.deepcopy(self.cache[name]["reviewer"])
                    if name in self.cache
                    else None
                )
                for name in ("text", "images")
            },
        )
        return result, files


def export_review(
    run_root, audit, selection, report_selection, data_root, asset_dir, output
):
    run, data, assets, output = (
        Path(path).resolve() for path in (run_root, data_root, asset_dir, output)
    )
    require(
        not output.exists() and not assets.exists(),
        "review output and asset directory must both be fresh",
    )
    require(
        output.parent == run / "report"
        and not assets.is_relative_to(run)
        and not assets.is_relative_to(data)
        and not output.is_relative_to(assets),
        "review publication output/assets must be separate from frozen inputs",
    )
    review = Review(run, audit, selection, report_selection, data)
    result, files = review.build()
    body = (
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    credits = "Selected curated illustrations; sealed coding-harness judgments are not human ground truth or population accuracy.\n\n"
    for example in result["examples"]:
        photo = example["image"]
        if photo:
            credits += f"{Path(photo['src']).name}: {photo['title']} by {photo['author']} ({photo['author_url']}); {photo['source_url']}; {photo['license_name']} {photo['license_url']}. {photo['changes']} SHA256 {photo['sha256']}\n"
    created = False
    try:
        assets.mkdir(parents=True, exist_ok=False)
        created = True
        for filename, raw in files.items():
            (assets / filename).write_bytes(raw)
        (assets / "ATTRIBUTION.txt").write_text(credits)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target:
            target.write(body)
    except BaseException:
        if created:
            shutil.rmtree(assets)
        raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "run-root",
        "audit",
        "selection",
        "report-selection",
        "data-root",
        "asset-dir",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = export_review(
        args.run_root,
        args.audit,
        args.selection,
        args.report_selection,
        args.data_root,
        args.asset_dir,
        args.output,
    )
    print(
        json.dumps(
            dict(
                status="exported",
                examples=len(result["examples"]),
                output=str(args.output),
            )
        )
    )


if __name__ == "__main__":
    main()
