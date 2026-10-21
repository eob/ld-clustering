#!/usr/bin/env python3
"""Lossless terminal evidence packaging. Classifiers and metrics remain in Rust.

create --run-root RUN --data-root DATA --output NEW --source-commit SHA
       --binary FROZEN --binary-sha256 SHA
verify ARCHIVE [--manifest-sha256 SHA]

Never run create while paid workers are active. The verifier needs only Python's
standard library and archived files; it does not contact a provider or rebuild.
"""
import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from datetime import datetime, timezone

MIB = 1024 * 1024
READABLE_LIMIT = 4 * MIB


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(MIB), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError(f'unsafe archive member: {name}')
    return name


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def active_workers(run_root, proc_root=Path('/proc'), binaries=()):
    """Match actual worker executables and run paths, not archive/supervisor text."""
    root = run_root.resolve()
    pinned = {Path(binary).resolve() for binary in binaries}
    found = []
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            args = [part.decode(errors='replace') for part in (proc/'cmdline').read_bytes().split(b'\0') if part]
            if not args:
                continue
            family = any(word in Path(args[0]).name for word in ('guided_agreement', 'guided-agreement', 'ld-clustering'))
            if not family and (proc/'exe').resolve() not in pinned:
                continue
            cwd = (proc/'cwd').resolve()
            for arg in args[1:]:
                value = arg.split('=', 1)[1] if arg.startswith('--') and '=' in arg else arg
                if value.startswith('-'):
                    continue
                path = Path(value)
                path = (cwd/path).resolve() if not path.is_absolute() else path.resolve()
                if path == root or root in path.parents:
                    found.append({'pid': int(proc.name), 'command': args})
                    break
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
    return found


def refuse_active(root, binary):
    binaries = [binary]
    for pin in root.rglob('binary-sha256.txt'):
        fields = pin.read_text().strip().split(maxsplit=1)
        if len(fields) == 2:
            binaries.append(Path(fields[1].lstrip('*')))
    workers = active_workers(root, binaries=binaries)
    if workers:
        raise RuntimeError(f'paid workers still active for run root: {workers}')


def validate_inputs(manifest, entries, small):
    """Recompute selected-input payload/order hashes and licensed image bindings."""
    files = manifest['archival_files']
    if len(files) != 272 or len(set(files)) != 272 or 'manifest.json' not in files:
        raise ValueError('expected exactly the frozen 272 selected input files')
    if set(files) - entries.keys():
        raise ValueError('selected input files are missing')
    source_catalog = manifest.get('source_metadata', {}).get('photo_catalog_sha256')
    if source_catalog and entries['licenses/openimages-selected-attribution.json']['sha256'] != source_catalog:
        raise ValueError('selected attribution differs from frozen source catalog')
    photos = manifest['photos']
    expected_extras = set()
    for point_id, photo in photos.items():
        path = f'images/{point_id}.jpg'
        if entries[path]['sha256'] != photo['supplied_sha256']:
            raise ValueError(f'supplied image checksum differs: {point_id}')
        if photo['metadata']['License'] != 'https://creativecommons.org/licenses/by/2.0/':
            raise ValueError(f'missing expected image license: {point_id}')
        if photo['source_sha256'] != photo['supplied_sha256']:
            name = f'source-evidence/{point_id}.jpg'
            expected_extras.add(name)
            if name not in entries or entries[name]['sha256'] != photo['source_sha256']:
                raise ValueError(f'transformed source checksum differs: {point_id}')
    if set(entries) != set(files) | expected_extras:
        raise ValueError('input payload includes unselected files or omits transformed source')
    for split, modalities in manifest['partitions'].items():
        for modality, evidence in modalities.items():
            name = safe_name(evidence['file'])
            rows = [json.loads(line) for line in small[name].decode().splitlines() if line.strip()]
            ids = [row['id'] for row in rows]
            if len(rows) != evidence['count'] or ids != evidence['ordered_ids'] or len(ids) != len(set(ids)):
                raise ValueError(f'input count/order differs: {name}')
            if sha(canonical(ids)) != evidence['order_sha256'] or sha(canonical(rows)) != evidence['payload_sha256']:
                raise ValueError(f'input payload hash differs: {name}')
            hashes = []
            for row in rows:
                if modality == 'images':
                    expected_path = f"../images/{row['id']}.jpg"
                    if row.get('image') != expected_path or row.get('text') != 'Photograph.' or row.get('label') is not None:
                        raise ValueError(f'nonneutral image item: {row["id"]}')
                    hashes.append({'id': row['id'], 'sha256': entries[f"images/{row['id']}.jpg"]['sha256']})
                elif row.get('image') is not None:
                    raise ValueError(f'image in text stream: {name}')
            if hashes != evidence['ordered_image_hashes'] or sha(canonical(hashes)) != evidence['ordered_image_content_sha256']:
                raise ValueError(f'ordered image content differs: {name}')


def input_files(root):
    manifest = json.loads((root/'manifest.json').read_bytes())
    files = {safe_name(name): root/name for name in manifest['archival_files']}
    for point_id, photo in manifest['photos'].items():
        if photo['source_sha256'] != photo['supplied_sha256']:
            files[f'source-evidence/{point_id}.jpg'] = root/'sources/photos'/f'{point_id}.jpg'
    entries = {}
    small = {}
    for name, path in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'missing or nonregular input: {name}')
        entries[name] = {'sha256': file_hash(path), 'bytes': path.stat().st_size}
        if not name.startswith(('images/', 'source-evidence/')):
            small[name] = path.read_bytes()
    validate_inputs(manifest, entries, small)
    return files


def run_files(root):
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'run evidence may not be a symlink: {path}')
        if not path.is_file():
            continue
        name = safe_name(path.relative_to(root).as_posix())
        if path.name == '.env':
            raise ValueError('environment credential file is outside evidence scope')
        with path.open('rb') as file:
            if file.read(4) == b'\x7fELF':
                raise ValueError('runtime binaries must be pinned, not included in run evidence')
        files[name] = path
    if not files:
        raise ValueError('run root contains no evidence')
    return files


class SplitXZ:
    def __init__(self, output, prefix, limit):
        self.output, self.prefix, self.limit = output, prefix, limit
        self.encoder = lzma.LZMACompressor(format=lzma.FORMAT_XZ, filters=[{'id': lzma.FILTER_LZMA2, 'preset': 6, 'dict_size': 64*MIB}])
        self.raw_hash = hashlib.sha256()
        self.raw_bytes = 0
        self.files = []
        self.current = None
        self.size = 0

    def _save(self, data):
        while data:
            if self.current is None:
                name = f'payloads/{self.prefix}.tar.xz.part{len(self.files):04d}'
                path = self.output/name
                self.files.append(name)
                self.current = path.open('xb')
                self.size = 0
            take = min(len(data), self.limit-self.size)
            self.current.write(data[:take])
            self.size += take
            data = data[take:]
            if self.size == self.limit:
                self.current.close()
                self.current = None

    def write(self, data):
        self.raw_hash.update(data)
        self.raw_bytes += len(data)
        self._save(self.encoder.compress(data))
        return len(data)

    def close(self):
        self._save(self.encoder.flush())
        if self.current:
            self.current.close()
        return {'parts': [{'file': name, 'bytes': (self.output/name).stat().st_size, 'sha256': file_hash(self.output/name)} for name in self.files], 'tar_sha256': self.raw_hash.hexdigest(), 'tar_bytes': self.raw_bytes}


def pack(output, prefix, files, limit):
    writer = SplitXZ(output, prefix, limit)
    index = {}
    with tarfile.open(fileobj=writer, mode='w|', format=tarfile.PAX_FORMAT) as tar:
        for name, path in sorted(files.items()):
            stat = path.stat()
            digest = file_hash(path)
            info = tarfile.TarInfo(safe_name(name))
            info.size, info.mtime, info.mode = stat.st_size, 0, 0o644
            with path.open('rb') as source:
                tar.addfile(info, source)
            if path.stat().st_size != stat.st_size or file_hash(path) != digest:
                raise RuntimeError(f'source changed during snapshot: {path}')
            index[name] = {'bytes': stat.st_size, 'sha256': digest, 'source_mtime_ns': stat.st_mtime_ns}
    result = writer.close()
    result['files'] = index
    return result


class PartsReader(io.RawIOBase):
    def __init__(self, paths):
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def read(self, size=-1):
        if size < 0:
            return b''.join(iter(lambda: self.read(MIB), b''))
        output = bytearray()
        while len(output) < size:
            if self.current is None:
                try:
                    self.current = next(self.paths).open('rb')
                except StopIteration:
                    break
            block = self.current.read(size-len(output))
            if block:
                output.extend(block)
            else:
                self.current.close()
                self.current = None
        return bytes(output)

    def close(self):
        if self.current:
            self.current.close()
        super().close()


class HashReader:
    def __init__(self, file):
        self.file, self.digest, self.count = file, hashlib.sha256(), 0

    def read(self, size=-1):
        data = self.file.read(size)
        self.digest.update(data)
        self.count += len(data)
        return data


def unpack_verify(root, payload):
    paths = []
    for part in payload['parts']:
        path = root/safe_name(part['file'])
        if path.stat().st_size != part['bytes'] or file_hash(path) != part['sha256'] or part['bytes'] >= 90*MIB:
            raise ValueError(f'compressed part differs or exceeds GitHub bound: {path}')
        paths.append(path)
    entries, small = {}, {}
    with PartsReader(paths) as joined, lzma.LZMAFile(joined) as decoded:
        reader = HashReader(decoded)
        with tarfile.open(fileobj=reader, mode='r|') as tar:
            for member in tar:
                name = safe_name(member.name)
                if name in entries or not member.isfile():
                    raise ValueError(f'duplicate or nonregular tar member: {name}')
                expected = payload['files'].get(name)
                if expected is None:
                    raise ValueError(f'unindexed tar member: {name}')
                digest, count = hashlib.sha256(), 0
                capture = io.BytesIO() if name.endswith(('.json', '.jsonl', '.txt')) and member.size <= READABLE_LIMIT else None
                with tar.extractfile(member) as file:
                    for block in iter(lambda: file.read(MIB), b''):
                        digest.update(block)
                        count += len(block)
                        if capture is not None:
                            capture.write(block)
                entries[name] = {'sha256': digest.hexdigest(), 'bytes': count}
                if count != expected['bytes'] or digest.hexdigest() != expected['sha256']:
                    raise ValueError(f'decompressed bytes differ: {name}')
                if capture is not None:
                    small[name] = capture.getvalue()
        for _ in iter(lambda: reader.read(MIB), b''):
            pass
        if reader.count != payload['tar_bytes'] or reader.digest.hexdigest() != payload['tar_sha256']:
            raise ValueError('complete uncompressed tar checksum differs')
    if set(entries) != set(payload['files']):
        raise ValueError('tar omitted indexed evidence')
    return entries, small


def verify_archive(root, manifest_sha256=None):
    root = Path(root)
    body = (root/'manifest.json').read_bytes()
    if manifest_sha256 and sha(body) != manifest_sha256:
        raise ValueError('archive manifest differs from external immutable pin')
    manifest = json.loads(body)
    listed = {}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        listed[safe_name(name)] = digest
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    if set(listed) != actual:
        raise ValueError('SHA256SUMS file set differs')
    anchored = manifest['archive_files']
    if set(anchored) != actual - {'manifest.json'}:
        raise ValueError('manifest does not bind the complete archive file set')
    for name, record in anchored.items():
        if (root/name).stat().st_size != record['bytes'] or file_hash(root/name) != record['sha256']:
            raise ValueError(f'manifest-pinned archive file differs: {name}')
    for name, digest in listed.items():
        if file_hash(root/name) != digest:
            raise ValueError(f'archived file checksum differs: {name}')
    input_entries, small = unpack_verify(root, manifest['payloads']['inputs'])
    dataset = json.loads(small['manifest.json'])
    if sha(small['manifest.json']) != manifest['dataset_manifest_sha256']:
        raise ValueError('dataset manifest pin differs')
    validate_inputs(dataset, input_entries, small)
    run_entries, _ = unpack_verify(root, manifest['payloads']['run'])
    for name, record in manifest['readable_copies'].items():
        source = run_entries[record['raw_run_path']]
        if file_hash(root/name) != source['sha256']:
            raise ValueError(f'readable summary differs from raw evidence: {name}')
    return {'verified_files': len(input_entries)+len(run_entries), 'dataset_manifest_sha256': manifest['dataset_manifest_sha256'], 'archive_manifest_sha256': sha(body), 'cost_or_metrics_recomputed': False}


def create_archive(run_root, data_root, output, source_commit, binary, binary_sha256, chunk_bytes=89*MIB):
    run_root, data_root, output, binary = map(Path, (run_root, data_root, output, binary))
    if output.exists():
        raise FileExistsError(f'refusing to overwrite archive: {output}')
    if not re.fullmatch('[0-9a-f]{40}', source_commit) or not re.fullmatch('[0-9a-f]{64}', binary_sha256):
        raise ValueError('use full source and executable SHA pins')
    if file_hash(binary) != binary_sha256:
        raise ValueError('frozen executable checksum differs')
    if not 1 <= chunk_bytes < 90*MIB:
        raise ValueError('every compressed chunk must be below 90 MiB')
    refuse_active(run_root, binary)
    selected = input_files(data_root)
    raw = run_files(run_root)
    if run_root.resolve() == output.resolve() or run_root.resolve() in output.resolve().parents:
        raise ValueError('archive output cannot be inside the raw run root')
    pins = {}
    for name, path in raw.items():
        if name.endswith('source-commit.txt'):
            binary_path = path.with_name('binary-sha256.txt')
            if not binary_path.is_file():
                raise ValueError(f'launch binary pin missing beside {name}')
            pins[str(PurePosixPath(name).parent)] = {'source_commit': path.read_text().strip(), 'binary_sha256': binary_path.read_text().split()[0]}
    if not any(p == {'source_commit': source_commit, 'binary_sha256': binary_sha256} for p in pins.values()):
        raise ValueError('primary source/binary pins do not match any archived launch stage')
    refuse_active(run_root, binary)
    output.mkdir(parents=True, exist_ok=False)
    (output/'payloads').mkdir()
    payloads = {'inputs': pack(output, 'inputs', selected, chunk_bytes), 'run': pack(output, 'run', raw, chunk_bytes)}
    readable = {}
    for name, path in raw.items():
        if path.suffix == '.json' and path.stat().st_size <= READABLE_LIMIT:
            destination = output/'readable'/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            readable[destination.relative_to(output).as_posix()] = {'raw_run_path': name}
    helper = Path(__file__).resolve()
    shutil.copyfile(helper, output/'archive_guided_agreement.py')
    test = helper.parent.parent/'tests/test_archive_guided_agreement.py'
    if test.exists():
        shutil.copyfile(test, output/'test_archive_guided_agreement.py')
    manifest = {'schema_version': 1, 'kind': 'terminal_evidence_snapshot', 'created_at_utc': datetime.now(timezone.utc).isoformat(), 'dataset_manifest_sha256': file_hash(data_root/'manifest.json'), 'primary_runtime': {'source_commit': source_commit, 'binary_basename': binary.name, 'binary_sha256': binary_sha256}, 'stage_launch_pins': pins, 'compression': {'format': 'xz', 'filter': 'LZMA2', 'dictionary_bytes': 64*MIB, 'preset': 6, 'maximum_part_bytes': chunk_bytes, 'tar_mtime': 0}, 'payloads': payloads, 'readable_copies': readable, 'unknown_usage_policy': 'Raw attempts, failure rows and partial final records preserved exactly. No usage, cost or metrics imputed; separate independent analysis required.'}
    (output/'README.md').write_text('Terminal evidence snapshot; completion is determined by the raw stage artifacts, not this archive label.\n\nRun `python3 archive_guided_agreement.py verify . --manifest-sha256 <published manifest SHA256>` for offline byte/input verification. Concatenate each payload parts array in order and xz-decompress to recover its POSIX tar. Tar headers use zero timestamps; original source mtimes are indexed in manifest.json. Every decompressed file has its original exact bytes and SHA256, including failed or partial calls.\n\nInput payload contains the frozen272 selected files plus only the raw JPEG source for each transformed supplied image. Other downloads, binaries and caches are excluded. Selected photo author/title/CC license, original dimensions and publisher evidence are retained in the dataset attribution JSON. Primary executable is hash-pinned, not archived. Later stages may have distinct source/binary pins. Small raw JSON summaries are also readable byte-identical copies. The archiver does not recompute cost or agreement metrics.\n')
    refuse_active(run_root, binary)
    final_files = run_files(run_root)
    packed = payloads['run']['files']
    if set(final_files) != set(packed) or any(path.stat().st_size != packed[name]['bytes'] or file_hash(path) != packed[name]['sha256'] for name, path in final_files.items()):
        raise RuntimeError('run evidence changed after snapshot; refusing archive finalization')
    manifest['archive_files'] = {path.relative_to(output).as_posix(): {'sha256': file_hash(path), 'bytes': path.stat().st_size} for path in sorted(output.rglob('*')) if path.is_file()}
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)+'\n')
    sums = []
    for path in sorted(output.rglob('*')):
        if path.is_file():
            sums.append(f'{file_hash(path)}  {path.relative_to(output).as_posix()}\n')
    (output/'SHA256SUMS').write_text(''.join(sums))
    return verify_archive(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    for name in ('run-root', 'data-root', 'output', 'source-commit', 'binary', 'binary-sha256'):
        create.add_argument('--'+name, required=True)
    create.add_argument('--chunk-mib', type=int, default=89, choices=range(1, 90))
    verify = commands.add_parser('verify')
    verify.add_argument('archive', type=Path)
    verify.add_argument('--manifest-sha256')
    args = parser.parse_args()
    if args.command == 'create':
        result = create_archive(args.run_root, args.data_root, args.output, args.source_commit, args.binary, args.binary_sha256, args.chunk_mib*MIB)
    else:
        result = verify_archive(args.archive, args.manifest_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
