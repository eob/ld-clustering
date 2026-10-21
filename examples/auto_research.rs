//! Separately identified bounded adaptive trials; paid stages require frozen source.
use anyhow::Result;
use clap::{Args, Parser, Subcommand};
use ld_clustering::auto_research::{
    ClassificationRun, RewriteRun, StudyStage, compare_runs, run_classification, run_rewrite,
};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    about = "Bounded adaptive catalog trials with explicit protocol, catalog and option order"
)]
struct Cli {
    #[command(subcommand)]
    command: Stage,
}

#[derive(Subcommand)]
enum Stage {
    SourcePins,
    Classify(ClassifyArgs),
    Rewrite(RewriteArgs),
    Compare {
        #[arg(long)]
        reference: PathBuf,
        #[arg(long)]
        candidate: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
}

#[derive(Args)]
struct ClassifyArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    catalog: PathBuf,
    #[arg(long)]
    order: PathBuf,
    #[arg(long)]
    protocol: PathBuf,
    #[arg(long, value_enum)]
    stage: StudyStage,
    #[arg(long,value_parser=["llm","ld"])]
    mode: String,
    #[arg(long)]
    expected: usize,
    #[arg(long)]
    k: usize,
    #[arg(long)]
    log: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long)]
    dry_run: bool,
}

#[derive(Args)]
struct RewriteArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    expected: usize,
    #[arg(long)]
    catalog: PathBuf,
    #[arg(long)]
    parent_sha256: String,
    #[arg(long)]
    instructions: PathBuf,
    #[arg(long)]
    design_id: String,
    #[arg(long)]
    protocol: PathBuf,
    #[arg(long)]
    log: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    match Cli::parse().command {
        Stage::SourcePins => {
            println!("{}", ld_clustering::auto_research::source_version()?);
            Ok(())
        }
        Stage::Compare {
            reference,
            candidate,
            output,
        } => compare_runs(&reference, &candidate, &output),
        Stage::Classify(a) => {
            run_classification(&ClassificationRun {
                input: a.input,
                catalog: a.catalog,
                order: a.order,
                protocol: a.protocol,
                stage: a.stage,
                mode: a.mode,
                expected: a.expected,
                k: a.k,
                log: a.log,
                output: a.output,
                dry_run: a.dry_run,
            })
            .await
        }
        Stage::Rewrite(a) => {
            run_rewrite(&RewriteRun {
                input: a.input,
                expected: a.expected,
                catalog: a.catalog,
                parent_sha256: a.parent_sha256,
                instructions: a.instructions,
                design_id: a.design_id,
                protocol: a.protocol,
                log: a.log,
                output: a.output,
                dry_run: a.dry_run,
            })
            .await
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_pin_inspection_requires_no_paid_arguments() {
        assert!(matches!(
            Cli::try_parse_from(["auto_research", "source-pins"])
                .unwrap()
                .command,
            Stage::SourcePins
        ));
    }

    fn classify_args() -> Vec<&'static str> {
        vec![
            "auto_research",
            "classify",
            "--input",
            "input.jsonl",
            "--catalog",
            "design.json",
            "--order",
            "order.json",
            "--protocol",
            "protocol.json",
            "--stage",
            "calibration",
            "--mode",
            "ld",
            "--expected",
            "4",
            "--k",
            "16",
            "--log",
            "calls.jsonl",
            "--output",
            "output.json",
            "--dry-run",
        ]
    }

    #[test]
    fn classification_requires_explicit_stage_order_and_k() {
        let parsed = Cli::try_parse_from(classify_args()).unwrap();
        let Stage::Classify(args) = parsed.command else {
            panic!("classify expected")
        };
        assert!(args.dry_run && matches!(args.stage, StudyStage::Calibration));
        for flag in ["--stage", "--order", "--k"] {
            let mut invalid = classify_args();
            let position = invalid.iter().position(|value| *value == flag).unwrap();
            invalid.drain(position..position + 2);
            assert!(Cli::try_parse_from(invalid).is_err(), "{flag}");
        }
        let mut invalid = classify_args();
        let position = invalid
            .iter()
            .position(|value| *value == "calibration")
            .unwrap();
        invalid[position] = "guided";
        assert!(Cli::try_parse_from(invalid).is_err());
    }

    #[test]
    fn custom_rewrite_requires_frozen_parent_hash_and_instructions() {
        let args = vec![
            "auto_research",
            "rewrite",
            "--input",
            "generation.jsonl",
            "--expected",
            "2",
            "--catalog",
            "parent.json",
            "--parent-sha256",
            "raw-parent-hash",
            "--instructions",
            "instructions.txt",
            "--design-id",
            "compact-v1",
            "--protocol",
            "protocol.json",
            "--log",
            "calls.jsonl",
            "--output",
            "rewrite.json",
            "--dry-run",
        ];
        assert!(Cli::try_parse_from(&args).is_ok());
        for flag in ["--parent-sha256", "--instructions"] {
            let mut invalid = args.clone();
            let position = invalid.iter().position(|value| *value == flag).unwrap();
            invalid.drain(position..position + 2);
            assert!(Cli::try_parse_from(invalid).is_err());
        }
    }
}
