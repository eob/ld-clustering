use anyhow::{Result, ensure};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Agreement {
    pub n: usize,
    pub adjusted_rand_index: f64,
    pub pairwise_precision: f64,
    pub pairwise_recall: f64,
    pub pairwise_f1: f64,
}

/// Compare partitions. Callers should give every rejected point a unique label.
pub fn compare(reference: &[String], candidate: &[String]) -> Result<Agreement> {
    ensure!(
        reference.len() == candidate.len(),
        "partition lengths differ"
    );
    ensure!(!reference.is_empty(), "cannot compare empty partitions");
    let mut rows = HashMap::new();
    let mut columns = HashMap::new();
    let mut cells = HashMap::new();
    for (left, right) in reference.iter().zip(candidate) {
        *rows.entry(left).or_insert(0_usize) += 1;
        *columns.entry(right).or_insert(0_usize) += 1;
        *cells.entry((left, right)).or_insert(0_usize) += 1;
    }
    let pairs = |size: usize| size as f64 * size.saturating_sub(1) as f64 / 2.0;
    let shared: f64 = cells.values().map(|&count| pairs(count)).sum();
    let reference_pairs: f64 = rows.values().map(|&count| pairs(count)).sum();
    let candidate_pairs: f64 = columns.values().map(|&count| pairs(count)).sum();
    let all_pairs = pairs(reference.len());
    let expected = if all_pairs == 0.0 {
        0.0
    } else {
        reference_pairs * candidate_pairs / all_pairs
    };
    let denominator = (reference_pairs + candidate_pairs) / 2.0 - expected;
    let adjusted_rand_index = if denominator == 0.0 {
        1.0
    } else {
        (shared - expected) / denominator
    };
    let (pairwise_precision, pairwise_recall, pairwise_f1) =
        if reference_pairs == 0.0 && candidate_pairs == 0.0 {
            (1.0, 1.0, 1.0)
        } else {
            let precision = if candidate_pairs == 0.0 {
                0.0
            } else {
                shared / candidate_pairs
            };
            let recall = if reference_pairs == 0.0 {
                0.0
            } else {
                shared / reference_pairs
            };
            let f1 = 2.0 * shared / (reference_pairs + candidate_pairs);
            (precision, recall, f1)
        };
    Ok(Agreement {
        n: reference.len(),
        adjusted_rand_index,
        pairwise_precision,
        pairwise_recall,
        pairwise_f1,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn labels(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    #[test]
    fn partition_agreement_ignores_cluster_names() -> Result<()> {
        let score = compare(
            &labels(&["a", "a", "b", "b"]),
            &labels(&["y", "y", "x", "x"]),
        )?;
        assert_eq!(score.n, 4);
        assert_eq!(score.adjusted_rand_index, 1.0);
        assert_eq!(score.pairwise_precision, 1.0);
        assert_eq!(score.pairwise_recall, 1.0);
        assert_eq!(score.pairwise_f1, 1.0);
        Ok(())
    }

    #[test]
    fn crossed_partitions_have_negative_ari() -> Result<()> {
        let score = compare(
            &labels(&["a", "a", "b", "b"]),
            &labels(&["x", "y", "x", "y"]),
        )?;
        assert!((score.adjusted_rand_index + 0.5).abs() < 1e-12);
        assert_eq!(score.pairwise_precision, 0.0);
        assert_eq!(score.pairwise_recall, 0.0);
        assert_eq!(score.pairwise_f1, 0.0);
        Ok(())
    }

    #[test]
    fn splitting_and_merging_exchange_precision_and_recall() -> Result<()> {
        let reference = labels(&["a", "a", "a", "a"]);
        let candidate = labels(&["x", "x", "y", "y"]);
        let split = compare(&reference, &candidate)?;
        let merge = compare(&candidate, &reference)?;
        assert_eq!(split.adjusted_rand_index, 0.0);
        assert_eq!(split.pairwise_precision, 1.0);
        assert!((split.pairwise_recall - 1.0 / 3.0).abs() < 1e-12);
        assert_eq!(split.pairwise_f1, 0.5);
        assert_eq!(split.pairwise_precision, merge.pairwise_recall);
        assert_eq!(split.pairwise_recall, merge.pairwise_precision);
        Ok(())
    }

    #[test]
    fn degenerate_partitions_and_invalid_lengths_are_defined() -> Result<()> {
        for values in [&["a"][..], &["a", "b", "c"][..], &["a", "a", "a"][..]] {
            let score = compare(&labels(values), &labels(values))?;
            assert_eq!(score.adjusted_rand_index, 1.0);
            assert_eq!(score.pairwise_f1, 1.0);
        }
        let none = compare(&labels(&["a", "b", "c"]), &labels(&["x", "x", "x"]))?;
        assert_eq!(none.adjusted_rand_index, 0.0);
        assert_eq!(none.pairwise_f1, 0.0);
        assert!(compare(&[], &[]).is_err());
        assert!(compare(&labels(&["a"]), &labels(&["x", "y"])).is_err());
        Ok(())
    }
}
