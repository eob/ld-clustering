use crate::types::*;
use anyhow::{Result, bail};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::Path;

pub struct Store {
    pub connection: Connection,
}

impl Store {
    pub fn open(path: &Path, config: &Value) -> Result<Self> {
        let mut connection = Connection::open(path)?;
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
        let tx = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let columns = {
            let mut statement = tx.prepare("PRAGMA table_info(reassignment)")?;
            statement
                .query_map([], |row| row.get::<_, String>(1))?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        if !columns.iter().any(|name| name == "previous_cluster_id") {
            tx.execute_batch("ALTER TABLE reassignment ADD COLUMN previous_cluster_id INTEGER")?;
        }
        // Old pending rows cannot distinguish an original Other from an interim NULL.
        if !columns
            .iter()
            .any(|name| name == "previous_assignment_known")
        {
            tx.execute_batch("ALTER TABLE reassignment ADD COLUMN previous_assignment_known INTEGER NOT NULL DEFAULT 0")?;
        }
        tx.commit()?;
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

    pub fn bind_manager(&mut self, descriptor: &ManagerDescriptor) -> Result<()> {
        descriptor.validate()?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let saved: Option<String> = tx
            .query_row(
                "SELECT value FROM meta WHERE key='manager_descriptor'",
                [],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(saved) = saved {
            let existing: ManagerDescriptor = serde_json::from_str(&saved)?;
            existing.validate()?;
            if existing != *descriptor {
                bail!("database manager descriptor differs from this run");
            }
        } else {
            if descriptor.policy == ManagerPolicy::Contextual {
                let has_history: bool = tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM points UNION ALL SELECT 1 FROM assignments UNION ALL SELECT 1 FROM clusters UNION ALL SELECT 1 FROM calls UNION ALL SELECT 1 FROM events UNION ALL SELECT 1 FROM reassignment)",
                    [], |row| row.get(0)
                )?;
                if has_history {
                    bail!("contextual manager requires a fresh database without persisted history");
                }
            }
            tx.execute(
                "INSERT INTO meta(key,value) VALUES('manager_descriptor',?)",
                [serde_json::to_string(descriptor)?],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn manager_descriptor(&self) -> Result<ManagerDescriptor> {
        read_manager_descriptor(&self.connection)
    }

    pub fn get_meta(&self, key: &str) -> Result<Option<String>> {
        Ok(self
            .connection
            .query_row("SELECT value FROM meta WHERE key=?", [key], |r| r.get(0))
            .optional()?)
    }

    pub fn set_meta(&self, key: &str, value: &str) -> Result<()> {
        if key == "manager_descriptor" {
            bail!("use bind_manager to bind the manager descriptor");
        }
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
        read_catalog(&self.connection)
    }

    pub fn record_call(&self, call: &CallRecord) -> Result<()> {
        self.connection.execute(
            "INSERT INTO calls(payload) VALUES(?)",
            [serde_json::to_string(call)?],
        )?;
        Ok(())
    }

    pub fn record_event(&self, kind: &str, payload: &Value) -> Result<()> {
        self.connection.execute(
            "INSERT INTO events(kind,payload) VALUES(?,?)",
            params![kind, payload.to_string()],
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
        let origin: Option<(Option<i64>, bool)> = tx.query_row(
            "SELECT previous_cluster_id,previous_assignment_known FROM reassignment WHERE point_id=?",
            [&item.id], |row| Ok((row.get(0)?, row.get(1)?))
        ).optional()?;
        let Some((previous_cluster_id, previous_assignment_known)) = origin else {
            bail!("point {} is not pending reassignment", item.id);
        };
        let interim: Option<Option<i64>> = tx
            .query_row(
                "SELECT cluster_id FROM assignments WHERE point_id=?",
                [&item.id],
                |row| row.get(0),
            )
            .optional()?;
        let Some(interim_cluster_id) = interim else {
            bail!("point {} has no existing assignment", item.id);
        };
        let updated = tx.execute(
            "UPDATE assignments SET cluster_id=? WHERE point_id=?",
            params![cluster, item.id],
        )?;
        let deleted = tx.execute("DELETE FROM reassignment WHERE point_id=?", [&item.id])?;
        if updated != 1 || deleted != 1 {
            bail!("reassignment requires exactly one assignment and pending row");
        }
        let changed = previous_assignment_known.then_some(previous_cluster_id != cluster);
        tx.execute(
            "INSERT INTO events(kind,payload) VALUES('reassign',?)",
            [serde_json::json!({
                "point_id":item.id,"cluster_id":cluster,
                "previous_cluster_id":previous_cluster_id,
                "previous_assignment_known":previous_assignment_known,
                "interim_cluster_id":interim_cluster_id,"changed":changed
            })
            .to_string()],
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
        self.apply_with_policy(plan, max_clusters, ManagerPolicy::Original)
    }

    pub fn apply_with_policy(
        &mut self,
        plan: &Plan,
        max_clusters: usize,
        policy: ManagerPolicy,
    ) -> Result<()> {
        let tx = self.connection.transaction()?;
        if read_manager_descriptor(&tx)?.policy != policy {
            bail!("maintenance policy differs from the bound manager descriptor");
        }
        let before = read_catalog(&tx)?;
        let pending_before: usize =
            tx.query_row("SELECT COUNT(*) FROM reassignment", [], |row| row.get(0))?;
        let mut retired = Vec::new();
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
                if policy == ManagerPolicy::Original {
                    tx.execute("INSERT OR IGNORE INTO reassignment(point_id,previous_cluster_id,previous_assignment_known) SELECT point_id,cluster_id,1 FROM assignments WHERE cluster_id=?",[id])?;
                }
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
                    retired.push(id);
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
        let after = read_catalog(&tx)?;
        let catalog_changed = before != after;
        let catalog_change_count = before
            .iter()
            .filter(|cluster| !after.contains(cluster))
            .count()
            + after
                .iter()
                .filter(|cluster| !before.iter().any(|old| old.id == cluster.id))
                .count();
        let global_reconsideration = policy == ManagerPolicy::Contextual && catalog_changed;
        // Capture origins before retired members lose their previous assigned IDs.
        if global_reconsideration {
            tx.execute("INSERT OR IGNORE INTO reassignment(point_id,previous_cluster_id,previous_assignment_known) SELECT point_id,cluster_id,1 FROM assignments",[])?;
        } else if policy == ManagerPolicy::Original && !plan.operations.is_empty() {
            tx.execute("INSERT OR IGNORE INTO reassignment(point_id,previous_cluster_id,previous_assignment_known) SELECT point_id,cluster_id,1 FROM assignments WHERE cluster_id IS NULL",[])?;
        }
        for id in retired {
            tx.execute(
                "UPDATE assignments SET cluster_id=NULL WHERE cluster_id=?",
                [id],
            )?;
        }
        let pending_count: usize =
            tx.query_row("SELECT COUNT(*) FROM reassignment", [], |row| row.get(0))?;
        tx.execute(
            "INSERT INTO events(kind,payload) VALUES('maintenance',?)",
            [serde_json::to_string(plan)?],
        )?;
        tx.execute(
            "INSERT INTO events(kind,payload) VALUES('catalog_update',?)",
            [serde_json::json!({
                "policy":policy,
                "before_sha256":format!("{:x}", Sha256::digest(serde_json::to_vec(&before)?)),
                "after_sha256":format!("{:x}", Sha256::digest(serde_json::to_vec(&after)?)),
                "catalog_changed":catalog_changed,"catalog_change_count":catalog_change_count,
                "global_reconsideration":global_reconsideration,
                "newly_queued":pending_count-pending_before,"pending_count":pending_count
            })
            .to_string()],
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

fn read_manager_descriptor(connection: &Connection) -> Result<ManagerDescriptor> {
    let saved: Option<String> = connection
        .query_row(
            "SELECT value FROM meta WHERE key='manager_descriptor'",
            [],
            |row| row.get(0),
        )
        .optional()?;
    let descriptor = saved
        .map(|value| serde_json::from_str(&value))
        .transpose()?
        .unwrap_or_default();
    ManagerDescriptor::validate(&descriptor)?;
    Ok(descriptor)
}

fn read_catalog(connection: &Connection) -> Result<Vec<Cluster>> {
    let mut statement = connection
        .prepare("SELECT id,name,description FROM clusters WHERE active=1 ORDER BY id")?;
    Ok(statement
        .query_map([], |row| {
            Ok(Cluster {
                id: row.get(0)?,
                name: row.get(1)?,
                description: row.get(2)?,
            })
        })?
        .collect::<rusqlite::Result<_>>()?)
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
        assert_eq!(events, 2);
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

    fn managed(policy: ManagerPolicy) -> Result<Store> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        let descriptor = match policy {
            ManagerPolicy::Original => ManagerDescriptor::default(),
            ManagerPolicy::Contextual => {
                ManagerDescriptor::from_context("observed fixture evidence")?
            }
        };
        db.bind_manager(&descriptor)?;
        Ok(db)
    }

    fn origins(db: &Store) -> Result<Vec<(String, Option<i64>, bool)>> {
        Ok(db.connection.prepare("SELECT point_id,previous_cluster_id,previous_assignment_known FROM reassignment ORDER BY point_id")?
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .collect::<rusqlite::Result<_>>()?)
    }

    fn events(db: &Store, kind: &str) -> Result<Vec<Value>> {
        let payloads = db
            .connection
            .prepare("SELECT payload FROM events WHERE kind=? ORDER BY id")?
            .query_map([kind], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        payloads
            .into_iter()
            .map(|s| Ok(serde_json::from_str(&s)?))
            .collect()
    }

    fn state(db: &Store) -> Result<Vec<Vec<String>>> {
        [
            "SELECT quote(id)||quote(name)||quote(description)||quote(active) FROM clusters ORDER BY id",
            "SELECT quote(point_id)||quote(cluster_id) FROM assignments ORDER BY point_id",
            "SELECT quote(point_id)||quote(previous_cluster_id)||quote(previous_assignment_known) FROM reassignment ORDER BY point_id",
            "SELECT quote(key)||quote(value) FROM meta ORDER BY key",
            "SELECT quote(id)||quote(kind)||quote(payload)||quote(created_at) FROM events ORDER BY id",
        ].into_iter().map(|sql| {
            Ok(db.connection.prepare(sql)?.query_map([], |r| r.get(0))?.collect::<rusqlite::Result<Vec<String>>>()?)
        }).collect()
    }

    #[test]
    fn competing_create_reconsiders_untouched_named_members_only_contextually() -> Result<()> {
        for policy in [ManagerPolicy::Original, ManagerPolicy::Contextual] {
            let mut db = managed(policy)?;
            db.apply_with_policy(
                &Plan {
                    operations: vec![create("A")],
                },
                3,
                policy,
            )?;
            db.insert(&item("named"), Some(1))?;
            db.insert(&item("other"), None)?;
            db.apply_with_policy(
                &Plan {
                    operations: vec![create("competitor")],
                },
                3,
                policy,
            )?;
            let pending: Vec<_> = db.pending()?.into_iter().map(|i| i.id).collect();
            assert_eq!(
                pending,
                if policy == ManagerPolicy::Contextual {
                    vec!["named", "other"]
                } else {
                    vec!["other"]
                }
            );
            let event = events(&db, "catalog_update")?.pop().unwrap();
            assert_eq!(event["policy"], serde_json::to_value(policy)?);
            assert_eq!(event["catalog_changed"], true);
            assert_eq!(event["catalog_change_count"], 1);
            assert_eq!(
                event["global_reconsideration"],
                policy == ManagerPolicy::Contextual
            );
            assert_eq!(event["newly_queued"], pending.len());
            assert_eq!(event["pending_count"], pending.len());
            assert_ne!(event["before_sha256"], event["after_sha256"]);
        }
        Ok(())
    }

    #[test]
    fn contextual_description_change_queues_all_once_and_exact_noops_add_nothing() -> Result<()> {
        let policy = ManagerPolicy::Contextual;
        let mut db = managed(policy)?;
        db.apply_with_policy(
            &Plan {
                operations: vec![create("A"), create("B")],
            },
            3,
            policy,
        )?;
        for (id, cluster) in [("z", Some(2)), ("a", Some(1)), ("other", None)] {
            db.insert(&item(id), cluster)?;
        }
        let rename = Plan {
            operations: vec![Operation::Rename {
                id: 1,
                name: "A".into(),
                description: "changed boundary".into(),
            }],
        };
        db.apply_with_policy(&rename, 3, policy)?;
        assert_eq!(
            db.pending()?.into_iter().map(|i| i.id).collect::<Vec<_>>(),
            vec!["z", "a", "other"]
        );
        let captured = origins(&db)?;
        assert_eq!(
            captured,
            vec![
                ("a".into(), Some(1), true),
                ("other".into(), None, true),
                ("z".into(), Some(2), true)
            ]
        );
        db.apply_with_policy(&rename, 3, policy)?;
        db.apply_with_policy(&Plan { operations: vec![] }, 3, policy)?;
        assert_eq!(origins(&db)?, captured);
        for event in events(&db, "catalog_update")?.iter().rev().take(2) {
            assert_eq!(event["catalog_changed"], false);
            assert_eq!(event["catalog_change_count"], 0);
            assert_eq!(event["global_reconsideration"], false);
            assert_eq!(event["newly_queued"], 0);
            assert_eq!(event["pending_count"], 3);
            assert_eq!(event["before_sha256"], event["after_sha256"]);
        }
        for (point, target) in db.assignments()? {
            db.reassign(&point, target)?;
        }
        assert!(
            events(&db, "reassign")?
                .iter()
                .all(|e| e["changed"] == false)
        );
        db.apply_with_policy(&rename, 3, policy)?;
        assert!(db.pending()?.is_empty());
        Ok(())
    }

    #[test]
    fn original_noop_rename_keeps_targeted_and_other_queue_semantics() -> Result<()> {
        let mut db = managed(ManagerPolicy::Original)?;
        db.apply(
            &Plan {
                operations: vec![create("A"), create("B")],
            },
            2,
        )?;
        for (id, cluster) in [("a", Some(1)), ("b", Some(2)), ("other", None)] {
            db.insert(&item(id), cluster)?;
        }
        db.apply(
            &Plan {
                operations: vec![Operation::Rename {
                    id: 1,
                    name: "A".into(),
                    description: "A".into(),
                }],
            },
            2,
        )?;
        assert_eq!(
            db.pending()?.into_iter().map(|i| i.id).collect::<Vec<_>>(),
            vec!["a", "other"]
        );
        assert_eq!(
            origins(&db)?,
            vec![("a".into(), Some(1), true), ("other".into(), None, true)]
        );
        for point in db.pending()? {
            db.reassign(&point, None)?;
        }
        db.apply(&Plan { operations: vec![] }, 2)?;
        assert!(db.pending()?.is_empty());
        Ok(())
    }

    #[test]
    fn manager_binding_is_exact_nonoverwriting_and_enforced_by_both_apply_paths() -> Result<()> {
        let mut db = Store::open(Path::new(":memory:"), &serde_json::json!({}))?;
        assert_eq!(db.manager_descriptor()?, ManagerDescriptor::default());
        assert!(db.get_meta("manager_descriptor")?.is_none());
        let descriptor = ManagerDescriptor::from_context("frozen context")?;
        db.bind_manager(&descriptor)?;
        db.bind_manager(&descriptor)?;
        let before = state(&db)?;
        assert!(db.bind_manager(&ManagerDescriptor::default()).is_err());
        assert!(
            db.bind_manager(&ManagerDescriptor::from_context("different context")?)
                .is_err()
        );
        let mut revision = descriptor.clone();
        revision.prompt_revision = "future".into();
        assert!(db.bind_manager(&revision).is_err());
        assert!(
            db.apply(
                &Plan {
                    operations: vec![create("wrong")]
                },
                1
            )
            .is_err()
        );
        assert!(
            db.apply_with_policy(
                &Plan {
                    operations: vec![create("wrong")]
                },
                1,
                ManagerPolicy::Original
            )
            .is_err()
        );
        assert_eq!(db.manager_descriptor()?, descriptor);
        assert_eq!(state(&db)?, before);
        db.apply_with_policy(
            &Plan {
                operations: vec![create("right")],
            },
            1,
            ManagerPolicy::Contextual,
        )?;
        Ok(())
    }

    #[test]
    fn contextual_binding_requires_genuinely_empty_history_but_original_adopts_legacy() -> Result<()>
    {
        for sql in [
            "INSERT INTO points VALUES('p',0,'{}')",
            "INSERT INTO assignments VALUES('p',NULL)",
            "INSERT INTO clusters(name,description,active) VALUES('old','old',0)",
            "INSERT INTO calls(payload) VALUES('{}')",
            "INSERT INTO events(kind,payload) VALUES('old','{}')",
            "INSERT INTO reassignment(point_id) VALUES('p')",
        ] {
            let mut db = Store::open(
                Path::new(":memory:"),
                &serde_json::json!({"config_only":"allowed"}),
            )?;
            db.connection.execute_batch("PRAGMA foreign_keys=OFF")?;
            db.connection.execute_batch(sql)?;
            db.connection.execute_batch("PRAGMA foreign_keys=ON")?;
            assert!(
                db.bind_manager(&ManagerDescriptor::from_context("fixture")?)
                    .is_err(),
                "history must reject adoption: {sql}"
            );
            assert!(db.get_meta("manager_descriptor")?.is_none());
            db.bind_manager(&ManagerDescriptor::default())?;
            assert_eq!(db.manager_descriptor()?, ManagerDescriptor::default());
        }
        Ok(())
    }

    #[test]
    fn merge_split_retire_and_duplicate_queue_preserve_earliest_real_origins() -> Result<()> {
        for policy in [ManagerPolicy::Original, ManagerPolicy::Contextual] {
            let mut db = managed(policy)?;
            db.apply_with_policy(
                &Plan {
                    operations: vec![create("A"), create("B")],
                },
                5,
                policy,
            )?;
            db.insert(&item("a"), Some(1))?;
            db.insert(&item("b"), Some(2))?;
            db.insert(&item("other"), None)?;
            db.apply_with_policy(
                &Plan {
                    operations: vec![Operation::Merge {
                        ids: vec![1, 2],
                        name: "AB".into(),
                        description: "merged".into(),
                    }],
                },
                5,
                policy,
            )?;
            let captured = vec![
                ("a".into(), Some(1), true),
                ("b".into(), Some(2), true),
                ("other".into(), None, true),
            ];
            assert_eq!(origins(&db)?, captured);
            assert!(db.assignments()?.iter().all(|(_, c)| c.is_none()));
            db.apply_with_policy(
                &Plan {
                    operations: vec![create("untouched")],
                },
                5,
                policy,
            )?;
            assert_eq!(origins(&db)?, captured);
            db.reassign(&item("a"), Some(3))?;
            db.reassign(&item("b"), Some(3))?;
            db.reassign(&item("other"), None)?;
            let evaluations = events(&db, "reassign")?;
            assert_eq!(evaluations[0]["previous_cluster_id"], 1);
            assert_eq!(evaluations[0]["previous_assignment_known"], true);
            assert!(evaluations[0]["interim_cluster_id"].is_null());
            assert_eq!(evaluations[0]["changed"], true);
            assert_eq!(evaluations[2]["changed"], false);
            db.apply_with_policy(
                &Plan {
                    operations: vec![Operation::Split {
                        id: 3,
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
                5,
                policy,
            )?;
            assert!(
                origins(&db)?
                    .iter()
                    .filter(|(id, _, _)| id != "other")
                    .all(|(_, previous, known)| *previous == Some(3) && *known)
            );
            for point in db.pending()? {
                db.reassign(&point, Some(5))?;
            }
            db.apply_with_policy(
                &Plan {
                    operations: vec![Operation::Retire { id: 5 }],
                },
                5,
                policy,
            )?;
            assert!(
                origins(&db)?
                    .iter()
                    .all(|(_, previous, known)| *previous == Some(5) && *known)
            );
        }
        Ok(())
    }

    #[test]
    fn migration_is_idempotent_and_legacy_pending_origin_remains_unknown() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("legacy.sqlite");
        {
            let connection = Connection::open(&path)?;
            connection.execute_batch("CREATE TABLE clusters(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1); CREATE TABLE points(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL); CREATE TABLE assignments(point_id TEXT PRIMARY KEY REFERENCES points(id),cluster_id INTEGER REFERENCES clusters(id)); CREATE TABLE reassignment(point_id TEXT PRIMARY KEY REFERENCES points(id));")?;
            connection.execute(
                "INSERT INTO points VALUES('old',0,?)",
                [serde_json::to_string(&item("old"))?],
            )?;
            connection.execute("INSERT INTO assignments VALUES('old',NULL)", [])?;
            connection.execute("INSERT INTO reassignment(point_id) VALUES('old')", [])?;
        }
        for _ in 0..2 {
            let db = Store::open(&path, &serde_json::json!({}))?;
            assert_eq!(origins(&db)?, vec![("old".into(), None, false)]);
            assert_eq!(db.manager_descriptor()?, ManagerDescriptor::default());
            let columns: usize = db.connection.query_row(
                "SELECT COUNT(*) FROM pragma_table_info('reassignment')",
                [],
                |r| r.get(0),
            )?;
            assert_eq!(columns, 3);
        }
        let mut db = Store::open(&path, &serde_json::json!({}))?;
        db.bind_manager(&ManagerDescriptor::default())?;
        db.apply(
            &Plan {
                operations: vec![create("A")],
            },
            1,
        )?;
        assert_eq!(origins(&db)?, vec![("old".into(), None, false)]);
        db.reassign(&item("old"), Some(1))?;
        let event = events(&db, "reassign")?.pop().unwrap();
        assert_eq!(event["previous_assignment_known"], false);
        assert!(event["previous_cluster_id"].is_null());
        assert!(event["changed"].is_null());
        assert!(db.reassign(&item("old"), Some(1)).is_err());
        assert_eq!(events(&db, "reassign")?.len(), 1);
        Ok(())
    }

    #[test]
    fn reassign_requires_real_pending_and_existing_assignment_without_manufacturing_events()
    -> Result<()> {
        let mut db = managed(ManagerPolicy::Original)?;
        db.insert(&item("a"), None)?;
        assert!(db.reassign(&item("a"), None).is_err());
        assert!(db.reassign(&item("missing"), None).is_err());
        db.connection.execute("INSERT INTO reassignment(point_id,previous_cluster_id,previous_assignment_known) VALUES('a',NULL,1)",[])?;
        db.connection
            .execute("DELETE FROM assignments WHERE point_id='a'", [])?;
        assert!(db.reassign(&item("a"), None).is_err());
        assert_eq!(origins(&db)?, vec![("a".into(), None, true)]);
        assert!(events(&db, "reassign")?.is_empty());
        Ok(())
    }

    #[test]
    fn invalid_later_plan_and_cap_roll_back_origins_catalog_metadata_and_both_events() -> Result<()>
    {
        for policy in [ManagerPolicy::Original, ManagerPolicy::Contextual] {
            let mut db = managed(policy)?;
            db.apply_with_policy(
                &Plan {
                    operations: vec![create("A"), create("B")],
                },
                3,
                policy,
            )?;
            db.insert(&item("a"), Some(1))?;
            db.insert(&item("other"), None)?;
            db.apply_with_policy(
                &Plan {
                    operations: vec![Operation::Rename {
                        id: 1,
                        name: "A".into(),
                        description: "pending".into(),
                    }],
                },
                3,
                policy,
            )?;
            let before = state(&db)?;
            db.record_call(&CallRecord {
                phase: "plan".into(),
                model: "mock".into(),
                request: serde_json::json!({}),
                response: serde_json::json!({}),
                elapsed_ms: 0,
                usage: Usage::default(),
            })?;
            for (operations, cap) in [
                (
                    vec![
                        create("valid first"),
                        Operation::Create {
                            name: "".into(),
                            description: "invalid".into(),
                        },
                    ],
                    4,
                ),
                (
                    vec![Operation::Retire { id: 1 }, Operation::Retire { id: 999 }],
                    3,
                ),
                (
                    vec![
                        Operation::Rename {
                            id: 1,
                            name: "x".into(),
                            description: "x".into(),
                        },
                        Operation::Retire { id: 1 },
                    ],
                    3,
                ),
                (vec![create("valid first"), create("over cap")], 3),
            ] {
                assert!(
                    db.apply_with_policy(&Plan { operations }, cap, policy)
                        .is_err()
                );
                assert_eq!(state(&db)?, before);
            }
            let calls: usize = db
                .connection
                .query_row("SELECT COUNT(*) FROM calls", [], |r| r.get(0))?;
            assert_eq!(calls, 1);
        }
        Ok(())
    }
}
