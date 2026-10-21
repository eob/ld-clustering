from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def helper():
    path = ROOT / "scripts/verify_guided_streaming.py"
    module = types.ModuleType("verify_guided_streaming")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


class Fixture:
    def __init__(self, root):
        self.root, self.stage, self.data, self.repo = (
            root,
            root / "streaming",
            root / "data",
            root / "repo",
        )
        self.v = helper()
        self.stage.mkdir()
        self.repo.mkdir()
        self.binary = root / "frozen-binary"
        self.binary.write_bytes(b"OFFLINE FIXTURE: never executable")
        self.provider = (ROOT / "src/provider.rs").read_bytes()
        self.catalog = [
            {"id": 1, "name": "One", "description": "First"},
            {"id": 2, "name": "Two", "description": "Second"},
        ]
        self.protocol = {
            "schema_version": 1,
            "dataset_manifest_sha256": None,
            "offline_preflight": {},
            "modalities": {},
            "manager": {"contexts": {}},
            "policies": {
                "original": {
                    "descriptor": {
                        "policy": "original",
                        "context_sha256": None,
                        "prompt_revision": "original-v1",
                    }
                },
                "contextual": {"prompt_revision": "contextual-v1"},
            },
        }
        self.preflight = {
            "status": "offline_preflight_passed",
            "api_calls": 0,
            "dataset_manifest_sha256": None,
            "modalities": [],
        }
        manifest = {
            "partitions": {
                split: {} for split in ("streaming", "discovery", "heldout")
            },
            "photos": {},
        }
        self.inputs, self.images = {}, {}
        for modality, n in (("text", 1000), ("images", 100)):
            rows = []
            for i in range(n):
                item = {
                    "id": f"{modality}-{i}",
                    "text": f"Request {i}" if modality == "text" else "Photograph.",
                }
                if modality == "images":
                    item["image"] = f'../images/{item["id"]}.jpg'
                    image = b"\xff\xd8\xff" + item["id"].encode()
                    self.images[item["id"]] = image
                    self.write(self.data / f'images/{item["id"]}.jpg', image)
                    manifest["photos"][item["id"]] = {
                        "supplied_sha256": self.v.sha(image)
                    }
                rows.append(item)
            self.inputs[modality] = rows
            body = b"".join(self.v.struct_json(row) + b"\n" for row in rows)
            path = self.data / "streaming" / (modality + ".jsonl")
            self.write(path, body)
            hashes = [
                {"id": r["id"], "sha256": self.v.sha(self.images[r["id"]])}
                for r in rows
                if "image" in r
            ]
            manifest["partitions"]["streaming"][modality] = {
                "count": n,
                "ordered_ids": [r["id"] for r in rows],
                "payload_sha256": self.v.sha(self.v.struct_json(rows)),
                "order_sha256": self.v.sha(self.v.struct_json([r["id"] for r in rows])),
                "ordered_image_hashes": hashes,
                "ordered_image_content_sha256": self.v.sha(self.v.struct_json(hashes)),
            }
            for split in ("discovery", "heldout"):
                manifest["partitions"][split][modality] = {
                    "ordered_ids": [f"{split}-{modality}"]
                }
            fingerprint = self.v._shared["fingerprint"](path, rows, self.images)
            config = {
                "task": (
                    self.v._shared["TEXT_TASK"]
                    if modality == "text"
                    else self.v._shared["IMAGE_TASK"]
                ),
                "k": 8,
                "max_clusters": 16,
                "bootstrap_size": 24,
                "novelty_trigger": 8,
                "maintenance_interval": 100,
            }
            self.protocol["modalities"][modality] = {
                "config": config,
                "input_sha256": fingerprint,
                "jsonl_sha256": self.v.sha(body),
                "expected_count": n,
            }
            context = f"Frozen {modality} context\n"
            record = {
                "file": f"streaming-context-{modality}.md",
                "sha256": self.v.sha(context.encode()),
            }
            self.protocol["manager"]["contexts"][modality] = record
            self.write(
                self.stage / "preregistration" / record["file"], context.encode()
            )
            self.write(self.repo / self.v.EXPERIMENT / record["file"], context.encode())
            self.preflight["modalities"].append(
                {
                    "modality": modality,
                    "config": config,
                    "input_sha256": fingerprint,
                    "jsonl_sha256": self.v.sha(body),
                    "context_sha256": record["sha256"],
                    "count": n,
                    "policies": [
                        {"manager_descriptor": self.descriptor(modality, policy)}
                        for policy in ("original", "contextual")
                    ],
                }
            )
        self.json(self.data / "manifest.json", manifest)
        self.protocol["dataset_manifest_sha256"] = self.preflight[
            "dataset_manifest_sha256"
        ] = self.v.file_pin(self.data / "manifest.json")["sha256"]
        self.json(self.stage / "preregistration/request-preflight.json", self.preflight)
        self.protocol["offline_preflight"]["artifact_sha256"] = self.v.file_pin(
            self.stage / "preregistration/request-preflight.json"
        )["sha256"]
        self.json(self.stage / "preregistration/protocol.json", self.protocol)
        self.json(
            self.stage / "preregistration/pricing.json",
            {
                "per_million_tokens": {
                    self.v.SOL: {
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
        self.json(
            self.repo / self.v.EXPERIMENT / "streaming-protocol.json", self.protocol
        )
        for name in self.v.SOURCE_FILES:
            self.write(self.repo / name, (ROOT / name).read_bytes())
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Offline Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "Synthetic source",
            ],
            cwd=self.repo,
            check=True,
        )
        self.commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, text=True
        ).strip()
        self.receipt = self.v.file_pin(self.binary)["sha256"] + "  " + str(self.binary)
        self.write(self.stage / "source-commit.txt", self.commit.encode())
        self.write(self.stage / "binary-sha256.txt", self.receipt.encode())
        self.write(
            self.stage / "dataset-manifest-sha256.txt",
            self.protocol["dataset_manifest_sha256"].encode(),
        )
        self.write(self.stage / "supervisor-exit-code.txt", b"0\n")
        self.write(self.stage / "finished-at.txt", b"terminal\n")
        self.arms = []
        for modality in ("text", "images"):
            for policy in ("original", "contextual"):
                for backend in ("llm", "ld"):
                    self.make_arm(modality, policy, backend)
        self.plan = {
            "schema_version": 1,
            "source_commit": self.commit,
            "binary_sha256": self.v.file_pin(self.binary)["sha256"],
            "protocol_sha256": self.v.file_pin(
                self.stage / "preregistration/protocol.json"
            )["sha256"],
            "preflight_sha256": self.v.file_pin(
                self.stage / "preregistration/request-preflight.json"
            )["sha256"],
            "dataset_manifest_sha256": self.protocol["dataset_manifest_sha256"],
            "arms": self.arms,
        }
        self.json(self.stage / "run-plan.json", self.plan)
        for modality in ("text", "images"):
            for policy in ("original", "contextual"):
                n = len(self.inputs[modality])
                score = {
                    "n": n,
                    "adjusted_rand_index": 1.0,
                    "pairwise_precision": 1.0,
                    "pairwise_recall": 1.0,
                    "pairwise_f1": 1.0,
                }
                expected = {
                    "status": "complete",
                    "expected_count": n,
                    "config": self.protocol["modalities"][modality]["config"],
                    "manager_descriptor": self.descriptor(modality, policy),
                    "input_sha256": self.protocol["modalities"][modality][
                        "input_sha256"
                    ],
                    "baseline": self.measurement(modality, "llm", policy),
                    "ld": self.measurement(modality, "ld", policy),
                    "agreement": score,
                    "shared_other_sensitivity": score,
                    "assigned_other": {
                        "both_named": 1,
                        "baseline_named_ld_other": 0,
                        "baseline_other_ld_named": 0,
                        "both_other": n - 1,
                    },
                }
                self.json(
                    self.stage / "comparisons" / f"{modality}-{policy}.json", expected
                )

    @staticmethod
    def write(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def json(self, path, value):
        self.write(path, self.v.struct_json(value) + b"\n")

    def descriptor(self, modality, policy):
        return (
            self.protocol["policies"]["original"]["descriptor"]
            if policy == "original"
            else {
                "policy": "contextual",
                "context_sha256": self.protocol["manager"]["contexts"][modality][
                    "sha256"
                ],
                "prompt_revision": "contextual-v1",
            }
        )

    def response(self, model, value):
        result = {
            "model": model,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10 if model == self.v.SOL else 0,
            },
        }
        if model == self.v.SOL:
            result.update(
                service_tier="default",
                status="completed",
                output=[
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(value)}],
                    }
                ],
            )
        else:
            result["answers"] = [
                {"type": "choice", "name": "cluster", "choice": str(value)}
            ]
        return result

    def call(self, phase, request, response):
        cost, _, usage = self.v.reprice(response, request["model"])
        return {
            "phase": phase,
            "model": request["model"],
            "request": request,
            "response": response,
            "elapsed_ms": 2,
            "usage": {**usage, "cost_usd": float(cost)},
            "attempt": 1,
            "http_status": 200,
            "error": None,
            "refusal": False,
            "usage_available": True,
        }

    def make_arm(self, modality, policy, backend):
        name = f"{modality}-{policy}-{backend}"
        directory = self.stage / name
        directory.mkdir()
        registered = self.protocol["modalities"][modality]
        config, rows = registered["config"], self.inputs[modality]
        descriptor = self.descriptor(modality, policy)
        for filename, value in [
            ("source-commit.txt", self.commit),
            ("binary-sha256.txt", self.receipt),
            ("input-sha256.txt", registered["input_sha256"]),
            ("exit-code.txt", "0"),
            ("finished-at.txt", "terminal"),
        ]:
            self.write(directory / filename, value.encode())
        self.json(directory / "manager-descriptor.json", descriptor)
        argv = [
            str(self.binary),
            "run",
            "--input",
            str(self.data / "streaming" / (modality + ".jsonl")),
            "--database",
            str(directory / "state.sqlite"),
            "--log",
            str(directory / "calls.jsonl"),
            "--mode",
            backend,
            "--task",
            config["task"],
            "--k",
            "8",
            "--max-clusters",
            "16",
            "--bootstrap",
            "24",
            "--novelty",
            "8",
            "--maintenance-interval",
            "100",
            "--manager-policy",
            policy,
        ]
        if policy == "contextual":
            argv += [
                "--manager-context",
                str(
                    self.stage
                    / "preregistration"
                    / self.protocol["manager"]["contexts"][modality]["file"]
                ),
            ]
        self.arms.append(
            {
                "name": name,
                "modality": modality,
                "policy": policy,
                "backend": backend,
                "expected_count": len(rows),
                "directory": str(directory),
                "cwd": str(self.data / "streaming"),
                "argv": argv,
                "input_sha256": registered["input_sha256"],
                "manager_descriptor": descriptor,
            }
        )
        template = self.v.source_literal(
            self.provider, "You maintain a streaming semantic cluster catalog."
        )
        prompt = (
            template.replace("{task}", config["task"])
            .replace("{}", "[]", 1)
            .replace("{max_clusters}", "16")
        )
        if policy == "contextual":
            context = (
                self.stage
                / "preregistration"
                / self.protocol["manager"]["contexts"][modality]["file"]
            ).read_text()
            prompt = (
                self.v.source_literal(
                    self.provider, "{original}\n\nContextual manager policy."
                )
                .replace("{original}", prompt)
                .replace("{context}", context)
            )
        parts = [
            {"type": "input_text", "text": "Example 1. Current cluster: other."}
        ] + self.v._shared["evidence_parts"](rows[0], self.images)
        request = self.v._shared["sol_body"](
            [
                {"role": "developer", "content": prompt},
                {"role": "user", "content": parts},
            ],
            "cluster_plan",
            self.v.plan_schema(),
        )
        plan = {
            "operations": [
                {"op": "create", "name": c["name"], "description": c["description"]}
                for c in self.catalog
            ]
        }
        calls = [self.call("plan", request, self.response(self.v.SOL, plan))]
        request = self.v._shared["assignment_request"](
            backend, config["task"], rows[0], self.catalog, self.images
        )
        calls.append(
            self.call(
                "assign",
                request,
                self.response(
                    self.v.DECISIONS if backend == "ld" else self.v.SOL,
                    2 if backend == "ld" else {"cluster_id": "1"},
                ),
            )
        )
        self.journals = getattr(self, "journals", {})
        self.journals[name] = calls
        self.write(
            directory / "calls.jsonl",
            self.v.canonical(
                {"type": "ld-clustering-journal", "schema_version": 1, "run_id": name}
            )
            + b"\n"
            + b"".join(self.v.canonical(c) + b"\n" for c in calls),
        )
        with sqlite3.connect(directory / "state.sqlite") as db:
            db.executescript(
                "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE points(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL); CREATE TABLE clusters(id INTEGER PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,active INTEGER NOT NULL); CREATE TABLE assignments(point_id TEXT PRIMARY KEY REFERENCES points(id),cluster_id INTEGER REFERENCES clusters(id)); CREATE TABLE calls(id INTEGER PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL); CREATE TABLE reassignment(point_id TEXT PRIMARY KEY REFERENCES points(id),previous_cluster_id INTEGER,previous_assignment_known INTEGER NOT NULL DEFAULT 0);"
            )
            meta = {
                "config": json.dumps(config),
                "backend": backend,
                "manager_descriptor": json.dumps(descriptor),
                "input_sha256": registered["input_sha256"],
                "journal_run_id": name,
                "journal_path": str(directory / "calls.jsonl"),
                "journal_initialized": "1",
                "completed_count": str(len(rows)),
                "wall_ms": "100",
                "timing_complete": "true",
                "run_in_progress": "0",
            }
            db.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
            for c in self.catalog:
                db.execute(
                    "INSERT INTO clusters VALUES(?,?,?,?)",
                    (c["id"], c["name"], c["description"], 1),
                )
            for i, row in enumerate(rows):
                db.execute(
                    "INSERT INTO points VALUES(?,?,?)", (row["id"], i, json.dumps(row))
                )
                db.execute(
                    "INSERT INTO assignments VALUES(?,?)",
                    (row["id"], (1 if backend == "llm" else 2) if i == 0 else None),
                )
            for call in calls:
                db.execute(
                    "INSERT INTO calls(payload) VALUES(?)",
                    (json.dumps({k: call[k] for k in self.v.CALL_FIELDS}),),
                )
            events = [
                ("run_start", {"session": 1, "saved_count": 0, "prior_wall_ms": 0}),
                ("maintenance", plan),
                (
                    "catalog_update",
                    {
                        "policy": policy,
                        "before_sha256": self.v.sha(self.v.struct_json([])),
                        "after_sha256": self.v.sha(self.v.struct_json(self.catalog)),
                        "catalog_changed": True,
                        "catalog_change_count": 2,
                        "global_reconsideration": policy == "contextual",
                        "newly_queued": 0,
                        "pending_count": 0,
                    },
                ),
                (
                    "run_finish",
                    {"session": 1, "elapsed_ms": 100, "success": True, "error": None},
                ),
            ]
            db.executemany(
                "INSERT INTO events(kind,payload) VALUES(?,?)",
                [(k, json.dumps(v)) for k, v in events],
            )

    def measurement(self, modality, backend, policy="original"):
        name = f"{modality}-{policy}-{backend}"
        n = len(self.inputs[modality])
        calls = self.journals[name]
        usage = Counter()
        for call in calls:
            usage.update({k: v for k, v in call["usage"].items() if k != "cost_usd"})
        log = self.stage / name / "calls.jsonl"
        result = {
            "sample_count": n,
            "reassignment_evaluations": 0,
            "reassignment_id_moves": 0,
            "reassignment_unchanged": 0,
            "reassignment_origin_unknown": 0,
            "wall_seconds": 0.1,
            "timing_complete": True,
            "cost_usd": 0.0006 if backend == "llm" else 0.00031,
            "cost_complete": True,
            "calls": 2,
            "committed_success_calls": 2,
            "uncommitted_success_calls": 0,
            "assignment_calls": 1,
            "assignment_refusal_calls": 0,
            "run_sessions": 1,
            "timing_scope": "uninterrupted_loop",
            "maintenance_calls": 1,
            **usage,
            "request_seconds": 0.004,
            "error_calls": 0,
            "unknown_usage_calls": 0,
            "cluster_count": 2,
            "other_count": n - 1,
            "coverage": 1 - (n - 1) / n,
            "assignment_model": self.v.DECISIONS if backend == "ld" else self.v.SOL,
            "planner_model": self.v.SOL,
            "sol_reasoning_effort": "high",
            "journal_run_id": name,
            "journal_sha256": self.v.file_pin(log)["sha256"],
        }
        return result

    def audit(self):
        return self.v.audit_streaming(self.stage, self.data, self.repo)

    def write_journal(self, name):
        self.write(
            self.stage / name / "calls.jsonl",
            self.v.canonical(
                {"type": "ld-clustering-journal", "schema_version": 1, "run_id": name}
            )
            + b"\n"
            + b"".join(self.v.canonical(c) + b"\n" for c in self.journals[name]),
        )


class StreamingVerifierTests(unittest.TestCase):
    def test_terminal_streaming_audit_is_available(self):
        self.assertTrue(
            (ROOT / "scripts/verify_guided_streaming.py").is_file(),
            "offline terminal streaming verifier is missing",
        )

    def test_other_singletons_and_shared_other_sensitivity(self):
        v = helper()
        score = v.partition([None, None, 1, 1], [None, 2, 2, None])
        self.assertEqual(score["pairwise_f1"], 0)
        self.assertEqual(score["adjusted_rand_index"], -0.2)
        self.assertNotEqual(
            score, v.partition([None, None, 1, 1], [None, 2, 2, None], False)
        )

    def test_reassignment_origins_and_operations_are_not_semantic_corrections(self):
        v = helper()
        events = [
            (
                "reassign",
                {
                    "changed": True,
                    "previous_assignment_known": True,
                    "previous_cluster_id": 1,
                    "cluster_id": 2,
                },
            ),
            (
                "reassign",
                {
                    "changed": False,
                    "previous_assignment_known": True,
                    "previous_cluster_id": None,
                    "cluster_id": None,
                },
            ),
            (
                "reassign",
                {
                    "changed": None,
                    "previous_assignment_known": False,
                    "previous_cluster_id": None,
                    "cluster_id": 2,
                },
            ),
        ]
        result, _ = v.event_summaries(events, "original", [])
        self.assertEqual(
            result["reassignment"],
            {"evaluations": 3, "id_moves": 1, "unchanged": 1, "origin_unknown": 1},
        )
        events[0][1]["changed"] = False
        with self.assertRaisesRegex(ValueError, "origin"):
            v.event_summaries(events, "original", [])

    def test_full_terminal_eight_arm_audit_and_saved_numeric_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            result = f.audit()
            self.assertEqual(result["status"], "verified")
            self.assertEqual(len(result["arms"]), 8)
            self.assertEqual(len(result["comparisons"]), 4)
            self.assertTrue(result["cost_summary"]["cost_complete"])
            self.assertEqual(result["cost_summary"]["total_cost_usd"], "0.00364")
            path = f.stage / "comparisons/text-original.json"
            value = f.v.read(path)
            value["agreement"]["pairwise_f1"] = 0.9
            f.json(path, value)
            with self.assertRaisesRegex(ValueError, "pairwise_f1"):
                f.audit()

    def test_decimal_all_attempts_unknown_tier_and_cache_write_boundary(self):
        v = helper()
        body = {
            "model": v.SOL,
            "service_tier": "default",
            "usage": {
                "input_tokens": 300000,
                "output_tokens": 1000,
                "input_tokens_details": {
                    "cached_tokens": 100000,
                    "cache_write_tokens": 50000,
                },
            },
        }
        self.assertEqual(v.reprice(body, v.SOL)[0], Decimal(".885"))
        self.assertEqual(
            v.reprice({**body, "model": v.DECISIONS}, v.DECISIONS)[0], Decimal(".06")
        )
        self.assertEqual(
            v.reprice({**body, "service_tier": "priority"}, v.SOL)[1], "pricing"
        )

    def test_nonterminal_stage_is_refused_before_database_reads(self):
        v = helper()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "not terminal"):
                v.terminal_guard(Path(directory), [])

    def test_failed_partial_arm_keeps_every_attempt_and_unknown_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-ld"
            original = f.journals[name][-1]
            failed = {
                **original,
                "response": None,
                "error": "HTTP503",
                "http_status": 503,
                "usage_available": False,
                "usage": {
                    "input_tokens": 0,
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0,
                },
            }
            f.journals[name] = [f.journals[name][0], failed, {**original, "attempt": 2}]
            f.write_journal(name)
            f.write(f.stage / name / "exit-code.txt", b"1\n")
            f.write(f.stage / "supervisor-exit-code.txt", b"1\n")
            with sqlite3.connect(f.stage / name / "state.sqlite") as db:
                db.execute(
                    "DELETE FROM assignments WHERE point_id IN (SELECT id FROM points WHERE ordinal>=500)"
                )
                db.execute("DELETE FROM points WHERE ordinal>=500")
                db.execute("DELETE FROM meta WHERE key='completed_count'")
                db.execute("INSERT INTO meta VALUES('cost_history_complete','false')")
                db.execute(
                    "UPDATE events SET payload=? WHERE kind='run_finish'",
                    (
                        json.dumps(
                            {
                                "session": 1,
                                "elapsed_ms": 100,
                                "success": False,
                                "error": "later terminal failure",
                            }
                        ),
                    ),
                )
            result = f.audit()
            arm = result["arms"][name]
            self.assertEqual(result["status"], "verified_with_partial_streams")
            self.assertEqual(arm["persisted_count"], 500)
            self.assertEqual(
                (
                    arm["calls"],
                    arm["retry_attempts"],
                    arm["error_calls"],
                    arm["unknown_usage_calls"],
                ),
                (3, 1, 1, 1),
            )
            self.assertEqual(arm["known_cost_usd"], "0.00031")
            self.assertIsNone(arm["coverage"])
            self.assertIsNone(arm["total_cost_usd"])
            self.assertIsNone(result["comparisons"][0]["comparison"])
            self.assertFalse(result["cost_summary"]["cost_complete"])
            self.assertIsNone(result["cost_summary"]["total_cost_usd"])

    def test_sqlite_call_missing_from_journal_and_wrong_image_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "images-original-ld"
            call = f.journals[name][-1]
            call["request"]["input"][0]["content"][1]["image_url"] += "QQ=="
            f.write_journal(name)
            with self.assertRaisesRegex(ValueError, "unregistered"):
                f.audit()
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            with sqlite3.connect(f.stage / "text-original-ld/state.sqlite") as db:
                db.execute(
                    "UPDATE calls SET payload=replace(payload,'First','Changed') WHERE id=2"
                )
            with self.assertRaisesRegex(ValueError, "matching accepted"):
                f.audit()

    def test_source_renderer_preserves_evidence_braces(self):
        v = helper()
        self.assertEqual(
            v.render_source(
                "{original}\n{context}", original="category {context}", context="frozen"
            ),
            "category {context}\nfrozen",
        )

    def test_unpaired_journal_never_silently_discards_recorded_charges(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-llm"
            (f.stage / name / "state.sqlite").unlink()
            f.write(f.stage / name / "exit-code.txt", b"1\n")
            f.write(f.stage / "supervisor-exit-code.txt", b"1\n")
            self.assertTrue((f.stage / name / "calls.jsonl").is_file())
            with self.assertRaisesRegex(ValueError, "unpaired"):
                f.audit()

    def test_fresh_cli_output_is_preserved_before_any_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("keep")
            process = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts/verify_guided_streaming.py"),
                    "--run-root",
                    str(Path(directory) / "unstarted"),
                    "--data-root",
                    str(Path(directory) / "no-data"),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("fresh path", process.stderr)
            self.assertEqual(output.read_text(), "keep")

    def test_final_assignment_cannot_disagree_with_accepted_raw_response(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            with sqlite3.connect(f.stage / "text-original-llm/state.sqlite") as db:
                db.execute(
                    "UPDATE assignments SET cluster_id=2 WHERE point_id='text-0'"
                )
            with self.assertRaisesRegex(ValueError, "final assignments"):
                f.audit()

    def test_nonzero_prior_without_origin_session_cannot_claim_complete_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            with sqlite3.connect(f.stage / "text-original-llm/state.sqlite") as db:
                db.execute("UPDATE meta SET value='150' WHERE key='wall_ms'")
                db.execute(
                    "UPDATE events SET payload=? WHERE kind='run_start'",
                    (
                        json.dumps(
                            {"session": 1, "saved_count": 10, "prior_wall_ms": 50}
                        ),
                    ),
                )
            path = f.stage / "comparisons/text-original.json"
            saved = f.v.read(path)
            saved["baseline"]["wall_seconds"] = 0.15
            saved["baseline"]["timing_scope"] = "cumulative_active_loops"
            f.json(path, saved)
            with self.assertRaisesRegex(ValueError, "timing_complete"):
                f.audit()

    def test_self_consistent_wrong_dynamic_page_and_response_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-ld"
            original = json.loads(json.dumps(f.journals[name][-1]))
            for mutation, message in (
                ("definition", "candidate"),
                ("choice", "outside requested page"),
            ):
                call = json.loads(json.dumps(original))
                if mutation == "definition":
                    call["request"]["questions"][0]["choices"][0][
                        "description"
                    ] = "One: forged criteria"
                else:
                    call["response"]["answers"][0]["choice"] = "999"
                f.journals[name][-1] = call
                f.write_journal(name)
                with sqlite3.connect(f.stage / name / "state.sqlite") as db:
                    db.execute(
                        "UPDATE calls SET payload=? WHERE id=2",
                        (json.dumps({k: call[k] for k in f.v.CALL_FIELDS}),),
                    )
                with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    ValueError, message
                ):
                    f.audit()

    def test_self_consistent_manager_marker_cannot_leak_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-llm"
            call = f.journals[name][0]
            call["request"]["input"][1]["content"][0][
                "source_path"
            ] = "private-source-name"
            f.write_journal(name)
            with sqlite3.connect(f.stage / name / "state.sqlite") as db:
                db.execute(
                    "UPDATE calls SET payload=? WHERE id=1",
                    (json.dumps({k: call[k] for k in f.v.CALL_FIELDS}),),
                )
            path = f.stage / "comparisons/text-original.json"
            saved = f.v.read(path)
            saved["baseline"]["journal_sha256"] = f.v.file_pin(
                f.stage / name / "calls.jsonl"
            )["sha256"]
            f.json(path, saved)
            with self.assertRaisesRegex(ValueError, "marker"):
                f.audit()

    def test_refusals_are_per_request_and_failed_known_usage_is_charged(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-ld"
            original = f.journals[name][-1]
            refusal = json.loads(json.dumps(original))
            refusal["response"]["answers"] = [{"type": "refusal", "name": "cluster"}]
            refusal["refusal"] = True
            failed = {**original, "error": "HTTP503", "http_status": 503}
            f.journals[name] = [
                f.journals[name][0],
                failed,
                {**original, "attempt": 2},
                refusal,
                refusal,
            ]
            f.write_journal(name)
            rows = f.inputs["text"]
            evidence = {
                f.v.canonical(f.v._shared["evidence_parts"](item, {})): item
                for item in rows
            }
            ledger, _, _ = f.v.journal(
                f.stage / name / "calls.jsonl",
                "ld",
                f.protocol["modalities"]["text"]["config"],
                None,
                f.provider,
                evidence,
                True,
            )
            self.assertEqual(
                (ledger["calls"], ledger["error_calls"], ledger["retry_attempts"]),
                (5, 1, 1),
            )
            self.assertEqual(
                (ledger["raw_refusal_attempts"], ledger["assignment_refusal_calls"]),
                (2, 2),
            )
            self.assertEqual(ledger["known_cost_usd"], "0.00034")

    def test_catalog_replay_preserves_ids_through_rename_merge_split_retire(self):
        v = helper()
        catalog, next_id = v.apply_catalog(
            [],
            1,
            {
                "operations": [
                    {"op": "create", "name": "A", "description": "a"},
                    {"op": "create", "name": "B", "description": "b"},
                ]
            },
            16,
        )
        catalog, next_id = v.apply_catalog(
            catalog,
            next_id,
            {
                "operations": [
                    {
                        "op": "rename",
                        "id": 1,
                        "name": "Renamed",
                        "description": "same scope",
                    }
                ]
            },
            16,
        )
        self.assertEqual((catalog[0]["id"], next_id), (1, 3))
        catalog, next_id = v.apply_catalog(
            catalog,
            next_id,
            {
                "operations": [
                    {
                        "op": "merge",
                        "ids": [1, 2],
                        "name": "Parent",
                        "description": "both",
                    }
                ]
            },
            16,
        )
        self.assertEqual([c["id"] for c in catalog], [3])
        catalog, next_id = v.apply_catalog(
            catalog,
            next_id,
            {
                "operations": [
                    {
                        "op": "split",
                        "id": 3,
                        "children": [
                            {"name": "C", "description": "c"},
                            {"name": "D", "description": "d"},
                        ],
                    }
                ]
            },
            16,
        )
        catalog, next_id = v.apply_catalog(
            catalog, next_id, {"operations": [{"op": "retire", "id": 4}]}, 16
        )
        self.assertEqual(([c["id"] for c in catalog], next_id), ([5], 6))

    def test_empty_catalog_reevaluation_needs_no_request_and_precedes_follow_on_plan(
        self,
    ):
        v = helper()
        a = [{"id": 1, "name": "A", "description": "a"}]
        b = [{"id": 2, "name": "B", "description": "b"}]
        plans = [
            {"operations": [{"op": "create", "name": "A", "description": "a"}]},
            {"operations": [{"op": "retire", "id": 1}]},
            {"operations": [{"op": "create", "name": "B", "description": "b"}]},
        ]
        updates = [
            {
                "before_sha256": v.sha(v.struct_json(before)),
                "after_sha256": v.sha(v.struct_json(after)),
                "catalog_change_count": 1,
                "pending_count": pending,
            }
            for before, after, pending in [([], a, 0), (a, [], 1), ([], b, 1)]
        ]
        calls, frames = [], []

        def add(phase, **binding):
            call = {
                "phase": phase,
                "model": "synthetic",
                "request": {"sequence": len(calls)},
                "response": {},
                "elapsed_ms": 0,
                "usage": {},
            }
            calls.append(call)
            frames.append(
                {
                    "phase": "plan" if phase == "plan" else "assign",
                    "failed": False,
                    "key": v.call_key(call),
                    **binding,
                }
            )

        add("plan", catalog=[], plan=plans[0])
        add(
            "assign",
            page_choices=[{"value": "1", "description": "A: a"}],
            item_id="p",
            outcome=(1, False),
        )
        add("plan", catalog=a, plan=plans[1])
        add("plan", catalog=[], plan=plans[2])
        add(
            "reassign",
            page_choices=[{"value": "2", "description": "B: b"}],
            item_id="p",
            outcome=(2, False),
        )
        events = [
            {
                "_catalog_epoch": 2,
                "point_id": "p",
                "cluster_id": None,
                "interim_cluster_id": None,
                "previous_cluster_id": 1,
                "previous_assignment_known": True,
                "changed": True,
            },
            {
                "_catalog_epoch": 3,
                "point_id": "p",
                "cluster_id": 2,
                "interim_cluster_id": None,
                "previous_cluster_id": None,
                "previous_assignment_known": True,
                "changed": True,
            },
        ]
        args = (
            frames,
            calls,
            plans,
            updates,
            b,
            {"k": 8, "max_clusters": 16},
            False,
            {"p": 2},
        )
        v.replay_catalog_requests(*args, events)
        named_without_request = [{**events[0], "cluster_id": 1}, events[1]]
        with self.assertRaisesRegex(ValueError, "empty-catalog"):
            v.replay_catalog_requests(*args, named_without_request)
        missing_nonempty_request = [{**events[0], "_catalog_epoch": 1}, events[1]]
        with self.assertRaisesRegex(ValueError, "skipped committed"):
            v.replay_catalog_requests(*args, missing_nonempty_request)
        retired_prefix = (
            frames[:3],
            calls[:3],
            plans[:2],
            updates[:2],
            [],
            {"k": 8, "max_clusters": 16},
        )
        with self.assertRaisesRegex(ValueError, "missing committed reevaluation"):
            v.replay_catalog_requests(*retired_prefix, False, {"p": None}, [])
        v.replay_catalog_requests(*retired_prefix, True, {"p": None}, [])

    def test_failed_impossible_cache_usage_remains_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-ld"
            failed = json.loads(json.dumps(f.journals[name][-1]))
            failed["response"]["usage"]["input_tokens_details"] = {"cached_tokens": 101}
            failed.update(
                error="invalid provider usage",
                usage={
                    "input_tokens": 0,
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0,
                },
            )
            f.journals[name] = [f.journals[name][0], failed]
            f.write_journal(name)
            evidence = {
                f.v.canonical(f.v._shared["evidence_parts"](item, {})): item
                for item in f.inputs["text"]
            }
            ledger, _, _ = f.v.journal(
                f.stage / name / "calls.jsonl",
                "ld",
                f.protocol["modalities"]["text"]["config"],
                None,
                f.provider,
                evidence,
                False,
            )
            self.assertEqual(ledger["unknown_usage_calls"], 1)
            self.assertEqual(ledger["known_cost_usd"], "0.0003")

    def test_unknown_returned_tier_keeps_known_subtotal_and_frozen_estimate_separate(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(Path(directory))
            name = "text-original-llm"
            call = f.journals[name][-1]
            del call["response"]["service_tier"]
            f.write_journal(name)
            with sqlite3.connect(f.stage / name / "state.sqlite") as db:
                db.execute(
                    "UPDATE calls SET payload=? WHERE id=2",
                    (json.dumps({k: call[k] for k in f.v.CALL_FIELDS}),),
                )
            path = f.stage / "comparisons/text-original.json"
            saved = f.v.read(path)
            saved["baseline"]["journal_sha256"] = f.v.file_pin(
                f.stage / name / "calls.jsonl"
            )["sha256"]
            f.json(path, saved)
            result = f.audit()
            arm = result["arms"][name]
            self.assertEqual(arm["unknown_pricing_calls"], 1)
            self.assertEqual(arm["known_cost_usd"], "0.0003")
            self.assertTrue(arm["measurement"]["cost_complete"])
            self.assertFalse(arm["cost_complete"])
            self.assertIsNone(result["cost_summary"]["total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
