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
            match reply.value {
                Assignment::Cluster(id) => {
                    if !page.iter().any(|c| c.id == id) {
                        bail!("model selected cluster {id} outside candidate page");
                    }
                    return Ok(Some(id));
                }
                Assignment::Other => (),
                Assignment::Refused => {
                    self.store.record_event(
                        "assignment_refusal",
                        &serde_json::json!({"point_id":item.id,"phase":phase}),
                    )?;
                    return Ok(None);
                }
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
        let session: usize = self.store.connection.query_row(
            "SELECT COUNT(*)+1 FROM events WHERE kind='run_start'",
            [],
            |row| row.get(0),
        )?;
        self.store.record_event("run_start", &serde_json::json!({
            "session":session,"saved_count":saved.len(),"prior_wall_ms":prior_ms,
            "started_at_unix_ms":std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_millis() as u64
        }))?;
        let result = self.run_inner(items, saved.len()).await;
        let elapsed_ms = started.elapsed().as_millis() as u64;
        if result.is_err() {
            // A terminal error can include a dispatched request whose journal write failed.
            self.store.set_meta("cost_history_complete", "false")?;
        }
        self.store
            .set_meta("wall_ms", &(prior_ms + elapsed_ms).to_string())?;
        self.store.record_event(
            "run_finish",
            &serde_json::json!({
                "session":session,"elapsed_ms":elapsed_ms,"success":result.is_ok(),
                "error":result.as_ref().err().map(ToString::to_string)
            }),
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
        refuse: bool,
        fail: bool,
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
        ) -> Result<ModelReply<Assignment>> {
            self.pages
                .lock()
                .unwrap()
                .push(clusters.iter().map(|c| c.id).collect());
            if self.fail {
                bail!("request completed but journal write failed");
            }
            Ok(reply(if self.refuse {
                Assignment::Refused
            } else {
                clusters
                    .iter()
                    .find(|c| c.name == "target")
                    .map(|c| Assignment::Cluster(c.id))
                    .unwrap_or(Assignment::Other)
            }))
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
                refuse: false,
                fail: false,
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
    #[tokio::test]
    async fn refusal_stops_paging_and_retains_unassigned_point_with_reason() -> Result<()> {
        let mut c = clusterer()?;
        c.config.k = 1;
        c.model.refuse = true;
        c.store.apply(
            &Plan {
                operations: vec![
                    Operation::Create {
                        name: "a".into(),
                        description: "a".into(),
                    },
                    Operation::Create {
                        name: "b".into(),
                        description: "b".into(),
                    },
                ],
            },
            5,
        )?;
        let point = item("refused");
        let target = c.assign(&point, "assign").await?;
        c.store.insert(&point, target)?;
        assert_eq!(target, None);
        assert_eq!(c.model.pages.lock().unwrap().len(), 1);
        assert_eq!(c.store.assignments()?, vec![(point, None)]);
        let payload: String = c.store.connection.query_row(
            "SELECT payload FROM events WHERE kind='assignment_refusal'",
            [],
            |r| r.get(0),
        )?;
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&payload)?,
            serde_json::json!({"point_id":"refused","phase":"assign"})
        );
        Ok(())
    }

    #[tokio::test]
    async fn session_boundaries_identify_appended_processing_and_terminal_errors() -> Result<()> {
        let mut c = clusterer()?;
        c.run(&[item("a"), item("b")]).await?;
        c.run(&[item("a"), item("b"), item("c")]).await?;
        let starts: Vec<String> = c
            .store
            .connection
            .prepare("SELECT payload FROM events WHERE kind='run_start' ORDER BY id")?
            .query_map([], |r| r.get(0))?
            .collect::<rusqlite::Result<_>>()?;
        assert_eq!(starts.len(), 2);
        let first: serde_json::Value = serde_json::from_str(&starts[0])?;
        let second: serde_json::Value = serde_json::from_str(&starts[1])?;
        assert_eq!(first["session"], 1);
        assert_eq!(first["saved_count"], 0);
        assert_eq!(first["prior_wall_ms"], 0);
        assert_eq!(second["session"], 2);
        assert_eq!(second["saved_count"], 2);
        c.model.fail = true;
        assert!(
            c.run(&[item("a"), item("b"), item("c"), item("d")])
                .await
                .is_err()
        );
        assert_eq!(
            c.store.get_meta("cost_history_complete")?,
            Some("false".into())
        );
        assert_eq!(c.store.get_meta("run_in_progress")?, Some("0".into()));
        let finish: String = c.store.connection.query_row(
            "SELECT payload FROM events WHERE kind='run_finish' ORDER BY id DESC LIMIT 1",
            [],
            |r| r.get(0),
        )?;
        let finish: serde_json::Value = serde_json::from_str(&finish)?;
        assert_eq!(finish["session"], 3);
        assert_eq!(finish["success"], false);
        assert_eq!(c.store.count()?, 3);
        Ok(())
    }
}
