"""Synthetic published inputs and bounded raw arms only; zero model calls."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import types
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts/export_method_comparison.py"
exporter=types.ModuleType("export_method_comparison")
exporter.__file__=str(SCRIPT)
exec(compile(SCRIPT.read_bytes(),str(SCRIPT),"exec"),exporter.__dict__)


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+"\n")


def source():
    return dict(repository=exporter.REPOSITORY,commit="1"*40,runtime_commit="2"*40,
                run_path="experiments/synthetic",manifest_sha256="3"*64)


def measurement(cost="0.1000001",seconds=1.1,complete=True):
    return dict(cost_usd=cost,cost_complete=complete,wall_seconds=seconds,
                timing_complete=True,coverage=0.75)


def comparison(n=4):
    return dict(n=n,direct_agreement=0.5,reference_coverage=0.75,candidate_coverage=0.5,
                partition=dict(n=n,adjusted_rand_index=0.25))


def publications():
    p=dict(schema_version=1,status="complete",source=source(),experiments=[])
    for mod in ("text","images"):
        p["experiments"].append(dict(id=mod,count=4,status="complete",baseline=measurement(),
            ld=measurement(complete=mod!="text"),agreement=dict(adjusted_rand_index=0.25)))
    p["frozen_catalog_control"]=dict(status="complete",count=4,run_path="experiments/frozen",
        baseline=measurement(),ld=measurement(),agreement=dict(direct_assignment_agreement=0.5,adjusted_rand_index=0.25))
    g=dict(schema_version=1,status="complete",source=source(),modalities=[])
    d=dict(schema_version=1,status="complete",audit_sha256="4"*64,modalities=[])
    s=dict(schema_version=1,status="complete",source=source(),modalities=[])
    for mod in ("text","images"):
        roles={role:dict(comparison=comparison(),measurements=dict(baseline=measurement(),candidate=measurement())) for role in ("original","guided")}
        g["modalities"].append(dict(modality=mod,heldout_count=4,**roles))
        variants=[dict(policy=policy,comparison=comparison(),measurements=dict(llm=measurement("0.2",2),ld=measurement("0.03",0.3))) for policy in ("reverse","k16")]
        d["modalities"].append(dict(modality=mod,n=4,primary_subset=comparison(),variants=variants))
        policies={role:dict(complete=True,comparison=dict(agreement=dict(n=4,adjusted_rand_index=0.25)),llm=measurement(),ld=measurement()) for role in ("original","contextual")}
        s["modalities"].append(dict(modality=mod,n=4,**policies))
    return dict(zip(exporter.PUBLICATIONS,[p,g,d,s]))


class MethodComparison(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.prior=self.root/"report/prior-publications"
        docs=publications();files={}
        for name,document in docs.items():
            path=self.prior/name;write(path,document)
            files[name]=dict(sha256=exporter.sha(path),**({"source":document["source"]} if "source" in document else {"audit_sha256":document["audit_sha256"]}))
        write(self.prior/"input-bindings.json",dict(schema_version=1,files=files))
        self.bindings_sha=exporter.sha(self.prior/"input-bindings.json")
        self.audit=dict(experiment="guidance-auto-research",status="verified",failed_conditions=[],source=dict(commit="5"*40),comparisons={},costs={},evidence_files={})
        self.specs=[]
        for style in ("short","redundant-positive","negative-boundaries"):
            for order in range(4):self.add_pair(f"r1-{style}-o{order}",20)
        for mod,n in (("text",200),("images",40)):
            for variant in ("baseline","compact"):self.add_pair(f"r2-{mod}-{variant}",n)
            self.add_pair(f"r3-{mod}-boundary",n)
        for mod,n in (("text",1000),("images",100)):
            for variant in ("baseline","challenger"):self.add_pair(f"confirmation-{mod}-{variant}",n)
        write(self.root/"preregistration/conditions.json",dict(conditions=self.specs))
        write(self.root/"preregistration/protocol.json",dict(experiment="guidance-auto-research"))
        for rel in ("preregistration/conditions.json","preregistration/protocol.json"):
            self.audit["evidence_files"][rel]=exporter.sha(self.root/rel)
        self.audit["protocol_sha256"]=self.audit["evidence_files"]["preregistration/protocol.json"]
        self.audit_path=self.root/"validation/final-independent-audit.json"
        self.save_audit()

    def save_audit(self):
        write(self.audit_path,self.audit);self.audit_sha=exporter.sha(self.audit_path)

    def add_pair(self,stem,n):
        self.audit["comparisons"][stem]=comparison(n)
        for mode in ("llm","ld"):
            cid=stem+"-"+mode;rel="raw/"+cid+".json"
            raw=dict(status="complete",processed_count=n,expected_count=n,
                     assignments=[dict(id=str(i),cluster_id=1) for i in range(n)],
                     metadata=dict(mode=mode,k=8,management_calls=0),
                     measurement=dict(journal_sha256="6"*64,timing_complete=True,wall_ms=1100))
            write(self.root/rel,raw)
            self.specs.append(dict(id=cid,kind="classification",expected_count=n,k=8,mode=mode,output=rel))
            self.audit["evidence_files"][rel]=exporter.sha(self.root/rel)
            self.audit["costs"][cid]=dict(journal_sha256="6"*64,cost_complete=True,known_cost_usd="0.1234567",wall_ms=1100)

    def instance(self,commit=None):
        return exporter.Exporter(self.root,self.prior,self.bindings_sha,self.audit_path,self.audit_sha,commit)

    def test_all_designs_and_scope_are_preserved(self):
        data=self.instance().export()
        self.assertEqual(len(data["groups"]),9)
        self.assertEqual(sum(len(g["rows"]) for g in data["groups"]),18)
        self.assertIsNone(data["groups"][0]["rows"][0]["text"])
        final=data["groups"][-1]["rows"][1]
        self.assertEqual(final["text"]["n"],1000)
        self.assertEqual(final["images"]["n"],100)
        self.assertIn("frozen before confirmation",final["note"])

    def test_independent_catalogs_never_gain_direct_id_agreement(self):
        data=self.instance().export()
        for index in (1,5):
            for row in data["groups"][index]["rows"]:
                self.assertIsNone(row["text"]["agreement"])
                self.assertEqual(row["text"]["ari"],0.25)

    def test_subset_never_borrows_full_cohort_cost_or_time(self):
        group=self.instance().export()["groups"][4]
        for mod in ("text","images"):
            for backend in ("sol","ld"):
                arm=group["rows"][0][mod][backend]
                self.assertIsNone(arm["known_cost_usd"])
                self.assertIsNone(arm["total_cost_usd"])
                self.assertFalse(arm["cost_complete"])
                self.assertIsNone(arm["wall_seconds"])
            self.assertEqual(group["rows"][1][mod]["sol"]["total_cost_usd"],"0.2")

    def test_calibration_repetitions_sum_only_each_backend_loops(self):
        row=self.instance().export()["groups"][6]["rows"][0]["text"]
        self.assertEqual((row["n"],row["unique_n"],row["repetitions"]),(80,20,4))
        self.assertEqual(row["agreement"],0.5)
        self.assertIsNone(row["ari"])
        for backend in ("sol","ld"):
            self.assertEqual(row[backend]["total_cost_usd"],"0.4938268")
            self.assertEqual(row[backend]["wall_seconds"],4.4)
            self.assertEqual(row[backend]["timing_scope"],"sum_of_4_order_loops")

    def test_incomplete_legacy_cost_retains_subtotal_without_complete_total(self):
        arm=self.instance().export()["groups"][1]["rows"][0]["text"]["ld"]
        self.assertEqual(arm["known_cost_usd"],"0.1000001")
        self.assertFalse(arm["cost_complete"])
        self.assertIsNone(arm["total_cost_usd"])
        self.assertEqual(arm["wall_seconds"],1.1)

    def test_decimal_precision_is_preserved_without_float_summing(self):
        value=exporter.arm(measurement(Decimal("0.000000123456789")),"assignment_only_loop")
        self.assertEqual(value["total_cost_usd"],"0.000000123456789")

    def test_unknown_timing_is_missing_even_if_a_number_is_present(self):
        value=measurement();value["timing_complete"]=False
        self.assertIsNone(exporter.arm(value,"assignment_only_loop")["wall_seconds"])

    def test_missing_complete_cost_and_contradictory_total_are_rejected(self):
        with self.assertRaises(ValueError):exporter.arm(dict(cost_complete=True),"assignment_only_loop")
        with self.assertRaises(ValueError):exporter.arm(dict(cost_complete=False,cost_usd="1",total_cost_usd="1"),"assignment_only_loop")

    def test_external_binding_and_audit_hashes_are_required(self):
        with self.assertRaisesRegex(ValueError,"external prior"):
            exporter.Exporter(self.root,self.prior,"0"*64,self.audit_path,self.audit_sha)
        with self.assertRaisesRegex(ValueError,"external final"):
            exporter.Exporter(self.root,self.prior,self.bindings_sha,self.audit_path,"0"*64)

    def test_changed_prior_publication_is_rejected(self):
        path=self.prior/"guided-agreement.json";path.write_text(path.read_text()+" ")
        with self.assertRaisesRegex(ValueError,"prior publication bytes"):
            self.instance()

    def test_changed_audited_raw_measurement_is_rejected(self):
        path=self.root/"raw/r2-text-baseline-llm.json";raw=json.loads(path.read_text());raw["measurement"]["wall_ms"]=1;write(path,raw)
        with self.assertRaisesRegex(ValueError,"unbound new-study"):
            self.instance().export()

    def test_incomplete_raw_arm_does_not_receive_a_full_score(self):
        rel="raw/confirmation-text-challenger-llm.json";path=self.root/rel;raw=json.loads(path.read_text());raw["status"]="running";write(path,raw);self.audit["evidence_files"][rel]=exporter.sha(path);self.save_audit()
        with self.assertRaisesRegex(ValueError,"incomplete classification"):
            self.instance().export()

    def test_publication_commit_changes_only_new_group_links(self):
        before=self.instance().export();after=self.instance("a"*40).export()
        self.assertEqual(before["groups"][:6],after["groups"][:6])
        for old,new in zip(before["groups"][6:],after["groups"][6:]):
            self.assertNotEqual(old["evidence"],new["evidence"])
            old["evidence"]=new["evidence"]
        self.assertEqual(before,after)

    def test_partition_denominator_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"partition denominator"):
            exporter.cell(4,dict(partition=dict(n=3,adjusted_rand_index=0.5)),{},{} )


if __name__=="__main__":
    unittest.main()
