//! Offline input and maximum-request preflight for the reserved stream experiment.
use anyhow::{Context, Result, ensure};
use clap::Parser;
use ld_clustering::{
    agreement::{Modality, load_input, sha256},
    engine::Config,
    provider::{assignment_request, management_request},
    types::{Cluster, Example, ManagerDescriptor},
};
use serde_json::{Value, json};
use std::{cmp::Reverse, fs, io::Write, path::PathBuf};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    data: PathBuf,
    #[arg(long)]
    text_context: PathBuf,
    #[arg(long)]
    image_context: PathBuf,
    #[arg(long)]
    output: PathBuf,
}

fn request_pin(body: Value) -> Result<Value> {
    let bytes = serde_json::to_vec(&body)?;
    ensure!(bytes.len() <= 32 * 1024 * 1024, "request exceeds 32 MiB");
    Ok(json!({"bytes":bytes.len(),"sha256":sha256(&bytes)}))
}

fn main() -> Result<()> {
    let args = Args::parse();
    ensure!(!args.output.exists(), "preflight output must be fresh");
    let manifest_bytes = fs::read(args.data.join("manifest.json"))?;
    let manifest: Value = serde_json::from_slice(&manifest_bytes)?;
    let mut modalities = Vec::new();
    // Escaping these valid maximum-byte definitions also stresses nested JSON framing.
    let worst_catalog: Vec<_> = (1..=16)
        .map(|id| Cluster {
            id,
            name: format!("group-{id:02}{}", "\u{0001}".repeat(492)),
            description: format!("membership:{}", "\u{0001}".repeat(3989)),
        })
        .collect();
    for (modality, name, expected, context_path) in [
        (Modality::Text, "text", 1000, args.text_context),
        (Modality::Images, "images", 100, args.image_context),
    ] {
        let input = load_input(
            &args.data.join("streaming").join(format!("{name}.jsonl")),
            expected,
            modality,
        )?;
        let context = fs::read_to_string(&context_path).context("read frozen UTF-8 context")?;
        let contextual = ManagerDescriptor::from_context(&context)?;
        let ids: Vec<_> = input.items.iter().map(|item| &item.id).collect();
        ensure!(
            serde_json::to_value(&ids)? == manifest["partitions"]["streaming"][name]["ordered_ids"],
            "reserved item order differs from manifest"
        );
        ensure!(
            input.jsonl_sha256
                == sha256(&fs::read(
                    args.data.join("streaming").join(format!("{name}.jsonl"))
                )?),
            "input changed while loading"
        );
        let config = Config {
            task: modality.task().into(),
            k: 8,
            max_clusters: 16,
            bootstrap_size: 24,
            novelty_trigger: 8,
            maintenance_interval: 100,
        };
        config.validate()?;
        let mut weighted = input
            .items
            .iter()
            .map(|item| {
                let size = match &item.image {
                    Some(path) => fs::metadata(path)?.len(),
                    None => item.text.len() as u64,
                };
                Ok((size, item.clone()))
            })
            .collect::<Result<Vec<_>>>()?;
        weighted.sort_by_key(|(size, item)| (Reverse(*size), item.id.clone()));
        let upper_bound: Vec<_> = weighted
            .iter()
            .take(40)
            .enumerate()
            .map(|(i, (_, item))| Example {
                item: item.clone(),
                cluster_id: (i < 32).then_some((i / 2 + 1) as i64),
            })
            .collect();
        let bootstrap: Vec<_> = input.items[..24]
            .iter()
            .map(|item| Example {
                item: item.clone(),
                cluster_id: None,
            })
            .collect();
        let mut policies = Vec::new();
        for (descriptor, frozen_context) in [
            (ManagerDescriptor::default(), None),
            (contextual, Some(context.as_str())),
        ] {
            let bootstrap_request = management_request(
                modality.task(),
                &[],
                &bootstrap,
                16,
                &descriptor,
                frozen_context,
            )?;
            let largest_request = management_request(
                modality.task(),
                &worst_catalog,
                &upper_bound,
                16,
                &descriptor,
                frozen_context,
            )?;
            policies.push(json!({
                "manager_descriptor":descriptor,
                "bootstrap_request":request_pin(bootstrap_request)?,
                "maximum_definition_and_40_largest_evidence_request":request_pin(largest_request)?
            }));
        }
        let largest = &weighted[0].1;
        modalities.push(json!({
            "modality":name,"count":expected,"config":config,
            "input_sha256":input.fingerprint,"jsonl_sha256":input.jsonl_sha256,
            "context_sha256":sha256(context.as_bytes()),"policies":policies,
            "assignment_request_upper_bound":{
                "llm":request_pin(assignment_request("llm",modality.task(),largest,&worst_catalog[..8])?)?,
                "ld":request_pin(assignment_request("ld",modality.task(),largest,&worst_catalog[..8])?)?
            }
        }));
    }
    let report = json!({"schema_version":1,"status":"offline_preflight_passed", "api_calls":0,
        "dataset_manifest_sha256":sha256(&manifest_bytes),"modalities":modalities,
        "request_scope":"Bootstrap uses actual first24 inputs and empty catalog. Upper bounds use synthetic16 maximum-byte category definitions and40 largest reserved inputs; none of these requests are dispatched."});
    if let Some(parent) = args.output.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args.output)?;
    serde_json::to_writer_pretty(&mut output, &report)?;
    output.write_all(b"\n")?;
    output.sync_all()?;
    Ok(())
}
