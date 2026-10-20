use crate::types::Item;
use anyhow::{Context, Result, ensure};
use flate2::read::GzDecoder;
use image::GrayImage;
use rand::{SeedableRng, seq::SliceRandom};
use rand_chacha::ChaCha8Rng;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    fs::{self, File},
    io::{BufWriter, Read, Write},
    path::Path,
    time::Duration,
};

#[derive(Serialize)]
struct Source {
    name: &'static str,
    url: &'static str,
    sha256: &'static str,
    license: &'static str,
}

const SOURCES: [Source; 6] = [
    Source {
        name: "clinc-data",
        url: "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/data/data_full.json",
        sha256: "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0",
        license: "CC-BY-3.0",
    },
    Source {
        name: "clinc-domains",
        url: "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/data/domains.json",
        sha256: "b947b579d3b8e74b06f93b01083d8efaff2888b43a3e362533bd88a6e1211b3a",
        license: "CC-BY-3.0",
    },
    Source {
        name: "clinc-license",
        url: "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/LICENSE",
        sha256: "e6bc9e9c474700b708f568bac9e5a8a9bcb2b1dad53442f5ba449fcb848b8e76",
        license: "CC-BY-3.0",
    },
    Source {
        name: "fashion-images",
        url: "https://raw.githubusercontent.com/zalandoresearch/fashion-mnist/b2617bb6d3ffa2e429640350f613e3291e10b141/data/fashion/t10k-images-idx3-ubyte.gz",
        sha256: "346e55b948d973a97e58d2351dde16a484bd415d4595297633bb08f03db6a073",
        license: "MIT",
    },
    Source {
        name: "fashion-labels",
        url: "https://raw.githubusercontent.com/zalandoresearch/fashion-mnist/b2617bb6d3ffa2e429640350f613e3291e10b141/data/fashion/t10k-labels-idx1-ubyte.gz",
        sha256: "67da17c76eaffca5446c3361aaab5c3cd6d1c2608764d35dfb1850b086bf8dd5",
        license: "MIT",
    },
    Source {
        name: "fashion-license",
        url: "https://raw.githubusercontent.com/zalandoresearch/fashion-mnist/b2617bb6d3ffa2e429640350f613e3291e10b141/LICENSE",
        sha256: "13ef4788476d292858fa60eb9a5f74aeca5c65770bc885ccaa05823a17ef7be1",
        license: "MIT",
    },
];

/// Write the two benchmark streams and provenance into a dataset directory.
pub async fn prepare(output: &Path, seed: u64) -> Result<()> {
    let client = reqwest::Client::builder()
        .user_agent("ld-clustering/0.1 dataset preparation")
        .timeout(Duration::from_secs(90))
        .build()?;
    let (corpus, domains, text_license, images, labels, image_license) = tokio::try_join!(
        download(&client, &SOURCES[0]),
        download(&client, &SOURCES[1]),
        download(&client, &SOURCES[2]),
        download(&client, &SOURCES[3]),
        download(&client, &SOURCES[4]),
        download(&client, &SOURCES[5]),
    )?;
    let text = select_text(&corpus, &domains, seed)?;
    let image_samples = select_images(&images, &labels, seed)?;
    fs::create_dir_all(output.join("images"))?;
    fs::create_dir_all(output.join("licenses"))?;
    let output = fs::canonicalize(output)?;
    let mut image_items = Vec::new();
    let mut png_hashes = BTreeMap::new();
    for (mut item, pixels) in image_samples {
        let path = output.join("images").join(format!("{}.png", item.id));
        pixels.save(&path)?;
        png_hashes.insert(item.id.clone(), hash(&fs::read(&path)?));
        item.image = Some(path.to_string_lossy().into_owned());
        image_items.push(item);
    }
    write_jsonl(&output.join("text.jsonl"), &text)?;
    write_jsonl(&output.join("images.jsonl"), &image_items)?;
    fs::write(output.join("licenses/clinc-CC-BY-3.0.txt"), text_license)?;
    fs::write(output.join("licenses/fashion-MIT.txt"), image_license)?;
    fs::write(
        output.join("licenses/ATTRIBUTION.txt"),
        "CLINC150: Stefan Larson, Anish Mahendran, Joseph J. Peper, Christopher Clarke, Andrew Lee, Parker Hill, Jonathan K. Kummerfeld, Kevin Leach, Michael A. Laurenzano, Lingjia Tang and Jason Mars. An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction. EMNLP-IJCNLP 2019. https://github.com/clinc/oos-eval . CC BY 3.0: https://creativecommons.org/licenses/by/3.0/ . Changes: deterministic subset and JSONL conversion, intent labels mapped to broad domains for evaluation.\n\nFashion-MNIST: Han Xiao, Kashif Rasul and Roland Vollgraf; Copyright 2017 Zalando SE. Fashion-MNIST: a Novel Image Dataset for Benchmarking Machine Learning Algorithms. https://github.com/zalandoresearch/fashion-mnist . MIT license retained in fashion-MIT.txt. Changes: deterministic test subset and lossless IDX-to-PNG conversion.\n",
    )?;
    let text_ids: Vec<_> = text.iter().map(|item| &item.id).collect();
    let image_ids: Vec<_> = image_items.iter().map(|item| &item.id).collect();
    let manifest = json!({
        "schema_version": 1,
        "seed": seed,
        "sources": SOURCES,
        "selection": "ChaCha8 seeded separately for each modality; lexical domain/class order, shuffle each group, take quota, then shuffle complete stream",
        "text": {
            "file": "text.jsonl", "count": text.len(),
            "selection": "90 test requests per broad CLINC domain plus 100 oos_test requests",
            "ordered_ids": text_ids,
            "order_sha256": hash(&serde_json::to_vec(&text_ids)?),
            "payload_sha256": hash(&serde_json::to_vec(&text)?),
        },
        "images": {
            "file": "images.jsonl", "count": image_items.len(),
            "selection": "10 Fashion-MNIST test images per class",
            "transform": "28x28 grayscale; lossless PNG conversion without resizing",
            "ordered_ids": image_ids,
            "order_sha256": hash(&serde_json::to_vec(&image_ids)?),
            "png_sha256_by_id": png_hashes,
        },
        "labels": "Evaluation only; never model evidence. CLINC oos is not a coherent semantic class.",
        "licenses": ["licenses/clinc-CC-BY-3.0.txt", "licenses/fashion-MIT.txt", "licenses/ATTRIBUTION.txt"],
    });
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    Ok(())
}

async fn download(client: &reqwest::Client, source: &Source) -> Result<Vec<u8>> {
    let bytes = client
        .get(source.url)
        .send()
        .await?
        .error_for_status()?
        .bytes()
        .await?
        .to_vec();
    verify_checksum(&bytes, source.sha256).with_context(|| source.name)?;
    Ok(bytes)
}

fn verify_checksum(bytes: &[u8], expected: &str) -> Result<()> {
    ensure!(
        hash(bytes) == expected,
        "source checksum differs from pinned SHA-256"
    );
    Ok(())
}

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn stable_id(source: &str, index: usize) -> String {
    hash(format!("{source}/{index}").as_bytes())[..20].to_owned()
}

#[derive(Deserialize)]
struct TextCorpus {
    test: Vec<(String, String)>,
    oos_test: Vec<(String, String)>,
}

fn select_text(corpus: &[u8], domains: &[u8], seed: u64) -> Result<Vec<Item>> {
    let corpus: TextCorpus = serde_json::from_slice(corpus)?;
    let domains: BTreeMap<String, Vec<String>> = serde_json::from_slice(domains)?;
    ensure!(domains.len() == 10, "expected ten CLINC domains");
    let mut intent_domains = HashMap::new();
    let mut grouped: BTreeMap<&str, Vec<Item>> = BTreeMap::new();
    for (domain, intents) in &domains {
        grouped.insert(domain, Vec::new());
        for intent in intents {
            ensure!(
                intent_domains
                    .insert(intent.as_str(), domain.as_str())
                    .is_none(),
                "intent appears in multiple domains"
            );
        }
    }
    for (index, (text, intent)) in corpus.test.into_iter().enumerate() {
        let domain = *intent_domains
            .get(intent.as_str())
            .context("unmapped CLINC intent")?;
        grouped.get_mut(domain).unwrap().push(Item {
            id: stable_id("clinc/test", index),
            text,
            image: None,
            label: Some(domain.to_owned()),
        });
    }
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut selected = Vec::new();
    for group in grouped.values_mut() {
        ensure!(group.len() >= 90, "insufficient test requests for a domain");
        group.shuffle(&mut rng);
        selected.extend(group.drain(..90));
    }
    let mut other: Vec<Item> = corpus
        .oos_test
        .into_iter()
        .enumerate()
        .map(|(index, (text, _))| Item {
            id: stable_id("clinc/oos_test", index),
            text,
            image: None,
            label: Some("oos".to_owned()),
        })
        .collect();
    ensure!(other.len() >= 100, "insufficient out-of-scope requests");
    other.shuffle(&mut rng);
    selected.extend(other.drain(..100));
    selected.shuffle(&mut rng);
    Ok(selected)
}

fn select_images(images: &[u8], labels: &[u8], seed: u64) -> Result<Vec<(Item, GrayImage)>> {
    let mut image_bytes = Vec::new();
    let mut label_bytes = Vec::new();
    GzDecoder::new(images).read_to_end(&mut image_bytes)?;
    GzDecoder::new(labels).read_to_end(&mut label_bytes)?;
    ensure!(
        image_bytes.len() >= 16 && label_bytes.len() >= 8,
        "truncated IDX header"
    );
    let number = |bytes: &[u8], offset| {
        u32::from_be_bytes(bytes[offset..offset + 4].try_into().unwrap()) as usize
    };
    ensure!(
        number(&image_bytes, 0) == 2051 && number(&label_bytes, 0) == 2049,
        "invalid IDX magic"
    );
    let count = number(&image_bytes, 4);
    ensure!(
        number(&label_bytes, 4) == count,
        "IDX image/label counts differ"
    );
    ensure!(
        number(&image_bytes, 8) == 28 && number(&image_bytes, 12) == 28,
        "expected 28x28 images"
    );
    ensure!(
        count.checked_mul(784).and_then(|size| size.checked_add(16)) == Some(image_bytes.len())
            && count.checked_add(8) == Some(label_bytes.len()),
        "IDX payload length differs from header"
    );
    let mut grouped: BTreeMap<u8, Vec<usize>> = BTreeMap::new();
    for (index, &label) in label_bytes[8..].iter().enumerate() {
        ensure!(label < 10, "invalid Fashion-MNIST class");
        grouped.entry(label).or_default().push(index);
    }
    ensure!(grouped.len() == 10, "expected ten image classes");
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut selected = Vec::new();
    for (label, group) in &mut grouped {
        ensure!(group.len() >= 10, "insufficient images for a class");
        group.shuffle(&mut rng);
        for index in group.drain(..10) {
            let start = 16 + index * 784;
            let pixels = GrayImage::from_raw(28, 28, image_bytes[start..start + 784].to_vec())
                .context("invalid image dimensions")?;
            selected.push((
                Item {
                    id: stable_id("fashion/test", index),
                    text: "Clothing product image.".to_owned(),
                    image: None,
                    label: Some(label.to_string()),
                },
                pixels,
            ));
        }
    }
    selected.shuffle(&mut rng);
    Ok(selected)
}

fn write_jsonl(path: &Path, items: &[Item]) -> Result<()> {
    let mut file = BufWriter::new(File::create(path)?);
    for item in items {
        serde_json::to_writer(&mut file, item)?;
        file.write_all(b"\n")?;
    }
    file.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{Compression, write::GzEncoder};
    use serde_json::json;
    use std::collections::{BTreeMap, HashSet};
    use std::io::Write;

    fn gzip(bytes: &[u8]) -> Result<Vec<u8>> {
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(bytes)?;
        Ok(encoder.finish()?)
    }

    #[test]
    fn image_selection_preserves_pixels_and_balances_classes() -> Result<()> {
        let mut image_bytes = Vec::new();
        for number in [2051_u32, 120, 28, 28] {
            image_bytes.extend_from_slice(&number.to_be_bytes());
        }
        let mut label_bytes = Vec::new();
        for number in [2049_u32, 120] {
            label_bytes.extend_from_slice(&number.to_be_bytes());
        }
        for index in 0..120_u8 {
            image_bytes.extend_from_slice(&[index; 784]);
            label_bytes.push(index / 12);
        }
        let images = gzip(&image_bytes)?;
        let labels = gzip(&label_bytes)?;
        let selected = select_images(&images, &labels, 42)?;
        assert_eq!(selected.len(), 100);
        assert_eq!(selected, select_images(&images, &labels, 42)?);
        assert_ne!(selected, select_images(&images, &labels, 43)?);
        let mut counts = BTreeMap::new();
        for (item, image) in selected {
            let label: u8 = item.label.as_deref().unwrap().parse()?;
            *counts.entry(label).or_insert(0) += 1;
            assert_eq!(image.dimensions(), (28, 28));
            assert!(image.pixels().all(|pixel| pixel.0[0] / 12 == label));
            assert_eq!(item.text, "Clothing product image.");
        }
        assert_eq!(counts.len(), 10);
        assert!(counts.values().all(|&count| count == 10));
        let truncated = gzip(&image_bytes[..image_bytes.len() - 1])?;
        assert!(select_images(&truncated, &labels, 42).is_err());
        label_bytes[3] = 0;
        assert!(select_images(&images, &gzip(&label_bytes)?, 42).is_err());
        Ok(())
    }

    #[test]
    fn hashes_reject_different_source_bytes() -> Result<()> {
        let expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        verify_checksum(b"abc", expected)?;
        assert!(verify_checksum(b"abd", expected).is_err());
        Ok(())
    }

    #[test]
    fn text_selection_has_exact_counts_hidden_labels_and_reproducible_order() -> Result<()> {
        let domains: BTreeMap<String, Vec<String>> = (0..10)
            .map(|domain| {
                (
                    format!("private-domain-{domain}"),
                    vec![format!("private-intent-{domain}")],
                )
            })
            .collect();
        let test: Vec<(String, String)> = (0..1000)
            .map(|index| {
                (
                    format!("request number {index}"),
                    format!("private-intent-{}", index / 100),
                )
            })
            .collect();
        let oos_test: Vec<(String, String)> = (1000..1120)
            .map(|index| (format!("request number {index}"), "oos".into()))
            .collect();
        let corpus = serde_json::to_vec(&json!({"test": test, "oos_test": oos_test}))?;
        let mapping = serde_json::to_vec(&domains)?;
        let items = select_text(&corpus, &mapping, 42)?;
        assert_eq!(items.len(), 1000);
        assert_eq!(items, select_text(&corpus, &mapping, 42)?);
        assert_ne!(items, select_text(&corpus, &mapping, 43)?);
        assert_eq!(
            items
                .iter()
                .map(|item| &item.id)
                .collect::<HashSet<_>>()
                .len(),
            1000
        );
        let mut counts = BTreeMap::new();
        for item in &items {
            *counts.entry(item.label.as_deref().unwrap()).or_insert(0) += 1;
            assert!(item.text.starts_with("request number "));
            assert!(!item.text.contains("private"));
            assert!(!item.id.contains("oos"));
            assert!(item.image.is_none());
        }
        assert_eq!(counts.remove("oos"), Some(100));
        assert_eq!(counts.len(), 10);
        assert!(counts.values().all(|&count| count == 90));
        Ok(())
    }
}
