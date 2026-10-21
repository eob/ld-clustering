#!/usr/bin/env python3
"""Lossless offline archives for the separately frozen auto-research dataset.

The externally pinned independent dataset gate supplies the exact selected-file
inventory. This packager binds that gate and every raw evidence byte; it does
not recompute native-image eligibility, classification metrics, or model costs.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import types


GENERIC = Path(__file__).with_name('archive_guided_agreement.py')
common = types.ModuleType('guided_archive_primitives')
common.__file__ = str(GENERIC)
exec(compile(GENERIC.read_bytes(), str(GENERIC), 'exec'), common.__dict__)
sha, file_hash, pack = common.sha, common.file_hash, common.pack
active_workers = common.active_workers
MIB = common.MIB
EXPERIMENT = 'guidance-auto-research'
KIND = 'terminal_auto_research_evidence_snapshot'
RUNTIME_SOURCE = 'preregistration/runtime-source-pins.json'
AUDIT_READABLE_LIMIT = 32 * MIB


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_sha(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def safe_name(name):
    require(isinstance(name, str) and name and '\\' not in name
            and not any(character in name for character in ('\x00', '\n', '\r')), 'unsafe archive path')
    path = PurePosixPath(name)
    require(path.parts and not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'unsafe archive path: ' + name)
    return name


def regular(root, name):
    path = root / safe_name(name)
    current = root
    for component in PurePosixPath(name).parts:
        current = current / component
        require(not current.is_symlink(), 'symlink is outside archive scope: ' + name)
    require(path.is_file() and stat.S_ISREG(path.stat().st_mode), 'missing/nonregular archive file: ' + name)
    require(path.resolve().is_relative_to(root.resolve()), 'archive file escapes its root')
    return path


def validate_dataset(manifest_bytes, gate_bytes, entries, expected_manifest, expected_gate):
    require(sha(manifest_bytes) == expected_manifest and sha(gate_bytes) == expected_gate,
            'dataset manifest or independent gate differs from external pin')
    manifest, gate = json.loads(manifest_bytes), json.loads(gate_bytes)
    require(manifest.get('schema_version') == 3 and manifest.get('experiment') == EXPERIMENT,
            'archive requires auto-research dataset schema3')
    names = manifest['archival_files']
    require(len(names) == len(set(names)) == 397 and 'manifest.json' in names,
            'expected exactly397 selected dataset files')
    for name in names:
        safe_name(name)
    require(gate.get('schema_version') == 1 and gate.get('status') == 'passed'
            and gate.get('manifest_sha256') == expected_manifest and gate.get('archival_file_count') == 397,
            'independent dataset gate is incomplete or belongs to another dataset')
    require(set(entries) == set(names) == set(gate['artifact_sha256']),
            'selected dataset file set differs from independently audited inventory')
    inventory = {record['file']: record for record in gate['artifact_inventory']}
    require(len(inventory) == len(gate['artifact_inventory']) == 397 and set(inventory) == set(names),
            'independent gate inventory is incomplete or duplicated')
    for name in names:
        require(valid_sha(gate['artifact_sha256'][name])
                and entries[name]['sha256'] == gate['artifact_sha256'][name] == inventory[name]['sha256']
                and entries[name]['bytes'] == inventory[name]['bytes'], 'audited selected bytes differ: ' + name)


def selected_files(root, gate, manifest_sha, gate_sha):
    manifest_bytes = regular(root, 'manifest.json').read_bytes()
    require(sha(manifest_bytes) == manifest_sha, 'dataset manifest differs from external pin')
    manifest = json.loads(manifest_bytes)
    files = {safe_name(name): regular(root, name) for name in manifest['archival_files']}
    entries = {name: {'sha256': file_hash(path), 'bytes': path.stat().st_size} for name, path in files.items()}
    validate_dataset(manifest_bytes, gate, entries, manifest_sha, gate_sha)
    return files, entries


def run_files(root):
    files, excluded = {}, []
    for path in sorted(root.rglob('*')):
        name = safe_name(path.relative_to(root).as_posix())
        require(not path.is_symlink(), 'run evidence may not be a symlink: ' + name)
        if path.is_dir():
            continue
        require(stat.S_ISREG(path.stat().st_mode), 'nonregular run evidence: ' + name)
        reason = None
        if any(part in ('acquisition', '.git', 'node_modules', 'target', '__pycache__') for part in path.relative_to(root).parts):
            reason = 'unselected acquisition/build/cache files'
        elif (path.name.startswith('.env')
              or path.name in ('credentials', 'credentials.json', 'secrets', 'secrets.json')
              or path.suffix.lower() in ('.pem', '.key', '.p12', '.pfx')):
            reason = 'credential filename'
        else:
            with path.open('rb') as source:
                magic = source.read(4)
            if (magic == b'\x7fELF' or magic[:2] == b'MZ'
                    or magic in (b'\x00asm', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
                                 b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe')):
                reason = 'runtime binary; hash pinned separately'
        if reason:
            excluded.append({'path': name, 'reason': reason})
        else:
            files[name] = path
    require(files, 'run root contains no archivable evidence')
    return files, excluded


def assert_idle(run_root, binary):
    workers = active_workers(run_root, binaries=[binary])
    if workers:
        raise RuntimeError('workers still active for this run root: ' + repr(workers))


@contextmanager
def dispatcher_lock(run_root):
    import fcntl
    with regular(run_root, 'dispatcher.lock').open('rb') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('phase dispatcher still owns this run root') from error
        yield


def supervisor_receipts(names, read_bytes):
    phases = {name.split('/')[1] for name in names if name.startswith('registrations/') and len(name.split('/')) >= 3}
    require(phases, 'no terminal phase registrations are present')
    result = {}
    for phase in sorted(phases):
        prefix = 'registrations/' + phase + '/'
        paths = {key: prefix + filename for key, filename in [
            ('registration', 'registration.json'), ('start', 'supervisor-start.json'),
            ('terminal', 'supervisor-terminal.json')]}
        require(set(paths.values()) <= set(names), 'phase supervisor has no terminal registration receipt: ' + phase)
        bodies = {key: read_bytes(name) for key, name in paths.items()}
        registration, start, terminal = [json.loads(bodies[key]) for key in ('registration', 'start', 'terminal')]
        planned = [condition['id'] for condition in registration['conditions']]
        finished = [condition['id'] for condition in terminal['conditions']]
        not_started = terminal['not_started']
        require(planned and len(planned) == len(set(planned)) and len(finished) == len(set(finished))
                and len(not_started) == len(set(not_started)) and not set(finished) & set(not_started)
                and set(planned) == set(finished) | set(not_started), 'terminal phase condition accounting differs')
        require(terminal.get('status') in ('complete', 'failed', 'interrupted')
                and terminal.get('registration_sha256') == sha(bodies['registration'])
                and terminal.get('containment') == start.get('containment'), 'terminal supervisor identity differs')
        require(terminal['status'] != 'complete' or (not not_started and all(
            row.get('successful') is True for row in terminal['conditions'])), 'failed or pending conditions claim complete')
        result[phase] = {'status': terminal['status'], 'finished_conditions': len(finished),
                         'not_started_conditions': len(not_started),
                         'files': {key: {'path': name, 'sha256': sha(bodies[key])} for key, name in paths.items()}}
    return result


def readable(name, size):
    path = PurePosixPath(name)
    if path.suffix.lower() not in ('.json', '.md'):
        return False
    if path.stem in ('key', 'keys', 'golden-key') or 'progress' in path.name:
        return False
    # Audit inventories grow with every registered call. Extend only direct
    # validation/*independent-audit*.json files; ordinary reports keep 4 MiB.
    if (len(path.parts) == 2 and path.parts[0] == 'validation'
            and path.suffix.lower() == '.json' and 'independent-audit' in path.name):
        return size <= AUDIT_READABLE_LIMIT
    if size > common.READABLE_LIMIT:
        return False
    return (path.parts[0] in ('preregistration', 'catalogs', 'comparisons', 'selection', 'qualitative', 'report', 'analysis', 'repeat')
            or (path.parts[0] == 'validation' and 'independent-audit' in path.name)
            or name in ('calibration/analysis.json', 'calibration-analysis.json', 'selection.json', 'report.json'))


def validate_runtime(body, source_commit, binary_sha256):
    source = json.loads(body)
    require(source.get('commit') == source_commit and valid_sha(source_commit, 40)
            and source.get('executable_sha256') == binary_sha256 and valid_sha(binary_sha256)
            and source.get('committed_sources_verified') is True,
            'frozen run source/executable identity differs')
    hashes = source.get('embedded_file_sha256')
    require(isinstance(hashes, dict) and hashes
            and all(safe_name(name) and valid_sha(digest) for name, digest in hashes.items()),
            'frozen embedded source pins are missing/invalid')
    return source


def unchanged(files, entries):
    return set(files) == set(entries) and all(
        path.stat().st_size == entries[name]['bytes'] and file_hash(path) == entries[name]['sha256']
        for name, path in files.items())


def verify_archive(root, manifest_sha256):
    root = Path(root).resolve()
    require(valid_sha(manifest_sha256), 'a full external archive manifest anchor is required')
    body = regular(root, 'manifest.json').read_bytes()
    require(sha(body) == manifest_sha256, 'archive manifest differs from external anchor')
    manifest = json.loads(body)
    require(manifest.get('schema_version') == 1 and manifest.get('experiment') == EXPERIMENT
            and manifest.get('kind') == KIND, 'foreign archive identity/schema')
    actual = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'archive contains a symlink')
        if path.is_dir():
            continue
        name = safe_name(path.relative_to(root).as_posix())
        regular(root, name)
        actual[name] = path
    anchored = manifest['archive_files']
    require(set(anchored) == set(actual) - {'manifest.json', 'SHA256SUMS'},
            'manifest does not bind complete archive file set')
    for name, entry in anchored.items():
        path = regular(root, name)
        require(path.stat().st_size == entry['bytes'] and file_hash(path) == entry['sha256'],
                'manifest-pinned archive file differs: ' + name)
    listed = {}
    for line in regular(root, 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        require(valid_sha(digest) and safe_name(name) not in listed, 'invalid/duplicate checksum entry')
        listed[name] = digest
    require(set(listed) == set(actual) - {'SHA256SUMS'}, 'checksum file set differs')
    require(all(file_hash(regular(root, name)) == digest for name, digest in listed.items()), 'archive checksum differs')
    for payload in manifest['payloads'].values():
        require(payload['parts'], 'payload has no compressed parts')
        for part in payload['parts']:
            regular(root, part['file'])
        for name in payload['files']:
            safe_name(name)
    inputs, small = common.unpack_verify(root, manifest['payloads']['inputs'])
    run, run_small = common.unpack_verify(root, manifest['payloads']['run'])
    gate = manifest['dataset_gate']
    require(safe_name(gate['run_path']) in run_small, 'independent dataset gate is not archived/readable')
    validate_dataset(small['manifest.json'], run_small[gate['run_path']], inputs,
                     manifest['dataset_manifest_sha256'], gate['sha256'])
    runtime = manifest['runtime']
    require(runtime['source_pins_run_path'] == RUNTIME_SOURCE and RUNTIME_SOURCE in run_small,
            'frozen run source object is not archived')
    runtime_bytes = run_small[RUNTIME_SOURCE]
    require(sha(runtime_bytes) == runtime['source_pins_sha256'], 'frozen runtime source bytes differ')
    source = validate_runtime(runtime_bytes, runtime['source']['commit'], runtime['source']['executable_sha256'])
    require(source == runtime['source'], 'archive runtime differs from frozen run source object')
    require(supervisor_receipts(run, lambda name: run_small[name]) == manifest['supervisors'],
            'archived supervisor terminal receipts differ')
    mirrors = manifest['readable_copies']
    expected_mirrors = {'readable/' + name for name, entry in run.items() if readable(name, entry['bytes'])}
    require(set(mirrors) == expected_mirrors, 'readable scientific mirror set differs')
    for name, record in mirrors.items():
        raw_name = safe_name(record['raw_run_path'])
        require(name == 'readable/' + raw_name and raw_name in run
                and file_hash(regular(root, name)) == run[raw_name]['sha256']
                and regular(root, name).stat().st_size == run[raw_name]['bytes'],
                'readable scientific copy differs from raw tar bytes')
    return {'archive_manifest_sha256': sha(body), 'dataset_manifest_sha256': manifest['dataset_manifest_sha256'],
            'dataset_gate_sha256': gate['sha256'], 'dataset_files': len(inputs), 'run_files': len(run),
            'cost_or_metrics_recomputed': False}


def create_archive(run_root, data_root, output, *, dataset_manifest_sha256, dataset_gate,
                   dataset_gate_sha256, source_commit, binary, binary_sha256, chunk_bytes=89*MIB):
    run_root, data_root, output, binary = [Path(path).resolve() for path in (run_root, data_root, output, binary)]
    if output.exists():
        raise FileExistsError('refusing to overwrite archive: ' + str(output))
    require(not output.is_relative_to(run_root) and not output.is_relative_to(data_root),
            'archive output cannot be inside run-root or data-root')
    require(valid_sha(dataset_manifest_sha256) and valid_sha(dataset_gate_sha256)
            and valid_sha(source_commit, 40) and valid_sha(binary_sha256), 'full immutable pins are required')
    require(file_hash(binary) == binary_sha256, 'frozen executable checksum differs')
    require(type(chunk_bytes) is int and 1 <= chunk_bytes < 90*MIB, 'compressed chunks must be below90MiB')
    with dispatcher_lock(run_root):
        assert_idle(run_root, binary)
        runtime_bytes = regular(run_root, RUNTIME_SOURCE).read_bytes()
        source = validate_runtime(runtime_bytes, source_commit, binary_sha256)
        gate_path = regular(run_root, dataset_gate)
        gate_bytes = gate_path.read_bytes()
        require(sha(gate_bytes) == dataset_gate_sha256, 'independent dataset gate differs from external pin')
        selected, selected_entries = selected_files(data_root, gate_bytes, dataset_manifest_sha256, dataset_gate_sha256)
        raw, excluded = run_files(run_root)
        require(dataset_gate in raw, 'dataset gate is excluded from archived evidence')
        supervisors = supervisor_receipts(raw, lambda name: raw[name].read_bytes())
        phase_directories = {path.name for path in (run_root / 'registrations').iterdir() if path.is_dir()}
        require(phase_directories == set(supervisors), 'empty or incomplete phase registration directory')
        assert_idle(run_root, binary)
        output.mkdir(parents=True, exist_ok=False)
        (output / 'payloads').mkdir()
        payloads = {'inputs': pack(output, 'inputs', selected, chunk_bytes), 'run': pack(output, 'run', raw, chunk_bytes)}
        readable_copies = {}
        for name, path in raw.items():
            if not readable(name, payloads['run']['files'][name]['bytes']):
                continue
            relative = 'readable/' + name
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            require(file_hash(destination) == payloads['run']['files'][name]['sha256'], 'readable copy changed during snapshot')
            readable_copies[relative] = {'raw_run_path': name}
        shutil.copyfile(Path(__file__), output / 'archive_auto_research.py')
        shutil.copyfile(GENERIC, output / 'archive_guided_agreement.py')
        tests = Path(__file__).with_name('test_archive_auto_research.py')
        if not tests.is_file():
            tests = Path(__file__).resolve().parent.parent / 'tests/test_archive_auto_research.py'
        require(tests.is_file(), 'archive lifecycle tests are missing')
        shutil.copyfile(tests, output / 'test_archive_auto_research.py')
        (output / 'README.md').write_text(
            'Auto-research terminal evidence snapshot. Run `python3 archive_auto_research.py verify . '
            '--manifest-sha256 <published SHA256>` for offline byte verification.\n\n'
            'The input payload contains exactly the397 externally audited selected dataset files. '
            'The run payload preserves failed, unknown-usage and partial attempt bytes unchanged. '
            'Explicit credential filenames, runtime binaries and unselected acquisition/build/cache files are excluded. '
            'Concatenate each ordered parts array and xz-decompress to recover its POSIX tar. '
            'Scientific JSON/Markdown up to 4 MiB has byte-identical readable/ copies bound to the raw tar inventory; '
            'only direct validation/*independent-audit*.json files allow up to 32 MiB. '
            'Larger files remain in the raw payload without readable copies. '
            'Every started phase has a terminal supervisor receipt; packaging holds the dispatcher lock. '
            'No cost or metric is recomputed or imputed. Dataset semantic/native/license eligibility is bound '
            'to the separately pinned independent dataset gate. Runtime executable bytes are hash-pinned, not archived.\n')
        assert_idle(run_root, binary)
        final_raw, final_excluded = run_files(run_root)
        final_selected, _ = selected_files(data_root, regular(run_root, dataset_gate).read_bytes(),
                                           dataset_manifest_sha256, dataset_gate_sha256)
        if not unchanged(final_raw, payloads['run']['files']) or final_excluded != excluded:
            raise RuntimeError('run evidence changed after snapshot')
        if not unchanged(final_selected, selected_entries):
            raise RuntimeError('selected dataset changed after snapshot')
        manifest = {'schema_version': 1, 'experiment': EXPERIMENT, 'kind': KIND,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'dataset_manifest_sha256': dataset_manifest_sha256,
            'dataset_gate': {'run_path': dataset_gate, 'sha256': dataset_gate_sha256},
            'runtime': {'source': source, 'source_pins_run_path': RUNTIME_SOURCE,
                        'source_pins_sha256': sha(runtime_bytes), 'binary_basename': binary.name},
            'compression': {'format': 'xz', 'filter': 'LZMA2', 'dictionary_bytes': 64*MIB,
                            'maximum_part_bytes': chunk_bytes, 'tar_mtime': 0},
            'payloads': payloads, 'excluded_run_files': excluded, 'supervisors': supervisors,
            'readable_copies': readable_copies,
            'unknown_usage_policy': 'Preserved raw failures/partial attempts; no costs, usage or metrics imputed.'}
        manifest['archive_files'] = {path.relative_to(output).as_posix(): {'sha256': file_hash(path), 'bytes': path.stat().st_size}
            for path in sorted(output.rglob('*')) if path.is_file()}
        body = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
        (output / 'manifest.json').write_bytes(body)
        (output / 'SHA256SUMS').write_text(''.join(f'{file_hash(path)}  {path.relative_to(output).as_posix()}\n'
            for path in sorted(output.rglob('*')) if path.is_file()))
        return verify_archive(output, sha(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    for name in ('run-root', 'data-root', 'output', 'dataset-manifest-sha256', 'dataset-gate',
                 'dataset-gate-sha256', 'source-commit', 'binary', 'binary-sha256'):
        create.add_argument('--' + name, required=True)
    create.add_argument('--chunk-mib', type=int, default=89, choices=range(1, 90))
    verify = commands.add_parser('verify')
    verify.add_argument('archive', type=Path)
    verify.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'create':
        result = create_archive(args.run_root, args.data_root, args.output,
            dataset_manifest_sha256=args.dataset_manifest_sha256, dataset_gate=args.dataset_gate,
            dataset_gate_sha256=args.dataset_gate_sha256, source_commit=args.source_commit,
            binary=args.binary, binary_sha256=args.binary_sha256, chunk_bytes=args.chunk_mib*MIB)
    else:
        result = verify_archive(args.archive, args.manifest_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
