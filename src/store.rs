use crate::types::*;
use anyhow::{Result, bail};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::Value;
use std::path::Path;

pub struct Store {
    pub connection: Connection,
}

impl Store {
    pub fn open(path: &Path, config: &Value) -> Result<Self> {
        let connection = Connection::open(path)?;
        connection.execute_batch(
            "PRAGMA foreign_keys=ON;
             CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS points(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS clusters(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
             CREATE TABLE IF NOT EXISTS assignments(point_id TEXT PRIMARY KEY REFERENCES points(id),cluster_id INTEGER REFERENCES clusters(id));
             CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
             CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS reassignment(point_id TEXT PRIMARY KEY REFERENCES points(id));",
        )?;
        let store = Self { connection };
        match store.get_meta("config")? {
            Some(saved) if serde_json::from_str::<Value>(&saved)? != *config => {
                bail!("database configuration differs from this run")
            }
            Some(_) => (),
            None => store.set_meta("config", &config.to_string())?,
        }
        Ok(store)
    }

    pub fn get_meta(&self, key: &str) -> Result<Option<String>> {
        Ok(self
            .connection
            .query_row("SELECT value FROM meta WHERE key=?", [key], |r| r.get(0))
            .optional()?)
    }

    pub fn set_meta(&self, key: &str, value: &str) -> Result<()> {
        self.connection.execute(
            "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [key, value],
        )?;
        Ok(())
    }

    pub fn count(&self) -> Result<usize> {
        Ok(self
            .connection
            .query_row("SELECT COUNT(*) FROM points", [], |r| r.get(0))?)
    }

    pub fn item(&self, id: &str) -> Result<Option<Item>> {
        let payload: Option<String> = self
            .connection
            .query_row("SELECT payload FROM points WHERE id=?", [id], |r| r.get(0))
            .optional()?;
        payload.map(|s| Ok(serde_json::from_str(&s)?)).transpose()
    }

    pub fn clusters(&self) -> Result<Vec<Cluster>> {
        let mut stmt = self
            .connection
            .prepare("SELECT id,name,description FROM clusters WHERE active=1 ORDER BY id")?;
        Ok(stmt
            .query_map([], |r| {
                Ok(Cluster {
                    id: r.get(0)?,
                    name: r.get(1)?,
                    description: r.get(2)?,
                })
            })?
            .collect::<rusqlite::Result<_>>()?)
    }

    pub fn record_call(&self, call: &CallRecord) -> Result<()> {
        self.connection.execute(
            "INSERT INTO calls(payload) VALUES(?)",
            [serde_json::to_string(call)?],
        )?;
        Ok(())
    }

    pub fn insert(&mut self, item: &Item, cluster: Option<i64>) -> Result<()> {
        let tx = self.connection.transaction()?;
        tx.execute(
            "INSERT INTO points VALUES(?,(SELECT COALESCE(MAX(ordinal)+1,0) FROM points),?)",
            params![item.id, serde_json::to_string(item)?],
        )?;
        tx.execute(
            "INSERT INTO assignments VALUES(?,?)",
            params![item.id, cluster],
        )?;
        if cluster.is_none() {
            tx.execute("INSERT INTO meta VALUES('novelty','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1",[])?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn pending(&self) -> Result<Vec<Item>> {
        let mut stmt=self.connection.prepare("SELECT p.payload FROM points p JOIN reassignment q ON q.point_id=p.id ORDER BY p.ordinal")?;
        let values = stmt
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        values
            .into_iter()
            .map(|s| Ok(serde_json::from_str(&s)?))
            .collect()
    }

    pub fn reassign(&mut self, item: &Item, cluster: Option<i64>) -> Result<()> {
        let tx = self.connection.transaction()?;
        tx.execute(
            "UPDATE assignments SET cluster_id=? WHERE point_id=?",
            params![cluster, item.id],
        )?;
        tx.execute("DELETE FROM reassignment WHERE point_id=?", [&item.id])?;
        tx.execute(
            "INSERT INTO events(kind,payload) VALUES('reassign',?)",
            [serde_json::json!({"point_id":item.id,"cluster_id":cluster}).to_string()],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn examples(&self, limit: usize) -> Result<Vec<Example>> {
        if limit == 0 {
            return Ok(Vec::new());
        }
        let mut stmt=self.connection.prepare("SELECT p.payload,a.cluster_id FROM points p JOIN assignments a ON a.point_id=p.id ORDER BY p.ordinal")?;
        let rows = stmt
            .query_map([], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, Option<i64>>(1)?))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        // Spread representatives across the stream; retain extra room for novelty.
        let mut groups = std::collections::BTreeMap::<Option<i64>, Vec<Item>>::new();
        for (payload, cluster) in rows {
            groups
                .entry(cluster)
                .or_default()
                .push(serde_json::from_str(&payload)?);
        }
        let groups: Vec<_> = groups.into_iter().collect();
        let mut quotas = vec![0; groups.len()];
        let mut remaining = limit;
        'allocate: for round in 0..24 {
            for (index, (cluster, items)) in groups.iter().enumerate() {
                let take = if cluster.is_none() { 24 } else { 2 };
                if round >= take || round >= items.len() {
                    continue;
                }
                quotas[index] += 1;
                remaining -= 1;
                if remaining == 0 {
                    break 'allocate;
                }
            }
        }
        let mut result = Vec::new();
        for round in 0..24 {
            for ((cluster, items), &quota) in groups.iter().zip(&quotas) {
                if round >= quota {
                    continue;
                }
                // Use the allocated quota so a crowded review still spans the history.
                let index = if quota == 1 {
                    items.len() - 1
                } else {
                    round * (items.len() - 1) / (quota - 1)
                };
                result.push(Example {
                    item: items[index].clone(),
                    cluster_id: *cluster,
                });
            }
        }
        Ok(result)
    }

    pub fn apply(&mut self, plan: &Plan, max_clusters: usize) -> Result<()> {
        let tx = self.connection.transaction()?;
        let mut touched = std::collections::HashSet::new();
        for op in &plan.operations {
            let sources = match op {
                Operation::Create { .. } => vec![],
                Operation::Rename { id, .. }
                | Operation::Split { id, .. }
                | Operation::Retire { id } => vec![*id],
                Operation::Merge { ids, .. } => {
                    if ids.len() < 2 {
                        bail!("merge requires at least two clusters");
                    }
                    ids.clone()
                }
            };
            for id in &sources {
                if !touched.insert(*id) {
                    bail!("cluster {id} is used twice in one plan");
                }
                let exists: bool = tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM clusters WHERE id=? AND active=1)",
                    [id],
                    |r| r.get(0),
                )?;
                if !exists {
                    bail!("cluster {id} is not active");
                }
                tx.execute("INSERT OR IGNORE INTO reassignment SELECT point_id FROM assignments WHERE cluster_id=?",[id])?;
            }
            let add = |name: &str, description: &str| -> Result<()> {
                if name.trim().is_empty()
                    || description.trim().is_empty()
                    || name.len() > 500
                    || description.len() > 4000
                {
                    bail!("invalid cluster definition");
                }
                tx.execute(
                    "INSERT INTO clusters(name,description) VALUES(?,?)",
                    [name, description],
                )?;
                Ok(())
            };
            match op {
                Operation::Create { name, description } => add(name, description)?,
                Operation::Rename {
                    id,
                    name,
                    description,
                } => {
                    if name.trim().is_empty()
                        || description.trim().is_empty()
                        || name.len() > 500
                        || description.len() > 4000
                    {
                        bail!("invalid cluster definition");
                    }
                    tx.execute(
                        "UPDATE clusters SET name=?,description=? WHERE id=?",
                        params![name, description, id],
                    )?;
                }
                Operation::Merge {
                    name, description, ..
                } => add(name, description)?,
                Operation::Split { children, .. } => {
                    if children.len() < 2 {
                        bail!("split requires at least two children");
                    }
                    for child in children {
                        add(&child.name, &child.description)?;
                    }
                }
                Operation::Retire { .. } => (),
            }
            if !matches!(op, Operation::Rename { .. }) {
                for id in sources {
                    tx.execute("UPDATE clusters SET active=0 WHERE id=?", [id])?;
                    tx.execute(
                        "UPDATE assignments SET cluster_id=NULL WHERE cluster_id=?",
                        [id],
                    )?;
                }
            }
        }
        let count: usize =
            tx.query_row("SELECT COUNT(*) FROM clusters WHERE active=1", [], |r| {
                r.get(0)
            })?;
        if count > max_clusters {
            bail!("plan exceeds cluster cap: {count} > {max_clusters}");
        }
        if !plan.operations.is_empty() {
            tx.execute("INSERT OR IGNORE INTO reassignment SELECT point_id FROM assignments WHERE cluster_id IS NULL",[])?;
        }
        tx.execute(
            "INSERT INTO events(kind,payload) VALUES('maintenance',?)",
            [serde_json::to_string(plan)?],
        )?;
        tx.execute("INSERT INTO meta VALUES('last_maintenance',(SELECT COUNT(*) FROM points)) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[])?;
        tx.execute(
            "INSERT INTO meta VALUES('novelty','0') ON CONFLICT(key) DO UPDATE SET value='0'",
            [],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn assignments(&self) -> Result<Vec<(Item, Option<i64>)>> {
        let mut stmt=self.connection.prepare("SELECT p.payload,a.cluster_id FROM points p JOIN assignments a ON a.point_id=p.id ORDER BY p.ordinal")?;
        let rows = stmt
            .query_map([], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, Option<i64>>(1)?))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        rows.into_iter()
            .map(|(s, c)| Ok((serde_json::from_str(&s)?, c)))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn item(id: &str) -> Item {
        Item {
            id: id.into(),
            text: id.into(),
            image: None,
            label: None,
        }
    }
    fn create(name: &str) -> Operation {
        Operation::Create {
            name: name.into(),
            description: name.into(),
        }
    }
    #[test]
    fn maintenance_creates_clusters_and_queues_other() -> Result<()> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        db.insert(&item("a"), None)?;
        db.apply(
            &Plan {
                operations: vec![create("A"), create("B")],
            },
            2,
        )?;
        assert_eq!(db.clusters()?.len(), 2);
        assert_eq!(db.pending()?.len(), 1);
        Ok(())
    }

    #[test]
    fn crowded_review_samples_include_the_oldest_and_newest_other() -> Result<()> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        db.apply(
            &Plan {
                operations: (0..16)
                    .map(|index| create(&format!("cluster {index}")))
                    .collect(),
            },
            16,
        )?;
        for cluster in 1..=16 {
            db.insert(&item(&format!("cluster-{cluster}-first")), Some(cluster))?;
            db.insert(&item(&format!("cluster-{cluster}-last")), Some(cluster))?;
        }
        for index in 0..100 {
            db.insert(&item(&format!("other-{index}")), None)?;
        }
        let examples = db.examples(40)?;
        assert_eq!(examples.len(), 40);
        assert!(examples.iter().any(|example| example.item.id == "other-0"));
        assert!(
            examples.iter().any(|example| example.item.id == "other-99"),
            "novelty-triggered review must see the newest Other point even when named clusters consume most slots"
        );
        for cluster in 1..=16 {
            assert_eq!(
                examples
                    .iter()
                    .filter(|example| example.cluster_id == Some(cluster))
                    .count(),
                2
            );
        }
        assert!(db.examples(0)?.is_empty());
        Ok(())
    }

    #[test]
    fn one_review_slot_selects_the_latest_other_point() -> Result<()> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        for id in ["old", "middle", "new"] {
            db.insert(&item(id), None)?;
        }
        let examples = db.examples(1)?;
        assert_eq!(examples.len(), 1);
        assert_eq!(examples[0].item.id, "new");
        Ok(())
    }

    #[test]
    fn merge_split_retire_conserve_points_and_only_queue_affected() -> Result<()> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        db.apply(
            &Plan {
                operations: vec![create("A"), create("B"), create("C")],
            },
            4,
        )?;
        db.insert(&item("a"), Some(1))?;
        db.insert(&item("b"), Some(2))?;
        db.insert(&item("c"), Some(3))?;
        db.apply(
            &Plan {
                operations: vec![Operation::Merge {
                    ids: vec![1, 2],
                    name: "AB".into(),
                    description: "merged".into(),
                }],
            },
            4,
        )?;
        assert_eq!(db.count()?, 3);
        assert_eq!(
            db.pending()?
                .iter()
                .map(|p| p.id.as_str())
                .collect::<Vec<_>>(),
            vec!["a", "b"]
        );
        assert_eq!(db.assignments()?[2].1, Some(3));
        for point in db.pending()? {
            db.reassign(&point, Some(4))?;
        }
        db.apply(
            &Plan {
                operations: vec![Operation::Split {
                    id: 4,
                    children: vec![
                        Definition {
                            name: "AA".into(),
                            description: "a".into(),
                        },
                        Definition {
                            name: "BB".into(),
                            description: "b".into(),
                        },
                    ],
                }],
            },
            4,
        )?;
        assert_eq!(db.clusters()?.len(), 3);
        assert_eq!(db.pending()?.len(), 2);
        for point in db.pending()? {
            db.reassign(&point, Some(5))?;
        }
        db.apply(
            &Plan {
                operations: vec![Operation::Retire { id: 5 }],
            },
            4,
        )?;
        assert_eq!(db.count()?, 3);
        assert_eq!(db.pending()?.len(), 2);
        assert!(db.assignments()?.iter().take(2).all(|(_, c)| c.is_none()));
        Ok(())
    }

    #[test]
    fn invalid_plans_roll_back_clusters_assignments_events_and_queue() -> Result<()> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        db.apply(
            &Plan {
                operations: vec![create("A")],
            },
            1,
        )?;
        db.insert(&item("a"), Some(1))?;
        assert!(
            db.apply(
                &Plan {
                    operations: vec![create("B")]
                },
                1
            )
            .is_err()
        );
        assert!(
            db.apply(
                &Plan {
                    operations: vec![Operation::Merge {
                        ids: vec![1, 1],
                        name: "dup".into(),
                        description: "dup".into()
                    }]
                },
                2
            )
            .is_err()
        );
        assert!(
            db.apply(
                &Plan {
                    operations: vec![Operation::Retire { id: 999 }]
                },
                2
            )
            .is_err()
        );
        assert_eq!(db.clusters()?.len(), 1);
        assert_eq!(db.assignments()?[0].1, Some(1));
        assert!(db.pending()?.is_empty());
        let events: usize = db
            .connection
            .query_row("SELECT COUNT(*) FROM events", [], |r| r.get(0))?;
        assert_eq!(events, 1);
        Ok(())
    }

    #[test]
    fn state_and_pending_queue_survive_reopen_and_config_mismatch_is_rejected() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("state.sqlite");
        {
            let mut db = Store::open(&path, &serde_json::json!({"k":8}))?;
            db.insert(&item("a"), None)?;
            db.apply(
                &Plan {
                    operations: vec![create("A")],
                },
                1,
            )?;
        }
        let db = Store::open(&path, &serde_json::json!({"k":8}))?;
        assert_eq!(db.count()?, 1);
        assert_eq!(db.pending()?.len(), 1);
        assert!(Store::open(&path, &serde_json::json!({"k":4})).is_err());
        Ok(())
    }
}
