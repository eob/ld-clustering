#!/usr/bin/env python3
"""Copy independently audited terminal streams into the public report.

Verify the archive separately with archive_guided_agreement.py first. This
copier binds the indexed file identities; it does not decompress payloads,
compute scientific metrics, or contact a provider.
"""
import argparse
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3

EXPERIMENT = 'experiments/2026-10-20-guided-agreement-seed1042'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def pin(value, length=64):
    require(isinstance(value, str) and re.fullmatch(f'[0-9a-f]{{{length}}}', value), 'invalid immutable pin')
    return value


def member(root, name):
    path = (root / name).resolve()
    require(root.resolve() in path.parents, 'evidence path escapes root')
    return path


def number(value, name, fraction=False):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, f'invalid {name}')
    require(not fraction or value <= 1, f'invalid fraction: {name}')
    return value


def money(value):
    require(isinstance(value, str), 'cost must retain audited Decimal text')
    amount = Decimal(value)
    require(amount.is_finite() and amount >= 0, 'invalid audited cost')
    return value


def cost_fields(value):
    require(type(value['cost_complete']) is bool, 'missing cost completeness')
    known = money(value['known_cost_usd'])
    total = value['total_cost_usd']
    require((total is not None) == value['cost_complete'], 'complete cost/total mismatch')
    if total is not None:
        require(money(total) == known, 'audited cost total differs from known charges')
    return {'known_cost_usd': known, 'total_cost_usd': total, 'cost_complete': value['cost_complete']}


def arm_publication(arm, expected):
    require(type(arm['complete']) is bool and type(arm['exit_code']) is int, 'invalid terminal arm')
    require(arm['expected_count'] == expected, 'arm count differs')
    if arm['persisted_count'] is None:
        require(not arm['complete'] and arm['exit_code'] != 0 and arm.get('unknown_dispatch_history') is True, 'missing state must remain explicitly unknown')
        require(all(arm[key] is None for key in ('measurement', 'catalog', 'coverage')) and not arm['cost_complete'], 'unknown state contains asserted measurements')
        return {
            'complete': False, 'exit_code': arm['exit_code'], 'persisted_count': None,
            'expected_count': expected, 'coverage': None, **cost_fields(arm),
            'wall_seconds': None, 'timing_complete': False, 'calls': None,
            'error_calls': None, 'retry_attempts': None, 'refusal_attempts': None,
            'reassignment': None, 'catalog': None, 'unknown_dispatch_history': True,
        }
    require(type(arm['persisted_count']) is int and 0 <= arm['persisted_count'] <= expected, 'arm count differs')
    if arm['complete']:
        require(arm['exit_code'] == 0 and arm['persisted_count'] == expected and arm['pending_reassignments'] == 0, 'complete arm has incomplete evidence')
        coverage = number(arm['coverage'], 'coverage', fraction=True)
    else:
        require(arm['coverage'] is None, 'partial prefix must not become primary coverage')
        coverage = None
    measured = arm['measurement']
    require(type(measured['timing_complete']) is bool, 'missing timing completeness')
    wall = measured['wall_seconds']
    if wall is not None:
        number(wall, 'wall seconds')
    counts = {key: arm[key] for key in ('calls', 'error_calls', 'retry_attempts')}
    counts['refusal_attempts'] = arm['raw_refusal_attempts']
    moves = {key: arm['reassignment'][key] for key in ('evaluations', 'id_moves', 'unchanged', 'origin_unknown')}
    require(all(type(value) is int and value >= 0 for value in (*counts.values(), *moves.values())), 'invalid work counters')
    require(moves['evaluations'] == moves['id_moves'] + moves['unchanged'] + moves['origin_unknown'], 'reassignment accounting differs')
    catalog = [{key: category[key] for key in ('id', 'name', 'description')} for category in arm['catalog']]
    require(len({category['id'] for category in catalog}) == len(catalog), 'duplicate active category')
    require(all(type(category['id']) is int and category['id'] > 0 and all(isinstance(category[key], str) and category[key].strip() for key in ('name', 'description')) for category in catalog), 'invalid active catalog')
    return {
        'complete': arm['complete'], 'exit_code': arm['exit_code'],
        'persisted_count': arm['persisted_count'], 'expected_count': expected,
        'coverage': coverage, **cost_fields(arm),
        'wall_seconds': wall, 'timing_complete': measured['timing_complete'],
        **counts, 'reassignment': moves, 'catalog': catalog,
    }


def publication(audit, protocol, source, launched_at, finished_at):
    require(audit['schema_version'] == 1 and audit['status'] in ('verified', 'verified_with_partial_streams'), 'terminal independent audit required')
    names = {f'{modality}-{policy}-{backend}' for modality in ('text', 'images') for policy in ('original', 'contextual') for backend in ('llm', 'ld')}
    require(set(audit['arms']) == names, 'exactly eight registered arms required')
    all_complete = all(arm['complete'] for arm in audit['arms'].values())
    require((audit['status'] == 'verified') == all_complete, 'audit completion status differs')
    comparisons = {(row['modality'], row['policy']): row for row in audit['comparisons']}
    require(len(audit['comparisons']) == len(comparisons) == 4, 'four unique policy comparisons required')
    modalities = []
    for modality in ('text', 'images'):
        n = protocol['modalities'][modality]['expected_count']
        require(n == (1000 if modality == 'text' else 100), 'registered sample count differs')
        result = {'modality': modality, 'n': n}
        for policy in ('original', 'contextual'):
            llm, ld = [arm_publication(audit['arms'][f'{modality}-{policy}-{backend}'], n) for backend in ('llm', 'ld')]
            pair = comparisons[modality, policy]
            complete = llm['complete'] and ld['complete']
            require(pair['complete'] == complete, 'pair completion differs from arms')
            comparison = pair['comparison']
            if complete:
                require(comparison is not None and all(comparison[key]['n'] == n for key in ('agreement', 'shared_other_sensitivity')), 'full registered comparison required')
                require(set(comparison['assigned_other']) == {'both_named', 'baseline_named_ld_other', 'baseline_other_ld_named', 'both_other'} and all(type(value) is int and value >= 0 for value in comparison['assigned_other'].values()) and sum(comparison['assigned_other'].values()) == n, 'assigned/Other cells differ from full denominator')
            else:
                require(comparison is None, 'partial pair cannot publish a primary comparison')
            result[policy] = {'complete': complete, 'comparison': comparison, 'llm': llm, 'ld': ld}
        modalities.append(result)
    accounting = cost_fields(audit['cost_summary'])
    require(accounting['cost_complete'] == all(arm['cost_complete'] for arm in audit['arms'].values()), 'overall accounting differs from arms')
    for value in (launched_at, finished_at):
        require(datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None, 'timestamps must retain timezone')
    return {'schema_version': 1, 'status': 'complete' if all_complete else 'partial', 'source': source,
            'launched_at': launched_at, 'finished_at': finished_at, 'accounting': accounting, 'modalities': modalities}


def selected_photo_review(stage, audit, data_root, dataset_hash):
    folder = 'qualitative/photos/'
    names = ('blinded-input.json', 'review.json', 'provenance.json', 'unblinding-and-selection.json', 'report-selection.json')
    require(all(folder + name in audit['evidence_files'] for name in names), 'photo review evidence is not audited')
    bodies = {name: member(stage, folder + name).read_bytes() for name in names}
    packet, review, provenance, key, selection = [json.loads(bodies[name]) for name in names]
    require(all(value['schema_version'] == 1 for value in (packet, review, provenance, key, selection)), 'photo review schema differs')
    require(selection['review_sha256'] == sha(bodies['review.json']), 'sealed photo review differs')
    require(review['blinded'] is True and review['packet_sha256'] == provenance['packet_sha256'] == sha(bodies['blinded-input.json']), 'blinded packet binding differs')
    require(provenance['blinded_at_review'] is True and provenance['unblinding_read'] is False and provenance['human_validation'] is False and provenance['population_accuracy_claim'] is False and provenance['experiment_model_api_calls'] == 0 and provenance['coding_harness_compute_in_experiment_ledger'] is False, 'photo reviewer scope differs')
    require(isinstance(provenance['reviewer'], str) and provenance['reviewer'].strip(), 'missing photo reviewer')
    identities = key['catalog_identity']
    arms = {f'images-{policy}-{backend}' for policy in ('original', 'contextual') for backend in ('llm', 'ld')}
    require(set(identities) == set('ABCD') and set(identities.values()) == arms and set(packet['catalogs']) == set('ABCD'), 'anonymous catalog identities differ')
    for letter, arm in identities.items():
        require(audit['arms'][arm]['complete'] and packet['catalogs'][letter] == audit['arms'][arm]['catalog'], 'review catalog differs from audited final catalog')
    cases = {case['item_id']: case for case in packet['cases']}
    judgments = {case['item_id']: case for case in review['cases']}
    reviewed = {case['item_id']: case for case in provenance['reviewed_images']}
    require(len(cases) == len(packet['cases']) == len(judgments) == len(review['cases']) == len(reviewed) == len(provenance['reviewed_images']) == provenance['reviewed_image_count'] and cases.keys() == judgments.keys() == reviewed.keys() == key['selection'].keys(), 'photo case inventory differs')
    require(len({case['case_id'] for case in cases.values()}) == len(cases), 'duplicate photo case ID')
    manifest_body = (data_root / 'manifest.json').read_bytes()
    require(sha(manifest_body) == dataset_hash, 'photo dataset manifest differs')
    manifest = json.loads(manifest_body)
    prefix = selection['asset_url_prefix'].rstrip('/')
    require(prefix.startswith('/') and not prefix.startswith('//') and '..' not in PurePosixPath(prefix).parts and not any(c in prefix for c in ('?', '#', '\\')), 'invalid photo asset URL prefix')
    picks = selection['cases']
    require(isinstance(selection['selection_note'], str) and selection['selection_note'].strip() and len(picks) == 4 and len({pick['item_id'] for pick in picks}) == 4, 'four explicit curated photo cases required')
    helper_path = Path(__file__).with_name('export_guided_agreement.py')
    helper = {'__name__': 'guided_photo_export_helper', '__file__': str(helper_path)}
    exec(compile(helper_path.read_bytes(), str(helper_path), 'exec'), helper)
    examples, assets = [], {}
    for pick in picks:
        item = pick['item_id']
        require(item in cases and re.fullmatch(r'[A-Za-z0-9_-]+', item) is not None, 'selected photo case is missing or invalid')
        case, judgment, receipt = cases[item], judgments[item], reviewed[item]
        require(all(value['case_id'] == case['case_id'] and value['image_sha256'] == case['image_sha256'] for value in (judgment, receipt)), 'reviewed photo identity differs')
        require(set(case['assignments']) == set(judgment['assessments']) == set('ABCD'), 'four anonymous assignments required')
        require(isinstance(judgment['visible_subject'], str) and judgment['visible_subject'].strip(), 'photo judgment text is missing')
        for name in ('literal_evidence', 'themes', 'uncertainty'):
            require(isinstance(judgment[name], list) and all(isinstance(value, str) and value.strip() for value in judgment[name]), 'photo judgment evidence differs')
        index = pick['alt_evidence_index']
        require(type(index) is int and 0 <= index < len(judgment['literal_evidence']), 'selected photo alt evidence index differs')
        assignments = []
        for letter in 'ABCD':
            arm, assessment = identities[letter], judgment['assessments'][letter]
            catalog = {category['id']: category for category in packet['catalogs'][letter]}
            cluster = case['assignments'][letter]
            require(cluster is None or type(cluster) is int and cluster in catalog, 'photo assignment ID is not in own catalog')
            name = 'Other' if cluster is None else catalog[cluster]['name']
            require(assessment['assigned_cluster_id'] == cluster and assessment['assigned_category'] == name, 'reviewed photo assignment differs')
            require(assessment['fit'] in ('supported', 'plausible', 'unsupported', 'unclear') and assessment['severity'] in ('none', 'minor', 'major', 'unclear') and isinstance(assessment['reason'], str) and assessment['reason'].strip(), 'invalid photo judgment')
            nearest = assessment['nearest_alternative']
            if nearest is not None:
                alternative = nearest['cluster_id']
                require((alternative is None or type(alternative) is int and alternative in catalog) and nearest['category'] == ('Other' if alternative is None else catalog[alternative]['name']) and nearest['fit'] in ('supported', 'plausible', 'unsupported', 'unclear') and isinstance(nearest['reason'], str) and nearest['reason'].strip(), 'photo alternative is not in own catalog')
            database_name = f'{arm}/state.sqlite'
            require(database_name in audit['evidence_files'], 'photo assignment database is not audited')
            with closing(sqlite3.connect(member(stage, database_name).as_uri() + '?mode=ro&immutable=1', uri=True)) as database:
                saved = database.execute('SELECT cluster_id FROM assignments WHERE point_id=?', (item,)).fetchone()
            require(saved is not None and saved[0] == cluster, 'photo assignment differs from audited database')
            assignments.append({'anonymous_id': letter, 'arm': arm, 'cluster_id': cluster, 'category': name, **{name: assessment[name] for name in ('fit', 'reason', 'severity', 'nearest_alternative')}})
        image_name = f'images/{item}.jpg'
        body = member(data_root, image_name).read_bytes()
        require(audit['input_files'].get(image_name) == {'sha256': sha(body), 'bytes': len(body)}, 'selected photo differs from audited input')
        photo = manifest['photos'][item]
        require(sha(body) == photo['supplied_sha256'] == case['image_sha256'], 'selected photo byte hash differs')
        width, height = photo['supplied_width'], photo['supplied_height']
        native_width, native_height = photo['native_width'], photo['native_height']
        require(all(type(value) is int and value > 0 for value in (width, height, native_width, native_height)) and native_width >= width and native_height >= height and abs(native_width * height - native_height * width) <= native_width + native_height, 'selected photo aspect differs or implies upscaling')
        require(isinstance(photo['transform'], str) and photo['transform'].strip(), 'missing photo change description')
        filename = f'input-{len(assets)+1:02}.jpg'
        image = helper['example_image'](body, photo, filename, prefix, judgment['literal_evidence'][index])
        require(all(image[name].startswith('https://') for name in ('author_url', 'source_url', 'license_url')), 'invalid photo attribution URL')
        assets[filename] = (body, image)
        examples.append({name: judgment[name] for name in ('case_id', 'item_id', 'visible_subject', 'literal_evidence', 'themes', 'uncertainty')} | {'image': image, 'assignments': assignments})
    return {'schema_version': 1, 'selection_note': selection['selection_note'], 'reviewer': provenance['reviewer'],
            'packet_sha256': sha(bodies['blinded-input.json']), 'review_sha256': sha(bodies['review.json']),
            'provenance_sha256': sha(bodies['provenance.json']), 'selection_sha256': sha(bodies['report-selection.json']),
            'unblinding_sha256': sha(bodies['unblinding-and-selection.json']),
            'catalogs': {identities[letter]: packet['catalogs'][letter] for letter in 'ABCD'}, 'examples': examples}, assets


def export_publication(stage, audit_path, archive, archive_manifest_sha256, repository_commit, data_root=None, asset_dir=None):
    stage, audit_path, archive = [Path(path).resolve() for path in (stage, audit_path, archive)]
    pin(repository_commit, 40)
    manifest_body = (archive / 'manifest.json').read_bytes()
    require(sha(manifest_body) == pin(archive_manifest_sha256), 'archive manifest pin differs')
    manifest = json.loads(manifest_body)
    archived = manifest['payloads']['run']['files']
    audit_body = audit_path.read_bytes()
    require(stage in audit_path.parents, 'audit must belong to stream stage')
    audit_name = str(audit_path.relative_to(stage))
    require(archived[audit_name]['sha256'] == sha(audit_body), 'archived audit differs')
    audit = json.loads(audit_body)
    for name, expected in audit['evidence_files'].items():
        body = member(stage, name).read_bytes()
        actual = {'sha256': sha(body), 'bytes': len(body)}
        require(actual == expected, f'audited stream evidence changed: {name}')
        require(all(archived[name][key] == value for key, value in actual.items()), f'archived evidence differs: {name}')
    protocol_name = 'preregistration/protocol.json'
    require(protocol_name in audit['evidence_files'] and 'finished-at.txt' in audit['evidence_files'], 'terminal preregistration evidence missing')
    protocol_body = (stage / protocol_name).read_bytes()
    protocol = json.loads(protocol_body)
    plan = json.loads((stage / 'run-plan.json').read_bytes())
    require(audit['source_commit'] == plan['source_commit'] == manifest['primary_runtime']['source_commit'], 'stream runtime source differs')
    require(audit['binary']['sha256'] == plan['binary_sha256'] == manifest['primary_runtime']['binary_sha256'], 'stream runtime binary differs')
    require(protocol['dataset_manifest_sha256'] == manifest['dataset_manifest_sha256'], 'archived selected inputs differ')
    source = {
        'repository': 'https://github.com/eob/ld-clustering', 'commit': repository_commit,
        'runtime_commit': pin(audit['source_commit'], 40), 'executable_sha256': pin(plan['binary_sha256']),
        'run_path': EXPERIMENT + '/streaming-evidence', 'manifest_sha256': archive_manifest_sha256,
        'protocol_sha256': sha(protocol_body), 'audit_sha256': sha(audit_body),
        'dataset_manifest_sha256': pin(protocol['dataset_manifest_sha256']),
    }
    result = publication(audit, protocol, source, (stage / 'launched-at.txt').read_text().strip(), (stage / 'finished-at.txt').read_text().strip())
    for modality in result['modalities']:
        name = f'posthoc/{modality["modality"]}-common-named.json'
        if (stage / name).is_file():
            helpers = ('reproduction/analyze_common_named.py', 'reproduction/verify_guided_streaming.py')
            require(all(path in audit['evidence_files'] for path in (name, *helpers)), 'common-named subset and helpers must be audited')
            subset = json.loads((stage / name).read_bytes())
            n = subset['conditional_n']
            require(subset['schema_version'] == 1 and subset['status'] == 'complete' and subset['scope'] == 'post_hoc_common_named_subset' and subset['modality'] == modality['modality'] and subset['full_n'] == modality['n'], 'common-named subset scope differs')
            require(subset['source_commit'] == source['runtime_commit'] and subset['verifier_sha256'] == sha((stage / helpers[1]).read_bytes()), 'common-named subset source/helper pin differs')
            require(modality['original']['complete'] and modality['contextual']['complete'] and type(n) is int and 0 <= n <= modality['n'] and len(subset['selected_item_ids']) == len(set(subset['selected_item_ids'])) == n and all(isinstance(item, str) and item for item in subset['selected_item_ids']), 'common-named subset denominator differs')
            require(set(subset['partition_by_policy']) == {'original', 'contextual'} and all((score is None and n == 0) or score is not None and score['n'] == n for score in subset['partition_by_policy'].values()), 'common-named subset score denominator differs')
            require(isinstance(subset['selection_note'], str) and subset['selection_note'].strip(), 'common-named subset needs a selection caveat')
            modality['common_named_subset'] = subset
    require((data_root is None) == (asset_dir is None), 'photo data root and asset directory must be supplied together')
    if data_root is not None:
        asset_dir = Path(asset_dir)
        require(not asset_dir.exists(), 'photo asset directory must be fresh')
        review, assets = selected_photo_review(stage, audit, Path(data_root).resolve(), source['dataset_manifest_sha256'])
        credits = ['Four post hoc qualitative examples. Exact supplied JPEG bytes; no further crop, resize or re-encoding.', 'Automated same-family coding-harness review is not human truth; reviewer compute is outside the experiment API ledger.', '']
        for name, (_, image) in assets.items():
            credits.extend([f'{name}: {image["title"]} — {image["author"]}', image['author_url'], image['source_url'], f'{image["license_name"]}: {image["license_url"]}', f'Changes before model input: {image["changes"]}', f'Supplied JPEG SHA-256: {image["sha256"]}', ''])
        asset_dir.parent.mkdir(parents=True, exist_ok=True)
        asset_dir.mkdir()
        try:
            for name, (body, _) in assets.items():
                (asset_dir / name).write_bytes(body)
            (asset_dir / 'ATTRIBUTION.txt').write_text('\n'.join(credits))
        except BaseException:
            shutil.rmtree(asset_dir)
            raise
        result['photo_review'] = review
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stage-root', 'audit', 'archive-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--archive-manifest-sha256', required=True)
    parser.add_argument('--repository-commit', required=True)
    parser.add_argument('--data-root', type=Path, help='Opt in to the sealed four-photo illustration export')
    parser.add_argument('--asset-dir', type=Path, help='Fresh destination for exact supplied JPEGs and credits')
    args = parser.parse_args()
    require(not args.output.exists(), 'output must be fresh')
    require((args.data_root is None) == (args.asset_dir is None), 'photo data root and asset directory must be supplied together')
    if args.asset_dir is not None:
        require(args.output.resolve() != args.asset_dir.resolve() and args.output.resolve() not in args.asset_dir.resolve().parents and args.asset_dir.resolve() not in args.output.resolve().parents, 'output JSON and photo assets must be separate paths')
    value = export_publication(args.stage_root, args.audit, args.archive_root, args.archive_manifest_sha256, args.repository_commit, args.data_root, args.asset_dir)
    created_output = False
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as file:
            created_output = True
            json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write('\n')
    except BaseException:
        if created_output: args.output.unlink()
        if args.asset_dir is not None: shutil.rmtree(args.asset_dir)
        raise


if __name__ == '__main__':
    main()
