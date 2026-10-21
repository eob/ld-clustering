//! Staged immutable-catalog experiment. Paid stages require committed source.
use anyhow::Result;
use clap::{Args, Parser, Subcommand};
use ld_clustering::agreement::{
    CatalogRun, ClassificationRun, Modality, prepare_review, run_catalog, run_classification,
    run_review,
};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    about = "Preregistered discovery, joint rewrite, classification, repeats and blinded review"
)]
struct Cli {
    #[command(subcommand)]
    command: Stage,
}

#[derive(Subcommand)]
enum Stage {
    Discover(CatalogArgs),
    Rewrite {
        #[arg(long)]
        catalog: PathBuf,
        #[command(flatten)]
        args: CatalogArgs,
    },
    Classify(ClassifyArgs),
    Repeat(ClassifyArgs),
    PrepareReview {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        catalog: PathBuf,
        #[arg(long)]
        reference: PathBuf,
        #[arg(long)]
        candidate: PathBuf,
        #[arg(long)]
        cohort_id: String,
        #[arg(long)]
        output: PathBuf,
    },
    Review {
        #[arg(long)]
        bundle: PathBuf,
        #[arg(long)]
        log: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        dry_run: bool,
    },
}

#[derive(Args)]
struct CatalogArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long, value_enum)]
    modality: Modality,
    #[arg(long)]
    expected: usize,
    #[arg(long, default_value_t = 16)]
    max_clusters: usize,
    #[arg(long)]
    log: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long)]
    dry_run: bool,
}
impl From<CatalogArgs> for CatalogRun {
    fn from(a: CatalogArgs) -> Self {
        Self {
            input: a.input,
            modality: a.modality,
            expected: a.expected,
            max_clusters: a.max_clusters,
            log: a.log,
            output: a.output,
            dry_run: a.dry_run,
        }
    }
}
#[derive(Args)]
struct ClassifyArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    catalog: PathBuf,
    #[arg(long,value_parser=["llm","ld"])]
    mode: String,
    #[arg(long)]
    expected: usize,
    #[arg(long, default_value_t = 8)]
    k: usize,
    #[arg(long)]
    log: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long)]
    dry_run: bool,
    #[arg(long)]
    reverse_catalog_order: bool,
    #[arg(long)]
    diagnostic: bool,
    #[arg(long)]
    reference: Option<PathBuf>,
    #[arg(long)]
    reference_input: Option<PathBuf>,
    #[arg(long, default_value_t = 1)]
    repeat_index: u32,
}
impl From<ClassifyArgs> for ClassificationRun {
    fn from(a: ClassifyArgs) -> Self {
        Self {
            input: a.input,
            catalog: a.catalog,
            mode: a.mode,
            expected: a.expected,
            k: a.k,
            log: a.log,
            output: a.output,
            dry_run: a.dry_run,
            reverse_catalog_order: a.reverse_catalog_order,
            diagnostic: a.diagnostic,
            reference: a.reference,
            reference_input: a.reference_input,
            repeat_index: a.repeat_index,
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    match Cli::parse().command {
        Stage::Discover(args) => run_catalog(&args.into(), None).await,
        Stage::Rewrite { catalog, args } => run_catalog(&args.into(), Some(&catalog)).await,
        Stage::Classify(args) => run_classification(&args.into(), false).await,
        Stage::Repeat(args) => run_classification(&args.into(), true).await,
        Stage::PrepareReview {
            input,
            catalog,
            reference,
            candidate,
            cohort_id,
            output,
        } => prepare_review(
            &input, &catalog, &reference, &candidate, &cohort_id, &output,
        ),
        Stage::Review {
            bundle,
            log,
            output,
            dry_run,
        } => run_review(&bundle, &log, &output, dry_run).await,
    }
}
