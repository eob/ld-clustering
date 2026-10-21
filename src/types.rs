use anyhow::{Result, ensure};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const MAX_MANAGER_CONTEXT_BYTES: usize = 32 * 1024;
pub const CONTEXTUAL_MANAGER_REVISION: &str = "contextual-v1";

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, clap::ValueEnum, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ManagerPolicy {
    #[default]
    Original,
    Contextual,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ManagerDescriptor {
    pub policy: ManagerPolicy,
    pub context_sha256: Option<String>,
    pub prompt_revision: String,
}

impl Default for ManagerDescriptor {
    fn default() -> Self {
        Self {
            policy: ManagerPolicy::Original,
            context_sha256: None,
            prompt_revision: "original-v1".into(),
        }
    }
}

impl ManagerDescriptor {
    pub fn from_context(context: &str) -> Result<Self> {
        use sha2::{Digest, Sha256};
        ensure!(
            !context.trim().is_empty() && context.len() <= MAX_MANAGER_CONTEXT_BYTES,
            "manager context must contain 1 to {MAX_MANAGER_CONTEXT_BYTES} UTF-8 bytes"
        );
        Ok(Self {
            policy: ManagerPolicy::Contextual,
            context_sha256: Some(format!("{:x}", Sha256::digest(context.as_bytes()))),
            prompt_revision: CONTEXTUAL_MANAGER_REVISION.into(),
        })
    }

    pub fn validate(&self) -> Result<()> {
        match self.policy {
            ManagerPolicy::Original => ensure!(
                self.context_sha256.is_none() && self.prompt_revision == "original-v1",
                "original manager identity must use its original prompt without context"
            ),
            ManagerPolicy::Contextual => {
                ensure!(
                    self.prompt_revision == CONTEXTUAL_MANAGER_REVISION,
                    "unsupported contextual manager prompt revision"
                );
                ensure!(
                    self.context_sha256.as_ref().is_some_and(|hash| {
                        hash.len() == 64
                            && hash
                                .bytes()
                                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                    }),
                    "contextual manager identity requires a lowercase SHA-256"
                );
            }
        }
        Ok(())
    }
}

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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Assignment {
    Cluster(i64),
    Other,
    Refused,
}

#[async_trait]
pub trait Model: Send + Sync {
    async fn assign(
        &self,
        task: &str,
        item: &Item,
        clusters: &[Cluster],
    ) -> Result<ModelReply<Assignment>>;
    async fn plan(
        &self,
        task: &str,
        clusters: &[Cluster],
        examples: &[Example],
        max_clusters: usize,
    ) -> Result<ModelReply<Plan>>;
}

#[cfg(test)]
mod manager_tests {
    use super::*;
    use sha2::{Digest, Sha256};

    #[test]
    fn context_identity_pins_raw_bytes_and_validates_policy_revision() -> Result<()> {
        ManagerDescriptor::default().validate()?;
        let plain = ManagerDescriptor::from_context("observed boundary evidence")?;
        assert_eq!(plain.policy, ManagerPolicy::Contextual);
        assert_eq!(plain.prompt_revision, CONTEXTUAL_MANAGER_REVISION);
        assert_eq!(
            plain.context_sha256,
            Some(format!(
                "{:x}",
                Sha256::digest(b"observed boundary evidence")
            ))
        );
        assert_ne!(
            plain,
            ManagerDescriptor::from_context("observed boundary evidence\n")?
        );
        assert!(ManagerDescriptor::from_context("  \n").is_err());
        assert!(
            ManagerDescriptor::from_context(&"x".repeat(MAX_MANAGER_CONTEXT_BYTES + 1)).is_err()
        );
        for invalid in [
            ManagerDescriptor {
                prompt_revision: "future-revision".into(),
                ..plain.clone()
            },
            ManagerDescriptor {
                context_sha256: None,
                ..plain.clone()
            },
            ManagerDescriptor {
                context_sha256: Some("A".repeat(64)),
                ..plain.clone()
            },
            ManagerDescriptor {
                policy: ManagerPolicy::Original,
                ..plain
            },
        ] {
            assert!(invalid.validate().is_err());
        }
        Ok(())
    }
}
