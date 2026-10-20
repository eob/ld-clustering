//! Assignment-only image control with one immutable catalog shared by both arms.
use anyhow::{Context, Result, bail, ensure};
use clap::Parser;
use ld_clustering::{
    metrics,
    provider::OpenAi,
    types::{CallRecord, Cluster, Item, Model, Usage},
};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs::{File, OpenOptions},
    io::{Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    process::Command,
    time::{Instant, SystemTime, UNIX_EPOCH},
};

const TASK: &str = "Group clothing images by the visible kind of garment, footwear, or accessory, rather than color, style, orientation, or background. Create coherent reusable groups from observed evidence. Keep unclear or unrelated images in Other when no group fits.";

#[derive(Parser)]
#[command(about = "Measure assignment-only LLM/Decisions behavior using one frozen image catalog")]
struct Args {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    catalog: PathBuf,
    #[arg(long,value_parser=["llm","ld"])]
    mode: String,
    #[arg(long, default_value_t = 8)]
    k: usize,
    #[arg(long, default_value_t = 100)]
    expected: usize,
    #[arg(long)]
    log: PathBuf,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Serialize)]
struct Assignment {
    id: String,
    cluster_id: Option<i64>,
    label: Option<String>,
}

async fn assign_pages<M: Model>(
    model: &M,
    task: &str,
    item: &Item,
    catalog: &[Cluster],
    k: usize,
) -> Result<Option<i64>> {
    ensure!((1..=254).contains(&k), "k must be between 1 and 254");
    for page in catalog.chunks(k) {
        let reply = model.assign(task, item, page).await?;
        if let Some(id) = reply.value {
            ensure!(
                page.iter().any(|c| c.id == id),
                "model selected a cluster outside its candidate page"
            );
            return Ok(Some(id));
        }
    }
    Ok(None)
}

fn reserve_artifacts(paths: &[&Path]) -> Result<Vec<File>> {
    let mut files = Vec::new();
    for path in paths {
        match OpenOptions::new().write(true).create_new(true).open(path) {
            Ok(file) => files.push(file),
            Err(error) => {
                // Only files created by this reservation are eligible for cleanup.
                let created_count = files.len();
                drop(files);
                for created in &paths[..created_count] {
                    let _ = std::fs::remove_file(created);
                }
                return Err(error)
                    .with_context(|| format!("artifact path must be fresh: {}", path.display()));
            }
        }
    }
    Ok(files)
}

fn completion_status(success: bool, processed: usize, expected: usize) -> &'static str {
    if success && processed == expected {
        "complete"
    } else {
        "failed"
    }
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn input_fingerprint(bytes: &[u8], items: &[Item]) -> Result<String> {
    let mut digest = Sha256::new();
    digest.update(b"ld-clustering-input-v1\0");
    digest.update((bytes.len() as u64).to_le_bytes());
    digest.update(bytes);
    for item in items {
        let image = item
            .image
            .as_deref()
            .context("image control requires image evidence for every point")?;
        ensure!(
            !image.starts_with("http://") && !image.starts_with("https://"),
            "download remote image evidence before running the reproducible control"
        );
        if !image.starts_with("data:image/") {
            let bytes = std::fs::read(image).context("hash local image evidence")?;
            digest.update(b"local-image\0");
            digest.update((bytes.len() as u64).to_le_bytes());
            digest.update(bytes);
        }
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn source_version() -> Result<Value> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let output = Command::new("git")
        .current_dir(root)
        .args(["rev-parse", "HEAD"])
        .output()?;
    ensure!(output.status.success(), "cannot identify the source commit");
    let commit = String::from_utf8(output.stdout)?.trim().to_owned();
    let sources: &[(&str, &[u8])] = &[
        (
            "examples/frozen_catalog.rs",
            include_bytes!("frozen_catalog.rs"),
        ),
        ("src/provider.rs", include_bytes!("../src/provider.rs")),
        ("src/types.rs", include_bytes!("../src/types.rs")),
        ("src/metrics.rs", include_bytes!("../src/metrics.rs")),
        ("src/lib.rs", include_bytes!("../src/lib.rs")),
        ("Cargo.toml", include_bytes!("../Cargo.toml")),
        ("Cargo.lock", include_bytes!("../Cargo.lock")),
    ];
    let mut hashes = serde_json::Map::new();
    for (path, embedded) in sources {
        let tracked = Command::new("git")
            .current_dir(root)
            .args(["show", &format!("{commit}:{path}")])
            .output()?;
        ensure!(
            tracked.status.success() && tracked.stdout == *embedded,
            "commit the exact control source before running: {path}"
        );
        ensure!(
            std::fs::read(root.join(path))? == *embedded,
            "source changed after this control executable was built: {path}"
        );
        hashes.insert((*path).to_owned(), json!(sha256(embedded)));
    }
    Ok(
        json!({"commit":commit,"embedded_file_sha256":hashes,"executable_sha256":sha256(&std::fs::read(std::env::current_exe()?)?)}),
    )
}

fn append(file: &mut impl Write, value: &Value) -> Result<()> {
    serde_json::to_writer(&mut *file, value)?;
    file.write_all(b"\n")?;
    file.flush()?;
    Ok(())
}

fn write_output(file: &mut File, value: &Value) -> Result<()> {
    file.set_len(0)?;
    file.seek(SeekFrom::Start(0))?;
    serde_json::to_writer_pretty(&mut *file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

async fn process<M: Model>(
    model: &M,
    items: &[Item],
    catalog: &[Cluster],
    k: usize,
    assignments: &mut Vec<Assignment>,
    progress: &mut impl Write,
) -> Result<()> {
    for (ordinal, item) in items.iter().enumerate() {
        let cluster_id = assign_pages(model, TASK, item, catalog, k).await?;
        append(
            progress,
            &json!({"type":"assignment","ordinal":ordinal,"id":item.id,"cluster_id":cluster_id}),
        )?;
        assignments.push(Assignment {
            id: item.id.clone(),
            cluster_id,
            label: item.label.clone(),
        });
        eprintln!("processed {} / {}", assignments.len(), items.len());
    }
    Ok(())
}

fn journal_summary(path: &Path, run_id: &str, mode: &str, k: usize) -> Result<Value> {
    let text = std::fs::read_to_string(path)?;
    let mut lines = text.lines();
    let header: Value =
        serde_json::from_str(lines.next().context("missing request journal header")?)?;
    ensure!(
        header["type"] == "ld-clustering-frozen-journal" && header["run_id"] == run_id,
        "request journal identity differs from this control"
    );
    let expected_model = if mode == "ld" {
        "gpt-6-luna"
    } else {
        "gpt-6.1-sol"
    };
    let mut calls = 0;
    let mut errors = 0;
    let mut comparisons = 0;
    let mut elapsed_ms = 0_u64;
    let mut usage = Usage::default();
    let mut cost_complete = true;
    for line in lines {
        let row: Value = serde_json::from_str(line)?;
        let call: CallRecord = serde_json::from_value(row.clone())?;
        ensure!(
            call.phase == "assign"
                && call.model == expected_model
                && call.request["model"] == expected_model,
            "control journal contains an unexpected phase or model"
        );
        if mode == "llm" {
            ensure!(
                call.request["reasoning"]["effort"] == "high",
                "Sol request omitted high reasoning"
            );
        }
        let choices = if mode == "ld" {
            &call.request["questions"][0]["choices"]
        } else {
            &call.request["text"]["format"]["schema"]["properties"]["cluster_id"]["enum"]
        };
        let count = choices
            .as_array()
            .context("missing assignment choices")?
            .len();
        ensure!(
            (2..=k + 1).contains(&count),
            "assignment exceeded its comparison bound or omitted Other"
        );
        comparisons += count - 1;
        calls += 1;
        elapsed_ms += call.elapsed_ms;
        errors += usize::from(!row["error"].is_null());
        cost_complete &= row["usage_available"] == true;
        usage.input_tokens += call.usage.input_tokens;
        usage.cached_tokens += call.usage.cached_tokens;
        usage.cache_write_tokens += call.usage.cache_write_tokens;
        usage.output_tokens += call.usage.output_tokens;
        usage.cost_usd += call.usage.cost_usd;
    }
    Ok(
        json!({"calls":calls,"error_calls":errors,"cluster_comparisons":comparisons,"request_seconds":elapsed_ms as f64/1000.,"usage":usage,"cost_usd":usage.cost_usd,"cost_complete":cost_complete,"journal_sha256":sha256(text.as_bytes())}),
    )
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    ensure!(
        (1..=254).contains(&args.k) && args.expected > 0,
        "invalid k or expected count"
    );
    let input_bytes = std::fs::read(&args.input)?;
    let items = std::str::from_utf8(&input_bytes)?
        .lines()
        .filter(|s| !s.trim().is_empty())
        .map(serde_json::from_str::<Item>)
        .collect::<serde_json::Result<Vec<_>>>()?;
    ensure!(
        items.len() == args.expected,
        "input count differs from expected count"
    );
    let mut ids = HashSet::new();
    ensure!(
        items.iter().all(|p| ids.insert(&p.id)),
        "duplicate point ID"
    );
    let input_hash = input_fingerprint(&input_bytes, &items)?;
    let catalog_bytes = std::fs::read(&args.catalog)?;
    let catalog: Vec<Cluster> = serde_json::from_slice(&catalog_bytes)?;
    ensure!(
        !catalog.is_empty()
            && catalog
                .iter()
                .all(|c| c.id > 0 && !c.name.trim().is_empty() && !c.description.trim().is_empty()),
        "catalog must contain positive IDs and nonempty definitions"
    );
    ensure!(
        catalog.windows(2).all(|w| w[0].id < w[1].id),
        "catalog IDs must be unique and ordered ascending, matching the engine"
    );
    let source = source_version()?;
    let run_id = format!("{:032x}", rand::random::<u128>());
    let progress_path = args.output.with_extension("progress.jsonl");
    let metadata = json!({
        "schema_version": 1,
        "experiment": "frozen-catalog-images",
        "run_id": run_id,
        "mode": args.mode,
        "task": TASK,
        "k": args.k,
        "expected_count": args.expected,
        "input_sha256": input_hash,
        "input_jsonl_sha256": sha256(&input_bytes),
        "catalog_sha256": sha256(&catalog_bytes),
        "catalog": catalog,
        "source": source,
        "assignment_model": if args.mode=="ld" {"gpt-6-luna"} else {"gpt-6.1-sol"},
        "sol_reasoning_effort": "high",
        "pricing_date": "2026-10-20",
        "management_calls": 0,
        "started_at_unix_ms": SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64
    });
    for path in [&args.output, &args.log, &progress_path] {
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)?;
        }
    }
    let mut files = reserve_artifacts(&[&args.output, &args.log, &progress_path])?;
    let mut output = files.remove(0);
    let mut log = files.remove(0);
    let mut progress = files.remove(0);
    write_output(
        &mut output,
        &json!({"status":"running","processed_count":0,"metadata":metadata}),
    )?;
    append(
        &mut log,
        &json!({"type":"ld-clustering-frozen-journal","schema_version":1,"run_id":run_id}),
    )?;
    log.sync_all()?;
    drop(log);
    append(
        &mut progress,
        &json!({"type":"metadata","metadata":metadata}),
    )?;
    let mut assignments = Vec::new();
    let started = Instant::now();
    let outcome = match OpenAi::new(&args.mode, &args.log) {
        Ok(model) => {
            process(
                &model,
                &items,
                &catalog,
                args.k,
                &mut assignments,
                &mut progress,
            )
            .await
        }
        Err(error) => Err(error),
    };
    let elapsed_ms = started.elapsed().as_millis() as u64;
    let mut error = outcome.err().map(|e| format!("{e:#}"));
    let measurement = match journal_summary(&args.log, &run_id, &args.mode, args.k) {
        Ok(summary) => summary,
        Err(e) => {
            error.get_or_insert_with(|| format!("journal audit failed: {e:#}"));
            json!({"cost_complete":false,"audit_error":e.to_string()})
        }
    };
    let status = completion_status(error.is_none(), assignments.len(), args.expected);
    let other = assignments
        .iter()
        .filter(|a| a.cluster_id.is_none())
        .count();
    let label_agreement = if status == "complete" {
        assignments
            .iter()
            .map(|a| a.label.clone())
            .collect::<Option<Vec<_>>>()
            .map(|labels| {
                let partition = assignments
                    .iter()
                    .map(|a| {
                        a.cluster_id
                            .map(|id| format!("cluster:{id}"))
                            .unwrap_or_else(|| format!("other:{}", a.id))
                    })
                    .collect::<Vec<_>>();
                metrics::compare(&labels, &partition)
            })
            .transpose()?
    } else {
        None
    };
    append(
        &mut progress,
        &json!({"type":"terminal","status":status,"processed_count":assignments.len(),"error":error}),
    )?;
    progress.sync_all()?;
    let final_output = json!({
        "status": status,
        "metadata": metadata,
        "processed_count": assignments.len(),
        "expected_count": args.expected,
        "wall_seconds": elapsed_ms as f64/1000.,
        "timing_complete": status=="complete",
        "other_count": other,
        "coverage": (assignments.len()-other) as f64/args.expected as f64,
        "measurement": measurement,
        "dataset_label_agreement": label_agreement,
        "assignments": assignments,
        "error": error,
        "progress_sha256": sha256(&std::fs::read(&progress_path)?)
    });
    write_output(&mut output, &final_output)?;
    println!("{}", serde_json::to_string_pretty(&final_output)?);
    if status != "complete" {
        bail!(
            "control failed; partial evidence retained in {}",
            args.output.display()
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use ld_clustering::types::{CallRecord, Example, ModelReply, Plan, Usage};
    use std::sync::Mutex;
    struct Fake {
        target: Option<i64>,
        pages: Mutex<Vec<Vec<i64>>>,
        fail_after: usize,
    }
    #[async_trait]
    impl Model for Fake {
        async fn assign(
            &self,
            _task: &str,
            _item: &Item,
            clusters: &[Cluster],
        ) -> Result<ModelReply<Option<i64>>> {
            let mut pages = self.pages.lock().unwrap();
            ensure!(pages.len() < self.fail_after, "injected model failure");
            pages.push(clusters.iter().map(|c| c.id).collect());
            Ok(ModelReply {
                value: self
                    .target
                    .filter(|id| clusters.iter().any(|c| c.id == *id)),
                call: CallRecord {
                    phase: "assign".into(),
                    model: "fake".into(),
                    request: serde_json::json!({}),
                    response: serde_json::json!({}),
                    elapsed_ms: 0,
                    usage: Usage::default(),
                },
            })
        }
        async fn plan(
            &self,
            _task: &str,
            _clusters: &[Cluster],
            _examples: &[Example],
            _max: usize,
        ) -> Result<ModelReply<Plan>> {
            panic!("frozen control must never request management")
        }
    }
    fn catalog() -> Vec<Cluster> {
        (1..=5)
            .map(|i| Cluster {
                id: i * 10,
                name: i.to_string(),
                description: "category".into(),
            })
            .collect()
    }
    fn item() -> Item {
        Item {
            id: "opaque".into(),
            text: "evidence".into(),
            image: None,
            label: Some("evaluation-only".into()),
        }
    }
    #[tokio::test]
    async fn paging_preserves_ids_and_visits_every_page_until_match() -> Result<()> {
        let model = Fake {
            target: Some(50),
            pages: Mutex::new(vec![]),
            fail_after: usize::MAX,
        };
        assert_eq!(
            assign_pages(&model, "group", &item(), &catalog(), 2).await?,
            Some(50)
        );
        assert_eq!(
            *model.pages.lock().unwrap(),
            vec![vec![10, 20], vec![30, 40], vec![50]]
        );
        Ok(())
    }
    #[tokio::test]
    async fn other_requires_every_page_to_have_no_match() -> Result<()> {
        let model = Fake {
            target: None,
            pages: Mutex::new(vec![]),
            fail_after: usize::MAX,
        };
        assert_eq!(
            assign_pages(&model, "group", &item(), &catalog(), 2).await?,
            None
        );
        assert_eq!(model.pages.lock().unwrap().len(), 3);
        Ok(())
    }
    #[test]
    fn existing_artifact_is_refused_without_changing_contents() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("existing.json");
        std::fs::write(&path, "original evidence")?;
        assert!(
            reserve_artifacts(&[&path]).is_err(),
            "existing evidence was silently replaced"
        );
        assert_eq!(std::fs::read_to_string(path)?, "original evidence");
        Ok(())
    }
    #[test]
    fn partial_and_failed_runs_never_claim_complete() {
        assert_eq!(completion_status(true, 99, 100), "failed");
        assert_eq!(completion_status(false, 100, 100), "failed");
        assert_eq!(completion_status(true, 100, 100), "complete");
    }

    #[test]
    fn failed_reservation_preserves_old_files_and_removes_its_new_prefix() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let new = dir.path().join("new.json");
        let old = dir.path().join("old.json");
        std::fs::write(&old, "original")?;
        assert!(reserve_artifacts(&[&new, &old]).is_err());
        assert!(!new.exists());
        assert_eq!(std::fs::read_to_string(old)?, "original");
        Ok(())
    }

    #[tokio::test]
    async fn model_failure_retains_only_the_successful_assignment_prefix() -> Result<()> {
        let model = Fake {
            target: Some(10),
            pages: Mutex::new(vec![]),
            fail_after: 1,
        };
        let mut assignments = Vec::new();
        let mut progress = Vec::new();
        let items = (0..3)
            .map(|i| {
                let mut p = item();
                p.id = i.to_string();
                p
            })
            .collect::<Vec<_>>();
        let outcome = process(
            &model,
            &items,
            &catalog(),
            2,
            &mut assignments,
            &mut progress,
        )
        .await;
        assert!(outcome.is_err());
        assert_eq!(assignments.len(), 1);
        assert_eq!(assignments[0].id, "0");
        let lines = String::from_utf8(progress)?;
        assert_eq!(lines.lines().count(), 1);
        assert_eq!(
            completion_status(outcome.is_ok(), assignments.len(), 3),
            "failed"
        );
        Ok(())
    }

    #[test]
    fn image_fingerprint_pins_bytes_at_the_same_path() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("image.png");
        std::fs::write(&path, "first pixels")?;
        let mut p = item();
        p.image = Some(path.to_string_lossy().into_owned());
        let first = input_fingerprint(b"JSONL", &[p.clone()])?;
        std::fs::write(&path, "second pixels")?;
        assert_ne!(first, input_fingerprint(b"JSONL", &[p])?);
        Ok(())
    }

    #[tokio::test]
    async fn a_matching_page_stops_before_later_candidates() -> Result<()> {
        let model = Fake {
            target: Some(30),
            pages: Mutex::new(vec![]),
            fail_after: usize::MAX,
        };
        assert_eq!(
            assign_pages(&model, "group", &item(), &catalog(), 2).await?,
            Some(30)
        );
        assert_eq!(
            *model.pages.lock().unwrap(),
            vec![vec![10, 20], vec![30, 40]]
        );
        Ok(())
    }
}
