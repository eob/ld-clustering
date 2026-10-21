use crate::types::Item;
use anyhow::{Context, Result, ensure};
use image::GenericImageView;
use rand::{SeedableRng, seq::SliceRandom};
use rand_chacha::ChaCha8Rng;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs,
    io::Write,
    path::Path,
    time::Duration,
};

const CLINC: &str = "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/data/data_full.json";
const DOMAINS: &str = "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/data/domains.json";
const CLINC_LICENSE: &str = "https://raw.githubusercontent.com/clinc/oos-eval/828f8093932c8fe6ca7936c3d2e52903b1c523de/LICENSE";
const METADATA: &str = "https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv";
const PHOTO_CATALOG: &str = include_str!("../datasets/guided-agreement-photos-1042.json");
const PARTITIONS: [&str; 3] = ["discovery", "heldout", "streaming"];

#[derive(Deserialize, Serialize)]
struct PhotoCatalog {
    selection_seed: u64,
    photos: Vec<Photo>,
}

#[derive(Deserialize, Serialize)]
struct Photo {
    image_id: String,
    source_url: String,
    source_sha256: String,
    source_bytes: usize,
    source_retrieved_at_utc: String,
    license_observed_at_utc: String,
    width: u32,
    height: u32,
    native_width: u32,
    native_height: u32,
    original_sha256: Option<String>,
    metadata: BTreeMap<String, String>,
    license_page_sha256: String,
    native_size_evidence: Value,
    license_jsonld: Value,
    inspection: String,
}

/// Prepare frozen, disjoint discovery, controlled, reserved-streaming and repeat inputs.
/// `previous` is the v2 text JSONL (or its containing dataset directory).
pub async fn prepare(output: &Path, seed: u64, previous: &Path) -> Result<()> {
    ensure!(
        seed == 1042,
        "this curated photo cohort is preregistered for seed 1042"
    );
    ensure!(
        !output.join("manifest.json").exists(),
        "refusing to overwrite a frozen dataset manifest"
    );
    let previous = if previous.is_dir() {
        previous.join("text.jsonl")
    } else {
        previous.to_path_buf()
    };
    let previous_bytes = fs::read(&previous).context("read prior v2 text inputs")?;
    ensure!(
        hash(&previous_bytes) == "934875f651f0ba9365084921f1a0aa440adf8c802e7650d4a7cadf607fb65352",
        "previous inputs differ from the pinned v2 cohort"
    );
    let previous_items: Vec<Item> = std::str::from_utf8(&previous_bytes)?
        .lines()
        .map(serde_json::from_str)
        .collect::<std::result::Result<_, _>>()?;
    ensure!(
        previous_items.len() == 1000,
        "expected all 1000 v2 text inputs"
    );
    let client = reqwest::Client::builder()
        .user_agent("ld-clustering guided dataset preparation/0.1")
        .timeout(Duration::from_secs(90))
        .build()?;
    fs::create_dir_all(output.join("sources"))?;
    fs::create_dir_all(output.join("images"))?;
    fs::create_dir_all(output.join("sources/photos"))?;
    fs::create_dir_all(output.join("licenses"))?;
    let corpus = fetch(
        &client,
        CLINC,
        "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0",
        &output.join("sources/clinc-data.json"),
    )
    .await?;
    let domains = fetch(
        &client,
        DOMAINS,
        "b947b579d3b8e74b06f93b01083d8efaff2888b43a3e362533bd88a6e1211b3a",
        &output.join("sources/clinc-domains.json"),
    )
    .await?;
    fetch(
        &client,
        CLINC_LICENSE,
        "e6bc9e9c474700b708f568bac9e5a8a9bcb2b1dad53442f5ba449fcb848b8e76",
        &output.join("licenses/clinc-CC-BY-3.0.txt"),
    )
    .await?;
    let source_metadata = fetch(
        &client,
        METADATA,
        "ed93a0e121fe345effdfc7359b848dbc64a1ff6778c8c73563157cb500b33a17",
        &output.join("sources/openimages-validation-metadata.csv"),
    )
    .await?;
    let mut source_rows = HashMap::new();
    for row in csv::Reader::from_reader(source_metadata.as_slice())
        .deserialize::<BTreeMap<String, String>>()
    {
        let row = row?;
        source_rows.insert(row.get("ImageID").context("missing image ID")?.clone(), row);
    }
    let catalog: PhotoCatalog = serde_json::from_str(PHOTO_CATALOG)?;
    ensure!(
        catalog.selection_seed == seed && catalog.photos.len() == 260,
        "expected the frozen 260-photo catalog"
    );
    let text = select_text(&corpus, &domains, &previous_items, seed)?;
    let mut photos = Vec::new();
    let mut photo_evidence = BTreeMap::new();
    let mut source_hashes = HashSet::new();
    let mut decoded_hashes = HashSet::new();
    for photo in &catalog.photos {
        ensure!(
            source_rows.get(&photo.image_id) == Some(&photo.metadata),
            "photo metadata differs from official pinned CSV"
        );
        ensure!(
            photo.metadata.get("License").map(String::as_str)
                == Some("https://creativecommons.org/licenses/by/2.0/"),
            "photo license must be CC BY 2.0"
        );
        ensure!(
            photo.inspection == "natural_color_photograph",
            "photo lacks frozen visual acceptance"
        );
        let id = stable_id(&format!("openimages/validation/{}", photo.image_id));
        let relative = format!("../images/{id}.jpg");
        let path = output.join("sources/photos").join(format!("{id}.jpg"));
        let bytes = fetch(&client, &photo.source_url, &photo.source_sha256, &path).await?;
        ensure!(
            bytes.len() == photo.source_bytes,
            "photo byte length differs"
        );
        let decoded = validate_photo(
            &bytes,
            photo.width,
            photo.height,
            photo.native_width,
            photo.native_height,
        )?;
        ensure!(
            source_hashes.insert(hash(&bytes)) && decoded_hashes.insert(hash(decoded.as_raw())),
            "duplicate photo content in curated cohort"
        );
        let (supplied, supplied_width, supplied_height, transform) = if photo
            .width
            .max(photo.height)
            > 1024
        {
            let resized = image::DynamicImage::ImageRgb8(decoded).resize(
                1024,
                1024,
                image::imageops::FilterType::Lanczos3,
            );
            let (width, height) = resized.dimensions();
            let mut encoded = Vec::new();
            image::codecs::jpeg::JpegEncoder::new_with_quality(&mut encoded, 85)
                .encode_image(&resized)?;
            (
                encoded,
                width,
                height,
                "downscale to max1024 using image0.25.10 Lanczos3 and JPEGquality85; original aspect preserved, never upscale",
            )
        } else {
            (
                bytes,
                photo.width,
                photo.height,
                "none; exact CVDF mirror JPEG",
            )
        };
        fs::write(output.join("images").join(format!("{id}.jpg")), &supplied)?;
        let mut evidence = serde_json::to_value(photo)?;
        evidence["supplied_sha256"] = json!(hash(&supplied));
        evidence["supplied_bytes"] = json!(supplied.len());
        evidence["supplied_width"] = json!(supplied_width);
        evidence["supplied_height"] = json!(supplied_height);
        evidence["transform"] = json!(transform);
        photos.push(Item {
            id: id.clone(),
            text: "Photograph.".into(),
            image: Some(relative),
            label: None,
        });
        photo_evidence.insert(id, evidence);
    }
    let mut rng = ChaCha8Rng::seed_from_u64(seed ^ 0x70686f746f);
    photos.shuffle(&mut rng);
    let image_parts = vec![
        photos[..60].to_vec(),
        photos[60..160].to_vec(),
        photos[160..].to_vec(),
    ];
    let mut partitions = BTreeMap::new();
    for ((name, text_items), image_items) in PARTITIONS.into_iter().zip(&text).zip(&image_parts) {
        fs::create_dir_all(output.join(name))?;
        write_jsonl(&output.join(name).join("text.jsonl"), text_items)?;
        write_jsonl(&output.join(name).join("images.jsonl"), image_items)?;
        partitions.insert(name, json!({"text":stream_evidence(&format!("{name}/text.jsonl"), text_items, &photo_evidence)?, "images":stream_evidence(&format!("{name}/images.jsonl"), image_items, &photo_evidence)?}));
    }
    let repeat_text = repeat_subset(&text[1], 100, seed ^ 0x74657874);
    let repeat_images = repeat_subset(&image_parts[1], 25, seed ^ 0x696d616765);
    fs::create_dir_all(output.join("repeat"))?;
    write_jsonl(&output.join("repeat/text.jsonl"), &repeat_text)?;
    write_jsonl(&output.join("repeat/images.jsonl"), &repeat_images)?;
    partitions.insert("repeat", json!({"text":stream_evidence("repeat/text.jsonl", &repeat_text, &photo_evidence)?, "images":stream_evidence("repeat/images.jsonl", &repeat_images, &photo_evidence)?}));
    fs::write(
        output.join("licenses/openimages-selected-attribution.json"),
        PHOTO_CATALOG,
    )?;
    fs::write(
        output.join("licenses/ATTRIBUTION.txt"),
        "CLINC150: Larson et al., An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction (EMNLP-IJCNLP 2019), https://github.com/clinc/oos-eval ; CC BY 3.0, upstream license retained. Changes: deterministic, normalized-text-disjoint subsets; intent labels mapped to broad domains for evaluation only.\n\nOpen Images: Kuznetsova et al., The Open Images Dataset V4: Unified image classification, object detection, and visual relationship detection at scale (IJCV 2020), https://storage.googleapis.com/openimages/web/index.html . Selected individual photographs are CC BY 2.0, https://creativecommons.org/licenses/by/2.0/ ; per-photo author, title, original landing URL, license and original-dimension evidence are retained in openimages-selected-attribution.json. Google annotation metadata CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . Supplied JPEG files <=1024 retain exact CVDF-hosted source bytes; the observed 4608x3456 source outlier is downscaled to longest-side1024 with image0.25.10 Lanczos3/JPEGquality85, without upscaling. Source and supplied hashes/dimensions are retained; CVDF documents at-most-1024-long-edge rescaling preserving aspect. We additionally rejected every image whose current Flickr original dimensions were below the mirror dimensions, allowing orientation swaps and integer rounding. No cropping or upscaling. The sole above-limit source is downsampled and re-encoded as specified. Current Flickr licensing JSON-LD and native sizes metadata were checked before any model call; full-page SHA-256 identifies each observation. Some original URLs were unavailable; original byte SHA-256 is null in those cases, and official original MD5 plus publisher-reported dimensions are retained without asserting byte verification.\n",
    )?;
    let mut exclusion: Vec<_> = previous_items
        .iter()
        .map(|item| normalize_text(&item.text))
        .collect();
    exclusion.sort();
    exclusion.dedup();
    let mut archival_files = vec![
        "manifest.json".to_owned(),
        "licenses/clinc-CC-BY-3.0.txt".to_owned(),
        "licenses/ATTRIBUTION.txt".to_owned(),
        "licenses/openimages-selected-attribution.json".to_owned(),
    ];
    for name in ["discovery", "heldout", "streaming", "repeat"] {
        for modality in ["text", "images"] {
            archival_files.push(format!("{name}/{modality}.jsonl"));
        }
    }
    archival_files.extend(photos.iter().map(|item| format!("images/{}.jpg", item.id)));
    archival_files.sort();
    let manifest = json!({
        "schema_version":2,"seed":seed,"archival_files":archival_files,"encoder":{"crate":"image","version":"0.25.10","resize_filter":"Lanczos3","jpeg_quality":85,"long_edge_limit":1024,"policy":"only sources above1024 are resized/reencoded; no upscaling"},
        "source_metadata":{"clinc_url":CLINC,"clinc_sha256":hash(&corpus),"domains_url":DOMAINS,"domains_sha256":hash(&domains),"openimages_url":METADATA,"openimages_sha256":hash(&source_metadata),"photo_catalog_sha256":hash(PHOTO_CATALOG.as_bytes())},
        "previous_text_sha256":hash(&previous_bytes),"previous_text_count":previous_items.len(),"excluded_normalized_texts_sha256":hash(&serde_json::to_vec(&exclusion)?),
        "normalization":"Unicode alphanumeric characters only, lowercase; removes all punctuation and whitespace. Applied globally before selection to v2 and all new text inputs.",
        "text_selection":"Pinned CLINC test/oos_test only. Lexical domains; one seeded ChaCha8 shuffle per group; per-domain quotas discovery18/heldout90/streaming90 and OOS20/100/100; independently shuffle each complete partition.",
        "image_selection":"Seed1042 SHA256-ranked Open Images validation candidate pool; current Flickr CC-BY2.0 and original-dimension checks; visually inspected natural color photographs only. No evaluation taxonomy. Selected source JPEG and decoded RGB hashes unique across260. ChaCha8 seeded separately shuffles accepted260 into60/100/100.",
        "repeat_selection":"Draw100text/25images from heldout with separate seeded ChaCha8 shuffles, then retain original heldout relative order. Frozen before outcomes; repeat reuses identical bytes and IDs intentionally.",
        "partitions":partitions,"photos":photo_evidence,
        "image_transform":"SourceJPEGs<=1024 longedge are unaltered; sourceJPEGs>1024 downscaled preservingaspect with image0.25.10 Lanczos3 thenJPEG85. No upscale/crop. Bothsource/suppliedhash+dims retained; everypublisher originaldimension >=mirror source required.",
        "model_evidence":"Only Item.text and image bytes. Opaque IDs, source metadata and evaluation labels are excluded by the provider. Image labels are absent.",
        "licenses":["licenses/clinc-CC-BY-3.0.txt","licenses/ATTRIBUTION.txt","licenses/openimages-selected-attribution.json"]
    });
    fs::write(
        output.join("manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    Ok(())
}

async fn fetch(
    client: &reqwest::Client,
    url: &str,
    expected: &str,
    path: &Path,
) -> Result<Vec<u8>> {
    let bytes = if path.exists() {
        fs::read(path)?
    } else {
        client
            .get(url)
            .send()
            .await?
            .error_for_status()?
            .bytes()
            .await?
            .to_vec()
    };
    ensure!(hash(&bytes) == expected, "source checksum differs: {url}");
    if !path.exists() {
        fs::write(path, &bytes)?;
    }
    Ok(bytes)
}

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn stable_id(key: &str) -> String {
    hash(key.as_bytes())[..20].to_owned()
}
fn normalize_text(text: &str) -> String {
    text.chars()
        .filter(|ch| ch.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

#[derive(Deserialize)]
struct TextCorpus {
    test: Vec<(String, String)>,
    oos_test: Vec<(String, String)>,
}

fn select_text(
    corpus: &[u8],
    domains: &[u8],
    previous: &[Item],
    seed: u64,
) -> Result<Vec<Vec<Item>>> {
    let corpus: TextCorpus = serde_json::from_slice(corpus)?;
    let domains: BTreeMap<String, Vec<String>> = serde_json::from_slice(domains)?;
    ensure!(domains.len() == 10, "expected ten CLINC domains");
    let mut mapping = HashMap::new();
    let mut groups: BTreeMap<String, Vec<Item>> = BTreeMap::new();
    for (domain, intents) in domains {
        for intent in intents {
            ensure!(
                mapping.insert(intent, domain.clone()).is_none(),
                "intent maps to multiple domains"
            );
        }
        groups.insert(domain, Vec::new());
    }
    let mut seen: HashSet<_> = previous.iter().map(|x| normalize_text(&x.text)).collect();
    for (index, (text, intent)) in corpus.test.into_iter().enumerate() {
        let domain = mapping.get(&intent).context("unknown CLINC intent")?;
        let normalized = normalize_text(&text);
        ensure!(!normalized.is_empty(), "empty normalized text");
        if !seen.insert(normalized) {
            continue;
        }
        groups.get_mut(domain).unwrap().push(Item {
            id: stable_id(&format!("clinc/test/{index}")),
            text,
            image: None,
            label: Some(domain.clone()),
        });
    }
    let mut other = Vec::new();
    for (index, (text, _)) in corpus.oos_test.into_iter().enumerate() {
        if !seen.insert(normalize_text(&text)) {
            continue;
        }
        other.push(Item {
            id: stable_id(&format!("clinc/oos_test/{index}")),
            text,
            image: None,
            label: Some("oos".into()),
        });
    }
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut selected = vec![Vec::new(), Vec::new(), Vec::new()];
    for group in groups.values_mut() {
        ensure!(
            group.len() >= 198,
            "insufficient unique requests for a domain"
        );
        group.shuffle(&mut rng);
        let mut offset = 0;
        for (part, count) in selected.iter_mut().zip([18, 90, 90]) {
            part.extend_from_slice(&group[offset..offset + count]);
            offset += count;
        }
    }
    ensure!(
        other.len() >= 220,
        "insufficient unique out-of-scope requests"
    );
    other.shuffle(&mut rng);
    let mut offset = 0;
    for (part, count) in selected.iter_mut().zip([20, 100, 100]) {
        part.extend_from_slice(&other[offset..offset + count]);
        offset += count;
        part.shuffle(&mut rng);
    }
    Ok(selected)
}

pub fn validate_photo(
    bytes: &[u8],
    width: u32,
    height: u32,
    native_width: u32,
    native_height: u32,
) -> Result<image::RgbImage> {
    ensure!(bytes.starts_with(&[0xff, 0xd8]), "expected JPEG source");
    let image = image::load_from_memory(bytes)?;
    ensure!(
        image.dimensions() == (width, height),
        "encoded dimensions differ from frozen catalog"
    );
    ensure!(
        image.color() == image::ColorType::Rgb8,
        "expected native RGB JPEG"
    );
    ensure!(width.max(height) >= 512, "supplied long edge below512");
    ensure!(
        native_width.max(native_height) >= width.max(height)
            && native_width.min(native_height) >= width.min(height),
        "source would require upscaling"
    );
    let (nw, nh) = if (width as f64 / height as f64 - native_width as f64 / native_height as f64)
        .abs()
        <= (width as f64 / height as f64 - native_height as f64 / native_width as f64).abs()
    {
        (native_width, native_height)
    } else {
        (native_height, native_width)
    };
    let target_height = (width as f64 * nh as f64 / nw as f64).round();
    ensure!(
        (height as f64 - target_height).abs() <= 1.0,
        "source aspect differs beyond pixel rounding"
    );
    let rgb = image.to_rgb8();
    let colorful = rgb
        .pixels()
        .filter(|p| p.0.iter().max().unwrap() - p.0.iter().min().unwrap() >= 12)
        .count();
    ensure!(
        colorful as f64 / (rgb.width() as f64 * rgb.height() as f64) >= 0.03,
        "photo is effectively grayscale"
    );
    Ok(rgb)
}

fn repeat_subset(items: &[Item], count: usize, seed: u64) -> Vec<Item> {
    let mut indices: Vec<_> = (0..items.len()).collect();
    indices.shuffle(&mut ChaCha8Rng::seed_from_u64(seed));
    indices.truncate(count);
    indices.sort();
    indices.into_iter().map(|i| items[i].clone()).collect()
}

fn stream_evidence(file: &str, items: &[Item], photos: &BTreeMap<String, Value>) -> Result<Value> {
    let ids: Vec<_> = items.iter().map(|x| &x.id).collect();
    let image_hashes: Vec<_> = items
        .iter()
        .filter_map(|item| {
            photos
                .get(&item.id)
                .map(|p| json!({"id":item.id,"sha256":p["supplied_sha256"]}))
        })
        .collect();
    Ok(
        json!({"file":file,"count":items.len(),"ordered_ids":ids,"order_sha256":hash(&serde_json::to_vec(&ids)?),"payload_sha256":hash(&serde_json::to_vec(items)?),"ordered_image_content_sha256":hash(&serde_json::to_vec(&image_hashes)?),"ordered_image_hashes":image_hashes}),
    )
}
fn write_jsonl(path: &Path, items: &[Item]) -> Result<()> {
    let mut f = fs::File::create(path)?;
    for item in items {
        serde_json::to_writer(&mut f, item)?;
        f.write_all(b"\n")?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::BTreeMap;

    #[test]
    fn text_partitions_exclude_prior_normalized_duplicates_and_each_other() -> Result<()> {
        let domains: BTreeMap<_, _> = (0..10)
            .map(|n| (format!("domain{n}"), vec![format!("intent{n}")]))
            .collect();
        let mut test = Vec::new();
        for n in 0..10 {
            for i in 0..205 {
                test.push((format!("request {n} distinct {i}"), format!("intent{n}")));
            }
        }
        test.push(("REQUEST 0 DISTINCT 0!!!".into(), "intent0".into()));
        let oos: Vec<_> = (0..240)
            .map(|n| (format!("outside {n}"), "oos".to_owned()))
            .collect();
        let prior = vec![Item {
            id: "prior".into(),
            text: " Request 0 distinct 0? ".into(),
            image: None,
            label: None,
        }];
        let corpus = serde_json::to_vec(&json!({"test":test,"oos_test":oos}))?;
        let map = serde_json::to_vec(&domains)?;
        let parts = select_text(&corpus, &map, &prior, 1042)?;
        assert_eq!(
            parts.iter().map(Vec::len).collect::<Vec<_>>(),
            vec![200, 1000, 1000]
        );
        assert_eq!(parts, select_text(&corpus, &map, &prior, 1042)?);
        assert_ne!(parts, select_text(&corpus, &map, &prior, 1043)?);
        let mut seen: HashSet<_> = prior.iter().map(|x| normalize_text(&x.text)).collect();
        let mut ids = HashSet::new();
        for (part, domain_quota) in parts.iter().zip([18, 90, 90]) {
            let mut counts = BTreeMap::new();
            for item in part {
                assert!(
                    seen.insert(normalize_text(&item.text)),
                    "normalized duplicate"
                );
                assert!(ids.insert(&item.id));
                assert!(item.image.is_none());
                assert!(!item.id.contains("domain") && !item.id.contains("oos"));
                *counts.entry(item.label.as_deref().unwrap()).or_insert(0) += 1;
            }
            assert_eq!(counts.remove("oos"), Some(domain_quota / 9 * 10));
            assert_eq!(counts.len(), 10);
            assert!(counts.values().all(|n| *n == domain_quota));
        }
        Ok(())
    }

    #[test]
    fn photos_require_native_color_resolution_and_unaltered_aspect() -> Result<()> {
        fn jpeg(width: u32, height: u32, color: bool) -> Result<Vec<u8>> {
            let pixels = image::RgbImage::from_fn(width, height, |x, y| {
                if color {
                    image::Rgb([200, (x % 80) as u8, (y % 60) as u8])
                } else {
                    image::Rgb([80, 80, 80])
                }
            });
            let mut out = Vec::new();
            image::codecs::jpeg::JpegEncoder::new_with_quality(&mut out, 85)
                .encode_image(&pixels)?;
            Ok(out)
        }
        let bytes = jpeg(640, 480, true)?;
        assert_eq!(
            validate_photo(&bytes, 640, 480, 1280, 960)?.dimensions(),
            (640, 480)
        );
        assert!(validate_photo(&bytes, 640, 480, 960, 1280).is_ok());
        assert!(validate_photo(&bytes, 640, 480, 500, 375).is_err());
        assert!(validate_photo(&bytes, 640, 480, 1280, 1000).is_err());
        assert!(validate_photo(&bytes, 641, 480, 1280, 960).is_err());
        assert!(validate_photo(&jpeg(400, 300, true)?, 400, 300, 800, 600).is_err());
        assert!(validate_photo(&jpeg(640, 480, false)?, 640, 480, 1280, 960).is_err());
        Ok(())
    }

    #[test]
    fn repeated_items_are_a_deterministic_subset_with_original_order() {
        let rows: Vec<_> = (0..120)
            .map(|i| Item {
                id: i.to_string(),
                text: i.to_string(),
                image: None,
                label: None,
            })
            .collect();
        let repeated = repeat_subset(&rows, 100, 1042);
        assert_eq!(repeated.len(), 100);
        assert_eq!(repeated, repeat_subset(&rows, 100, 1042));
        assert_ne!(repeated, repeat_subset(&rows, 100, 1043));
        let positions: Vec<_> = repeated
            .iter()
            .map(|x| x.id.parse::<usize>().unwrap())
            .collect();
        assert!(positions.windows(2).all(|w| w[0] < w[1]));
    }

    #[test]
    fn normalization_excludes_case_punctuation_and_whitespace_variants() {
        assert_eq!(
            normalize_text("What's my BALANCE?!"),
            normalize_text("whats  my balance")
        );
        assert_ne!(normalize_text("balance one"), normalize_text("balance two"));
    }
}
