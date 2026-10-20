use anyhow::Result;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Item {
    pub id: String,
    pub text: String,
    /// Local PNG path or public/inline image URL. Never a category label.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub image: Option<String>,
    /// Evaluation-only: providers must never place this in model inputs.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Cluster {
    pub id: i64,
    pub name: String,
    pub description: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Definition {
    pub name: String,
    pub description: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Operation {
    Create {
        name: String,
        description: String,
    },
    Rename {
        id: i64,
        name: String,
        description: String,
    },
    Merge {
        ids: Vec<i64>,
        name: String,
        description: String,
    },
    Split {
        id: i64,
        children: Vec<Definition>,
    },
    Retire {
        id: i64,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Plan {
    pub operations: Vec<Operation>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Example {
    pub item: Item,
    pub cluster_id: Option<i64>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Usage {
    pub input_tokens: u64,
    pub cached_tokens: u64,
    pub cache_write_tokens: u64,
    pub output_tokens: u64,
    pub cost_usd: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CallRecord {
    pub phase: String,
    pub model: String,
    pub request: Value,
    pub response: Value,
    pub elapsed_ms: u64,
    pub usage: Usage,
}

pub struct ModelReply<T> {
    pub value: T,
    pub call: CallRecord,
}

#[async_trait]
pub trait Model: Send + Sync {
    async fn assign(
        &self,
        task: &str,
        item: &Item,
        clusters: &[Cluster],
    ) -> Result<ModelReply<Option<i64>>>;
    async fn plan(
        &self,
        task: &str,
        clusters: &[Cluster],
        examples: &[Example],
        max_clusters: usize,
    ) -> Result<ModelReply<Plan>>;
}
