#!/usr/bin/env python3
"""Freeze and supervise only preregistered Rust auto-research invocations."""
import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

EXPERIMENT = 'guidance-auto-research'
STUDY = '2026-10-21-auto-research-seed2043'
PRIOR_NAMES = ['v2-text'] + [f'guided-{split}-{modality}'
    for split in ('discovery', 'heldout', 'streaming') for modality in ('text', 'images')]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        while block := file.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())


def member(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
            and '..' not in Path(relative).parts, 'path must be portable and run-relative')
    path = (root / relative).resolve()
    require(path.is_relative_to(root), 'path escapes run-root')
    return path


def pin(root, relative, expected=None):
    path = member(root, relative)
    digest = sha(path)
    require(expected is None or digest == expected, 'frozen bytes changed: ' + relative)
    return dict(path=relative, sha256=digest)


def git(repo, *arguments):
    return subprocess.check_output(['git', *arguments], cwd=repo, text=True,
                                  env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}).strip()


def command_json(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    require(result.returncode == 0, 'offline Rust preflight failed: ' + result.stderr[-4000:])
    return json.loads(result.stdout)


def source_pins(args):
    repo = args.source_repo
    require(git(repo, 'branch', '--show-current').startswith('feat-'), 'feature branch required')
    source = command_json([str(args.binary), 'source-pins'], args.run_root)
    require(source.get('committed_sources_verified') is True
            and source.get('commit') == git(repo, 'rev-parse', 'HEAD')
            and source.get('executable_sha256') == sha(args.binary), 'Rust source/executable pins differ')
    hashes = source.get('embedded_file_sha256')
    require(isinstance(hashes, dict) and {'src/auto_research.rs', 'examples/auto_research.rs',
            'src/provider.rs', 'src/lib.rs'} <= set(hashes), 'missing embedded runtime sources')
    names = {**hashes, 'scripts/run_auto_research.py': sha(Path(__file__))}
    names.update({str(path.relative_to(repo)): sha(path) for path in args.fixtures.rglob('*') if path.is_file()})
    for name, digest in names.items():
        blob = subprocess.check_output(['git', 'show', source['commit'] + ':' + name], cwd=repo)
        require(hashlib.sha256(blob).hexdigest() == digest == sha(repo / name),
                'source/fixture differs from immutable commit: ' + name)
    return source


def input_pin(root, relative, modality):
    path = member(root, relative)
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    require(rows and len({row['id'] for row in rows}) == len(rows), 'empty or duplicate input IDs')
    digest = hashlib.sha256(b'ld-clustering-input-v1\0' + struct.pack('<Q', len(raw)) + raw)
    images = []
    for row in rows:
        require(isinstance(row.get('id'), str) and row['id'] and isinstance(row.get('text'), str)
                and (row.get('image') is not None) == (modality == 'images'), 'input modality/identity differs')
        if modality == 'images':
            image = row['image']
            require(isinstance(image, str) and not image.startswith(('http:', 'https:', 'data:')),
                    'images must be pinned local files')
            image_path = (path.parent / image).resolve()
            require(image_path.is_relative_to(root), 'input image escapes run-root')
            body = image_path.read_bytes()
            digest.update(b'local-image\0' + struct.pack('<Q', len(body)) + body)
            images.append(dict(id=row['id'], sha256=hashlib.sha256(body).hexdigest(),
                               path=str(image_path.relative_to(root))))
    frozen = pin(root, relative)
    frozen.update(input_sha256=digest.hexdigest(), ordered_ids=[row['id'] for row in rows],
                  images=[dict(id=image['id'], sha256=image['sha256']) for image in images])
    return frozen, rows, images


def design(root, relative):
    value = read(member(root, relative))
    if 'design' in value:
        require(value.get('experiment') == EXPERIMENT and value.get('stage') == 'custom_rewrite'
                and value.get('status') == 'complete' and value.get('error') is None,
                'adaptive catalog must be a complete custom rewrite')
        value = value['design']
    require(value.get('schema_version') == 1 and value.get('modality') in ('text', 'images')
            and isinstance(value.get('task'), str) and value['task'].strip()
            and isinstance(value.get('provenance'), dict) and value['provenance'], 'invalid design')
    definitions = value['definitions']
    ids = [row['id'] for row in definitions]
    require(1 <= len(ids) <= 16 and all(type(i) is int and i > 0 for i in ids)
            and ids == sorted(set(ids)), 'invalid canonical catalog IDs')
    require(all(row['name'].strip() and row['description'].strip() for row in definitions)
            and len({row['name'].strip().lower() for row in definitions}) == len(ids)
            and all(row['name'].strip().lower() != 'other' for row in definitions), 'invalid catalog definitions')
    return value


def validate_boundary_evidence(root, modality, rows, frozen, adaptive, catalog):
    old_pin, old_rows, _ = input_pin(root, 'discovery/' + modality + '.jsonl', modality)
    dev_pin, dev_rows, _ = input_pin(root, 'inputs/development/' + modality + '.jsonl', modality)
    manifest = read(member(root, 'preregistration/dataset-manifest.json'))
    expected = manifest['partitions']['development'][modality]
    previous = read(member(root, 'preregistration/prior-dataset-manifest.json'))
    require(dev_pin['sha256'] == expected['jsonl_sha256']
            and old_pin['sha256'] == previous['partitions']['discovery'][modality]['jsonl_sha256'],
            'development/discovery bytes changed')
    for frozen_input, source_manifest in ((old_pin, previous), (dev_pin, manifest)):
        require(all(image['sha256'] == source_manifest['photos'][image['id']]['supplied_sha256']
                    for image in frozen_input['images']), 'frozen generation source photograph changed')
    by_role = {ref['role']: ref for ref in adaptive}
    key = read(member(root, by_role['key:' + modality]['path']))
    packet = read(member(root, by_role['packet:' + modality]['path']))
    require(key.get('phase') == packet.get('phase') == 'development'
            and key.get('modality') == packet.get('modality') == modality,
            'boundary review packet identity differs')
    selected = [entry['item_id'] for entry in key['keys']]
    require(len(selected) == len(set(selected)) <= (20 if modality == 'text' else 12),
            'boundary selected IDs duplicate or exceed quota')
    old_ids = {row['id'] for row in old_rows}
    require(not old_ids & set(selected) and set(frozen['ordered_ids']) == old_ids | set(selected),
            'generation IDs differ from discovery plus exact sealed review selection')
    dev = {row['id']: row for row in dev_rows}
    require(set(selected) <= set(dev), 'review selected a non-development item')
    require(len(packet['cases']) == len(key['keys'])
            and {case['case_id'] for case in packet['cases']} == {entry['case_id'] for entry in key['keys']},
            'review packet/key case identities differ')
    all_rows = {row['id']: row for row in old_rows + dev_rows}
    expected_images = {image['id']: image['sha256'] for image in old_pin['images'] + dev_pin['images']}
    actual_images = {image['id']: image['sha256'] for image in frozen['images']}
    for row in rows:
        original = all_rows[row['id']]
        require(row['text'] == original['text'] and row.get('label') == original.get('label')
                and actual_images.get(row['id']) == expected_images.get(row['id']),
                'generation row changed frozen text/label/image bytes under a retained ID')
    cases = {case['case_id']: case for case in packet['cases']}
    for entry in key['keys']:
        case = cases[entry['case_id']]
        require(case['text'] == dev[entry['item_id']]['text'], 'review text differs from selected development item')
        require(all(pair['catalog'] == catalog['definitions'] for pair in case['pairs']),
                'review uses a different parent catalog')
        if modality == 'images':
            require(case['image_sha256'] == expected_images[entry['item_id']]
                    == sha(member(root, case['image'])), 'review photograph differs from selected development bytes')


def make_argv(binary, root, spec, dry=False):
    argv = [str(binary), 'classify' if spec['kind'] == 'classify' else 'rewrite']
    paths = ['input', 'catalog', 'order', 'instructions']
    for key in paths:
        if key in spec:
            argv += ['--' + key, str(member(root, spec[key]['path']))]
    argv += ['--protocol', str(member(root, 'preregistration/protocol.json'))]
    for key in ('stage', 'mode', 'k') if spec['kind'] == 'classify' else ('parent_sha256', 'design_id'):
        argv += ['--' + key.replace('_', '-'), str(spec[key])]
    argv += ['--expected', str(spec['expected_count'])]
    for key in ('log', 'output'):
        argv += ['--' + key, str(member(root, spec[key]))]
    if dry:
        argv.append('--dry-run')
    return argv


def prepare(args):
    args.run_root = Path(args.run_root).resolve()
    args.source_repo = Path(args.source_repo).resolve()
    args.fixtures = Path(args.fixtures).resolve()
    args.binary = Path(args.binary).resolve()
    root = args.run_root
    require(root.is_dir() and args.binary.is_file() and os.access(args.binary, os.X_OK),
            'portable run root and frozen executable required')
    protocol_spec = pin(root, 'preregistration/protocol.json', sha(args.fixtures / 'protocol.json'))
    protocol = read(member(root, protocol_spec['path']))
    require(protocol.get('schema_version') == 1 and protocol.get('experiment') == EXPERIMENT,
            'invalid protocol header')
    registry_spec = pin(root, 'preregistration/conditions.json', protocol['conditions_sha256'])
    require(registry_spec['sha256'] == sha(args.fixtures / 'conditions.json'), 'condition registry differs from source')
    registry = read(member(root, registry_spec['path']))
    require(registry.get('schema_version') == 1 and registry.get('experiment') == EXPERIMENT
            and args.phase in registry['phase_order'], 'unregistered phase')
    require(not member(root, 'registrations/' + args.phase).exists(), 'phase registration already exists; never rerun')
    selected = [row for row in registry['conditions'] if row['phase'] == args.phase]
    require(selected and len({row['id'] for row in registry['conditions']}) == len(registry['conditions']),
            'empty phase or duplicate condition IDs')
    source = source_pins(args)
    dataset_spec = pin(root, 'preregistration/dataset-manifest.json', protocol['data']['dataset_manifest_sha256'])
    dataset = read(member(root, dataset_spec['path']))
    prior_dataset_spec = pin(root, 'preregistration/prior-dataset-manifest.json', dataset['prior_dataset_manifest_sha256'])
    prior_dataset = read(member(root, prior_dataset_spec['path']))
    prior_inputs = []
    for name in PRIOR_NAMES:
        modality = 'images' if name.endswith('-images') else 'text'
        if name == 'v2-text':
            expected = dataset['previous_text_sha256']
        else:
            _, split, _ = name.split('-')
            expected = prior_dataset['partitions'][split][modality]['jsonl_sha256']
        prior_inputs.append(dict(**pin(root, 'prior-inputs/' + name + '.jsonl', expected),
                                 modality=modality, role=name))
    adaptive = []
    if args.adaptive_registration is not None:
        path = Path(args.adaptive_registration).resolve()
        require(path.is_relative_to(root), 'adaptive registration must be inside run-root')
        adaptive = read(path)
        require(isinstance(adaptive, list) and len({ref['role'] for ref in adaptive}) == len(adaptive),
                'adaptive references must have distinct roles')
        adaptive = [dict(**pin(root, ref['path'], ref['sha256']), role=ref['role']) for ref in adaptive]
    required_roles = set()
    if args.phase == 'round3-generation':
        required_roles = {role + ':' + modality for role in ('packet', 'key', 'judgments') for modality in ('text', 'images')}
    if args.phase in ('confirmation', 'repeats'):
        required_roles = {'selection'}
    require(required_roles <= {ref['role'] for ref in adaptive}, 'missing required frozen adaptive references')
    conditions, preflights, image_files = [], {}, {}
    for allowed in selected:
        require(allowed['kind'] in ('classification', 'rewrite'), 'unknown registered condition kind')
        spec = {key: allowed[key] for key in ('id', 'round', 'phase', 'stage', 'modality', 'mode', 'output', 'log', 'progress')}
        spec['kind'] = 'classify' if allowed['kind'] == 'classification' else 'custom_rewrite'
        require(allowed['command'] == ('classify' if spec['kind'] == 'classify' else 'rewrite'), 'registered command differs')
        frozen, rows, images = input_pin(root, allowed['input'], spec['modality'])
        require(allowed.get('input_jsonl_sha256') in (None, frozen['sha256'])
                and allowed.get('input_sha256') in (None, frozen['input_sha256']), 'registered input bytes differ')
        spec['expected_count'] = len(rows)
        require(allowed.get('expected_count') in (None, len(rows))
                and len(rows) <= allowed.get('maximum_expected_count', len(rows)), 'registered input count differs')
        spec['input'] = frozen
        for image in images:
            image_files[image['path']] = image['sha256']
        spec['catalog'] = pin(root, allowed['catalog'], allowed.get('catalog_sha256') or allowed.get('parent_sha256'))
        catalog = design(root, allowed['catalog'])
        require(catalog['modality'] == spec['modality'], 'catalog/input modality differs')
        if spec['kind'] == 'classify':
            require(spec['mode'] in ('llm', 'ld') and spec['stage'] in ('calibration', 'development', 'confirmation'), 'invalid classification role')
            spec['k'] = allowed['k']
            spec['order'] = pin(root, allowed['order'], allowed['order_file_sha256'])
            order = read(member(root, allowed['order']))
            require(len(order) == len(catalog['definitions'])
                    and set(order) == {row['id'] for row in catalog['definitions']}, 'order is not a stable-ID permutation')
            if spec['stage'] != 'calibration':
                split = 'repeat' if allowed.get('role') == 'reference_repeat' else spec['stage']
                expected = dataset['partitions'][split][spec['modality']]
                require(frozen['sha256'] == expected['jsonl_sha256'] and frozen['ordered_ids'] == expected['ordered_ids'], 'input differs from frozen dataset partition')
                for image in images:
                    require(image['sha256'] == dataset['photos'][image['id']]['supplied_sha256'], 'supplied photograph changed')
            if spec['stage'] == 'confirmation':
                require(not set(frozen['ordered_ids']) & set(catalog['provenance'].get('evidence_ids', [])), 'confirmation overlaps generation IDs')
            if allowed.get('role') == 'reference_repeat':
                primary = next(row for row in registry['conditions'] if row['id'] == allowed['reference_condition_id'])
                artifact = read(member(root, primary['output']))
                require(artifact.get('status') == 'complete' and artifact['processed_count'] == artifact['expected_count'] == primary['expected_count'], 'repeat requires complete primary')
                spec['reference_artifact'] = pin(root, primary['output'])
                spec['reference_condition_id'] = primary['id']
        else:
            require(spec['mode'] == 'llm' and spec['stage'] == 'custom_rewrite', 'invalid generation role')
            spec['design_id'] = allowed['design_id']
            spec['parent_sha256'] = spec['catalog']['sha256']
            spec['instructions'] = pin(root, allowed['instructions'], allowed.get('instructions_sha256'))
            require(member(root, allowed['instructions']).read_text().strip(), 'empty generation instructions')
            if args.phase == 'round3-generation':
                validate_boundary_evidence(root, spec['modality'], rows, frozen, adaptive, catalog)
        paths = [spec[key] for key in ('output', 'log', 'progress')]
        require(len(set(paths)) == 3 and spec['progress'] == str(Path(spec['output']).with_suffix('.progress.jsonl'))
                and all(not member(root, path).exists() for path in paths), 'arm artifacts must be fresh and distinct')
        spec['argv'] = make_argv(args.binary, root, spec)
        spec['cwd'] = str(root)
        preflight = command_json(make_argv(args.binary, root, spec, dry=True), root)
        require(preflight.get('dry_run') is True, 'Rust preflight did not confirm zero-dispatch mode')
        if spec['kind'] == 'classify':
            require(preflight['input_sha256'] == frozen['input_sha256']
                    and preflight['catalog_sha256'] == spec['catalog']['sha256']
                    and preflight['effective_order'] == order, 'Rust preflight differs from frozen classification')
        else:
            require(preflight['generation_evidence_sha256'] == frozen['input_sha256']
                    and preflight['parent_catalog_sha256'] == spec['parent_sha256'], 'Rust rewrite preflight differs')
        preflights[spec['id']] = preflight
        conditions.append(spec)
    paths = [spec[key] for spec in conditions for key in ('output', 'log', 'progress')]
    require(len(set(paths)) == len(paths), 'registered arms share an artifact path')
    comparisons = [row for row in registry.get('comparisons', [])
                   if row['reference'] in {spec['id'] for spec in conditions}]
    require(all(not member(root, row['output']).exists() for row in comparisons),
            'comparison output must also be fresh')
    return dict(schema_version=1, experiment=EXPERIMENT, phase=args.phase, source=source,
                protocol=protocol_spec, conditions_manifest=registry_spec, dataset=dataset_spec,
                prior_dataset=prior_dataset_spec, prior_inputs=prior_inputs,
                conditions=conditions, comparisons=comparisons, adaptive_references=adaptive,
                image_files=[dict(path=path, sha256=digest) for path, digest in sorted(image_files.items())],
                preflights=preflights, binary=str(args.binary), cwd=str(root),
                launcher_sha256=sha(Path(__file__)))


def containment(unit):
    require(unit, 'paid run requires explicit outer systemd --user unit')
    result = subprocess.run(['systemctl', '--user', 'show', unit, '--property=KillMode,ControlGroup,ActiveState'], capture_output=True, text=True, check=True)
    props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    groups = [line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()]
    group = props.get('ControlGroup', '')
    require(props.get('KillMode') == 'control-group' and props.get('ActiveState') in ('active', 'activating')
            and group and any(path == group or path.startswith(group + '/') for path in groups),
            'launcher is not contained by the declared control-group unit')
    return dict(unit=unit, properties=props, observed_cgroups=groups)


def descendants():
    records = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            records[int(path.name)] = (int(fields[1]), fields[19], fields[0])
        except (OSError, ValueError, IndexError):
            continue
    owned = {os.getpid()}
    while True:
        additions = {pid for pid, (parent, _, _) in records.items() if parent in owned} - owned
        if not additions:
            break
        owned |= additions
    return {pid: records[pid] for pid in owned if pid != os.getpid()}


def signal_owned(signum):
    for pid, (_, ticks, state) in descendants().items():
        if state == 'Z':
            continue
        try:
            current = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            if current[19] == ticks:
                os.kill(pid, signum)
        except (OSError, ProcessLookupError):
            pass


def verify_frozen(plan, args):
    require(source_pins(args) == plan['source'], 'runtime source changed after registration')
    for spec in [plan['protocol'], plan['conditions_manifest'], plan['dataset'], plan['prior_dataset'],
                 *plan['prior_inputs'], *plan['adaptive_references'], *plan['image_files']]:
        pin(args.run_root, spec['path'], spec['sha256'])
    for condition in plan['conditions']:
        for key in ('input', 'catalog', 'order', 'instructions', 'reference_artifact'):
            if key in condition:
                pin(args.run_root, condition[key]['path'], condition[key]['sha256'])


def execute(plan, args):
    require(os.environ.get('OPENAI_API_KEY', '').strip(), 'OPENAI_API_KEY required; value is never logged')
    scope = containment(args.systemd_unit)
    require(ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0, 'Linux child-subreaper setup failed')
    verify_frozen(plan, args)
    lock_path = args.run_root / 'dispatcher.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('another phase dispatcher owns this run') from error
        folder = member(args.run_root, 'registrations/' + args.phase)
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.mkdir()
        write_new(folder / 'registration.json', plan)
        write_new(folder / 'supervisor-start.json', dict(started_at_utc=now(), pid=os.getpid(), containment=scope))
        pending = list(plan['conditions'])
        children, receipts = {}, []
        interrupted = 0
        def stop(signum, frame):
            nonlocal interrupted
            interrupted = signum
        old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        def collect(pid, child, code):
            child['stream'].close()
            spec = child['spec']
            output_path = member(args.run_root, spec['output'])
            artifact = None
            try:
                artifact = read(output_path)
            except (OSError, ValueError):
                pass
            valid = isinstance(artifact, dict) and artifact.get('schema_version') == 1 and artifact.get('experiment') == EXPERIMENT
            success = code == 0 and valid and artifact.get('status') == 'complete'
            if success and spec['kind'] == 'classify':
                success = artifact.get('processed_count') == artifact.get('expected_count') == spec['expected_count']
            receipt = dict(id=spec['id'], pid=pid, returncode=code, finished_at_utc=now(), successful=success,
                           artifact_status=artifact.get('status') if valid else None,
                           in_flight_completion_unknown=code < 0 or not valid or artifact.get('status') not in ('complete', 'failed'),
                           cost_complete=bool(success and artifact.get('measurement', {}).get('cost_complete') is True),
                           files={key: pin(args.run_root, spec[key]) if member(args.run_root, spec[key]).is_file() else None for key in ('output', 'log', 'progress')})
            write_new(folder / 'terminal' / (spec['id'] + '.json'), receipt)
            receipts.append(receipt)
            del children[pid]
        stopping_at = None
        error = None
        try:
            while pending or children:
                if interrupted:
                    if stopping_at is None:
                        stopping_at = time.monotonic()
                    signal_owned(signal.SIGTERM if time.monotonic() - stopping_at < 5 else signal.SIGKILL)
                if not interrupted:
                    for spec in list(pending):
                        count = sum(child['spec']['mode'] == spec['mode'] for child in children.values())
                        if count >= 2 or len(children) >= 4:
                            continue
                        verify_frozen(plan, args)
                        require(all(not member(args.run_root, spec[key]).exists() for key in ('output', 'log', 'progress')), 'arm was already dispatched')
                        if interrupted:
                            break
                        process_log = folder / 'process' / (spec['id'] + '.log')
                        process_log.parent.mkdir(exist_ok=True)
                        stream = process_log.open('xb')
                        try:
                            process = subprocess.Popen(spec['argv'], cwd=args.run_root, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                        except BaseException:
                            stream.close()
                            raise
                        children[process.pid] = dict(process=process, stream=stream, spec=spec)
                        pending.remove(spec)
                        write_new(folder / 'started' / (spec['id'] + '.json'), dict(id=spec['id'], pid=process.pid, started_at_utc=now(), argv=spec['argv'], cwd=str(args.run_root)))
                for pid, child in list(children.items()):
                    code = child['process'].poll()
                    if code is None:
                        continue
                    collect(pid, child, code)
                if interrupted and not children:
                    break
                if pending or children:
                    time.sleep(.05)
        except BaseException as caught:
            error = str(caught)
            interrupted = interrupted or signal.SIGTERM
        finally:
            if children or descendants():
                signal_owned(signal.SIGTERM)
                deadline = time.monotonic() + 5
                while children or descendants():
                    if time.monotonic() >= deadline:
                        signal_owned(signal.SIGKILL)
                    for pid, child in list(children.items()):
                        code = child['process'].poll()
                        if code is not None:
                            collect(pid, child, code)
                    if not children:
                        while True:
                            try:
                                reaped, _ = os.waitpid(-1, os.WNOHANG)
                                if not reaped:
                                    break
                            except ChildProcessError:
                                break
                    if children or descendants():
                        time.sleep(.02)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
        comparison_receipts = []
        successful = {row['id'] for row in receipts if row['successful']}
        by_id = {spec['id']: spec for spec in plan['conditions']}
        if not interrupted and not error:
            for comparison in plan['comparisons']:
                if not {comparison['reference'], comparison['candidate']} <= successful:
                    continue
                argv = [str(args.binary), 'compare', '--reference',
                        str(member(args.run_root, by_id[comparison['reference']]['output'])),
                        '--candidate', str(member(args.run_root, by_id[comparison['candidate']]['output'])),
                        '--output', str(member(args.run_root, comparison['output']))]
                result = subprocess.run(argv, cwd=args.run_root, capture_output=True, text=True)
                receipt = dict(id=comparison['id'], returncode=result.returncode,
                               stdout=result.stdout, stderr=result.stderr,
                               output=pin(args.run_root, comparison['output']) if member(args.run_root, comparison['output']).is_file() else None)
                write_new(folder / 'comparison' / (comparison['id'] + '.json'), receipt)
                comparison_receipts.append(receipt)
        terminal = dict(status='complete' if not interrupted and not error and all(row['successful'] for row in receipts) and len(receipts) == len(plan['conditions']) and all(row['returncode'] == 0 for row in comparison_receipts) else 'failed',
                        finished_at_utc=now(), signal=interrupted or None, error=error,
                        conditions=receipts, comparisons=comparison_receipts, not_started=[spec['id'] for spec in pending],
                        containment=scope, registration_sha256=sha(folder / 'registration.json'))
        write_new(folder / 'supervisor-terminal.json', terminal)
        return 0 if terminal['status'] == 'complete' else 1


def main():
    parser = argparse.ArgumentParser(description='Plan without writes, or supervise registered paid Rust stages.')
    parser.add_argument('mode', choices=('plan', 'run'))
    for name in ('run-root', 'phase', 'binary'):
        parser.add_argument('--' + name, required=True, type=Path if name != 'phase' else str)
    parser.add_argument('--source-repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--adaptive-registration', type=Path)
    parser.add_argument('--systemd-unit')
    args = parser.parse_args()
    if args.fixtures is None:
        args.fixtures = args.source_repo / 'experiments' / STUDY
    plan = prepare(args)
    if args.mode == 'plan':
        print(json.dumps(plan, indent=2))
        return 0
    return execute(plan, args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('launcher refused: ' + str(error), file=sys.stderr)
        sys.exit(1)
