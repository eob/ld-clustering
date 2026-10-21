#!/usr/bin/env python3
"""Offline analyses and bounded selection, consuming independently audited trials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as file:
        json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write('\n')


def design(value):
    return value.get('design', value)


def protocol(root, audit):
    relative = 'preregistration/protocol.json'
    path = root / relative
    digest = sha(path)
    require(audit['evidence_files'].get(relative) == digest == audit['protocol_sha256'],
            'protocol does not match the independent audit')
    return read(path)


def bound_file(root, audit, registered, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root), 'analysis input escapes run-root')
    name = path.relative_to(root).as_posix()
    digest = sha(path)
    fixed_name = name.removeprefix('preregistration/')
    fixed = registered.get('fixed_fixture_sha256', {}).get(fixed_name)
    if name == 'preregistration/review-plan.json':
        require(digest == registered['review_plan_sha256'], 'registered review plan differs')
    expected = audit['evidence_files'].get(name, fixed)
    require(expected is not None and digest == expected,
            'analysis input is not bound to audited or registered bytes: ' + name)
    if fixed is not None:
        require(digest == fixed, 'registered fixture differs: ' + name)
    return path


def audited(root, audit_path):
    audit = read(audit_path)
    require(audit['experiment'] == 'guidance-auto-research' and audit['status'] in
            ('verified', 'verified_with_failed_conditions'), 'independent audit required')
    for relative, digest in audit['evidence_files'].items():
        path = (root / relative).resolve()
        require(path.is_relative_to(root) and sha(path) == digest,
                'audited bytes changed: ' + relative)
    protocol(root, audit)
    return audit


def rank_candidate(name, metrics):
    return (metrics['named_id_agreement_count'], metrics['direct_agreement_count'],
            min(metrics['reference_assigned_count'], metrics['candidate_assigned_count']),
            int(name == 'compact'))


def choose(baseline, candidates):
    """Exact preregistered integer inequalities; no conditional-denominator selection."""
    if baseline is None or not candidates:
        return dict(status='selection_unavailable', adopted=None, challenger=None, ranking=[])
    n = baseline['n']
    require(n > 0, 'nonempty development comparison required')
    ranking = []
    for name, metrics in candidates.items():
        require(name in ('compact', 'boundary') and metrics['n'] == n, 'candidate cohort differs')
        checks = dict(
            named_improved=metrics['named_id_agreement_count'] > baseline['named_id_agreement_count'],
            direct_retained=metrics['direct_agreement_count'] >= baseline['direct_agreement_count'],
            reference_coverage_retained=100 * (baseline['reference_assigned_count'] - metrics['reference_assigned_count']) <= 2 * n,
            candidate_coverage_retained=100 * (baseline['candidate_assigned_count'] - metrics['candidate_assigned_count']) <= 2 * n)
        ranking.append(dict(name=name, eligible=all(checks.values()), checks=checks, metrics=metrics))
    ranking.sort(key=lambda row: rank_candidate(row['name'], row['metrics']), reverse=True)
    eligible = [row for row in ranking if row['eligible']]
    challenger = (eligible or ranking)[0]['name']
    return dict(status='ADOPTED' if eligible else 'NOT_ADOPTED',
                adopted=challenger if eligible else 'baseline', challenger=challenger,
                baseline=baseline, ranking=ranking)


def select(root, audit, audit_path, output):
    registered = protocol(root, audit)
    require(not list((root / 'confirmation').glob('*.json*')), 'selection must precede confirmation outputs')
    require(not any(name.startswith('confirmation-') for name in audit['comparisons']),
            'selection audit already contains confirmation comparisons')
    result = dict(schema_version=1, experiment='guidance-auto-research',
                  frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                  audit_sha256=sha(audit_path), protocol_sha256=audit['protocol_sha256'],
                  dataset_manifest_sha256=audit['dataset_manifest_sha256'], modalities={})
    for modality in ('text', 'images'):
        comparisons = audit['comparisons']
        baseline = comparisons.get(f'r2-{modality}-baseline')
        candidates = {name: comparisons[f'{round_id}-{modality}-{name}']
                      for name, round_id in [('compact', 'r2'), ('boundary', 'r3')]
                      if f'{round_id}-{modality}-{name}' in comparisons}
        selected = choose(baseline, candidates)
        if selected['challenger'] is not None:
            original = bound_file(root, audit, registered, f'catalogs/baseline-{modality}.json')
            source = bound_file(root, audit, registered, f"catalogs/{selected['challenger']}-{modality}.json")
            target = root / f'catalogs/challenger-{modality}.json'
            require(not target.exists(), 'challenger snapshot already exists')
            shutil.copyfile(source, target)
            selected.update(original_catalog=dict(path=str(original.relative_to(root)), sha256=sha(original)),
                            challenger_catalog=dict(path=str(target.relative_to(root)), sha256=sha(target)),
                            producer_catalog=dict(path=str(source.relative_to(root)), sha256=sha(source)))
        result['modalities'][modality] = selected
    write(output, result)
    return result


def calibration(root, audit):
    registered = protocol(root, audit)
    key = {row['id']: row['expected_cluster_id'] for row in read(bound_file(
        root, audit, registered, 'calibration/golden-key.json'))['answers']}
    conditions = read(bound_file(root, audit, registered, 'preregistration/conditions.json'))['conditions']
    results = {}
    for spec in conditions:
        if spec['phase'] != 'calibration':
            continue
        path = bound_file(root, audit, registered, spec['output'])
        arm = read(path)
        if arm['status'] != 'complete':
            results[spec['id']] = dict(status=arm['status'], n=None, correct=None)
            continue
        choices = {row['id']: row['cluster_id'] for row in arm['assignments']}
        require(choices.keys() == key.keys(), 'calibration key/cohort differ')
        order = arm['metadata']['effective_order']
        rows = []
        for point, expected in key.items():
            actual = choices[point]
            expected_position = order.index(expected) if expected is not None else len(order)
            actual_position = order.index(actual) if actual is not None else len(order)
            rows.append(dict(id=point, expected=expected, actual=actual,
                             expected_position=expected_position, actual_position=actual_position,
                             correct=expected == actual))
        correct = sum(row['correct'] for row in rows)
        results[spec['id']] = dict(status='complete', style=spec['description_style'],
                                  cyclic_order=spec['cyclic_order'], mode=spec['mode'],
                                  n=len(rows), correct=correct, accuracy=correct / len(rows), rows=rows)
    grouped = []
    for style in ('short', 'redundant-positive', 'negative-boundaries'):
        for mode in ('llm', 'ld'):
            arms = [row for row in results.values() if row.get('style') == style and row.get('mode') == mode]
            if len(arms) != 4:
                grouped.append(dict(style=style, mode=mode, status='incomplete', n=None, accuracy=None))
                continue
            rows = [point for arm in arms for point in arm['rows']]
            stable = sum(len({next(row['actual'] for row in arm['rows'] if row['id'] == point) for arm in arms}) == 1 for point in key)
            grouped.append(dict(style=style, mode=mode, status='complete', n=len(rows),
                                correct=sum(row['correct'] for row in rows),
                                accuracy=sum(row['correct'] for row in rows) / len(rows),
                                same_choice_in_all_four_orders=stable, distinct_cases=len(key)))
    return dict(schema_version=1, experiment='guidance-auto-research',
                scope='Synthetic constructed-key calibration only; four repeated orders of the same20 cases are dependent. No natural-data accuracy or causal API-defect claim.',
                protocol_sha256=audit['protocol_sha256'], conditions=results, grouped=grouped,
                within_condition_comparisons=audit['comparisons'])


def review_rank(phase, modality, stratum, point):
    return hashlib.sha256(('auto-research-review-v1\0' + '2043\0' + phase + '\0' + modality + '\0' + stratum + '\0' + point).encode()).digest()


def strata(a, b):
    if a is None and b is None:
        return 'both_other'
    if a is None:
        return 'sol_other_native_named'
    if b is None:
        return 'sol_named_native_other'
    return 'equal_named' if a == b else 'different_named'


def sample_review(phase, modality, assignments, quotas):
    buckets = {stratum: [] for stratum in quotas}
    for point, (a, b) in assignments.items():
        buckets[strata(a, b)].append(point)
    selected = []
    counts = {}
    for stratum, quota in quotas.items():
        ranked = sorted(buckets[stratum], key=lambda point: (review_rank(phase, modality, stratum, point), point))
        selected.extend(ranked[:quota])
        counts[stratum] = dict(available=len(ranked), quota=quota, selected=min(quota, len(ranked)))
    selected.sort(key=lambda point: (review_rank(phase, modality, 'presentation', point), point))
    return selected, counts


def packet(root, audit, phase, modality, directory):
    registered = protocol(root, audit)
    require(phase in ('development', 'confirmation') and modality in ('text', 'images'),
            'invalid review phase or modality')
    directory = directory.resolve()
    require(directory.is_relative_to(root), 'review packet must stay within run-root')
    require(not directory.exists(), 'review packet directory must be fresh')
    role = 'compact' if phase == 'development' else 'challenger'
    stem = f'r2-{modality}-compact' if phase == 'development' else f'confirmation-{modality}-challenger'
    require(stem in audit['comparisons'], 'review requires a complete audited comparison')
    base = 'development' if phase == 'development' else 'confirmation'
    arms = [read(bound_file(root, audit, registered, f'{base}/{stem}-{mode}.json')) for mode in ('llm', 'ld')]
    indexed = [{row['id']: row['cluster_id'] for row in arm['assignments']} for arm in arms]
    pairs = {point: (indexed[0][point], indexed[1][point]) for point in indexed[0]}
    plan = read(bound_file(root, audit, registered, 'preregistration/review-plan.json'))
    selected, counts = sample_review(phase, modality, pairs, plan[phase][modality])
    input_path = bound_file(root, audit, registered, f'inputs/{phase}/{modality}.jsonl')
    items = {row['id']: row for row in map(json.loads, input_path.read_text().splitlines())}
    catalog = design(read(bound_file(root, audit, registered, f'catalogs/{role}-{modality}.json')))['definitions']
    instruction = bound_file(root, audit, registered, 'prompts/blinded-review.md').read_text()
    original = None
    original_catalog = None
    if phase == 'confirmation':
        original_stem = f'confirmation-{modality}-baseline'
        require(original_stem in audit['comparisons'], 'confirmation review requires audited original pair')
        original = [{row['id']: row['cluster_id'] for row in read(bound_file(
            root, audit, registered, f'{base}/{original_stem}-{mode}.json'))['assignments']} for mode in ('llm', 'ld')]
        original_catalog = design(read(bound_file(root, audit, registered,
                                                  f'catalogs/baseline-{modality}.json')))['definitions']
    image_sources = {}
    if modality == 'images':
        for point in selected:
            source = (input_path.parent / items[point]['image']).resolve()
            require(source.is_relative_to(root), 'review image must be audited within run-root')
            image_sources[point] = bound_file(root, audit, registered, source.relative_to(root))
    cases, keys = [], []
    for point in selected:
        case_id = review_rank(phase, modality, 'case', point).hex()[:24]
        item = items[point]
        case = dict(case_id=case_id, text=item['text'], catalog=catalog, pairs=[])
        key = dict(case_id=case_id, item_id=point, stratum=strata(*pairs[point]), pairs=[])
        if modality == 'images':
            source = image_sources[point]
            expected_sha = audit['evidence_files'].get(source.relative_to(root).as_posix())
            require(expected_sha is not None, 'review image bytes were not independently audited')
            target = directory / 'images' / f'{case_id}.jpg'
            target.parent.mkdir(parents=True, exist_ok=True)
            require(not target.exists(), 'review image already exists')
            shutil.copyfile(source, target)
            require(sha(target) == expected_sha, 'review image copy differs from audited bytes')
            case['image'] = str(target.relative_to(root))
            case['image_sha256'] = sha(target)
        presentations = [('compact-pair' if phase == 'development' else 'challenger-pair', catalog, pairs[point])]
        if original is not None:
            presentations.append(('original-pair', original_catalog, (original[0][point], original[1][point])))
        for pair_role, definitions, choices in presentations:
            swap = review_rank(phase, modality, 'blind:' + pair_role, point)[0] >= 128
            order = (1, 0) if swap else (0, 1)
            case['pairs'].append(dict(pair_id=len(case['pairs']) + 1, catalog=definitions,
                                      assignments={label: choices[who] for label, who in zip(('A', 'B'), order)}))
            key['pairs'].append(dict(role=pair_role, A=('llm', 'ld')[order[0]], B=('llm', 'ld')[order[1]]))
        cases.append(case)
        keys.append(key)
    directory.mkdir(parents=True, exist_ok=True)
    write(directory / 'packet.json', dict(schema_version=1, phase=phase, modality=modality,
                                         instruction=instruction, cases=cases))
    write(directory / 'key.json', dict(schema_version=1, phase=phase, modality=modality,
                                      counts=counts, keys=keys, audit_comparison=stem))
    return dict(selected=len(cases), counts=counts, packet_sha256=sha(directory / 'packet.json'), key_sha256=sha(directory / 'key.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('calibration', 'selection', 'review-packet'))
    for name in ('run-root', 'audit', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--phase', choices=('development', 'confirmation'))
    parser.add_argument('--modality', choices=('text', 'images'))
    args = parser.parse_args()
    root = args.run_root.resolve()
    evidence = audited(root, args.audit)
    if args.command == 'selection':
        select(root, evidence, args.audit, args.output)
    elif args.command == 'calibration':
        result = calibration(root, evidence)
        result['audit_sha256'] = sha(args.audit)
        write(args.output, result)
    else:
        require(args.phase is not None and args.modality is not None, 'review phase and modality required')
        print(json.dumps(packet(root, evidence, args.phase, args.modality, args.output)))


if __name__ == '__main__':
    main()
