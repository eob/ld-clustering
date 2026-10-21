use anyhow::{Context, Result, ensure};
use clap::Parser;
use ld_clustering::types::Item;
use rand::{SeedableRng, seq::SliceRandom};
use rand_chacha::ChaCha8Rng;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
};

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn normalize(text: &str) -> String {
    text.chars()
        .filter(|ch| ch.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

#[derive(Deserialize)]
struct Corpus {
    test: Vec<(String, String)>,
    oos_test: Vec<(String, String)>,
}

fn select_text(
    corpus: &[u8],
    domains: &[u8],
    excluded: &[Item],
    seed: u64,
) -> Result<[Vec<Item>; 2]> {
    let corpus: Corpus = serde_json::from_slice(corpus)?;
    let domains: BTreeMap<String, Vec<String>> = serde_json::from_slice(domains)?;
    ensure!(domains.len() == 10, "expected ten pinned text domains");
    let mut mapping = HashMap::new();
    let mut groups = BTreeMap::<String, Vec<Item>>::new();
    for (domain, intents) in domains {
        for intent in intents {
            ensure!(
                mapping.insert(intent, domain.clone()).is_none(),
                "duplicate domain mapping"
            );
        }
        groups.insert(domain, vec![]);
    }
    let mut seen: HashSet<_> = excluded.iter().map(|item| normalize(&item.text)).collect();
    for (index, (text, intent)) in corpus.test.into_iter().enumerate() {
        let domain = mapping.get(&intent).context("unknown intent")?;
        let key = normalize(&text);
        ensure!(!key.is_empty(), "empty normalized input");
        if seen.insert(key) {
            groups.get_mut(domain).unwrap().push(Item {
                id: hash(format!("clinc/test/{index}").as_bytes())[..20].into(),
                text,
                image: None,
                label: Some(domain.clone()),
            });
        }
    }
    let mut other = vec![];
    for (index, (text, _)) in corpus.oos_test.into_iter().enumerate() {
        let key = normalize(&text);
        ensure!(!key.is_empty(), "empty normalized input");
        if seen.insert(key) {
            other.push(Item {
                id: hash(format!("clinc/oos_test/{index}").as_bytes())[..20].into(),
                text,
                image: None,
                label: Some("oos".into()),
            });
        }
    }
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut selected = [vec![], vec![]];
    for group in groups.values_mut() {
        ensure!(group.len() >= 108, "insufficient fresh text for a domain");
        group.shuffle(&mut rng);
        selected[0].extend_from_slice(&group[..18]);
        selected[1].extend_from_slice(&group[18..108]);
    }
    ensure!(other.len() >= 120, "insufficient fresh OOS text");
    other.shuffle(&mut rng);
    selected[0].extend_from_slice(&other[..20]);
    selected[1].extend_from_slice(&other[20..120]);
    for items in &mut selected {
        items.shuffle(&mut rng);
    }
    Ok(selected)
}

#[derive(Parser)]
struct Args {
    #[arg(long)]
    prior_root: PathBuf,
    #[arg(long)]
    previous: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long, default_value_t = 2043)]
    seed: u64,
    #[arg(long)]
    text_only: bool,
    #[arg(long)]
    photo_catalog: Option<PathBuf>,
}

fn write_exact(path: &Path, bytes: &[u8]) -> Result<()> {
    if path.exists() {
        ensure!(
            fs::read(path)? == bytes,
            "refusing to overwrite different frozen content: {}",
            path.display()
        );
    } else {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, bytes)?;
    }
    Ok(())
}
fn jsonl(items: &[Item]) -> Result<Vec<u8>> {
    let mut bytes = vec![];
    for item in items {
        serde_json::to_writer(&mut bytes, item)?;
        bytes.push(b'\n');
    }
    Ok(bytes)
}
fn pretty(value: &Value) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}
fn stream_evidence(file: &str, items: &[Item]) -> Result<Value> {
    let ids: Vec<_> = items.iter().map(|item| item.id.as_str()).collect();
    Ok(
        json!({"file":file,"count":items.len(),"ordered_ids":ids,"order_sha256":hash(&serde_json::to_vec(&ids)?),"payload_sha256":hash(&serde_json::to_vec(items)?),"jsonl_sha256":hash(&jsonl(items)?),"ordered_image_hashes":[],"ordered_image_content_sha256":hash(b"[]")}),
    )
}
fn read_items(path: &Path) -> Result<Vec<Item>> {
    fs::read_to_string(path)?
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).map_err(Into::into))
        .collect()
}
fn prepare_text(args: &Args) -> Result<Value> {
    ensure!(args.seed == 2043, "this follow-up is frozen for seed2043");
    ensure!(
        !args.output.join("manifest.json").exists(),
        "dataset is already frozen"
    );
    let prior_manifest = fs::read(args.prior_root.join("manifest.json"))?;
    ensure!(
        hash(&prior_manifest) == "c61ce5b4703e98ae79581c73e492aece53196777ac7510f121bbced59ed752f4",
        "prior dataset manifest changed"
    );
    let prior: Value = serde_json::from_slice(&prior_manifest)?;
    let previous = fs::read(&args.previous)?;
    ensure!(
        hash(&previous) == "934875f651f0ba9365084921f1a0aa440adf8c802e7650d4a7cadf607fb65352",
        "prior v2 text changed"
    );
    let mut excluded = read_items(&args.previous)?;
    for split in ["discovery", "heldout", "streaming"] {
        let rows = read_items(&args.prior_root.join(split).join("text.jsonl"))?;
        let evidence = &prior["partitions"][split]["text"];
        ensure!(
            rows.len() as u64 == evidence["count"].as_u64().context("prior count missing")?
                && hash(&serde_json::to_vec(&rows)?) == evidence["payload_sha256"],
            "prior split changed"
        );
        excluded.extend(rows);
    }
    let mut exclusion_keys: Vec<_> = excluded
        .iter()
        .map(|item| normalize(&item.text))
        .collect::<HashSet<_>>()
        .into_iter()
        .collect();
    exclusion_keys.sort();
    ensure!(
        exclusion_keys.len() == 3200,
        "expected all3200 prior unique texts"
    );
    let corpus = fs::read(args.prior_root.join("sources/clinc-data.json"))?;
    let domains = fs::read(args.prior_root.join("sources/clinc-domains.json"))?;
    ensure!(
        hash(&corpus) == "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0",
        "CLINC source changed"
    );
    ensure!(
        hash(&domains) == "b947b579d3b8e74b06f93b01083d8efaff2888b43a3e362533bd88a6e1211b3a",
        "CLINC domain source changed"
    );
    let parts = select_text(&corpus, &domains, &excluded, args.seed)?;
    let mut repeat = parts[1].clone();
    repeat.shuffle(&mut ChaCha8Rng::seed_from_u64(args.seed ^ 0x74657874));
    let repeat_ids: HashSet<_> = repeat[..100].iter().map(|item| item.id.clone()).collect();
    let repeat: Vec<_> = parts[1]
        .iter()
        .filter(|item| repeat_ids.contains(&item.id))
        .cloned()
        .collect();
    let mut partitions = BTreeMap::new();
    for (name, items) in [
        ("development", &parts[0]),
        ("confirmation", &parts[1]),
        ("repeat", &repeat),
    ] {
        let file = format!("{name}/text.jsonl");
        write_exact(&args.output.join(&file), &jsonl(items)?)?;
        partitions.insert(name, json!({"text":stream_evidence(&file,items)?}));
    }
    let value = json!({"schema_version":1,"experiment":"guidance-auto-research","seed":args.seed,"prior_dataset_manifest_sha256":hash(&prior_manifest),"previous_text_sha256":hash(&previous),"excluded_normalized_count":exclusion_keys.len(),"excluded_normalized_sha256":hash(&serde_json::to_vec(&exclusion_keys)?),"source_metadata":{"clinc_sha256":hash(&corpus),"domains_sha256":hash(&domains)},"selection":"Pinned CLINC test and oos_test only; exclude all prior normalized text and duplicates globally, lexical domains shuffled with ChaCha8 seed2043; development18/domain+20OOS, confirmation90/domain+100OOS; independently shuffle both partitions. Repeat100 confirmation items preselected with separate seed and retained in confirmation order.","partitions":partitions});
    write_exact(&args.output.join("text-selection.json"), &pretty(&value)?)?;
    Ok(value)
}

fn main() -> Result<()> {
    let args = Args::parse();
    let value = prepare_text(&args)?;
    if !args.text_only {
        let manifest = prepare_photos(&args, value)?;
        println!(
            "{}",
            json!({"status":"dataset_frozen","manifest_sha256":hash(&pretty(&manifest)?),"development_text":200,"confirmation_text":1000,"development_photos":40,"confirmation_photos":100})
        );
        return Ok(());
    }
    println!(
        "{}",
        json!({"status":"text_partitions_frozen","development":value["partitions"]["development"]["text"]["count"],"confirmation":value["partitions"]["confirmation"]["text"]["count"],"selection_sha256":hash(&pretty(&value)?)})
    );
    Ok(())
}

fn text_field<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .with_context(|| format!("missing {key}"))
}
fn dimension(value: &Value, key: &str) -> Result<u32> {
    Ok(value[key]
        .as_u64()
        .with_context(|| format!("missing {key}"))?
        .try_into()?)
}

fn selected_photo_bytes(photo: &Value, root: &Path) -> Result<Vec<u8>> {
    let bytes = fs::read(root.join(text_field(photo, "source_file")?))?;
    ensure!(
        hash(&bytes) == text_field(photo, "source_sha256")?
            && bytes.len() as u64
                == photo["source_bytes"]
                    .as_u64()
                    .context("source size missing")?,
        "selected JPEG bytes changed"
    );
    ensure!(
        photo["inspection"] == "natural_color_photograph",
        "photo lacks visual acceptance"
    );
    let (width, height) = (dimension(photo, "width")?, dimension(photo, "height")?);
    ensure!(
        width.max(height) <= 1024,
        "this frozen cohort requires unchanged at-most1024 JPEGs"
    );
    ld_clustering::agreement_data::validate_photo(
        &bytes,
        width,
        height,
        dimension(photo, "native_width")?,
        dimension(photo, "native_height")?,
    )?;
    Ok(bytes)
}

fn page_proof(photo: &Value, page: &[u8]) -> Result<()> {
    ensure!(
        hash(page) == text_field(photo, "license_page_sha256")?,
        "license page bytes changed"
    );
    let html = std::str::from_utf8(page)?;
    let license = "https://creativecommons.org/licenses/by/2.0/";
    ensure!(
        photo["metadata"]["License"] == license && photo["license_jsonld"]["license"] == license,
        "current and official licenses must be CC BY2"
    );
    let mut matches = 0;
    for rest in html.split("application/ld+json").skip(1) {
        let Some((_, body)) = rest.split_once('>') else {
            continue;
        };
        let Some((body, _)) = body.split_once("</script>") else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(body) else {
            continue;
        };
        if value == photo["license_jsonld"] {
            matches += 1;
        }
        if let Some(graph) = value["@graph"].as_array() {
            matches += graph
                .iter()
                .filter(|item| **item == photo["license_jsonld"])
                .count();
        }
    }
    ensure!(
        matches == 1,
        "saved licensing JSON-LD not uniquely bound to raw page"
    );
    let (_, sizes) = html
        .split_once("\"sizes\":")
        .context("publisher sizes missing")?;
    let sizes = serde_json::Deserializer::from_str(sizes)
        .into_iter::<Value>()
        .next()
        .context("publisher sizes missing")??;
    let original = &sizes["o"];
    ensure!(
        *original == photo["native_size_evidence"]["value"],
        "saved native-size evidence differs from page"
    );
    ensure!(
        original["width"].as_u64() == Some(dimension(photo, "native_width")? as u64)
            && original["height"].as_u64() == Some(dimension(photo, "native_height")? as u64),
        "native dimensions differ from publisher proof"
    );
    let original_url = text_field(&photo["metadata"], "OriginalURL")?;
    let flickr_id = original_url
        .rsplit('/')
        .next()
        .context("missing original photo ID")?
        .split('_')
        .next()
        .unwrap();
    ensure!(
        !flickr_id.is_empty() && flickr_id.chars().all(|c| c.is_ascii_digit()),
        "unexpected original photo URL"
    );
    ensure!(
        text_field(&photo["license_jsonld"], "contentUrl")?
            .rsplit('/')
            .next()
            .unwrap()
            .starts_with(&format!("{flickr_id}_")),
        "licensing proof belongs to a different photo"
    );
    Ok(())
}

fn previous_pixel_hashes(previous: &Value, root: &Path) -> Result<HashSet<String>> {
    let mut hashes = HashSet::new();
    for (id, photo) in previous["photos"]
        .as_object()
        .context("previous photos missing")?
    {
        for (folder, field) in [
            ("images", "supplied_sha256"),
            ("sources/photos", "source_sha256"),
        ] {
            let bytes = fs::read(root.join(folder).join(format!("{id}.jpg")))?;
            ensure!(
                hash(&bytes) == text_field(photo, field)?,
                "previous JPEG changed"
            );
            hashes.insert(hash(image::load_from_memory(&bytes)?.to_rgb8().as_raw()));
        }
    }
    Ok(hashes)
}

fn prepare_photos(args: &Args, mut manifest: Value) -> Result<Value> {
    let catalog_path = args
        .photo_catalog
        .as_deref()
        .context("--photo-catalog is required for finalization")?;
    let catalog_bytes = fs::read(catalog_path)?;
    ensure!(
        hash(&catalog_bytes) == "ea454cf9c6e75626044f425da938da84b20e9dcaa6ec38161ae1966faf0cb317",
        "selected photo catalog changed"
    );
    let catalog: Value = serde_json::from_slice(&catalog_bytes)?;
    ensure!(
        catalog["selection_seed"] == 2043,
        "photo selection seed differs"
    );
    let photos = catalog["photos"]
        .as_array()
        .context("photo catalog missing")?;
    ensure!(photos.len() == 140, "expected all140 selected photos");
    let root = catalog_path.parent().context("catalog directory missing")?;
    let previous: Value =
        serde_json::from_slice(&fs::read(args.prior_root.join("manifest.json"))?)?;
    let mut ids = HashSet::new();
    let mut byte_hashes = HashSet::new();
    let mut rgb_hashes = previous_pixel_hashes(&previous, &args.prior_root)?;
    ensure!(
        rgb_hashes.len() >= 260,
        "previous decoded-image exclusion is incomplete"
    );
    for photo in previous["photos"]
        .as_object()
        .context("previous photos missing")?
        .values()
    {
        ids.insert(text_field(photo, "image_id")?.to_owned());
        for field in ["source_sha256", "supplied_sha256", "original_sha256"] {
            if let Some(v) = photo[field].as_str() {
                byte_hashes.insert(v.to_owned());
            }
        }
    }
    let metadata_bytes = fs::read(root.join("validation-images-with-rotation.csv"))?;
    ensure!(
        hash(&metadata_bytes) == "ed93a0e121fe345effdfc7359b848dbc64a1ff6778c8c73563157cb500b33a17",
        "official OpenImages metadata changed"
    );
    let mut official = HashMap::new();
    for row in csv::Reader::from_reader(metadata_bytes.as_slice())
        .deserialize::<BTreeMap<String, String>>()
    {
        let row = row?;
        official.insert(row["ImageID"].clone(), serde_json::to_value(row)?);
    }
    let mut selected = vec![];
    let mut evidence = BTreeMap::new();
    let mut files = BTreeMap::<String, Vec<u8>>::new();
    for photo in photos {
        let image_id = text_field(photo, "image_id")?;
        ensure!(
            ids.insert(image_id.to_owned()),
            "photo repeats earlier selected image ID"
        );
        ensure!(
            official.get(image_id) == Some(&photo["metadata"]),
            "metadata differs from official pinned row"
        );
        let bytes = selected_photo_bytes(photo, root)?;
        ensure!(
            byte_hashes.insert(hash(&bytes)),
            "photo repeats earlier or selected source bytes"
        );
        let rgb = image::load_from_memory(&bytes)?.to_rgb8();
        let rgb_hash = hash(rgb.as_raw());
        ensure!(
            rgb_hashes.insert(rgb_hash.clone()),
            "photo repeats earlier or selected decoded pixels"
        );
        ensure!(
            !text_field(photo, "source_retrieved_at_utc")?.is_empty()
                && !text_field(photo, "license_observed_at_utc")?.is_empty(),
            "retrieval/observed date missing"
        );
        let page = fs::read(root.join(text_field(photo, "license_page_file")?))?;
        page_proof(photo, &page)?;
        let id = hash(format!("openimages/validation/{image_id}").as_bytes())[..20].to_owned();
        let page_path = format!("provenance/{image_id}.html");
        files.insert(page_path.clone(), page);
        let mut record = photo.clone();
        record["acquisition_decoded_rgb_sha256"] = photo["source_decoded_rgb_sha256"].clone();
        record["acquisition_rgb_decoder"] =
            json!("Pillow/libjpeg; retained separately from Rust decoder hashes");
        record["source_decoded_rgb_sha256"] = json!(rgb_hash);
        record["rgb_decoder"] = json!(
            "image0.25.10 RGB bytes, no EXIF transform; same decoder for new and prior inputs"
        );
        record["supplied_sha256"] = json!(hash(&bytes));
        record["supplied_bytes"] = json!(bytes.len());
        record["supplied_width"] = photo["width"].clone();
        record["supplied_height"] = photo["height"].clone();
        record["supplied_decoded_rgb_sha256"] = json!(rgb_hash);
        record["transform"] =
            json!("Exact source JPEG bytes; no resizing, cropping, reencoding or upscaling.");
        record["archived_license_page_file"] = json!(page_path);
        let image_path = format!("images/{id}.jpg");
        record["archived_source_file"] = json!(image_path);
        files.insert(image_path, bytes);
        if let Some(original_file) = photo["original_file"].as_str() {
            let bytes = fs::read(root.join(original_file))?;
            ensure!(
                hash(&bytes) == text_field(photo, "original_sha256")?,
                "known original bytes changed"
            );
            let original = image::load_from_memory(&bytes)?;
            let mut actual = [original.width(), original.height()];
            actual.sort();
            let mut claimed = [
                dimension(photo, "native_width")?,
                dimension(photo, "native_height")?,
            ];
            claimed.sort();
            ensure!(
                actual == claimed,
                "known original dimensions differ from publisher proof"
            );
            let path = format!("provenance/{image_id}-original.bin");
            record["archived_original_file"] = json!(path);
            files.insert(path, bytes);
        } else {
            ensure!(
                photo["original_sha256"].is_null(),
                "missing original bytes falsely claim known hash"
            );
            record["archived_original_file"] = Value::Null;
        }
        selected.push(Item {
            id: id.clone(),
            text: "Photograph.".into(),
            image: Some(format!("../images/{id}.jpg")),
            label: None,
        });
        evidence.insert(id, record);
    }
    selected.shuffle(&mut ChaCha8Rng::seed_from_u64(args.seed ^ 0x70686f746f));
    let mut repeat_indices: Vec<_> = (0..100).collect();
    repeat_indices.shuffle(&mut ChaCha8Rng::seed_from_u64(args.seed ^ 0x696d616765));
    repeat_indices.truncate(25);
    repeat_indices.sort();
    let repeat: Vec<_> = repeat_indices
        .iter()
        .map(|&i| selected[40 + i].clone())
        .collect();
    for (split, items) in [
        ("development", &selected[..40]),
        ("confirmation", &selected[40..]),
        ("repeat", repeat.as_slice()),
    ] {
        let file = format!("{split}/images.jsonl");
        files.insert(file.clone(), jsonl(items)?);
        let hashes: Vec<_> = items
            .iter()
            .map(|item| json!({"id":item.id,"sha256":evidence[&item.id]["supplied_sha256"]}))
            .collect();
        let mut value = stream_evidence(&file, items)?;
        value["ordered_image_hashes"] = json!(hashes);
        value["ordered_image_content_sha256"] = json!(hash(&serde_json::to_vec(&hashes)?));
        manifest["partitions"][split]["images"] = value;
    }
    for name in [
        "pool-plan.json",
        "acquisition.json",
        "curation.json",
        "previous-photo-exclusions.json",
        "validation-summary.json",
        "acquire-2043.py",
        "freeze-curation-2043.py",
    ] {
        let source = root.join(name);
        files.insert(format!("provenance/{name}"), fs::read(source)?);
    }
    files.insert(
        "licenses/openimages-selected-attribution.json".into(),
        catalog_bytes.clone(),
    );
    files.insert(
        "licenses/clinc-CC-BY-3.0.txt".into(),
        fs::read(args.prior_root.join("licenses/clinc-CC-BY-3.0.txt"))?,
    );
    files.insert("licenses/ATTRIBUTION.txt".into(),b"CLINC150 pinned test/oos_test: Larson et al., https://github.com/clinc/oos-eval ; CC BY3.0. New normalized-text-disjoint development/confirmation subsets; source labels are sampling metadata only. Open Images selected individual photographs: CC BY2.0 https://creativecommons.org/licenses/by/2.0/ ; full per-photo authors/titles/landing URLs/current license/native proof in selected attribution and provenance. All140 supplied JPEGs preserve exact source bytes; no resize/crop/reencode/upscale. Open Images annotation metadata CC BY4.0 https://creativecommons.org/licenses/by/4.0/ . Known original SHA only when bytes verified; unknown originals explicitly null.\n".to_vec());
    for (file, bytes) in &files {
        write_exact(&args.output.join(file), bytes)?;
    }
    let mut archival_files: Vec<_> = files.keys().cloned().collect();
    archival_files.extend(
        [
            "manifest.json",
            "text-selection.json",
            "development/text.jsonl",
            "confirmation/text.jsonl",
            "repeat/text.jsonl",
        ]
        .map(str::to_owned),
    );
    archival_files.sort();
    manifest["schema_version"] = json!(3);
    manifest["archival_files"] = json!(archival_files);
    manifest["photos"] = json!(evidence);
    manifest["source_metadata"]["photo_catalog_sha256"] = json!(hash(&catalog_bytes));
    manifest["source_metadata"]["openimages_sha256"] = json!(hash(&metadata_bytes));
    manifest["encoder"] = json!({"policy":"All140 supplied JPEGs are exact source bytes, no transformation.","long_edge_min":512,"long_edge_max":1024});
    manifest["image_selection"] = json!(
        "First140 native-dimension-verified, CC BY2, visually accepted natural RGB photos in registered seed2043 rank pool; previous IDs/Flickr IDs/byte/pixel hashes excluded. Shuffle accepted140 with ChaCha8 seed2043 xor0x70686f746f into40development and100confirmation. No taxonomy quota or classifier outcome filtering."
    );
    manifest["preparation_source_sha256"] = json!(hash(include_bytes!("prepare_auto_research.rs")));
    manifest["reused_validation_source_sha256"] =
        json!(hash(include_bytes!("../src/agreement_data.rs")));
    write_exact(&args.output.join("manifest.json"), &pretty(&manifest)?)?;
    Ok(manifest)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::{BTreeMap, HashSet};

    #[test]
    fn fresh_partitions_exclude_all_prior_normalized_content_and_each_other() -> Result<()> {
        let domains: BTreeMap<_, _> = (0..10)
            .map(|i| (format!("domain{i}"), vec![format!("intent{i}")]))
            .collect();
        let mut test = vec![];
        for i in 0..10 {
            for j in 0..125 {
                test.push(json!([
                    format!("Request {i} number {j}"),
                    format!("intent{i}")
                ]));
            }
        }
        test.push(json!(["REQUEST-0 NUMBER-0", "intent0"]));
        let oos: Vec<_> = (0..140)
            .map(|j| json!([format!("Out of scope {j}"), "oos"]))
            .collect();
        let corpus = serde_json::to_vec(&json!({"test":test,"oos_test":oos}))?;
        let excluded = vec![Item {
            id: "old".into(),
            text: "request 0 number 0".into(),
            image: None,
            label: None,
        }];
        let parts = select_text(&corpus, &serde_json::to_vec(&domains)?, &excluded, 2043)?;
        assert_eq!([parts[0].len(), parts[1].len()], [200, 1000]);
        let mut seen = HashSet::from(["request0number0".to_owned()]);
        for (items, quota) in parts.iter().zip([18, 90]) {
            let mut counts = BTreeMap::new();
            for item in items {
                let normalized: String = item
                    .text
                    .chars()
                    .filter(|c| c.is_alphanumeric())
                    .flat_map(char::to_lowercase)
                    .collect();
                assert!(
                    seen.insert(normalized),
                    "fresh partitions repeated prior or selected content"
                );
                assert!(item.image.is_none());
                *counts.entry(item.label.as_deref().unwrap()).or_insert(0) += 1;
            }
            assert_eq!(counts.remove("oos"), Some(quota / 9 * 10));
            assert!(counts.values().all(|&count| count == quota));
        }
        let replay = select_text(&corpus, &serde_json::to_vec(&domains)?, &excluded, 2043)?;
        assert_eq!(serde_json::to_vec(&parts)?, serde_json::to_vec(&replay)?);
        Ok(())
    }

    #[test]
    fn selected_photo_binding_rejects_changed_bytes_and_tiny_native_sources() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let image = image::RgbImage::from_pixel(512, 768, image::Rgb([190, 65, 30]));
        let mut bytes = vec![];
        image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, 85).encode_image(&image)?;
        fs::write(temp.path().join("input.jpg"), &bytes)?;
        let mut photo = json!({"source_file":"input.jpg","source_sha256":hash(&bytes),"source_bytes":bytes.len(),"width":512,"height":768,"native_width":1024,"native_height":1536,"inspection":"natural_color_photograph"});
        assert_eq!(selected_photo_bytes(&photo, temp.path())?, bytes);
        photo["source_sha256"] = json!("0".repeat(64));
        assert!(selected_photo_bytes(&photo, temp.path()).is_err());
        photo["source_sha256"] = json!(hash(&bytes));
        photo["native_width"] = json!(128);
        photo["native_height"] = json!(192);
        assert!(
            selected_photo_bytes(&photo, temp.path()).is_err(),
            "a larger supplied JPEG must not launder a tiny native source"
        );
        photo["native_width"] = json!(1024);
        photo["native_height"] = json!(1024);
        assert!(
            selected_photo_bytes(&photo, temp.path()).is_err(),
            "native aspect must agree"
        );
        Ok(())
    }

    #[test]
    fn license_and_dimensions_stay_bound_to_the_observed_publisher_page() -> Result<()> {
        let original = json!({"width":1024,"height":1536,"url":"https://live.staticflickr.com/x/123_hash_o.jpg"});
        let license = json!({"@type":"ImageObject","license":"https://creativecommons.org/licenses/by/2.0/","contentUrl":"https://live.staticflickr.com/x/123_hash_o.jpg"});
        let page = format!(
            "<script type=\"application/ld+json\">{license}</script><script>window.photo={{\"sizes\":{{\"o\":{original}}}}};</script>"
        );
        let mut photo = json!({"metadata":{"License":"https://creativecommons.org/licenses/by/2.0/","OriginalURL":"https://live.staticflickr.com/x/123_hash_o.jpg"},"license_jsonld":license,"license_page_sha256":hash(page.as_bytes()),"native_size_evidence":{"value":original},"native_width":1024,"native_height":1536});
        page_proof(&photo, page.as_bytes())?;
        photo["license_jsonld"]["license"] = json!("https://example.com/unrelated-license");
        assert!(page_proof(&photo, page.as_bytes()).is_err());
        photo["license_jsonld"]["license"] = json!("https://creativecommons.org/licenses/by/2.0/");
        photo["native_height"] = json!(1500);
        assert!(page_proof(&photo, page.as_bytes()).is_err());
        photo["native_height"] = json!(1536);
        assert!(page_proof(&photo, format!("{page}changed").as_bytes()).is_err());
        Ok(())
    }

    #[test]
    fn prior_pixel_exclusions_decode_verified_files_when_manifest_has_no_pixel_hashes() -> Result<()>
    {
        let temp = tempfile::tempdir()?;
        let image = image::RgbImage::from_pixel(8, 12, image::Rgb([190, 65, 30]));
        let mut bytes = vec![];
        image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, 85).encode_image(&image)?;
        for folder in ["images", "sources/photos"] {
            fs::create_dir_all(temp.path().join(folder))?;
            fs::write(temp.path().join(folder).join("old.jpg"), &bytes)?;
        }
        let previous =
            json!({"photos":{"old":{"source_sha256":hash(&bytes),"supplied_sha256":hash(&bytes)}}});
        let hashes = previous_pixel_hashes(&previous, temp.path())?;
        assert_eq!(hashes.len(), 1);
        assert!(hashes.contains(&hash(image::load_from_memory(&bytes)?.to_rgb8().as_raw())));
        fs::write(temp.path().join("images/old.jpg"), b"changed")?;
        assert!(previous_pixel_hashes(&previous, temp.path()).is_err());
        Ok(())
    }
}
