# Guided-agreement input selection

`guided-agreement-photos-1042.json` freezes 260 selected Open Images validation
photographs and their provenance. It contains metadata, not image pixels. The
Rust `prepare_agreement` example downloads checksum-verified JPEGs and produces
disjoint discovery, held-out, reserved-streaming and repeat inputs.

The selected rows derive from [Open Images](https://storage.googleapis.com/openimages/web/download_v7.html).
Open Images annotation metadata is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Individual photographs retain their authors' [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/)
licenses; each record preserves its author, title, original landing URL, license,
current Flickr licensing JSON-LD and observation date. Do not apply the code's
BSD license to these photographs or upstream metadata.

The [official CVDF mirror](https://github.com/cvdfoundation/open-images-dataset)
documents aspect-preserving rescaling, but selection independently checked
publisher-reported original dimensions against the downloaded bytes. Native long
edge is at least 512 pixels; supplied long edges are 978–1024 pixels. One mirror
file was 4608×3456 and is deterministically downsampled to 1024×768 at JPEG quality
85. Its source and supplied hashes remain distinct. Other selected source JPEGs
are unchanged. Unavailable original Flickr bytes have null original SHA-256;
publisher metadata is not represented as original-byte verification.

The generated dataset manifest records exact supplied bytes, dimensions,
partition order, CLINC150 CC BY 3.0 attribution, text normalization and exclusions,
repeat IDs and the selected files needed for an evidence archive. Photo titles,
authors, source IDs and dataset labels never enter classifier prompts.
