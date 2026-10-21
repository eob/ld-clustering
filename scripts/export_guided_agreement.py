#!/usr/bin/env python3
"""Copy validated frozen guided-agreement artifacts into the report DTO.

Offline only. Scientific metrics and reviewer judgments are copied, never
recomputed. Run the independent evidence audit separately before publication.

Selection JSON requires schema_version1, published_at (YYYY-MM-DD), a public
asset_url_prefix, and modalities.text/images containing selection_note and
1..8 explicit {condition, case_id} cases each. For photos, alt_evidence_index
optionally selects a literal judgment.evidence entry (default0). Titles remain
credits. The caller supplies the separately verified archive-manifest hash.
"""

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import struct

REPOSITORY = 'https://github.com/eob/ld-clustering'
RUN_PATH = 'experiments/2026-10-20-guided-agreement-seed1042/evidence'
CONDITIONS = ('original', 'guided')
COUNTS = {'text': (1000, 100), 'images': (100, 25)}
LICENSE = 'https://creativecommons.org/licenses/by/2.0/'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def read(path, expected=None):
    path = Path(path)
    body = path.read_bytes()
    digest = sha(body)
    require(expected is None or digest == expected, f'artifact hash differs: {path.name}')
    return json.loads(body), digest


def member(root, name):
    path = (root/name).resolve()
    require(root.resolve() in path.parents, f'artifact path escapes root: {name}')
    return path


def pin(value, length):
    require(isinstance(value, str) and re.fullmatch(f'[0-9a-f]{{{length}}}', value), 'invalid immutable hash pin')


def measurement(value, complete=False):
    require(isinstance(value, dict), 'missing measurement')
    require(all(type(value.get(key)) is bool for key in ('cost_complete', 'timing_complete')), 'missing measurement completeness flags')
    require(not complete or value['timing_complete'], 'incomplete measured loop')
    for key in ('cost_usd', 'wall_seconds', 'calls', 'error_calls', 'unknown_usage_calls', 'unknown_pricing_calls', 'assignment_refusal_calls'):
        number = value.get(key)
        require(type(number) in (int, float) and math.isfinite(number) and number >= 0, f'missing/invalid measurement: {key}')
    require(not value['cost_complete'] or value['unknown_usage_calls'] == value['unknown_pricing_calls'] == 0, 'complete cost has unknown usage/pricing')
    return value


def source_pin(artifact, runtime):
    source = artifact.get('source', artifact.get('metadata', {}).get('source', {}))
    require(source.get('commit') == runtime['source_commit'] and source.get('executable_sha256') == runtime['classification_executable_sha256'], 'artifact runtime pin differs')


def terminal(artifact):
    require(artifact.get('schema_version') == 1 and artifact.get('status') == 'complete' and artifact.get('error') is None, 'incomplete artifact')
    measurement(artifact['measurement'], complete=True)


def input_evidence(data_root, manifest, split, modality):
    spec = manifest['partitions'][split][modality]
    path = member(data_root, spec['file'])
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    ids = [row['id'] for row in rows]
    require(len(ids) == spec['count'] == len(set(ids)) and ids == spec['ordered_ids'], 'dataset input count/order differs')
    require(sha(compact(rows)) == spec['payload_sha256'] and sha(compact(ids)) == spec['order_sha256'], 'dataset input manifest hash differs')
    digest = hashlib.sha256(b'ld-clustering-input-v1\0'+struct.pack('<Q', len(raw))+raw)
    images = {}
    for row in rows:
        require(isinstance(row.get('text'), str) and (row.get('image') is not None) == (modality == 'images'), 'input modality differs')
        if modality == 'images':
            image = (path.parent/row['image']).resolve()
            require(data_root.resolve() in image.parents, 'image path escapes dataset')
            body = image.read_bytes()
            require(sha(body) == manifest['photos'][row['id']]['supplied_sha256'], 'supplied image hash differs')
            images[row['id']] = body
            digest.update(b'local-image\0'+struct.pack('<Q', len(body))+body)
    return {'rows': rows, 'sha256': sha(raw), 'fingerprint': digest.hexdigest(), 'images': images}


def classification(artifact, catalog, catalog_hash, inputs, mode, model, runtime, reference=None):
    terminal(artifact)
    source_pin(artifact, runtime)
    rows = artifact['assignments']
    n = len(inputs['rows'])
    require(artifact.get('processed_count') == artifact.get('expected_count') == len(rows) == n, 'incomplete classification count')
    expected = dict(mode=mode, modality=catalog['modality'], condition=catalog['stage'], task=catalog['task'], catalog=catalog['catalog'],
        catalog_sha256=catalog_hash, expected_count=n, ordered_ids=[row['id'] for row in inputs['rows']], input_sha256=inputs['fingerprint'],
        input_jsonl_sha256=inputs['sha256'], stage='repeat' if reference else 'classify', diagnostic=False, k=8,
        reverse_catalog_order=False, assignment_model=model, management_calls=0, reference_sha256=reference)
    require(all(artifact['metadata'].get(key) == value for key, value in expected.items()), 'classification input/catalog/backend binding differs')
    require([row['id'] for row in rows] == expected['ordered_ids'], 'classification assignment IDs/order differ')
    allowed = {category['id'] for category in catalog['catalog']}
    for row in rows:
        require(type(row.get('refused')) is bool and (row.get('cluster_id') is None or type(row['cluster_id']) is int and row['cluster_id'] in allowed), 'invalid assignment or catalog ID')
        require(not row['refused'] or row['cluster_id'] is None, 'refused assignment has a named category')
    return {row['id']: row for row in rows}


def review_evidence_hash(text, image):
    raw = text.encode()
    body = b'blinded-review-evidence-v1\0'+struct.pack('<Q', len(raw))+raw
    return sha(body+(b'no-image\0' if image is None else b'image\0'+struct.pack('<Q', len(image))+image))


def accepted_judgment(case, judgment):
    require(set(judgment) == {'case_id', 'a_fit', 'b_fit', 'verdict', 'severity', 'themes', 'evidence', 'explanation', 'proposed_alternative'}, 'accepted review judgment fields differ')
    require(judgment['case_id'] == case['case_id'] and judgment['a_fit'] in ('supported', 'unsupported', 'unclear') and judgment['b_fit'] in ('supported', 'unsupported', 'unclear'), 'accepted review identity/fit is invalid')
    require(judgment['verdict'] in ('a_better', 'b_better', 'both_reasonable', 'neither_reasonable', 'unclear') and judgment['severity'] in ('none', 'minor', 'major', 'unclear'), 'accepted review verdict/severity is invalid')
    require(isinstance(judgment['explanation'], str) and judgment['explanation'].strip(), 'accepted review explanation is empty')
    require(isinstance(judgment['evidence'], list) and 1 <= len(judgment['evidence']) <= 8 and all(isinstance(text, str) and text.strip() for text in judgment['evidence']), 'accepted review lacks literal evidence')
    require(isinstance(judgment['themes'], list) and judgment['themes'] and all(isinstance(theme, str) and theme.strip() for theme in judgment['themes']), 'accepted review themes are empty')
    alternative = judgment['proposed_alternative']
    require(alternative is None or isinstance(alternative, dict) and set(alternative) == {'cluster_id', 'reason'} and (alternative['cluster_id'] is None or type(alternative['cluster_id']) is int and alternative['cluster_id'] in {c['id'] for c in case['catalog']}) and isinstance(alternative['reason'], str) and alternative['reason'].strip(), 'review alternative is missing or outside catalog')
    if case['choice_a'] == case['choice_b']:
        require(judgment['a_fit'] == judgment['b_fit'] and judgment['verdict'] not in ('a_better', 'b_better'), 'identical choices received unequal review')
    for verdict, fit in [('both_reasonable', 'supported'), ('neither_reasonable', 'unsupported')]:
        require(judgment['verdict'] != verdict or judgment['a_fit'] == judgment['b_fit'] == fit, 'review verdict contradicts fit')


def review_bindings(analyzed, bundle, artifact, catalog, baseline, candidate, inputs, plan, runtime):
    require(artifact.get('status') in ('complete', 'failed'), 'review is not terminal')
    source_pin(artifact, runtime)
    require(bundle['sampling_plan'] == plan and bundle['plan_sha256'] == sha(compact(plan)), 'review plan hash differs')
    require(artifact['metadata']['plan_sha256'] == bundle['plan_sha256'] and artifact['metadata']['selected_count'] == len(bundle['cases']), 'review output selection binding differs')
    require(analyzed['aggregate'] == artifact['aggregate'] and analyzed['measurement'] == artifact['measurement'], 'review analysis differs from raw artifact')
    measurement(artifact['measurement'])
    audit = bundle['audit']
    require(audit['cohort_id'] == f"{catalog['modality']}-{catalog['stage']}" and audit['modality'] == catalog['modality'] and audit['total_input_count'] == len(inputs['rows']), 'review cohort binding differs')
    require(audit['catalog_sha256'] == sha(compact(catalog['catalog'])), 'review catalog hash differs')
    records = lambda rows: [dict(id=row['id'], cluster_id=row['cluster_id'], refused=row['refused'], label=row.get('label')) for row in rows.values()]
    require(audit['reference_assignments_sha256'] == sha(compact(records(baseline))) and audit['candidate_assignments_sha256'] == sha(compact(records(candidate))), 'review assignment hash differs')
    cases = {case['case_id']: case for case in bundle['cases']}
    keys = {key['case_id']: key for key in audit['keys']}
    require(len(cases) == len(bundle['cases']) == len(keys) == len(audit['keys']) and cases.keys() == keys.keys() == bundle['evidence_sha256'].keys(), 'duplicate/missing review case bindings')
    require(len({key['item_id'] for key in keys.values()}) == len(keys), 'review contains duplicate input points')
    require(analyzed['selected_count'] == len(cases), 'review selected count differs')
    items = {row['id']: row for row in inputs['rows']}
    for cid, case in cases.items():
        key = keys[cid]
        require(key['item_id'] in items and type(key['a_is_reference']) is bool, 'review key has unknown point or A/B identity')
        item = items[key['item_id']]
        left, right = baseline[item['id']]['cluster_id'], candidate[item['id']]['cluster_id']
        require(key['reference_cluster_id'] == left and key['candidate_cluster_id'] == right, 'review key differs from primary assignments')
        stratum = 'both_other' if left is None and right is None else 'reference_other_candidate_named' if left is None else 'reference_named_candidate_other' if right is None else 'equal_named' if left == right else 'different_named'
        require(key['stratum'] == stratum, 'review key stratum differs from assignments')
        a, b = (left, right) if key['a_is_reference'] else (right, left)
        require(case['choice_a'] == a and case['choice_b'] == b and case['task'] == catalog['task'] and case['catalog'] == catalog['catalog'], 'review displayed choices/catalog differ from audit key')
        require(case['item']['text'] == item['text'] and (case['item']['image'] is not None) == (catalog['modality'] == 'images'), 'review item differs from frozen input')
        require(key['payload_sha256'] == sha(compact(case)), 'review case payload hash differs')
        require(bundle['evidence_sha256'][cid] == review_evidence_hash(item['text'], inputs['images'].get(item['id'])), 'review text/image evidence hash differs')
    outcomes = {outcome['case_id']: outcome for outcome in artifact['outcomes']}
    require(len(outcomes) == len(artifact['outcomes']) and outcomes.keys() <= cases.keys(), 'duplicate/unknown review outcome')
    for cid, outcome in outcomes.items():
        judgment = outcome.get('judgment')
        require((judgment is None) != (outcome.get('error') is None), 'review outcome must contain one judgment or error')
        if judgment is not None:
            require(outcome.get('raw_response') == judgment and judgment.get('case_id') == cid, 'review judgment differs from accepted raw response')
            accepted_judgment(cases[cid], judgment)
    for name, ids in [('totals', set(cases))]+[(entry['stratum'], {cid for cid in cases if keys[cid]['stratum'] == entry['stratum']}) for entry in audit['strata']]:
        counts = artifact['aggregate']['totals'] if name == 'totals' else artifact['aggregate']['strata'][name]
        attempted = ids & outcomes.keys()
        accepted = sum(outcomes[cid]['judgment'] is not None for cid in attempted)
        require((counts['selected_count'], counts['attempted_count'], counts['accepted_count'], counts['failed_count'], counts['not_attempted_count']) == (len(ids), len(attempted), accepted, len(attempted)-accepted, len(ids)-len(attempted)), 'review attempted/accepted/failed accounting differs')
    complete = artifact['status'] == 'complete' and artifact.get('error') is None and len(outcomes) == len(cases) and all(outcome['judgment'] is not None for outcome in outcomes.values())
    require(type(analyzed['complete']) is bool and analyzed['complete'] == complete and (artifact['status'] != 'complete' or complete), 'review completeness differs')
    return cases, keys, outcomes


def jpeg_dimensions(body):
    require(body.startswith(b'\xff\xd8') and b'\xff\xd9' in body, 'selected photo is not a complete JPEG')
    position = 2
    while position+4 <= len(body):
        require(body[position] == 255, 'invalid JPEG marker')
        while position < len(body) and body[position] == 255:
            position += 1
        require(position < len(body), 'truncated JPEG marker')
        marker = body[position]
        position += 1
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(body[position:position+2], 'big')
        require(length >= 2 and position+length <= len(body), 'truncated JPEG segment')
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            require(length >= 8, 'invalid JPEG frame')
            return int.from_bytes(body[position+5:position+7], 'big'), int.from_bytes(body[position+3:position+5], 'big')
        position += length
    raise ValueError('JPEG lacks supported frame dimensions')


def example_image(body, photo, filename, prefix, alt):
    width, height = jpeg_dimensions(body)
    require((width, height) == (photo['supplied_width'], photo['supplied_height']) and max(width, height) >= 512, 'selected photo dimensions differ or are below512')
    native, supplied = sorted((photo['native_width'], photo['native_height'])), sorted((width, height))
    require(max(native) >= 512 and all(n >= s for n, s in zip(native, supplied)), 'selected photo native dimensions imply upscaling')
    metadata = photo['metadata']
    require(photo['inspection'] == 'natural_color_photograph' and metadata['License'] == LICENSE, 'selected photo license/inspection differs')
    require(all(isinstance(metadata.get(key), str) and metadata[key].strip() for key in ('Author', 'AuthorProfileURL', 'OriginalLandingURL', 'License')), 'selected photo attribution is incomplete')
    return dict(src=f'{prefix}/{filename}', width=width, height=height, alt=alt, title=metadata.get('Title', ''), author=metadata['Author'],
        author_url=metadata['AuthorProfileURL'], source_url=metadata['OriginalLandingURL'], license_name='CC BY 2.0', license_url=metadata['License'],
        changes=photo['transform'], sha256=photo['supplied_sha256'])


def export_publication(run_root, data_root, selection, repository_commit,
                       archive_manifest_sha256, output, asset_dir):
    run_root, data_root, output, asset_dir = map(Path, (run_root, data_root, output, asset_dir))
    require(not output.exists() and not asset_dir.exists(), 'output JSON and asset directory must both be fresh')
    require(output.resolve() != asset_dir.resolve() and output.resolve() not in asset_dir.resolve().parents and asset_dir.resolve() not in output.resolve().parents, 'output JSON and asset directory must be separate paths')
    pin(repository_commit, 40)
    pin(archive_manifest_sha256, 64)
    selected, _ = read(selection)
    require(selected['schema_version'] == 1 and set(selected['modalities']) == set(COUNTS), 'selection requires both modalities')
    date.fromisoformat(selected['published_at'])
    prefix = selected['asset_url_prefix'].rstrip('/')
    require(prefix.startswith('/') and not prefix.startswith('//') and '..' not in PurePosixPath(prefix).parts and not any(c in prefix for c in ('?', '#', '\\')), 'invalid asset URL prefix')
    runtime, _ = read(run_root/'preregistration/runtime.json')
    pin(runtime['source_commit'], 40)
    pin(runtime['classification_executable_sha256'], 64)
    protocol, _ = read(run_root/'preregistration/protocol.json', runtime['protocol_sha256'])
    manifest, manifest_hash = read(data_root/'manifest.json', runtime['dataset_manifest_sha256'])
    require(protocol['dataset_manifest_sha256'] == manifest_hash and manifest['seed'] == 1042, 'dataset manifest differs from frozen protocol')
    analysis, analysis_hash = read(run_root/'analysis.json')
    require(analysis.get('schema_version') == 1 and analysis.get('status') in ('complete', 'reviews_incomplete'), 'primary analysis is incomplete')
    paths, _ = read(run_root/'analysis-input.json', analysis['manifest_sha256'])
    plan, plan_file_hash = read(member(run_root, paths['review_plan']), analysis['review_plan_file_sha256'])
    plan_hash = sha(compact(plan))
    require(plan == analysis['review_plan'] == protocol['review_plan'] and plan_hash == analysis['review_plan_sha256'] and plan_file_hash == protocol['review_plan_sha256'], 'analysis/review plan hash differs')
    cohorts = {cohort['modality']: cohort for cohort in paths['cohorts']}
    analyzed = {modality['modality']: modality for modality in analysis['modalities']}
    require(len(cohorts) == len(paths['cohorts']) == len(analyzed) == len(analysis['modalities']) == 2 and set(cohorts) == set(analyzed) == set(COUNTS), 'analysis modalities differ')
    models = dict(reference=protocol['classifiers']['llm']['model'], candidate=protocol['classifiers']['ld']['model'], reviewer=protocol['reviewer']['model'])
    publication = dict(schema_version=1, status='complete', published_at=selected['published_at'], source=dict(repository=REPOSITORY, commit=repository_commit,
        runtime_commit=runtime['source_commit'], executable_sha256=runtime['classification_executable_sha256'], run_path=RUN_PATH,
        manifest_sha256=archive_manifest_sha256, analysis_sha256=analysis_hash, dataset_manifest_sha256=manifest_hash, review_plan_sha256=plan_file_hash), models=models, modalities=[])
    assets = {}
    for modality, (n, repeat_n) in COUNTS.items():
        result = analyzed[modality]
        require((result['heldout_count'], result['repeat_count']) == (n, repeat_n), 'analysis cohort size differs')
        inputs = {split: input_evidence(data_root, manifest, split, modality) for split in ('discovery', 'heldout', 'repeat')}
        require(len(inputs['heldout']['rows']) == n and len(inputs['repeat']['rows']) == repeat_n, 'dataset cohort size differs')
        held = {row['id']: row for row in inputs['heldout']['rows']}
        require(all(held.get(row['id']) == row for row in inputs['repeat']['rows']), 'repeat input differs from heldout')
        catalogues, reviews = {}, {}
        entry = dict(modality=modality, heldout_count=n, repeat_count=repeat_n, paired=result['paired'], examples=[], example_selection_note=selected['modalities'][modality]['selection_note'])
        for condition in CONDITIONS:
            condition_paths, summary = cohorts[modality][condition], result[condition]
            hashes = summary['artifact_sha256']
            catalog, catalog_hash = read(member(run_root, condition_paths['catalog']), hashes['catalog'])
            terminal(catalog)
            source_pin(catalog, runtime)
            require(catalog['modality'] == modality and catalog['stage'] == condition and catalog['discovery_count'] == len(inputs['discovery']['rows']) and catalog['discovery_ids'] == [row['id'] for row in inputs['discovery']['rows']] and catalog['discovery_sha256'] == inputs['discovery']['fingerprint'] and catalog['discovery_jsonl_sha256'] == inputs['discovery']['sha256'], 'catalog discovery/condition binding differs')
            cats = catalog['catalog']
            require(1 <= len(cats) <= 16 and [c['id'] for c in cats] == sorted({c['id'] for c in cats}) and all(type(c['id']) is int and c['id'] > 0 and c['name'].strip() and c['description'].strip() for c in cats), 'invalid catalog IDs/order/descriptions')
            names = {c['name'].strip().lower() for c in cats}
            require(len(names) == len(cats) and 'other' not in names, 'duplicate/reserved catalog names')
            require(condition != 'original' or catalog['parent_catalog_sha256'] is None, 'original catalog unexpectedly has a parent')
            if condition == 'guided':
                original = catalogues['original']
                require(catalog['parent_catalog_sha256'] == result['original']['artifact_sha256']['catalog'] and [(c['id'], c['name']) for c in cats] == [(c['id'], c['name']) for c in original['catalog']] and catalog['task'] == original['task'], 'guided catalog changed IDs/names/order/task')
            require(not set(catalog['discovery_ids']) & held.keys(), 'heldout evidence entered discovery')
            catalogues[condition] = catalog
            records = {}
            for name, mode, split in [('baseline', 'llm', 'heldout'), ('candidate', 'ld', 'heldout'), ('baseline_repeat', 'llm', 'repeat'), ('candidate_repeat', 'ld', 'repeat')]:
                if condition_paths.get(name) is None:
                    require(name == 'candidate_repeat' and summary[name] is None and summary['measurements'][name] is None and hashes[name] is None, 'missing required primary/repeat artifact')
                    continue
                artifact, _ = read(member(run_root, condition_paths[name]), hashes[name])
                reference = hashes['baseline' if mode == 'llm' else 'candidate'] if split == 'repeat' else None
                records[name] = classification(artifact, catalog, catalog_hash, inputs[split], mode, protocol['classifiers'][mode]['model'], runtime, reference)
                require(artifact['measurement'] == summary['measurements'][name], 'analysis measurement differs from artifact')
                require(summary['comparison' if split == 'heldout' else name]['n'] == len(inputs[split]['rows']), 'analysis metric sample count differs')
            review = summary['review']
            require(review is not None, 'missing review accounting')
            bundle, bundle_hash = read(member(run_root, condition_paths['review_bundle']), review['bundle_sha256'])
            artifact, _ = read(member(run_root, condition_paths['review_output']), review['output_sha256'])
            require(artifact['metadata']['bundle_sha256'] == bundle_hash and artifact['metadata']['model'] == models['reviewer'], 'review output bundle/model hash differs')
            reviews[condition] = review_bindings(review, bundle, artifact, catalog, records['baseline'], records['candidate'], inputs['heldout'], plan, runtime)
            eligible = {row['stratum']: row['eligible_count'] for row in bundle['audit']['strata']}
            require(len(eligible) == len(bundle['audit']['strata']) and sum(eligible.values()) == n, 'review eligible denominators differ')
            for row in bundle['audit']['strata']:
                selected_count = sum(key['stratum'] == row['stratum'] for key in reviews[condition][1].values())
                quota = row['eligible_count'] if modality == 'images' else plan['text_quotas'][row['stratum']]
                require(type(row['eligible_count']) is int and row['eligible_count'] >= 0 and row['selected_count'] == selected_count == min(row['eligible_count'], quota), 'review selected/eligible quota accounting differs')
            entry[condition] = dict(catalog=cats, comparison=summary['comparison'], baseline_repeat=summary['baseline_repeat'], candidate_repeat=summary['candidate_repeat'],
                measurements=summary['measurements'], review={**review, 'eligible': eligible})
        entry['task'] = catalogues['original']['task']
        entry['catalog_measurements'] = dict(discovery=catalogues['original']['measurement'], rewrite=catalogues['guided']['measurement'])
        entry['dataset'] = dict(name='CLINC150' if modality == 'text' else 'Open Images validation',
            url='https://github.com/clinc/oos-eval' if modality == 'text' else 'https://storage.googleapis.com/openimages/web/index.html',
            description=manifest['text_selection'] if modality == 'text' else manifest['image_selection']+' '+manifest['image_transform'])
        picks = selected['modalities'][modality]
        require(isinstance(picks['selection_note'], str) and picks['selection_note'].strip() and isinstance(picks['cases'], list) and 1 <= len(picks['cases']) <= 8, 'selection needs a note and1..8 explicit cases per modality')
        seen = set()
        for pick in picks['cases']:
            condition, cid = pick['condition'], pick['case_id']
            require(condition in CONDITIONS and (condition, cid) not in seen and set(pick) <= {'condition', 'case_id', 'alt_evidence_index'}, 'invalid or duplicate selected case')
            seen.add((condition, cid))
            cases, keys, outcomes = reviews[condition]
            require(cid in cases and cid in outcomes and outcomes[cid]['judgment'] is not None and outcomes[cid]['error'] is None, 'selected case has no accepted review')
            case, key, judgment = cases[cid], keys[cid], outcomes[cid]['judgment']
            image = None
            if modality == 'images':
                index = pick.get('alt_evidence_index', 0)
                require(type(index) is int and 0 <= index < len(judgment['evidence']), 'selected alt evidence index is invalid')
                body = inputs['heldout']['images'][key['item_id']]
                filename = f'input-{len(assets)+1:02}.jpg'
                image = example_image(body, manifest['photos'][key['item_id']], filename, prefix, judgment['evidence'][index])
                assets[filename] = (body, image)
            entry['examples'].append(dict(case_id=cid, condition=condition, stratum=key['stratum'], text=case['item']['text'], image=image,
                reference_cluster_id=key['reference_cluster_id'], candidate_cluster_id=key['candidate_cluster_id'], a_is_reference=key['a_is_reference'], judgment=judgment))
        publication['modalities'].append(entry)
    require((analysis['status'] == 'complete') == all(entry[condition]['review']['complete'] for entry in publication['modalities'] for condition in CONDITIONS), 'analysis overall review status differs')
    body = json.dumps(publication, ensure_ascii=False, indent=2, allow_nan=False).encode()+b'\n'
    credits = ['Selected reviewed inputs. JPEG bytes are copied without cropping, resizing or re-encoding.',
               'CLINC150 text: Larson et al.; https://github.com/clinc/oos-eval ; CC BY3.0 https://creativecommons.org/licenses/by/3.0/ .', '']
    for name, (_, photo) in assets.items():
        credits.extend([f'{name}: {photo["title"]} — {photo["author"]}', photo['author_url'], photo['source_url'], f'{photo["license_name"]}: {photo["license_url"]}', f'Changes before model input: {photo["changes"]}', f'Supplied JPEG SHA-256: {photo["sha256"]}', ''])
    output.parent.mkdir(parents=True, exist_ok=True)
    asset_dir.parent.mkdir(parents=True, exist_ok=True)
    created_output = created_assets = False
    try:
        with output.open('xb') as file:
            created_output = True
            asset_dir.mkdir()
            created_assets = True
            for name, (image, _) in assets.items():
                (asset_dir/name).write_bytes(image)
            (asset_dir/'ATTRIBUTION.txt').write_text('\n'.join(credits))
            file.write(body)
    except BaseException:
        if created_output: output.unlink()
        if created_assets: shutil.rmtree(asset_dir)
        raise
    return publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run-root', 'data-root', 'selection', 'repository-commit', 'archive-manifest-sha256', 'output', 'asset-dir'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    try:
        result = export_publication(**vars(args))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({'status': 'exported', 'modalities': len(result['modalities']), 'selected_examples': sum(len(m['examples']) for m in result['modalities'])}))


if __name__ == '__main__':
    main()
