use crate::{metrics, types::Cluster};
use anyhow::{Result, ensure};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct AssignmentRecord {
    pub id: String,
    pub cluster_id: Option<i64>,
    #[serde(default)]
    pub refused: bool,
    #[serde(default)]
    pub label: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AssignedOtherCounts {
    pub both_named: usize,
    pub reference_named_candidate_other: usize,
    pub reference_other_candidate_named: usize,
    pub both_other: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConfusionCell {
    pub reference_cluster_id: Option<i64>,
    pub candidate_cluster_id: Option<i64>,
    pub count: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CategoryConfusion {
    pub cluster_id: Option<i64>,
    pub reference_count: usize,
    pub candidate_count: usize,
    pub same_count: usize,
    pub false_positive_count: usize,
    pub false_negative_count: usize,
    pub true_negative_count: usize,
    pub precision: Option<f64>,
    pub recall: Option<f64>,
    pub f1: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AssignmentAgreement {
    pub n: usize,
    pub direct_agreement_count: usize,
    pub direct_agreement: f64,
    pub named_id_agreement_count: usize,
    pub named_id_agreement: f64,
    pub reference_assigned_count: usize,
    pub candidate_assigned_count: usize,
    pub reference_coverage: f64,
    pub candidate_coverage: f64,
    pub reference_refused_points: usize,
    pub candidate_refused_points: usize,
    pub assigned_other: AssignedOtherCounts,
    pub jointly_named_agreement: Option<f64>,
    pub categories: Vec<CategoryConfusion>,
    pub confusion: Vec<ConfusionCell>,
    pub partition: metrics::Agreement,
    pub other_policy: String,
    pub conditional_agreement_note: String,
    pub reference_note: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GainLoss {
    pub stayed_agree: usize,
    pub gained_agreement: usize,
    pub lost_agreement: usize,
    pub stayed_disagree: usize,
    pub original_agreement: f64,
    pub guided_agreement: f64,
    pub net_gain_count: i64,
    pub net_gain_fraction: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PairedGainLoss {
    pub n: usize,
    pub condition_matched_direct: GainLoss,
    pub condition_matched_named: GainLoss,
    pub original_reference_anchored_direct: GainLoss,
    pub original_reference_anchored_named: GainLoss,
    pub reference_id_changes: usize,
    pub candidate_id_changes: usize,
    pub anchored_diagnostic_note: String,
}

pub fn compare_assignments(
    reference: &[AssignmentRecord],
    candidate: &[AssignmentRecord],
    catalog: &[Cluster],
) -> Result<AssignmentAgreement> {
    let allowed = catalog_ids(catalog)?;
    let reference = index(reference, &allowed)?;
    let candidate = index(candidate, &allowed)?;
    ensure!(
        reference.keys().eq(candidate.keys()),
        "assignment ID sets differ"
    );
    let n = reference.len();
    let mut counts = BTreeMap::<(Option<i64>, Option<i64>), usize>::new();
    let mut assigned_other = AssignedOtherCounts::default();
    let mut reference_partition = Vec::with_capacity(n);
    let mut candidate_partition = Vec::with_capacity(n);
    for (id, left) in &reference {
        let right = candidate[id];
        *counts
            .entry((left.cluster_id, right.cluster_id))
            .or_default() += 1;
        match (left.cluster_id, right.cluster_id) {
            (Some(_), Some(_)) => assigned_other.both_named += 1,
            (Some(_), None) => assigned_other.reference_named_candidate_other += 1,
            (None, Some(_)) => assigned_other.reference_other_candidate_named += 1,
            (None, None) => assigned_other.both_other += 1,
        }
        let partition_label = |cluster_id: Option<i64>| match cluster_id {
            Some(cluster_id) => format!("cluster:{cluster_id}"),
            None => format!("other:{id}"),
        };
        reference_partition.push(partition_label(left.cluster_id));
        candidate_partition.push(partition_label(right.cluster_id));
    }
    let ids: Vec<_> = std::iter::once(None)
        .chain(allowed.into_iter().map(Some))
        .collect();
    let mut categories = Vec::new();
    let mut confusion = Vec::new();
    for &id in &ids {
        let reference_count = counts
            .iter()
            .filter(|((left, _), _)| *left == id)
            .map(|(_, count)| count)
            .sum::<usize>();
        let candidate_count = counts
            .iter()
            .filter(|((_, right), _)| *right == id)
            .map(|(_, count)| count)
            .sum::<usize>();
        let same_count = *counts.get(&(id, id)).unwrap_or(&0);
        let false_positive_count = candidate_count - same_count;
        let false_negative_count = reference_count - same_count;
        categories.push(CategoryConfusion {
            cluster_id: id,
            reference_count,
            candidate_count,
            same_count,
            false_positive_count,
            false_negative_count,
            true_negative_count: n - same_count - false_positive_count - false_negative_count,
            precision: fraction(same_count, candidate_count),
            recall: fraction(same_count, reference_count),
            f1: fraction(2 * same_count, reference_count + candidate_count),
        });
        for &other in &ids {
            confusion.push(ConfusionCell {
                reference_cluster_id: id,
                candidate_cluster_id: other,
                count: *counts.get(&(id, other)).unwrap_or(&0),
            });
        }
    }
    let named_id_agreement_count = categories
        .iter()
        .filter(|entry| entry.cluster_id.is_some())
        .map(|entry| entry.same_count)
        .sum::<usize>();
    let direct_agreement_count = named_id_agreement_count + assigned_other.both_other;
    let reference_assigned_count =
        assigned_other.both_named + assigned_other.reference_named_candidate_other;
    let candidate_assigned_count =
        assigned_other.both_named + assigned_other.reference_other_candidate_named;
    Ok(AssignmentAgreement {
        n,
        direct_agreement_count,
        direct_agreement: direct_agreement_count as f64 / n as f64,
        named_id_agreement_count,
        named_id_agreement: named_id_agreement_count as f64 / n as f64,
        reference_assigned_count,
        candidate_assigned_count,
        reference_coverage: reference_assigned_count as f64 / n as f64,
        candidate_coverage: candidate_assigned_count as f64 / n as f64,
        reference_refused_points: reference.values().filter(|row| row.refused).count(),
        candidate_refused_points: candidate.values().filter(|row| row.refused).count(),
        jointly_named_agreement: fraction(named_id_agreement_count, assigned_other.both_named),
        assigned_other,
        categories,
        confusion,
        partition: metrics::compare(&reference_partition, &candidate_partition)?,
        other_policy: "Direct agreement includes both choosing Other. Named-ID agreement divides matching named IDs by all points. ARI and pairwise scores give each Other point its own singleton label.".into(),
        conditional_agreement_note: "Jointly named agreement divides matching named IDs only by points named by both arms; null means no jointly named points. This conditional rate excludes rejected points and must be read with coverage and the full named/Other table.".into(),
        reference_note: "Per-category confusion, precision and recall are relative to the LLM assignments, not ground truth. Agreement and coverage do not establish semantic correctness.".into(),
    })
}

pub fn paired_gain_loss(
    original_reference: &[AssignmentRecord],
    original_candidate: &[AssignmentRecord],
    guided_reference: &[AssignmentRecord],
    guided_candidate: &[AssignmentRecord],
    catalog: &[Cluster],
) -> Result<PairedGainLoss> {
    let allowed = catalog_ids(catalog)?;
    let original_reference = index(original_reference, &allowed)?;
    let original_candidate = index(original_candidate, &allowed)?;
    let guided_reference = index(guided_reference, &allowed)?;
    let guided_candidate = index(guided_candidate, &allowed)?;
    ensure!(
        [&original_candidate, &guided_reference, &guided_candidate]
            .iter()
            .all(|rows| rows.keys().eq(original_reference.keys())),
        "paired assignment ID sets differ"
    );
    let changes = |anchored: bool, named_only: bool| {
        gain_loss(original_reference.keys().map(|id| {
            let original_ref = original_reference[id].cluster_id;
            let guided_ref = if anchored {
                original_ref
            } else {
                guided_reference[id].cluster_id
            };
            let old = original_candidate[id].cluster_id;
            let new = guided_candidate[id].cluster_id;
            (
                original_ref == old && (!named_only || original_ref.is_some()),
                guided_ref == new && (!named_only || guided_ref.is_some()),
            )
        }))
    };
    Ok(PairedGainLoss {
        n: original_reference.len(),
        condition_matched_direct: changes(false, false),
        condition_matched_named: changes(false, true),
        original_reference_anchored_direct: changes(true, false),
        original_reference_anchored_named: changes(true, true),
        reference_id_changes: original_reference.keys().filter(|id| original_reference[*id].cluster_id != guided_reference[*id].cluster_id).count(),
        candidate_id_changes: original_candidate.keys().filter(|id| original_candidate[*id].cluster_id != guided_candidate[*id].cluster_id).count(),
        anchored_diagnostic_note: "A preplanned post-hoc diagnostic anchored to original-reference assignments; primary agreement compares reference and candidate within the same description condition. Condition-matched gains may include reference drift and do not establish correctness.".into(),
    })
}

pub fn repeat_consistency(
    primary: &[AssignmentRecord],
    repeated: &[AssignmentRecord],
    predeclared_ids: &[String],
    catalog: &[Cluster],
) -> Result<AssignmentAgreement> {
    let allowed = catalog_ids(catalog)?;
    let primary_index = index(primary, &allowed)?;
    let repeated_index = index(repeated, &allowed)?;
    let declared: BTreeSet<_> = predeclared_ids.iter().map(String::as_str).collect();
    ensure!(
        !declared.is_empty() && declared.len() == predeclared_ids.len(),
        "repeat subset must be nonempty and unique"
    );
    ensure!(
        declared.iter().all(|id| primary_index.contains_key(id)),
        "repeat subset contains an unknown primary ID"
    );
    ensure!(
        repeated_index.keys().copied().eq(declared.iter().copied()),
        "repeated assignments differ from the predeclared subset"
    );
    let first: Vec<_> = declared
        .iter()
        .map(|id| primary_index[id].clone())
        .collect();
    compare_assignments(&first, repeated, catalog)
}

fn fraction(numerator: usize, denominator: usize) -> Option<f64> {
    (denominator != 0).then(|| numerator as f64 / denominator as f64)
}

fn catalog_ids(catalog: &[Cluster]) -> Result<BTreeSet<i64>> {
    let ids: BTreeSet<_> = catalog.iter().map(|cluster| cluster.id).collect();
    ensure!(
        !ids.is_empty() && ids.len() == catalog.len(),
        "catalog IDs must be nonempty and unique"
    );
    Ok(ids)
}

fn index<'a>(
    rows: &'a [AssignmentRecord],
    allowed: &BTreeSet<i64>,
) -> Result<BTreeMap<&'a str, &'a AssignmentRecord>> {
    ensure!(!rows.is_empty(), "cannot compare empty assignments");
    let mut index = BTreeMap::new();
    for row in rows {
        ensure!(!row.id.trim().is_empty(), "assignment ID is empty");
        ensure!(
            row.cluster_id.is_none_or(|id| allowed.contains(&id)),
            "assignment contains unknown catalog ID"
        );
        ensure!(
            !row.refused || row.cluster_id.is_none(),
            "refused assignment cannot have a named cluster"
        );
        ensure!(
            index.insert(row.id.as_str(), row).is_none(),
            "duplicate assignment ID {}",
            row.id
        );
    }
    Ok(index)
}

fn gain_loss(pairs: impl Iterator<Item = (bool, bool)>) -> GainLoss {
    let (mut stayed_agree, mut gained_agreement, mut lost_agreement, mut stayed_disagree) =
        (0, 0, 0, 0);
    for (old, new) in pairs {
        match (old, new) {
            (true, true) => stayed_agree += 1,
            (false, true) => gained_agreement += 1,
            (true, false) => lost_agreement += 1,
            (false, false) => stayed_disagree += 1,
        }
    }
    let n = stayed_agree + gained_agreement + lost_agreement + stayed_disagree;
    let net_gain_count = gained_agreement as i64 - lost_agreement as i64;
    GainLoss {
        stayed_agree,
        gained_agreement,
        lost_agreement,
        stayed_disagree,
        original_agreement: (stayed_agree + lost_agreement) as f64 / n as f64,
        guided_agreement: (stayed_agree + gained_agreement) as f64 / n as f64,
        net_gain_count,
        net_gain_fraction: net_gain_count as f64 / n as f64,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn catalog() -> Vec<crate::types::Cluster> {
        (1..=3)
            .map(|id| crate::types::Cluster {
                id,
                name: format!("Category {id}"),
                description: format!("Items in category {id}"),
            })
            .collect()
    }

    fn row(id: &str, cluster_id: Option<i64>) -> AssignmentRecord {
        AssignmentRecord {
            id: id.into(),
            cluster_id,
            refused: false,
            label: None,
        }
    }

    #[test]
    fn fixed_id_agreement_and_partition_agreement_measure_different_properties()
    -> anyhow::Result<()> {
        let reference = vec![row("a", Some(1)), row("b", Some(1)), row("c", Some(2))];
        let candidate = vec![row("c", Some(1)), row("b", Some(2)), row("a", Some(2))];
        let score = compare_assignments(&reference, &candidate, &catalog())?;
        assert_eq!(score.direct_agreement_count, 0);
        assert_eq!(score.named_id_agreement_count, 0);
        assert_eq!(score.partition.adjusted_rand_index, 1.0);
        assert_eq!(score.partition.pairwise_f1, 1.0);
        Ok(())
    }

    #[test]
    fn other_contingency_and_category_confusion_keep_all_points_in_denominators()
    -> anyhow::Result<()> {
        let reference = vec![
            row("a", Some(1)),
            row("b", Some(1)),
            row("c", Some(2)),
            row("d", Some(2)),
            row("e", None),
            row("f", None),
        ];
        let candidate = vec![
            row("f", None),
            row("d", Some(3)),
            row("b", Some(1)),
            row("e", Some(2)),
            row("a", Some(1)),
            row("c", None),
        ];
        let score = compare_assignments(&reference, &candidate, &catalog())?;
        assert_eq!(score.n, 6);
        assert_eq!(score.direct_agreement_count, 3);
        assert_eq!(score.direct_agreement, 0.5);
        assert_eq!(score.named_id_agreement_count, 2);
        assert_eq!(score.named_id_agreement, 2.0 / 6.0);
        assert_eq!(score.reference_coverage, 4.0 / 6.0);
        assert_eq!(score.candidate_coverage, 4.0 / 6.0);
        assert_eq!(score.assigned_other.both_named, 3);
        assert_eq!(score.assigned_other.reference_named_candidate_other, 1);
        assert_eq!(score.assigned_other.reference_other_candidate_named, 1);
        assert_eq!(score.assigned_other.both_other, 1);
        assert_eq!(score.jointly_named_agreement, Some(2.0 / 3.0));
        let category = score
            .categories
            .iter()
            .find(|entry| entry.cluster_id == Some(2))
            .unwrap();
        assert_eq!(
            (
                category.reference_count,
                category.candidate_count,
                category.same_count
            ),
            (2, 1, 0)
        );
        assert_eq!(
            (category.false_positive_count, category.false_negative_count),
            (1, 2)
        );
        assert_eq!(
            score.confusion.iter().map(|cell| cell.count).sum::<usize>(),
            6
        );
        assert!((score.partition.adjusted_rand_index - 26.0 / 41.0).abs() < 1e-12);
        assert_eq!(score.partition.pairwise_precision, 1.0);
        assert_eq!(score.partition.pairwise_recall, 0.5);
        Ok(())
    }

    #[test]
    fn all_other_agreement_has_zero_named_agreement_and_no_conditional_denominator()
    -> anyhow::Result<()> {
        let rows = vec![row("a", None), row("b", None), row("c", None)];
        let score = compare_assignments(&rows, &rows, &catalog())?;
        assert_eq!(score.direct_agreement, 1.0);
        assert_eq!(score.named_id_agreement, 0.0);
        assert_eq!(score.jointly_named_agreement, None);
        assert_eq!(score.partition.adjusted_rand_index, 1.0);
        assert_eq!(score.partition.pairwise_f1, 1.0);
        assert!(score.other_policy.contains("singleton"));
        Ok(())
    }

    #[test]
    fn comparisons_reject_duplicate_missing_unknown_and_contradictory_rows() {
        let reference = vec![row("a", Some(1)), row("b", None)];
        for candidate in [
            vec![row("a", Some(1))],
            vec![row("a", Some(1)), row("a", None)],
            vec![row("a", Some(9)), row("b", None)],
            vec![row("a", Some(1)), row("c", None)],
            vec![],
        ] {
            assert!(compare_assignments(&reference, &candidate, &catalog()).is_err());
        }
        let mut invalid = reference.clone();
        invalid[0].refused = true;
        assert!(compare_assignments(&reference, &invalid, &catalog()).is_err());
        let mut duplicate_catalog = catalog();
        duplicate_catalog.push(duplicate_catalog[0].clone());
        assert!(compare_assignments(&reference, &reference, &duplicate_catalog).is_err());
        assert!(compare_assignments(&[], &[], &catalog()).is_err());
    }

    #[test]
    fn paired_gains_expose_reference_drift_and_keep_original_reference_diagnostic_separate()
    -> anyhow::Result<()> {
        let original_reference = vec![
            row("a", Some(1)),
            row("b", Some(1)),
            row("c", None),
            row("d", Some(2)),
        ];
        let original_candidate = vec![
            row("a", Some(2)),
            row("b", Some(1)),
            row("c", None),
            row("d", Some(2)),
        ];
        let guided_reference = vec![
            row("a", Some(2)),
            row("b", Some(1)),
            row("c", None),
            row("d", Some(2)),
        ];
        let guided_candidate = vec![
            row("a", Some(2)),
            row("b", Some(3)),
            row("c", None),
            row("d", Some(2)),
        ];
        let gains = paired_gain_loss(
            &original_reference,
            &original_candidate,
            &guided_reference,
            &guided_candidate,
            &catalog(),
        )?;
        assert_eq!(gains.n, 4);
        assert_eq!(gains.condition_matched_direct.gained_agreement, 1);
        assert_eq!(gains.condition_matched_direct.lost_agreement, 1);
        assert_eq!(gains.condition_matched_direct.net_gain_count, 0);
        assert_eq!(gains.original_reference_anchored_direct.gained_agreement, 0);
        assert_eq!(gains.original_reference_anchored_direct.lost_agreement, 1);
        assert_eq!(gains.reference_id_changes, 1);
        assert_eq!(gains.candidate_id_changes, 1);
        assert!(gains.anchored_diagnostic_note.contains("preplanned"));
        assert!(gains.anchored_diagnostic_note.contains("diagnostic"));
        Ok(())
    }

    #[test]
    fn repeat_consistency_requires_the_exact_predeclared_subset() -> anyhow::Result<()> {
        let primary = vec![row("a", Some(1)), row("b", Some(2)), row("c", None)];
        let repeated = vec![row("c", None), row("a", Some(2))];
        let selected = vec!["a".into(), "c".into()];
        let score = repeat_consistency(&primary, &repeated, &selected, &catalog())?;
        assert_eq!(score.n, 2);
        assert_eq!(score.direct_agreement, 0.5);
        assert!(repeat_consistency(&primary, &repeated, &["a".into()], &catalog()).is_err());
        assert!(
            repeat_consistency(&primary, &repeated, &["a".into(), "a".into()], &catalog()).is_err()
        );
        assert!(
            repeat_consistency(
                &primary,
                &repeated,
                &["a".into(), "unknown".into()],
                &catalog()
            )
            .is_err()
        );
        Ok(())
    }
}
