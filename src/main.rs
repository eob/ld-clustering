use anyhow::{Context, Result, bail, ensure};
use clap::{Parser, Subcommand};
use ld_clustering::{
    datasets,
    engine::{Clusterer, Config},
    provider::OpenAi,
    store::Store,
    types::{Item, MAX_MANAGER_CONTEXT_BYTES, ManagerDescriptor, ManagerPolicy},
};
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::path::Path;
use std::path::PathBuf;

#[derive(Parser)]
#[command(version, about)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Download pinned, licensed inputs and prepare deterministic text/image streams.
    Prepare {
        #[arg(long, default_value = "data")]
        output: PathBuf,
        #[arg(long, default_value_t = 42)]
        seed: u64,
    },
    /// Process or resume an input stream; every successful change persists in SQLite.
    Run {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        database: PathBuf,
        #[arg(long)]
        log: PathBuf,
        #[arg(long,value_parser=["llm","ld"])]
        mode: String,
        #[arg(long)]
        task: String,
        #[arg(long, value_enum, default_value = "original")]
        manager_policy: ManagerPolicy,
        /// Frozen UTF-8 manager guidance; its raw bytes, not its path, identify the run.
        #[arg(long)]
        manager_context: Option<PathBuf>,
        #[arg(long, default_value_t = 8)]
        k: usize,
        #[arg(long, default_value_t = 16)]
        max_clusters: usize,
        #[arg(long, default_value_t = 24)]
        bootstrap: usize,
        #[arg(long, default_value_t = 8)]
        novelty: usize,
        #[arg(long, default_value_t = 100)]
        maintenance_interval: usize,
        /// Prefix size for a smoke run. Use a separate database from the full run.
        #[arg(long)]
        limit: Option<usize>,
    },
    /// Compare two completed runs and audit their measurements against raw journals.
    Compare {
        #[arg(long)]
        baseline: PathBuf,
        #[arg(long)]
        baseline_log: PathBuf,
        #[arg(long)]
        ld: PathBuf,
        #[arg(long)]
        ld_log: PathBuf,
        #[arg(long)]
        expected: usize,
        #[arg(long)]
        output: PathBuf,
    },
}

fn manager_options(
    policy: ManagerPolicy,
    path: Option<&Path>,
) -> Result<(ManagerDescriptor, Option<String>)> {
    match policy {
        ManagerPolicy::Original => {
            ensure!(
                path.is_none(),
                "original manager does not accept --manager-context"
            );
            let descriptor = ManagerDescriptor::default();
            descriptor.validate()?;
            Ok((descriptor, None))
        }
        ManagerPolicy::Contextual => {
            let path = path.context("contextual manager requires --manager-context")?;
            let mut bytes = Vec::new();
            std::fs::File::open(path)
                .with_context(|| format!("read manager context {}", path.display()))?
                .take((MAX_MANAGER_CONTEXT_BYTES + 1) as u64)
                .read_to_end(&mut bytes)?;
            ensure!(
                bytes.len() <= MAX_MANAGER_CONTEXT_BYTES,
                "manager context exceeds {MAX_MANAGER_CONTEXT_BYTES} bytes"
            );
            let context = String::from_utf8(bytes).context("manager context must be UTF-8")?;
            let descriptor = ManagerDescriptor::from_context(&context)?;
            descriptor.validate()?;
            Ok((descriptor, Some(context)))
        }
    }
}

fn bind_run_identity(
    store: &mut Store,
    manager: &ManagerDescriptor,
    backend: &str,
    input_sha256: &str,
) -> Result<()> {
    manager.validate()?;
    // Contextual adoption must see the untouched experiment history.
    store.bind_manager(manager)?;
    for (key, value) in [("backend", backend), ("input_sha256", input_sha256)] {
        ensure!(
            store.get_meta(key)?.is_none_or(|old| old == value),
            "{key} differs from saved run"
        );
        store.set_meta(key, value)?;
    }
    Ok(())
}

fn input_fingerprint(bytes: &[u8], items: &[Item]) -> Result<String> {
    let mut hash = Sha256::new();
    hash.update(b"ld-clustering-input-v1\0");
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
    for item in items {
        if let Some(image) = &item.image {
            ensure!(
                !image.starts_with("http://") && !image.starts_with("https://"),
                "download image to a local file to pin evidence; HTTP image URLs cannot be resumed reproducibly"
            );
            if !image.starts_with("data:image/") {
                let image_bytes = std::fs::read(image).context("hash local image evidence")?;
                hash.update(b"local-image\0");
                hash.update((image_bytes.len() as u64).to_le_bytes());
                hash.update(&image_bytes);
            }
        }
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn bind_request_journal(store: &Store, path: &Path) -> Result<PathBuf> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent)?;
    let canonical = std::fs::canonicalize(parent)?
        .join(path.file_name().context("journal path must name a file")?);
    let existing_len = std::fs::metadata(&canonical).map(|m| m.len()).unwrap_or(0);
    let run_id = match store.get_meta("journal_run_id")? {
        Some(id) => {
            ensure!(
                store.get_meta("journal_path")?.as_deref()
                    == Some(canonical.to_string_lossy().as_ref()),
                "request journal path differs from saved run"
            );
            id
        }
        None => {
            ensure!(
                store.count()? == 0,
                "existing database has no journal binding; use its original compatible evidence"
            );
            let calls: usize =
                store
                    .connection
                    .query_row("SELECT COUNT(*) FROM calls", [], |r| r.get(0))?;
            ensure!(
                calls == 0 && existing_len == 0,
                "fresh database requires an empty request journal"
            );
            let id = format!("{:032x}", rand::random::<u128>());
            let tx = store.connection.unchecked_transaction()?;
            for (key, value) in [
                ("journal_run_id", id.as_str()),
                ("journal_path", canonical.to_string_lossy().as_ref()),
                ("journal_initialized", "0"),
            ] {
                tx.execute("INSERT INTO meta VALUES(?,?)", [key, value])?;
            }
            tx.commit()?;
            id
        }
    };
    let initialized = store.get_meta("journal_initialized")?.as_deref() == Some("1");
    if !initialized && existing_len == 0 {
        // A crash before this header cannot have dispatched a model request.
        ensure!(
            store.count()? == 0,
            "uninitialized journal has persisted points"
        );
        let header = serde_json::json!({"type":ld_clustering::results::JOURNAL_FORMAT,"schema_version":1,"run_id":run_id});
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&canonical)?;
        writeln!(file, "{header}")?;
        file.sync_all()?;
    }
    let text = std::fs::read_to_string(&canonical)
        .context("cannot resume without the original request journal")?;
    let header: serde_json::Value = serde_json::from_str(
        text.lines()
            .next()
            .context("request journal was truncated")?,
    )?;
    ensure!(
        header["type"] == ld_clustering::results::JOURNAL_FORMAT
            && header["schema_version"] == 1
            && header["run_id"] == run_id,
        "request journal does not match saved run identity"
    );
    ld_clustering::results::verify_request_journal(&store.connection, &canonical)?;
    store.set_meta("journal_initialized", "1")?;
    Ok(canonical)
}

#[tokio::main]
async fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Prepare { output, seed } => datasets::prepare(&output, seed).await?,
        Command::Run {
            input,
            database,
            log,
            mode,
            task,
            manager_policy,
            manager_context,
            k,
            max_clusters,
            bootstrap,
            novelty,
            maintenance_interval,
            limit,
        } => {
            let (manager, context) = manager_options(manager_policy, manager_context.as_deref())?;
            let bytes =
                std::fs::read(&input).with_context(|| format!("read {}", input.display()))?;
            let mut items = String::from_utf8(bytes.clone())?
                .lines()
                .filter(|line| !line.trim().is_empty())
                .map(serde_json::from_str::<Item>)
                .collect::<std::result::Result<Vec<_>, _>>()?;
            let digest = input_fingerprint(&bytes, &items)?;
            if let Some(limit) = limit {
                items.truncate(limit);
            }
            if items.is_empty() {
                bail!("input stream is empty");
            }
            let config = Config {
                task,
                k,
                max_clusters,
                bootstrap_size: bootstrap,
                novelty_trigger: novelty,
                maintenance_interval,
            };
            config.validate()?;
            if let Some(parent) = database.parent().filter(|p| !p.as_os_str().is_empty()) {
                std::fs::create_dir_all(parent)?;
            }
            let mut store = Store::open(&database, &serde_json::to_value(&config)?)?;
            bind_run_identity(&mut store, &manager, &mode, &digest)?;
            if store.get_meta("started_at_unix_ms")?.is_none() {
                store.set_meta(
                    "started_at_unix_ms",
                    &std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)?
                        .as_millis()
                        .to_string(),
                )?;
            }
            let log = bind_request_journal(&store, &log)?;
            let model = OpenAi::new(&mode, &log)?.with_manager(manager, context)?;
            let mut clusterer = Clusterer {
                store,
                model,
                config,
            };
            clusterer.run(&items).await?;
            println!("completed {} points in {}", items.len(), database.display());
        }
        Command::Compare {
            baseline,
            baseline_log,
            ld,
            ld_log,
            expected,
            output,
        } => {
            let result = ld_clustering::results::compare_runs(
                &baseline,
                &baseline_log,
                &ld,
                &ld_log,
                expected,
            )?;
            if let Some(parent) = output.parent().filter(|p| !p.as_os_str().is_empty()) {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&output, serde_json::to_vec_pretty(&result)?)?;
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn run_args() -> Vec<String> {
        [
            "ld-clustering",
            "run",
            "--input",
            "input.jsonl",
            "--database",
            "state.sqlite",
            "--log",
            "requests.jsonl",
            "--mode",
            "ld",
            "--task",
            "Classify subjects",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect()
    }

    #[test]
    fn manager_cli_parses_contextual_and_rejects_unknown_policy() {
        match Cli::try_parse_from(run_args()).unwrap().command {
            Command::Run {
                manager_policy,
                manager_context,
                ..
            } => {
                assert_eq!(manager_policy, ManagerPolicy::Original);
                assert!(manager_context.is_none());
            }
            _ => panic!("expected run command"),
        }
        let mut args = run_args();
        args.extend([
            "--manager-policy".into(),
            "contextual".into(),
            "--manager-context".into(),
            "context.txt".into(),
        ]);
        assert!(
            Cli::try_parse_from(&args).is_ok(),
            "manager CLI flags were rejected"
        );
        let value = args.iter().position(|arg| arg == "contextual").unwrap();
        args[value] = "unknown".into();
        assert!(Cli::try_parse_from(args).is_err());
    }

    #[test]
    fn manager_options_pin_raw_context_not_its_location_and_validate_combinations() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let first = dir.path().join("first.txt");
        let relocated = dir.path().join("relocated.txt");
        std::fs::write(&first, "Boundaries from discovery.\n")?;
        std::fs::write(&relocated, "Boundaries from discovery.\n")?;
        let (plain, none) = manager_options(ManagerPolicy::Original, None)?;
        assert_eq!(plain, ManagerDescriptor::default());
        assert!(none.is_none());
        assert!(manager_options(ManagerPolicy::Original, Some(&first)).is_err());
        assert!(manager_options(ManagerPolicy::Contextual, None).is_err());
        let (identity, context) = manager_options(ManagerPolicy::Contextual, Some(&first))?;
        let (moved, _) = manager_options(ManagerPolicy::Contextual, Some(&relocated))?;
        assert_eq!(identity, moved);
        assert_eq!(context.as_deref(), Some("Boundaries from discovery.\n"));
        assert_eq!(
            identity,
            ManagerDescriptor::from_context(context.as_deref().unwrap())?
        );
        std::fs::write(&relocated, "Boundaries from discovery.")?;
        assert_ne!(
            identity,
            manager_options(ManagerPolicy::Contextual, Some(&relocated))?.0
        );
        std::fs::write(&relocated, vec![b'x'; MAX_MANAGER_CONTEXT_BYTES])?;
        assert!(manager_options(ManagerPolicy::Contextual, Some(&relocated)).is_ok());
        for bytes in [
            vec![],
            b" \n".to_vec(),
            vec![0xff],
            vec![b'x'; MAX_MANAGER_CONTEXT_BYTES + 1],
        ] {
            std::fs::write(&relocated, bytes)?;
            assert!(manager_options(ManagerPolicy::Contextual, Some(&relocated)).is_err());
        }
        Ok(())
    }

    #[test]
    fn manager_resume_mismatch_precedes_journal_and_session_events() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut store = Store::open(&dir.path().join("run.sqlite"), &json!({}))?;
        let manager = ManagerDescriptor::from_context("Fixed discovery context")?;
        bind_run_identity(&mut store, &manager, "ld", "input")?;
        bind_run_identity(&mut store, &manager, "ld", "input")?;
        for different in [
            ManagerDescriptor::default(),
            ManagerDescriptor::from_context("Different context")?,
            ManagerDescriptor {
                prompt_revision: "contextual-future".into(),
                ..manager.clone()
            },
        ] {
            assert!(bind_run_identity(&mut store, &different, "ld", "input").is_err());
        }
        assert_eq!(store.manager_descriptor()?, manager);
        assert!(store.get_meta("journal_run_id")?.is_none());
        let events: usize =
            store
                .connection
                .query_row("SELECT COUNT(*) FROM events", [], |row| row.get(0))?;
        assert_eq!(events, 0);
        assert!(!dir.path().join("requests.jsonl").exists());
        Ok(())
    }

    #[test]
    fn manager_original_can_resume_legacy_history_without_descriptor() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut store = Store::open(&dir.path().join("legacy.sqlite"), &json!({}))?;
        store.record_event("maintenance", &json!({"operations":[]}))?;
        assert!(store.get_meta("manager_descriptor")?.is_none());
        bind_run_identity(&mut store, &ManagerDescriptor::default(), "ld", "input")?;
        assert_eq!(store.manager_descriptor()?, ManagerDescriptor::default());
        Ok(())
    }

    fn item(image: Option<String>) -> Item {
        Item {
            id: "opaque".into(),
            text: "Image evidence".into(),
            image,
            label: None,
        }
    }

    #[test]
    fn evidence_hash_changes_with_image_bytes_and_rejects_remote_images() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let image = dir.path().join("image.png");
        std::fs::write(&image, b"original pixels")?;
        let items = vec![item(Some(image.to_string_lossy().into_owned()))];
        let original = input_fingerprint(b"same JSONL", &items)?;
        assert_eq!(original, input_fingerprint(b"same JSONL", &items)?);
        std::fs::write(&image, b"different pixels")?;
        assert_ne!(original, input_fingerprint(b"same JSONL", &items)?);
        assert!(
            input_fingerprint(
                b"JSONL",
                &[item(Some("https://example.com/image.png".into()))]
            )
            .is_err()
        );
        assert!(
            input_fingerprint(b"JSONL", &[item(Some("data:image/png;base64,AAAA".into()))]).is_ok()
        );
        Ok(())
    }

    #[test]
    fn fresh_journal_binding_resumes_and_rejects_nonempty_wrong_or_truncated_files() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let database = dir.path().join("state.sqlite");
        let log = dir.path().join("requests.jsonl");
        let store = Store::open(&database, &json!({}))?;
        let bound = bind_request_journal(&store, &log)?;
        let id = store.get_meta("journal_run_id")?.unwrap();
        assert!(!id.is_empty());
        assert_eq!(bound, bind_request_journal(&store, &log)?);
        assert_eq!(store.get_meta("journal_run_id")?, Some(id));
        assert!(bind_request_journal(&store, &dir.path().join("wrong.jsonl")).is_err());
        let second = Store::open(&dir.path().join("other.sqlite"), &json!({}))?;
        assert!(bind_request_journal(&second, &log).is_err());
        std::fs::write(&log, b"")?;
        assert!(bind_request_journal(&store, &log).is_err());
        Ok(())
    }

    #[test]
    fn fresh_database_rejects_preexisting_log_and_partial_header_can_recover() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let log = dir.path().join("requests.jsonl");
        std::fs::write(&log, b"unrelated requests\n")?;
        let store = Store::open(&dir.path().join("state.sqlite"), &json!({}))?;
        assert!(bind_request_journal(&store, &log).is_err());
        assert!(store.get_meta("journal_run_id")?.is_none());
        std::fs::write(&log, b"")?;
        let canonical = std::fs::canonicalize(dir.path())?.join("requests.jsonl");
        store.set_meta("journal_run_id", "interrupted-before-header")?;
        store.set_meta("journal_path", canonical.to_string_lossy().as_ref())?;
        store.set_meta("journal_initialized", "0")?;
        bind_request_journal(&store, &log)?;
        assert_eq!(store.get_meta("journal_initialized")?, Some("1".into()));
        assert!(std::fs::read_to_string(&log)?.contains("interrupted-before-header"));
        Ok(())
    }
}
