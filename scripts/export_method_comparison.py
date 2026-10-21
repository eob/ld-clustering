#!/usr/bin/env python3
"""Export the fixed method matrix from pinned publications and audited raw arms."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

PUBLICATIONS = ("publication.json", "guided-agreement.json", "guidance-diagnostics.json", "stream-publication.json")
REPOSITORY = "https://github.com/eob/ld-clustering"
STUDY = "experiments/2026-10-21-auto-research-seed2043"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(), parse_float=Decimal)


def decimal(value):
    require(not isinstance(value, bool), "boolean is not a measurement")
    result = Decimal(str(value))
    require(result.is_finite() and result >= 0, "cost/time must be finite and nonnegative")
    return result


def money(value):
    return None if value is None else format(decimal(value), "f")


def scalar(value, lower=0, upper=1):
    if value is None:
        return None
    require(not isinstance(value, bool), "boolean is not a metric")
    number = float(value)
    require(lower <= number <= upper, "metric out of bounds")
    return number


def arm(value, scope, coverage=None):
    value = value or {}
    complete = value.get("cost_complete", False)
    require(type(complete) is bool, "cost completeness must be explicit")
    known = money(value.get("known_cost_usd", value.get("cost_usd")))
    require(not complete or known is not None, "complete cost is missing")
    total = known if complete else None
    if "total_cost_usd" in value:
        require(money(value["total_cost_usd"]) == total, "total contradicts cost completeness")
    timed = value.get("timing_complete", False)
    require(type(timed) is bool, "timing completeness must be explicit")
    seconds = value.get("wall_seconds") if timed else None
    require(not timed or seconds is not None, "complete time is missing")
    return dict(known_cost_usd=known, total_cost_usd=total, cost_complete=complete,
                wall_seconds=float(decimal(seconds)) if seconds is not None else None,
                timing_scope=scope if seconds is not None else "unavailable",
                coverage=scalar(coverage if coverage is not None else value.get("coverage")))


def cell(n, comparison, sol, ld, independent=False, repetitions=1, unique_n=None):
    require(type(n) is int and n > 0, "positive integer denominator required")
    require(comparison.get("n", n) == n, "comparison denominator differs")
    partition = comparison.get("partition", comparison.get("agreement", comparison))
    require(partition.get("n", n) == n, "partition denominator differs")
    return dict(n=n, unique_n=unique_n or n, repetitions=repetitions,
                agreement=None if independent else scalar(comparison.get("direct_agreement", comparison.get("direct_assignment_agreement"))),
                ari=scalar(partition.get("adjusted_rand_index"), -1, 1), sol=sol, ld=ld)


def evidence(source, path=None):
    return [dict(label="Immutable source evidence", url=f'{source["repository"]}/tree/{source["commit"]}/{path or source["run_path"]}')]


def group(identifier, title, context, rows, links):
    return dict(id=identifier, title=title, context=context, rows=rows, evidence=links)


def legacy_groups(documents):
    p, g, d, s = [documents[name] for name in PUBLICATIONS]
    for document in (p, g, d, s):
        require(document["schema_version"] == 1 and document["status"] == "complete", "incomplete prior publication")
    result = [group("superseded", "Superseded initial implementation",
                    "Historical v1 execution; no final comparable measurements are imported.",
                    [dict(id="initial-v1", label="Initial v1 (superseded)", note="Unavailable values are retained as missing, not zero.", text=None, images=None)], evidence(p["source"]))]
    values = {}
    for modality in p["experiments"]:
        require(modality["status"] == "complete", "historical stream is incomplete")
        values[modality["id"]] = cell(modality["count"], modality["agreement"],
             arm(modality["baseline"], "clustering_loop"), arm(modality["ld"], "clustering_loop"), independent=True)
    result.append(group("v2-streams", "Corrected v2 streams", "Historical streaming: 1,000 CLINC requests and 100 Fashion-MNIST 28×28 images. Costs/times include catalog management and reassignment. Independent catalog IDs have no direct agreement score.",
                        [dict(id="v2", label="Corrected v2", **values)], evidence(p["source"])))
    frozen = p["frozen_catalog_control"]
    require(frozen["status"] == "complete", "frozen Fashion control is incomplete")
    result.append(group("fashion-fixed", "Reused Fashion-MNIST diagnostic", "Post hoc reuse of the same 100 clothing images with one frozen catalog; classification-only work. This is not fresh confirmation.",
         [dict(id="fashion-fixed", label="Frozen catalog", text=None,
               images=cell(frozen["count"], frozen["agreement"], arm(frozen["baseline"], "assignment_only_loop"), arm(frozen["ld"], "assignment_only_loop")))], evidence(p["source"], frozen["run_path"])))
    rows = []
    for variant, label in (("original", "Original short guide"), ("guided", "Joint rich guide")):
        values = {}
        for modality in g["modalities"]:
            v = modality[variant]; c = v["comparison"]; m = v["measurements"]
            values[modality["modality"]] = cell(modality["heldout_count"], c,
                arm(m["baseline"], "assignment_only_loop", c["reference_coverage"]),
                arm(m["candidate"], "assignment_only_loop", c["candidate_coverage"]))
        rows.append(dict(id="control-"+variant, label=label, **values))
    result.append(group("initial-control", "Initial shared-catalog control", "Fresh seed1042 evaluation: 1,000 requests and 100 natural photos, separate from discovery. Classification-only costs/times; shared catalog generation, reviews and repeats are separate in the research log. An incomplete photo review does not make these complete classification arms incomplete.", rows, evidence(g["source"])))
    rows = []
    for variant, label in (("primary", "Rich K8: reused primary subset"), ("reverse", "Rich K8: reversed order"), ("large-page", "Rich K16")):
        values = {}
        for modality in d["modalities"]:
            if variant == "primary":
                c = modality["primary_subset"]; measures = {}
            else:
                matches = [v for v in modality["variants"] if (v["policy"] == "reverse") == (variant == "reverse")]
                require(len(matches) == 1, "diagnostic variant missing/duplicated")
                c = matches[0]["comparison"]; measures = matches[0].get("measurements", {})
            values[modality["modality"]] = cell(modality["n"], c,
                arm(measures.get("llm"), "assignment_only_loop", c["reference_coverage"]),
                arm(measures.get("ld"), "assignment_only_loop", c["candidate_coverage"]))
        rows.append(dict(id="diagnostic-"+variant, label=label,
            note="Subset values are sliced from the primary cohort; no separate cost/time was measured." if variant == "primary" else "K16 photos have the same request content as K8: an extra repeat, not a page intervention." if variant == "large-page" else "Order and page membership change together; one recorded refusal is retained.", **values))
    result.append(group("order-diagnostics", "Reused order/page diagnostics", "Post hoc seed1042 subsets: 100 requests and 25 photos. These are not fresh data. Subset cost/time is missing when no separate loop was measured; full-cohort work is never borrowed.", rows, evidence(g["source"])))
    rows = []
    for policy, label in (("original", "Original manager"), ("contextual", "Contextual manager")):
        values = {}
        for modality in s["modalities"]:
            v = modality[policy]
            require(v["complete"] and v["comparison"] is not None, "reserved stream incomplete")
            values[modality["modality"]] = cell(modality["n"], v["comparison"],
                arm(v["llm"], "clustering_loop"), arm(v["ld"], "clustering_loop"), independent=True)
        rows.append(dict(id="reserved-"+policy, label=label, **values))
    result.append(group("reserved-streams", "Reserved evolving streams", "Separate seed1042 reserved cohort: 1,000 requests and 100 natural photos. Full streaming costs/times include manager calls and global reevaluation. Independent catalogs; the contextual intervention bundles guidance, prior findings and reconsideration.", rows, evidence(s["source"])))
    return result


class Exporter:
    def __init__(self, root, prior_dir, bindings_sha, audit_path, audit_sha, publication_commit=None):
        self.root = root.resolve(); self.prior = prior_dir.resolve(); self.sources = {}; self.ordered_ids = {}
        self.sources["producer"] = dict(path="reproduction/export_method_comparison.py", sha256=sha(Path(__file__)))
        require(self.prior.is_relative_to(self.root), "prior publications must be staged inside the portable run")
        manifest = self.prior / "input-bindings.json"
        require(sha(manifest) == bindings_sha, "external prior-publication binding hash differs")
        bindings = read_json(manifest)
        require(bindings["schema_version"] == 1 and set(bindings["files"]) == set(PUBLICATIONS), "prior publication inventory differs")
        self.documents = {}
        for name in PUBLICATIONS:
            path = self.prior / name; record = bindings["files"][name]
            require(not path.is_symlink() and sha(path) == record["sha256"], "prior publication bytes changed: "+name)
            document = read_json(path)
            if "source" in document:
                source = document["source"]
                require(record.get("source") == source and source["repository"] == REPOSITORY
                        and re.fullmatch(r"[0-9a-f]{40}", source["commit"]) is not None
                        and re.fullmatch(r"[0-9a-f]{64}", source["manifest_sha256"]) is not None,
                        "prior publication commit/manifest binding differs")
            self.documents[name] = document
            self.sources[name] = dict(path=str(path.relative_to(self.root)), sha256=sha(path), **({"source":document["source"]} if "source" in document else {}))
        require(self.documents["guidance-diagnostics.json"]["audit_sha256"] == bindings["files"]["guidance-diagnostics.json"]["audit_sha256"], "diagnostic audit pin differs")
        self.sources["prior-bindings"] = dict(path=str(manifest.relative_to(self.root)), sha256=bindings_sha)
        require(sha(audit_path) == audit_sha, "external final-audit hash differs")
        self.audit = read_json(audit_path)
        require(self.audit["experiment"] == "guidance-auto-research" and self.audit["status"] == "verified" and not self.audit["failed_conditions"], "verified final audit required")
        self.sources["auto-final-audit"] = dict(path=str(audit_path.resolve().relative_to(self.root)), sha256=audit_sha)
        self.conditions = {row["id"]:row for row in self.bound("preregistration/conditions.json")["conditions"]}
        protocol = self.bound("preregistration/protocol.json")
        require(protocol["experiment"] == "guidance-auto-research"
                and self.audit["protocol_sha256"] == self.sources["auto:preregistration/protocol.json"]["sha256"], "protocol identity differs")
        if publication_commit is not None:
            require(re.fullmatch(r"[0-9a-f]{40}", publication_commit) is not None, "invalid publication commit")
        self.new_links = [dict(label="Immutable study evidence", url=(f"{REPOSITORY}/blob/{publication_commit}/{STUDY}/evidence/readable/validation/final-independent-audit.json" if publication_commit else f'{REPOSITORY}/blob/{self.audit["source"]["commit"]}/{STUDY}/protocol.json'))]

    def bound(self, relative):
        path = (self.root / relative).resolve()
        require(path.is_relative_to(self.root) and self.audit["evidence_files"].get(relative) == sha(path), "unbound new-study input: "+relative)
        self.sources["auto:"+relative] = dict(path=relative, sha256=sha(path))
        return read_json(path)

    def new_arm(self, cid, coverage):
        spec = self.conditions[cid]; raw = self.bound(spec["output"]); cost = self.audit["costs"][cid]
        require(raw["status"] == "complete" and raw["processed_count"] == raw["expected_count"] == spec["expected_count"] == len(raw["assignments"]), "incomplete classification arm")
        require(spec["kind"] == "classification" and raw["metadata"]["management_calls"] == 0
                and raw["metadata"]["mode"] == spec["mode"] and raw["metadata"]["k"] == spec["k"], "classification conditions differ")
        self.ordered_ids[cid] = [row["id"] for row in raw["assignments"]]
        measurement = raw["measurement"]
        require(cost["journal_sha256"] == measurement["journal_sha256"], "measurement journal differs")
        if "wall_ms" in cost:
            require(cost["wall_ms"] == measurement["wall_ms"], "audited wall time differs")
        seconds = Decimal(measurement["wall_ms"])/1000 if measurement["timing_complete"] else None
        return arm(dict(known_cost_usd=cost["known_cost_usd"], cost_complete=cost["cost_complete"],
                        timing_complete=measurement["timing_complete"], wall_seconds=seconds),
                   "assignment_only_loop", coverage)

    def new_cell(self, stem):
        comparison = self.audit["comparisons"][stem]
        for mode in ("llm", "ld"):
            require(self.conditions[stem+"-"+mode]["expected_count"] == comparison["n"], "new comparison denominator differs")
        return cell(comparison["n"], comparison, self.new_arm(stem+"-llm", comparison["reference_coverage"]), self.new_arm(stem+"-ld", comparison["candidate_coverage"]))

    def new_groups(self):
        rows = []
        for style, label in (("short", "Short"), ("redundant-positive", "Redundant positive"), ("negative-boundaries", "Negative boundaries")):
            cells = [self.new_cell(f"r1-{style}-o{index}") for index in range(4)]
            require(all(value["n"] == 20 for value in cells), "calibration denominator differs")
            ids = [self.ordered_ids[f"r1-{style}-o{index}-{mode}"] for index in range(4) for mode in ("llm", "ld")]
            require(all(value == ids[0] for value in ids) and len(set(ids[0])) == 20, "calibration repeats are not the same20 cases")
            combined = dict(n=80, unique_n=20, repetitions=4, agreement=sum(value["agreement"]*20 for value in cells)/80, ari=None)
            for backend in ("sol", "ld"):
                values = [value[backend] for value in cells]
                known = sum((decimal(value["known_cost_usd"]) for value in values if value["known_cost_usd"] is not None), Decimal(0))
                complete = all(value["cost_complete"] for value in values)
                timed = all(value["wall_seconds"] is not None for value in values)
                combined[backend] = dict(known_cost_usd=format(known,"f"), total_cost_usd=format(known,"f") if complete else None, cost_complete=complete,
                    wall_seconds=float(sum((decimal(value["wall_seconds"]) for value in values),Decimal(0))) if timed else None,
                    timing_scope="sum_of_4_order_loops" if timed else "unavailable", coverage=sum(value[backend]["coverage"] for value in cells)/4)
            rows.append(dict(id="calibration-"+style,label=label,note="Same 20 constructed cases repeated in 4 orders: 80 dependent comparisons; ARI is not pooled across orders. Time is the sum of 4 loop times for each backend, not elapsed study time.",text=combined,images=None))
        groups = [group("calibration", "Constructed calibration", "Seed2043 calibration: 20 constructed text cases, four cyclic orders, four named categories plus Other. Agreement is between classifiers, not constructed-key accuracy or natural-data accuracy. Costs exclude later generation and review.", rows, self.new_links)]
        rows = []
        for variant,label in (("baseline","Original"),("compact","Compact"),("boundary","Boundary")):
            prefix="r3" if variant=="boundary" else "r2"
            rows.append(dict(id="development-"+variant,label=label,note="Reused adaptive development data; not fresh confirmation.",**{mod:self.new_cell(f"{prefix}-{mod}-{variant}") for mod in ("text","images")}))
        groups.append(group("development","Adaptive development","Seed2043: 200 fresh requests and 40 natural photos, reused for the compact and boundary revisions. Stable IDs/order/K8. Classification-only costs/times; shared catalog generation and qualitative review remain separate in the log.",rows,self.new_links))
        rows=[]
        for variant,label in (("baseline","Original"),("challenger","Frozen Boundary challenger")):
            rows.append(dict(id="confirmation-"+variant,label=label,note="The challenger was frozen before confirmation; development selection and confirmation results remain separate in the research log." if variant=="challenger" else "Separate fresh confirmation cohort; not a rerun of development.",**{mod:self.new_cell(f"confirmation-{mod}-{variant}") for mod in ("text","images")}))
        groups.append(group("confirmation","Fresh confirmation","Seed2043: 1,000 requests and 100 natural photos, disjoint from development and all earlier study inputs. Once-only frozen comparison; classification-only costs/times exclude generation, reviews and preselected repeats.",rows,self.new_links))
        return groups

    def export(self):
        groups = legacy_groups(self.documents) + self.new_groups()
        return dict(schema_version=1, updated_at=datetime.now(timezone.utc).date().isoformat(), sources=self.sources, groups=groups,
          scope_notes=["Agreement is direct category-ID agreement including Other, not semantic accuracy. It is unavailable for independently learned catalogs. ARI is unitless partition agreement, not percent accuracy.",
            "Each cost/time cell reports Sol and Decisions separately. Streams include manager and reassignment work; fixed-catalog rows measure classification only. Shared generation, reviews and repeats are accounted separately in the research log.",
            "Concurrent worker loop times are not summed into a study elapsed time. Calibration explicitly sums four order-loop times per backend; no other time aggregation is implied.",
            "Different groups use different datasets, catalog structures and stages. Reused, adaptive and constructed subsets are labeled; they are not interchangeable head-to-head accuracy estimates.",
            "Missing values remain unavailable. An incomplete cost reports its known subtotal with no fabricated complete total. Frozen-price token estimates are not invoices; cache and concurrent-load differences limit cost/time comparisons."])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root",type=Path,required=True)
    parser.add_argument("--prior-publications",type=Path,required=True)
    parser.add_argument("--prior-bindings-sha256",required=True)
    parser.add_argument("--audit",type=Path,required=True)
    parser.add_argument("--audit-sha256",required=True)
    parser.add_argument("--publication-commit")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=Exporter(args.run_root,args.prior_publications,args.prior_bindings_sha256,args.audit,args.audit_sha256,args.publication_commit).export()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as out:
        json.dump(result,out,indent=2,allow_nan=False);out.write("\n")
    print(json.dumps(dict(status="complete",output_sha256=sha(args.output),groups=len(result["groups"]),rows=sum(len(g["rows"]) for g in result["groups"]))))


if __name__ == "__main__":
    main()
