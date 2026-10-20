use anyhow::Result;
use clap::Parser;
use ld_clustering::agreement_data;
use std::path::PathBuf;

#[derive(Parser)]
struct Args {
    #[arg(long, default_value = "data")]
    output: PathBuf,
    #[arg(long, default_value_t = 1042)]
    seed: u64,
    #[arg(long)]
    previous: PathBuf,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    agreement_data::prepare(&args.output, args.seed, &args.previous).await
}
