use crate::{
    metrics,
    types::{CallRecord, Item},
};
use anyhow::{Context, Result, ensure};
use rusqlite::{Connection, OpenFlags};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::Path;

struct Run {
    measurement: Value,
    config: Value,
    input_sha256: String,
    assignments: Vec<(Item, Option<i64>)>,
}

pub const JOURNAL_FORMAT: &str = "ld-clustering-journal";

fn record_fingerprint(call: &CallRecord) -> Result<String> {
    let mut value = serde_json::to_value(call)?;
    // The engine labels successful reassignment calls after the provider journals them.
    value.as_object_mut().unwrap().remove("phase");
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(&value)?)))
}

fn committed_calls(db: &Connection, successes: &mut HashMap<String, usize>) -> Result<usize> {
    let mut count = 0;
    let mut stmt = db.prepare("SELECT payload FROM calls ORDER BY id")?;
    for payload in stmt.query_map([], |row| row.get::<_, String>(0))? {
        let call: CallRecord = serde_json::from_str(&payload?)?;
        let remaining = successes.get_mut(&record_fingerprint(&call)?).context(
            "SQLite successful call is missing from request journal (wrong or truncated log)",
        )?;
        ensure!(
            *remaining > 0,
            "request journal has fewer matching successful attempts than SQLite"
        );
        *remaining -= 1;
        count += 1;
    }
    Ok(count)
}

/// Verify persisted call coverage before spending on a resumed run.
pub fn verify_request_journal(db: &Connection, path: &Path) -> Result<()> {
    let text = std::fs::read_to_string(path)?;
    let mut lines = text.lines();
    let header: Value = serde_json::from_str(lines.next().context("request journal is empty")?)?;
    let run_id: String = db.query_row(
        "SELECT value FROM meta WHERE key='journal_run_id'",
        [],
        |r| r.get(0),
    )?;
    ensure!(
        header["type"] == JOURNAL_FORMAT
            && header["schema_version"] == 1
            && header["run_id"] == run_id,
        "request journal header does not match database run identity"
    );
    let mut successes = HashMap::<String, usize>::new();
    for line in lines.filter(|line| !line.trim().is_empty()) {
        let row: Value = serde_json::from_str(line)?;
        ensure!(
            row.get("error").is_some(),
            "journal row has no attempt outcome"
        );
        if row["error"].is_null() {
            let call: CallRecord = serde_json::from_value(row)?;
            *successes.entry(record_fingerprint(&call)?).or_default() += 1;
        }
    }
    committed_calls(db, &mut successes)?;
    Ok(())
}

fn read_run(database: &Path, log: &Path, expected: usize, backend: &str) -> Result<Run> {
    let db = Connection::open_with_flags(database, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let meta = |key: &str| -> Result<String> {
        Ok(db.query_row("SELECT value FROM meta WHERE key=?", [key], |r| r.get(0))?)
    };
    ensure!(meta("backend")? == backend, "unexpected assignment backend");
    ensure!(
        meta("completed_count")?.parse::<usize>()? == expected,
        "run is not complete at the expected count"
    );
    let point_count: usize = db.query_row("SELECT COUNT(*) FROM points", [], |r| r.get(0))?;
    let assignment_count: usize =
        db.query_row("SELECT COUNT(*) FROM assignments", [], |r| r.get(0))?;
    ensure!(
        point_count == expected && assignment_count == expected,
        "persisted point or assignment count differs from requested sample count"
    );
    let pending: usize = db.query_row("SELECT COUNT(*) FROM reassignment", [], |r| r.get(0))?;
    ensure!(pending == 0, "maintenance reassignment is incomplete");
    let mut stmt=db.prepare("SELECT p.payload,a.cluster_id FROM points p JOIN assignments a ON a.point_id=p.id ORDER BY p.ordinal")?;
    let rows = stmt
        .query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Option<i64>>(1)?))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    ensure!(
        rows.len() == expected,
        "point count differs from requested sample count"
    );
    let assignments = rows
        .into_iter()
        .map(|(s, c)| Ok((serde_json::from_str(&s)?, c)))
        .collect::<Result<Vec<(Item, Option<i64>)>>>()?;
    let clusters: usize =
        db.query_row("SELECT COUNT(*) FROM clusters WHERE active=1", [], |r| {
            r.get(0)
        })?;
    let inactive_assignments: usize = db.query_row(
        "SELECT COUNT(*) FROM assignments a JOIN clusters c ON c.id=a.cluster_id WHERE c.active=0",
        [],
        |r| r.get(0),
    )?;
    ensure!(
        inactive_assignments == 0,
        "assignments reference retired clusters"
    );
    let other = assignments.iter().filter(|(_, c)| c.is_none()).count();
    let journal = std::fs::read_to_string(log)?;
    let mut lines = journal.lines();
    let header: Value = serde_json::from_str(lines.next().context("request journal is empty")?)?;
    let run_id = meta("journal_run_id").context("database is not bound to a request journal")?;
    ensure!(
        header["type"] == JOURNAL_FORMAT
            && header["schema_version"] == 1
            && header["run_id"] == run_id,
        "request journal header does not match database run identity"
    );
    let mut calls = 0;
    let mut assignment_calls = 0;
    let mut maintenance_calls = 0;
    let mut errors = 0;
    let mut input_tokens = 0;
    let mut output_tokens = 0;
    let mut cached_tokens = 0;
    let mut cache_write_tokens = 0;
    let mut cost_usd = 0.;
    let mut request_ms = 0_u64;
    let mut cost_complete = true;
    let mut successes = HashMap::<String, usize>::new();
    for line in lines.filter(|line| !line.trim().is_empty()) {
        let raw: Value = serde_json::from_str(line)?;
        let call: CallRecord = serde_json::from_value(raw.clone())?;
        ensure!(
            raw.get("error").is_some() && raw["usage_available"].is_boolean(),
            "journal row is missing attempt outcome fields"
        );
        let failed = !raw["error"].is_null();
        ensure!(
            !failed || raw["error"].is_string(),
            "journal error must be a string or null"
        );
        let expected_model = match call.phase.as_str() {
            "assign" => {
                assignment_calls += 1;
                if backend == "ld" {
                    "gpt-6-luna"
                } else {
                    "gpt-6.1-sol"
                }
            }
            "plan" => {
                maintenance_calls += 1;
                "gpt-6.1-sol"
            }
            _ => anyhow::bail!("unknown provider phase {}", call.phase),
        };
        ensure!(
            call.model == expected_model && call.request["model"] == expected_model,
            "journal model differs from the pinned experiment model"
        );
        if expected_model == "gpt-6.1-sol" {
            ensure!(
                call.request["reasoning"]["effort"] == "high",
                "Sol request does not use high reasoning"
            );
        }
        if !failed {
            ensure!(
                raw["http_status"]
                    .as_u64()
                    .is_some_and(|s| (200..300).contains(&s)),
                "successful journal call has no successful HTTP status"
            );
            ensure!(
                call.response["model"] == expected_model,
                "successful response model differs from the pinned model"
            );
        }
        let has_usage = call.response["usage"]["input_tokens"].is_u64()
            && call.response["usage"]["output_tokens"].is_u64();
        ensure!(
            raw["usage_available"] == has_usage,
            "usage availability flag disagrees with raw provider usage"
        );
        let usage = if raw["usage_available"] == true {
            crate::provider::token_usage(&call.response, expected_model == "gpt-6-luna")
                .context("cannot recompute journal token charges")?
        } else {
            ensure!(failed, "successful journal call has no reported usage");
            cost_complete = false;
            crate::types::Usage::default()
        };
        ensure!(
            usage.input_tokens == call.usage.input_tokens
                && usage.output_tokens == call.usage.output_tokens
                && usage.cached_tokens == call.usage.cached_tokens
                && usage.cache_write_tokens == call.usage.cache_write_tokens
                && (usage.cost_usd - call.usage.cost_usd).abs() < 1e-12,
            "stored usage or cost disagrees with the raw provider usage"
        );
        calls += 1;
        errors += usize::from(failed);
        input_tokens += usage.input_tokens;
        output_tokens += usage.output_tokens;
        cached_tokens += usage.cached_tokens;
        cache_write_tokens += usage.cache_write_tokens;
        cost_usd += usage.cost_usd;
        request_ms += call.elapsed_ms;
        if !failed {
            *successes.entry(record_fingerprint(&call)?).or_default() += 1;
        }
    }
    ensure!(calls > 0, "request journal has no measured calls");
    let committed_success_calls = committed_calls(&db, &mut successes)?;
    ensure!(
        committed_success_calls > 0,
        "database has no committed provider calls"
    );
    let uncommitted_success_calls: usize = successes.values().sum();
    let wall_seconds = meta("wall_ms")?.parse::<u64>()? as f64 / 1000.;
    let timing_complete = meta("timing_complete").is_ok_and(|s| s == "true")
        && meta("run_in_progress").is_ok_and(|s| s == "0");
    Ok(Run {
        measurement: json!({"sample_count":expected,"wall_seconds":wall_seconds,"timing_complete":timing_complete,"cost_usd":cost_usd,"cost_complete":cost_complete,"calls":calls,"committed_success_calls":committed_success_calls,"uncommitted_success_calls":uncommitted_success_calls,"assignment_calls":assignment_calls,"maintenance_calls":maintenance_calls,"input_tokens":input_tokens,"output_tokens":output_tokens,"cached_tokens":cached_tokens,"cache_write_tokens":cache_write_tokens,"request_seconds":request_ms as f64/1000.,"error_calls":errors,"cluster_count":clusters,"other_count":other,"coverage":1.-other as f64/expected as f64,"assignment_model":if backend == "ld" {"gpt-6-luna"}else{"gpt-6.1-sol"},"planner_model":"gpt-6.1-sol","sol_reasoning_effort":"high","pricing_date":"2026-10-20","journal_run_id":run_id,"journal_sha256":format!("{:x}",Sha256::digest(journal.as_bytes()))}),
        config: serde_json::from_str(&meta("config")?)?,
        input_sha256: meta("input_sha256")?,
        assignments,
    })
}

pub fn compare_runs(
    baseline: &Path,
    baseline_log: &Path,
    ld: &Path,
    ld_log: &Path,
    expected: usize,
) -> Result<Value> {
    ensure!(expected > 0, "expected count must be positive");
    let baseline = read_run(baseline, baseline_log, expected, "llm")?;
    let ld = read_run(ld, ld_log, expected, "ld")?;
    ensure!(baseline.config == ld.config, "run configurations differ");
    ensure!(
        baseline.input_sha256 == ld.input_sha256,
        "run input hashes differ"
    );
    ensure!(
        baseline
            .assignments
            .iter()
            .zip(&ld.assignments)
            .all(|((a, _), (b, _))| a == b),
        "run item identities/order differ"
    );
    let labels = |run: &Run, singleton_other: bool| -> Vec<String> {
        run.assignments
            .iter()
            .map(|(p, c)| match c {
                Some(id) => format!("cluster:{id}"),
                None if singleton_other => format!("other:{}", p.id),
                None => "other".into(),
            })
            .collect()
    };
    let reference = labels(&baseline, true);
    let candidate = labels(&ld, true);
    let agreement = metrics::compare(&reference, &candidate)?;
    let shared_other = metrics::compare(&labels(&baseline, false), &labels(&ld, false))?;
    let ground_truth=baseline.assignments.iter().map(|(p,_)|p.label.clone()).collect::<Option<Vec<_>>>().map(|truth|->Result<Value>{Ok(json!({"baseline":metrics::compare(&truth,&reference)?,"ld":metrics::compare(&truth,&candidate)?}))}).transpose()?;
    Ok(
        json!({"status":"complete","expected_count":expected,"config":baseline.config,"input_sha256":baseline.input_sha256,"baseline":baseline.measurement,"ld":ld.measurement,"agreement":agreement,"shared_other_sensitivity":shared_other,"dataset_label_agreement":ground_truth}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::Usage;
    use rusqlite::params;

    fn call() -> CallRecord {
        CallRecord {
            phase: "plan".into(),
            model: "gpt-6.1-sol".into(),
            request: json!({"model":"gpt-6.1-sol","reasoning":{"effort":"high"},"input":"Group examples"}),
            response: json!({"model":"gpt-6.1-sol","status":"completed","usage":{"input_tokens":100,"output_tokens":10}}),
            elapsed_ms: 100,
            usage: Usage {
                input_tokens: 100,
                cached_tokens: 0,
                cache_write_tokens: 0,
                output_tokens: 10,
                cost_usd: 0.0003,
            },
        }
    }

    fn fixture(database: &Path, backend: &str, record: &CallRecord) -> Result<()> {
        let db = Connection::open(database)?;
        db.execute_batch("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE points(id TEXT PRIMARY KEY,ordinal INTEGER,payload TEXT); CREATE TABLE assignments(point_id TEXT,cluster_id INTEGER); CREATE TABLE clusters(id INTEGER,name TEXT,description TEXT,active INTEGER); CREATE TABLE reassignment(point_id TEXT); CREATE TABLE calls(id INTEGER PRIMARY KEY,payload TEXT);")?;
        for (key, value) in [
            ("backend", backend),
            ("completed_count", "2"),
            ("wall_ms", "2000"),
            ("config", "{}"),
            ("input_sha256", "same-hash"),
            ("timing_complete", "true"),
            ("run_in_progress", "0"),
            ("journal_run_id", backend),
            ("journal_initialized", "1"),
        ] {
            db.execute("INSERT INTO meta VALUES (?,?)", params![key, value])?;
        }
        db.execute("INSERT INTO clusters VALUES(1,'A','A',1)", [])?;
        for i in 0..2 {
            db.execute(
                "INSERT INTO points VALUES(?,?,?)",
                params![
                    i.to_string(),
                    i,
                    json!({"id":i.to_string(),"text":"example"}).to_string()
                ],
            )?;
            db.execute("INSERT INTO assignments VALUES(?,1)", [i.to_string()])?;
        }
        db.execute(
            "INSERT INTO calls(payload) VALUES(?)",
            [serde_json::to_string(record)?],
        )?;
        Ok(())
    }

    #[test]
    fn complete_databases_reject_one_unrelated_shared_journal() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let baseline = dir.path().join("llm.sqlite");
        let ld = dir.path().join("ld.sqlite");
        fixture(&baseline, "llm", &call())?;
        fixture(&ld, "ld", &call())?;
        let log = dir.path().join("unrelated.jsonl");
        let mut row = serde_json::to_value(call())?;
        row["error"] = Value::Null;
        row["usage_available"] = json!(true);
        std::fs::write(&log, format!("{row}\n"))?;
        assert!(
            compare_runs(&baseline, &log, &ld, &log, 2).is_err(),
            "a wrong shared log was accepted as complete measured evidence"
        );
        Ok(())
    }

    fn write_log(path: &Path, backend: &str, records: &[Value]) -> Result<()> {
        let header = json!({"type":JOURNAL_FORMAT,"schema_version":1,"run_id":backend});
        let mut text = format!("{header}\n");
        for row in records {
            text.push_str(&format!("{row}\n"));
        }
        std::fs::write(path, text)?;
        Ok(())
    }

    fn success(record: &CallRecord) -> Value {
        let mut row = serde_json::to_value(record).unwrap();
        row["error"] = Value::Null;
        row["usage_available"] = json!(true);
        row["http_status"] = json!(200);
        row["attempt"] = json!(1);
        row
    }

    #[test]
    fn valid_logs_match_sqlite_ignore_phase_and_report_real_orphan_costs() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let database = dir.path().join("run.sqlite");
        let log = dir.path().join("requests.jsonl");
        let mut committed = call();
        committed.phase = "reassign".into();
        let mut observed = committed.clone();
        observed.phase = "assign".into();
        fixture(&database, "llm", &committed)?;
        write_log(&log, "llm", &[success(&observed), success(&call())])?;
        verify_request_journal(&Connection::open(&database)?, &log)?;
        let run = read_run(&database, &log, 2, "llm")?;
        assert_eq!(run.measurement["committed_success_calls"], 1);
        assert_eq!(run.measurement["uncommitted_success_calls"], 1);
        assert_eq!(run.measurement["cost_complete"], true);
        assert_eq!(run.measurement["timing_complete"], true);
        assert!((run.measurement["cost_usd"].as_f64().unwrap() - 0.0006).abs() < 1e-12);
        Ok(())
    }

    #[test]
    fn truncated_journal_is_rejected_before_resume_and_comparison() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let database = dir.path().join("run.sqlite");
        let log = dir.path().join("requests.jsonl");
        fixture(&database, "llm", &call())?;
        write_log(&log, "llm", &[])?;
        assert!(verify_request_journal(&Connection::open(&database)?, &log).is_err());
        assert!(read_run(&database, &log, 2, "llm").is_err());
        let mut wrong = call();
        wrong.elapsed_ms += 1;
        write_log(&log, "llm", &[success(&wrong)])?;
        assert!(verify_request_journal(&Connection::open(&database)?, &log).is_err());
        Ok(())
    }

    #[test]
    fn altered_costs_models_and_usage_are_rejected() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let database = dir.path().join("run.sqlite");
        let log = dir.path().join("requests.jsonl");
        fixture(&database, "llm", &call())?;
        for (field, value) in [
            ("cost", json!(0.)),
            ("model", json!("another-model")),
            ("usage", json!(false)),
        ] {
            let mut row = success(&call());
            match field {
                "cost" => row["usage"]["cost_usd"] = value,
                "model" => row["model"] = value,
                _ => row["usage_available"] = value,
            }
            write_log(&log, "llm", &[row])?;
            assert!(
                read_run(&database, &log, 2, "llm").is_err(),
                "accepted tampered {field}"
            );
        }
        Ok(())
    }

    #[test]
    fn missing_usage_and_unclean_timing_are_explicitly_incomplete() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let database = dir.path().join("run.sqlite");
        let log = dir.path().join("requests.jsonl");
        fixture(&database, "llm", &call())?;
        let mut failure = success(&call());
        failure["error"] = json!("unknown server outcome");
        failure["http_status"] = json!(500);
        failure["response"] = json!({"error":"server"});
        failure["usage_available"] = json!(false);
        failure["usage"] = serde_json::to_value(Usage::default())?;
        write_log(&log, "llm", &[success(&call()), failure])?;
        let db = Connection::open(&database)?;
        db.execute(
            "UPDATE meta SET value='false' WHERE key='timing_complete'",
            [],
        )?;
        let run = read_run(&database, &log, 2, "llm")?;
        assert_eq!(run.measurement["cost_complete"], false);
        assert_eq!(run.measurement["timing_complete"], false);
        assert_eq!(run.measurement["error_calls"], 1);
        assert!((run.measurement["cost_usd"].as_f64().unwrap() - 0.0003).abs() < 1e-12);
        Ok(())
    }
}
