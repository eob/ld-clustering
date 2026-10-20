use crate::{store::Store, types::*};
use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Config {
    pub task: String,
    pub k: usize,
    pub max_clusters: usize,
    pub bootstrap_size: usize,
    pub novelty_trigger: usize,
    pub maintenance_interval: usize,
}

impl Config {
    pub fn validate(&self) -> Result<()> {
        if !(1..=254).contains(&self.k)
            || self.max_clusters == 0
            || self.bootstrap_size == 0
            || self.novelty_trigger == 0
            || self.maintenance_interval == 0
            || self.task.trim().is_empty()
        {
            bail!("invalid clustering configuration");
        }
        Ok(())
    }
}

pub struct Clusterer<M> {
    pub store: Store,
    pub model: M,
    pub config: Config,
}

impl<M: Model> Clusterer<M> {
    pub async fn assign(&mut self, item: &Item, phase: &str) -> Result<Option<i64>> {
        let clusters = self.store.clusters()?;
        for page in clusters.chunks(self.config.k) {
            let mut reply = self.model.assign(&self.config.task, item, page).await?;
            reply.call.phase = phase.to_owned();
            self.store.record_call(&reply.call)?;
            if let Some(id) = reply.value {
                if !page.iter().any(|c| c.id == id) {
                    bail!("model selected cluster {id} outside candidate page");
                }
                return Ok(Some(id));
            }
        }
        Ok(None)
    }

    pub async fn drain_reassignment(&mut self) -> Result<()> {
        for item in self.store.pending()? {
            let target = self.assign(&item, "reassign").await?;
            self.store.reassign(&item, target)?;
        }
        Ok(())
    }

    pub async fn maintain(&mut self) -> Result<()> {
        let clusters = self.store.clusters()?;
        let examples = self.store.examples(40)?;
        let reply = self
            .model
            .plan(
                &self.config.task,
                &clusters,
                &examples,
                self.config.max_clusters,
            )
            .await?;
        self.store.record_call(&reply.call)?;
        self.store.apply(&reply.value, self.config.max_clusters)?;
        self.drain_reassignment().await
    }

    async fn maybe_maintain(&mut self, final_pass: bool) -> Result<()> {
        let count = self.store.count()?;
        let last = self
            .store
            .get_meta("last_maintenance")?
            .unwrap_or_default()
            .parse::<usize>()
            .unwrap_or(0);
        let novelty = self
            .store
            .get_meta("novelty")?
            .unwrap_or_default()
            .parse::<usize>()
            .unwrap_or(0);
        if count == 0 || count == last {
            return Ok(());
        }
        if final_pass
            || (count >= self.config.bootstrap_size
                && (last == 0
                    || count - last >= self.config.maintenance_interval
                    || novelty >= self.config.novelty_trigger))
        {
            self.maintain().await?;
        }
        Ok(())
    }

    pub async fn run(&mut self, items: &[Item]) -> Result<()> {
        self.config.validate()?;
        let mut ids = std::collections::HashSet::new();
        for item in items {
            if !ids.insert(&item.id) {
                bail!("duplicate input id {}", item.id);
            }
        }
        let saved = self.store.assignments()?;
        if saved.len() > items.len()
            || saved
                .iter()
                .zip(items)
                .any(|((saved, _), input)| saved != input)
        {
            bail!("input stream differs from the persisted prefix");
        }
        let started = std::time::Instant::now();
        if self.store.get_meta("run_in_progress")?.as_deref() == Some("1") {
            self.store.set_meta("timing_complete", "false")?;
        } else if self.store.get_meta("timing_complete")?.is_none() {
            self.store.set_meta("timing_complete", "true")?;
        }
        self.store.set_meta("run_in_progress", "1")?;
        let prior_ms = self
            .store
            .get_meta("wall_ms")?
            .unwrap_or_default()
            .parse::<u64>()
            .unwrap_or(0);
        let result = self.run_inner(items, saved.len()).await;
        self.store.set_meta(
            "wall_ms",
            &(prior_ms + started.elapsed().as_millis() as u64).to_string(),
        )?;
        self.store.set_meta("run_in_progress", "0")?;
        result
    }

    async fn run_inner(&mut self, items: &[Item], saved: usize) -> Result<()> {
        self.drain_reassignment().await?;
        self.maybe_maintain(false).await?;
        for item in &items[saved..] {
            let target = self.assign(item, "assign").await?;
            self.store.insert(item, target)?;
            self.maybe_maintain(false).await?;
            eprintln!(
                "processed {} / {} ({} clusters)",
                self.store.count()?,
                items.len(),
                self.store.clusters()?.len()
            );
        }
        self.maybe_maintain(true).await?;
        self.store
            .set_meta("completed_count", &items.len().to_string())?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use std::{path::Path, sync::Mutex};
    struct Mock {
        pages: Mutex<Vec<Vec<i64>>>,
    }
    fn reply<T>(value: T) -> ModelReply<T> {
        ModelReply {
            value,
            call: CallRecord {
                phase: "test".into(),
                model: "mock".into(),
                request: serde_json::json!({}),
                response: serde_json::json!({}),
                elapsed_ms: 0,
                usage: Usage::default(),
            },
        }
    }
    #[async_trait]
    impl Model for Mock {
        async fn assign(
            &self,
            _task: &str,
            _item: &Item,
            clusters: &[Cluster],
        ) -> Result<ModelReply<Option<i64>>> {
            self.pages
                .lock()
                .unwrap()
                .push(clusters.iter().map(|c| c.id).collect());
            Ok(reply(
                clusters.iter().find(|c| c.name == "target").map(|c| c.id),
            ))
        }
        async fn plan(
            &self,
            _task: &str,
            clusters: &[Cluster],
            _examples: &[Example],
            _max: usize,
        ) -> Result<ModelReply<Plan>> {
            Ok(reply(Plan {
                operations: if clusters.is_empty() {
                    vec![Operation::Create {
                        name: "target".into(),
                        description: "target".into(),
                    }]
                } else {
                    vec![]
                },
            }))
        }
    }
    fn clusterer() -> Result<Clusterer<Mock>> {
        Ok(Clusterer {
            store: Store::open(Path::new(":memory:"), &serde_json::json!({}))?,
            model: Mock {
                pages: Mutex::new(vec![]),
            },
            config: Config {
                task: "group".into(),
                k: 2,
                max_clusters: 5,
                bootstrap_size: 2,
                novelty_trigger: 2,
                maintenance_interval: 100,
            },
        })
    }
    fn item(id: &str) -> Item {
        Item {
            id: id.into(),
            text: id.into(),
            image: None,
            label: None,
        }
    }

    #[tokio::test]
    async fn bounded_pages_visit_every_candidate_until_a_match() -> Result<()> {
        let mut c = clusterer()?;
        c.store.apply(
            &Plan {
                operations: (0..5)
                    .map(|i| Operation::Create {
                        name: if i == 4 {
                            "target".into()
                        } else {
                            i.to_string()
                        },
                        description: "x".into(),
                    })
                    .collect(),
            },
            5,
        )?;
        assert_eq!(c.assign(&item("a"), "assign").await?, Some(5));
        assert_eq!(
            *c.model.pages.lock().unwrap(),
            vec![vec![1, 2], vec![3, 4], vec![5]]
        );
        Ok(())
    }

    #[tokio::test]
    async fn other_is_retained_after_all_pages_fail_to_match() -> Result<()> {
        let mut c = clusterer()?;
        c.store.apply(
            &Plan {
                operations: vec![Operation::Create {
                    name: "unrelated".into(),
                    description: "x".into(),
                }],
            },
            5,
        )?;
        assert_eq!(c.assign(&item("a"), "assign").await?, None);
        assert_eq!(c.model.pages.lock().unwrap().len(), 1);
        Ok(())
    }

    #[tokio::test]
    async fn bootstrap_reassignment_restart_and_final_maintenance_preserve_stream() -> Result<()> {
        let mut c = clusterer()?;
        let items = vec![item("a"), item("b"), item("c")];
        c.run(&items).await?;
        assert_eq!(c.store.count()?, 3);
        assert!(c.store.assignments()?.iter().all(|(_, id)| *id == Some(1)));
        assert!(c.store.pending()?.is_empty());
        let requests = c.model.pages.lock().unwrap().len();
        c.run(&items).await?;
        assert_eq!(c.model.pages.lock().unwrap().len(), requests);
        assert!(c.run(&[item("wrong"), item("b"), item("c")]).await.is_err());
        assert!(c.run(&[item("a"), item("a")]).await.is_err());
        assert_eq!(c.store.get_meta("last_maintenance")?, Some("3".into()));
        Ok(())
    }

    #[test]
    fn invalid_config_is_rejected() -> Result<()> {
        let mut c = clusterer()?;
        c.config.k = 0;
        assert!(c.config.validate().is_err());
        c.config.k = 255;
        assert!(c.config.validate().is_err());
        Ok(())
    }

    #[tokio::test]
    async fn unclean_resume_does_not_claim_complete_wall_time() -> Result<()> {
        let mut c = clusterer()?;
        c.store.set_meta("run_in_progress", "1")?;
        c.run(&[item("a"), item("b")]).await?;
        assert_eq!(c.store.get_meta("timing_complete")?, Some("false".into()));
        assert_eq!(c.store.get_meta("run_in_progress")?, Some("0".into()));
        assert_eq!(c.store.get_meta("completed_count")?, Some("2".into()));
        Ok(())
    }
}
