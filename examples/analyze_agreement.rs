//! Offline analysis of frozen classification and blinded-review artifacts.
use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand};
use ld_clustering::{
    agreement::{
        CatalogArtifact, ClassificationArtifact, InputEvidence, Modality, load_input, read_catalog,
        sha256, validate_rewrite,
    },
    agreement_metrics::{
        AssignmentAgreement, PairedGainLoss, compare_assignments, paired_gain_loss,
        repeat_consistency,
    },
    agreement_review::{
        ReviewAggregate, ReviewBundle, ReviewInput, ReviewOutcome, ReviewSamplingPlan,
        aggregate_reviews, predeclared_plan, prepare_review_bundle,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};

#[derive(Parser)]
#[command(about = "Analyze frozen original/guided artifacts without making model calls")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Plan {
        #[arg(long)]
        output: PathBuf,
    },
    Analyze {
        #[arg(long)]
        manifest: PathBuf,
        #[arg(long)]
        output: PathBuf,
        /// Existing provider-generated MODALITY-CONDITION.bundle.json files; never overwritten.
        #[arg(long)]
        review_dir: Option<PathBuf>,
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AnalysisManifest {
    schema_version: u32,
    review_plan: PathBuf,
    cohorts: Vec<CohortPaths>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CohortPaths {
    modality: Modality,
    items: PathBuf,
    repeat_input: PathBuf,
    original: ConditionPaths,
    guided: ConditionPaths,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConditionPaths {
    catalog: PathBuf,
    baseline: PathBuf,
    candidate: PathBuf,
    baseline_repeat: PathBuf,
    candidate_repeat: Option<PathBuf>,
    review_bundle: Option<PathBuf>,
    review_output: Option<PathBuf>,
}

#[derive(Serialize)]
struct AnalysisReport {
    schema_version: u32,
    status: String,
    manifest_sha256: String,
    review_plan_sha256: String,
    review_plan_file_sha256: String,
    review_plan: ReviewSamplingPlan,
    modalities: Vec<ModalityAnalysis>,
}

#[derive(Serialize)]
struct ModalityAnalysis {
    modality: Modality,
    heldout_count: usize,
    repeat_count: usize,
    original: ConditionAnalysis,
    guided: ConditionAnalysis,
    paired: PairedGainLoss,
}

#[derive(Serialize)]
struct ConditionAnalysis {
    artifact_sha256: Value,
    comparison: AssignmentAgreement,
    baseline_repeat: AssignmentAgreement,
    candidate_repeat: Option<AssignmentAgreement>,
    measurements: Value,
    review: Option<ReviewAnalysis>,
}

#[derive(Serialize)]
struct ReviewAnalysis {
    bundle_sha256: String,
    selected_count: usize,
    complete: bool,
    output_sha256: Option<String>,
    aggregate: ReviewAggregate,
    measurement: Option<Value>,
}

#[derive(Deserialize)]
struct ReviewArtifact {
    status: String,
    metadata: Value,
    outcomes: Vec<ReviewOutcome>,
    aggregate: ReviewAggregate,
    measurement: Value,
    error: Option<String>,
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Plan { output } => write_new(&output, &predeclared_plan()),
        Command::Analyze {
            manifest,
            output,
            review_dir,
        } => {
            let report = analyze(&manifest, review_dir.as_deref())?;
            write_new(&output, &report)
        }
    }
}

fn write_new(path: &Path, value: &impl Serialize) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .context("analysis/plan output must be a fresh path")?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

fn resolve(base: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    }
}

fn read<T: serde::de::DeserializeOwned>(path: &Path) -> Result<(T, String)> {
    let bytes = fs::read(path).with_context(|| format!("read {}", path.display()))?;
    Ok((
        serde_json::from_slice(&bytes).with_context(|| format!("decode {}", path.display()))?,
        sha256(&bytes),
    ))
}

fn analyze(path: &Path, review_dir: Option<&Path>) -> Result<AnalysisReport> {
    let (manifest, manifest_sha256): (AnalysisManifest, _) = read(path)?;
    ensure!(
        manifest.schema_version == 1 && manifest.cohorts.len() == 2,
        "expected one text and one image cohort"
    );
    ensure!(
        manifest
            .cohorts
            .iter()
            .filter(|cohort| cohort.modality == Modality::Text)
            .count()
            == 1,
        "text/image cohorts must be unique"
    );
    let base = path.parent().unwrap_or(Path::new("."));
    let (plan, review_plan_file_sha256): (ReviewSamplingPlan, _) =
        read(&resolve(base, &manifest.review_plan))?;
    ensure!(
        plan == predeclared_plan(),
        "analysis review plan differs from the frozen protocol"
    );
    let mut modalities = Vec::new();
    for cohort in manifest.cohorts {
        let (count, repeat_count) = if cohort.modality == Modality::Text {
            (1000, 100)
        } else {
            (100, 25)
        };
        let input = load_input(&resolve(base, &cohort.items), count, cohort.modality)?;
        let repeat = load_input(
            &resolve(base, &cohort.repeat_input),
            repeat_count,
            cohort.modality,
        )?;
        let repeat_ids: Vec<_> = repeat.items.iter().map(|item| item.id.clone()).collect();
        let (original, original_hash) = read_catalog(&resolve(base, &cohort.original.catalog))?;
        let (guided, guided_hash) = read_catalog(&resolve(base, &cohort.guided.catalog))?;
        ensure!(
            original.modality == cohort.modality
                && guided.modality == cohort.modality
                && original.stage == "original"
                && guided.stage == "guided",
            "catalog condition/modality differs from analysis cohort"
        );
        validate_rewrite(&original.catalog, &guided.catalog)?;
        ensure!(
            guided.parent_catalog_sha256.as_deref() == Some(original_hash.as_str())
                && guided.discovery_sha256 == original.discovery_sha256
                && guided.discovery_ids == original.discovery_ids,
            "guided catalog is not derived from the frozen discovery catalog"
        );
        ensure!(
            input
                .items
                .iter()
                .all(|item| !original.discovery_ids.contains(&item.id)),
            "held-out ID entered discovery"
        );
        let context = ConditionContext {
            base,
            review_dir,
            input: &input,
            repeat: &repeat,
            repeat_ids: &repeat_ids,
            plan: &plan,
        };
        let old = condition(&context, &cohort.original, &original, &original_hash)?;
        let new = condition(&context, &cohort.guided, &guided, &guided_hash)?;
        let old_ref: ClassificationArtifact = read(&resolve(base, &cohort.original.baseline))?.0;
        let old_ld: ClassificationArtifact = read(&resolve(base, &cohort.original.candidate))?.0;
        let new_ref: ClassificationArtifact = read(&resolve(base, &cohort.guided.baseline))?.0;
        let new_ld: ClassificationArtifact = read(&resolve(base, &cohort.guided.candidate))?.0;
        let paired = paired_gain_loss(
            &old_ref.assignments,
            &old_ld.assignments,
            &new_ref.assignments,
            &new_ld.assignments,
            &original.catalog,
        )?;
        modalities.push(ModalityAnalysis {
            modality: cohort.modality,
            heldout_count: count,
            repeat_count,
            original: old,
            guided: new,
            paired,
        });
    }
    let complete = modalities.iter().all(|modality| {
        [&modality.original, &modality.guided]
            .iter()
            .all(|condition| {
                condition
                    .review
                    .as_ref()
                    .is_some_and(|review| review.complete)
            })
    });
    Ok(AnalysisReport {
        schema_version: 1,
        status: if complete {
            "complete"
        } else {
            "reviews_incomplete"
        }
        .into(),
        manifest_sha256,
        review_plan_sha256: sha256(&serde_json::to_vec(&plan)?),
        review_plan_file_sha256,
        review_plan: plan,
        modalities,
    })
}

struct Bindings<'a> {
    catalog: &'a CatalogArtifact,
    catalog_hash: &'a str,
    input: &'a InputEvidence,
    mode: &'a str,
    repeat_reference: Option<&'a str>,
}

fn expected_metadata(binding: &Bindings<'_>) -> Result<Value> {
    let ids: Vec<_> = binding
        .catalog
        .catalog
        .iter()
        .map(|cluster| cluster.id)
        .collect();
    Ok(
        json!({"experiment":"guided-agreement","stage":if binding.repeat_reference.is_some(){"repeat"}else{"classify"},"modality":binding.catalog.modality,"condition":binding.catalog.stage,"mode":binding.mode,"task":binding.catalog.task,"k":8,"reverse_catalog_order":false,"diagnostic":false,"expected_count":binding.input.items.len(),"input_sha256":binding.input.fingerprint,"input_jsonl_sha256":binding.input.jsonl_sha256,"ordered_ids":binding.input.items.iter().map(|item|item.id.as_str()).collect::<Vec<_>>(),"catalog_sha256":binding.catalog_hash,"catalog":binding.catalog.catalog,"effective_catalog_sha256":sha256(&serde_json::to_vec(&binding.catalog.catalog)?),"effective_order":ids,"effective_order_sha256":sha256(&serde_json::to_vec(&ids)?),"reference_sha256":binding.repeat_reference,"repeat_index":if binding.repeat_reference.is_some(){Some(1)}else{None},"management_calls":0,"assignment_model":if binding.mode=="llm"{"gpt-6.1-sol"}else{"gpt-6-luna"},"sol_reasoning_effort":"high"}),
    )
}

fn validate_classification(artifact: &ClassificationArtifact, expected: &Value) -> Result<()> {
    ensure!(
        artifact.schema_version == 1 && artifact.status == "complete" && artifact.error.is_none(),
        "classification artifact is incomplete"
    );
    let n = expected["expected_count"]
        .as_u64()
        .context("missing expected input count")? as usize;
    ensure!(
        artifact.processed_count == n
            && artifact.expected_count == n
            && artifact.assignments.len() == n,
        "classification sample count differs"
    );
    for (key, value) in expected
        .as_object()
        .context("metadata binding must be an object")?
    {
        ensure!(
            artifact.metadata.get(key) == Some(value),
            "classification metadata binding differs: {key}"
        );
    }
    ensure!(
        artifact.measurement["timing_complete"] == true
            && artifact.measurement["cost_complete"].is_boolean(),
        "classification completeness flags missing or invalid"
    );
    ensure!(
        artifact.progress_sha256.len() == 64
            && artifact
                .progress_sha256
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit()),
        "classification progress hash is invalid"
    );
    Ok(())
}

fn classification(path: &Path, binding: Bindings<'_>) -> Result<(ClassificationArtifact, String)> {
    let (artifact, hash) = read(path)?;
    validate_classification(&artifact, &expected_metadata(&binding)?)?;
    ensure!(
        artifact
            .assignments
            .iter()
            .map(|row| row.id.as_str())
            .eq(binding.input.items.iter().map(|item| item.id.as_str())),
        "classification row order differs from frozen input"
    );
    Ok((artifact, hash))
}

struct ConditionContext<'a> {
    base: &'a Path,
    review_dir: Option<&'a Path>,
    input: &'a InputEvidence,
    repeat: &'a InputEvidence,
    repeat_ids: &'a [String],
    plan: &'a ReviewSamplingPlan,
}

fn condition(
    context: &ConditionContext<'_>,
    paths: &ConditionPaths,
    catalog: &CatalogArtifact,
    catalog_hash: &str,
) -> Result<ConditionAnalysis> {
    let &ConditionContext {
        base,
        review_dir,
        input,
        repeat,
        repeat_ids,
        plan,
    } = context;
    let (baseline, baseline_hash) = classification(
        &resolve(base, &paths.baseline),
        Bindings {
            catalog,
            catalog_hash,
            input,
            mode: "llm",
            repeat_reference: None,
        },
    )?;
    let (candidate, candidate_hash) = classification(
        &resolve(base, &paths.candidate),
        Bindings {
            catalog,
            catalog_hash,
            input,
            mode: "ld",
            repeat_reference: None,
        },
    )?;
    let (baseline_again, baseline_repeat_hash) = classification(
        &resolve(base, &paths.baseline_repeat),
        Bindings {
            catalog,
            catalog_hash,
            input: repeat,
            mode: "llm",
            repeat_reference: Some(&baseline_hash),
        },
    )?;
    let baseline_repeat = repeat_consistency(
        &baseline.assignments,
        &baseline_again.assignments,
        repeat_ids,
        &catalog.catalog,
    )?;
    let (candidate_repeat, candidate_repeat_hash, candidate_repeat_measurement) =
        if let Some(path) = &paths.candidate_repeat {
            let (again, hash) = classification(
                &resolve(base, path),
                Bindings {
                    catalog,
                    catalog_hash,
                    input: repeat,
                    mode: "ld",
                    repeat_reference: Some(&candidate_hash),
                },
            )?;
            (
                Some(repeat_consistency(
                    &candidate.assignments,
                    &again.assignments,
                    repeat_ids,
                    &catalog.catalog,
                )?),
                Some(hash),
                Some(again.measurement),
            )
        } else {
            (None, None, None)
        };
    let name = if catalog.modality == Modality::Text {
        "text"
    } else {
        "images"
    };
    let cohort_id = format!("{name}-{}", catalog.stage);
    let bundle_path = paths
        .review_bundle
        .as_ref()
        .map(|path| resolve(base, path))
        .or_else(|| {
            review_dir.map(|dir| resolve(base, dir).join(format!("{cohort_id}.bundle.json")))
        });
    let review = if let Some(path) = bundle_path {
        let (bundle, bundle_hash): (ReviewBundle, _) = read(&path)?;
        let rebuilt = prepare_review_bundle(
            plan,
            ReviewInput {
                cohort_id: &cohort_id,
                modality: catalog.modality,
                task: &catalog.task,
                catalog: &catalog.catalog,
                items: &input.items,
                reference: &baseline.assignments,
                candidate: &candidate.assignments,
            },
        )?;
        verify_bundle(&bundle, &rebuilt)?;
        let mut aggregate = aggregate_reviews(&bundle, &[])?;
        let mut complete = false;
        let mut output_sha256 = None;
        let mut measurement = None;
        if let Some(path) = &paths.review_output {
            let (artifact, hash): (ReviewArtifact, _) = read(&resolve(base, path))?;
            ensure!(
                artifact.metadata["bundle_sha256"] == bundle_hash
                    && artifact.metadata["plan_sha256"] == bundle.plan_sha256
                    && artifact.metadata["selected_count"] == bundle.cases.len(),
                "review output belongs to a different frozen bundle"
            );
            aggregate = aggregate_reviews(&bundle, &artifact.outcomes)?;
            ensure!(
                serde_json::to_value(&aggregate)? == serde_json::to_value(&artifact.aggregate)?,
                "saved review aggregate differs from raw judgments"
            );
            complete = artifact.status == "complete"
                && artifact.error.is_none()
                && aggregate.totals.failed_count == 0
                && aggregate.totals.not_attempted_count == 0
                && aggregate.totals.accepted_count == bundle.cases.len();
            output_sha256 = Some(hash);
            measurement = Some(artifact.measurement);
        }
        Some(ReviewAnalysis {
            bundle_sha256: bundle_hash,
            selected_count: bundle.cases.len(),
            complete,
            output_sha256,
            aggregate,
            measurement,
        })
    } else {
        ensure!(
            paths.review_output.is_none(),
            "review output requires its frozen bundle"
        );
        None
    };
    Ok(ConditionAnalysis {
        artifact_sha256: json!({"catalog":catalog_hash,"baseline":baseline_hash,"candidate":candidate_hash,"baseline_repeat":baseline_repeat_hash,"candidate_repeat":candidate_repeat_hash}),
        comparison: compare_assignments(
            &baseline.assignments,
            &candidate.assignments,
            &catalog.catalog,
        )?,
        baseline_repeat,
        candidate_repeat,
        measurements: json!({"baseline":baseline.measurement,"candidate":candidate.measurement,"baseline_repeat":baseline_again.measurement,"candidate_repeat":candidate_repeat_measurement}),
        review,
    })
}

fn verify_bundle(saved: &ReviewBundle, rebuilt: &ReviewBundle) -> Result<()> {
    aggregate_reviews(saved, &[])?;
    ensure!(
        saved.plan_sha256 == rebuilt.plan_sha256
            && saved.audit.cohort_id == rebuilt.audit.cohort_id
            && saved.evidence_sha256 == rebuilt.evidence_sha256,
        "frozen review evidence/plan differs from analysis inputs"
    );
    ensure!(
        saved.audit.total_input_count == rebuilt.audit.total_input_count
            && saved.audit.catalog_sha256 == rebuilt.audit.catalog_sha256
            && saved.audit.reference_assignments_sha256
                == rebuilt.audit.reference_assignments_sha256
            && saved.audit.candidate_assignments_sha256
                == rebuilt.audit.candidate_assignments_sha256
            && serde_json::to_value(&saved.audit.strata)?
                == serde_json::to_value(&rebuilt.audit.strata)?,
        "frozen sampling denominators/assignments differ"
    );
    ensure!(
        saved.cases.len() == rebuilt.cases.len()
            && saved.audit.keys.len() == rebuilt.audit.keys.len(),
        "frozen review selection size differs"
    );
    for (old, new) in saved.cases.iter().zip(&rebuilt.cases) {
        ensure!(
            old.case_id == new.case_id
                && old.task == new.task
                && old.catalog == new.catalog
                && old.choice_a == new.choice_a
                && old.choice_b == new.choice_b
                && old.item.text == new.item.text
                && old.item.image.is_some() == new.item.image.is_some(),
            "frozen review payload differs"
        );
    }
    for (old, new) in saved.audit.keys.iter().zip(&rebuilt.audit.keys) {
        ensure!(
            old.case_id == new.case_id
                && old.item_id == new.item_id
                && old.stratum == new.stratum
                && old.reference_cluster_id == new.reference_cluster_id
                && old.candidate_cluster_id == new.candidate_cluster_id
                && old.a_is_reference == new.a_is_reference
                && old.inclusion_probability_within_cell == new.inclusion_probability_within_cell,
            "frozen review identity/selection key differs: saved {old:?}; rebuilt {new:?}"
        );
    }
    // Image locations may change when an archive is relocated; evidence bytes stay pinned above.
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ld_clustering::agreement_metrics::AssignmentRecord;

    fn artifact() -> ClassificationArtifact {
        ClassificationArtifact {
            schema_version: 1,
            status: "complete".into(),
            metadata: json!({"catalog_sha256":"catalog","input_sha256":"input","mode":"llm","expected_count":1}),
            processed_count: 1,
            expected_count: 1,
            assignments: vec![AssignmentRecord {
                id: "one".into(),
                cluster_id: Some(1),
                refused: false,
                label: None,
            }],
            measurement: json!({"timing_complete":true,"cost_complete":false}),
            error: None,
            progress_sha256: "a".repeat(64),
        }
    }

    #[test]
    fn analysis_rejects_wrong_evidence_backend_and_incomplete_counts() {
        let expected = artifact().metadata;
        validate_classification(&artifact(), &expected).unwrap();
        for key in ["catalog_sha256", "input_sha256", "mode"] {
            let mut invalid = artifact();
            invalid.metadata[key] = json!("different");
            assert!(
                validate_classification(&invalid, &expected).is_err(),
                "accepted a changed {key}"
            );
        }
        let mut incomplete = artifact();
        incomplete.processed_count = 0;
        assert!(validate_classification(&incomplete, &expected).is_err());
        let mut missing = artifact();
        missing
            .measurement
            .as_object_mut()
            .unwrap()
            .remove("cost_complete");
        assert!(validate_classification(&missing, &expected).is_err());
    }

    #[test]
    fn plan_output_is_fresh_and_preserves_existing_artifacts() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let output = directory.path().join("plan.json");
        write_new(&output, &predeclared_plan())?;
        let before = fs::read(&output)?;
        assert!(write_new(&output, &json!({"changed":true})).is_err());
        assert_eq!(fs::read(&output)?, before);
        let (saved, _): (ReviewSamplingPlan, _) = read(&output)?;
        assert_eq!(saved, predeclared_plan());
        Ok(())
    }

    #[test]
    fn persisted_sampling_probabilities_roundtrip_exactly() -> Result<()> {
        for (selected, eligible) in [
            (2, 11),
            (7, 31),
            (10, 11),
            (1, 11),
            (1, 89),
            (1, 13),
            (2, 42),
            (2, 82),
            (2, 127),
            (2, 183),
        ] {
            let expected = selected as f64 / eligible as f64;
            let bytes = serde_json::to_vec(&expected)?;
            let restored: f64 = serde_json::from_slice(&bytes)?;
            assert_eq!(
                restored.to_bits(),
                expected.to_bits(),
                "persisted sampling probability {selected}/{eligible} changed during JSON decoding"
            );
        }
        Ok(())
    }
}
