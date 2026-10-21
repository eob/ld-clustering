import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
HERE = Path(__file__).resolve()
HELPER = HERE.with_name('archive_guided_agreement.py') if HERE.with_name('archive_guided_agreement.py').exists() else HERE.parents[1] / 'scripts/archive_guided_agreement.py'
spec = importlib.util.spec_from_file_location('archive_guided_agreement', HELPER)
archive = importlib.util.module_from_spec(spec)
exec(compile(HELPER.read_bytes(), str(HELPER), 'exec'), archive.__dict__)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def write_json(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True) + '\n')

class ArchiveTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run'
        self.run.mkdir()
        self.data = self.root / 'data'
        self.data.mkdir()
        self.out = self.root / 'archive'
        self.binary = self.root / 'frozen'
        self.binary.write_bytes(b'frozen synthetic runtime')
        (self.run / 'controlled').mkdir()
        (self.run / 'controlled/a.calls.jsonl').write_bytes(b'{"error":"HTTP503","usage":null}\n{"attempt":2,"usage":{"cost_usd":0.1}}\npartial-last-record')
        write_json(self.run / 'controlled/a.json', {'status': 'complete', 'processed_count': 1000, 'measurement': {'unknown_usage_calls': 1}})
        (self.run / 'controlled/source-commit.txt').write_text('a' * 40 + '\n')
        (self.run / 'controlled/binary-sha256.txt').write_text(sha(self.binary.read_bytes()) + '  /tmp/frozen\n')
        (self.data / 'licenses').mkdir()
        (self.data / 'images').mkdir()
        for name in ['ATTRIBUTION.txt', 'clinc-CC-BY-3.0.txt', 'openimages-selected-attribution.json']:
            (self.data / 'licenses' / name).write_text('synthetic fixture notice\n')
        files = ['manifest.json'] + [f'licenses/{n}' for n in ['ATTRIBUTION.txt', 'clinc-CC-BY-3.0.txt', 'openimages-selected-attribution.json']]
        photos = {}
        for i in range(260):
            name = f'p{i:03}'
            body = f'synthetic image bytes {i}'.encode()
            (self.data / 'images' / f'{name}.jpg').write_bytes(body)
            photos[name] = {'supplied_sha256': sha(body), 'source_sha256': sha(body), 'supplied_width': 1024, 'supplied_height': 768, 'native_width': 2048, 'native_height': 1536, 'metadata': {'License': 'https://creativecommons.org/licenses/by/2.0/'}, 'transform': 'none; exact source'}
            files.append(f'images/{name}.jpg')
        parts = {}
        held = {}
        for split, count, start, icount in [('discovery', 200, 0, 60), ('heldout', 1000, 60, 100), ('streaming', 1000, 160, 100), ('repeat', 100, 60, 25)]:
            (self.data / split).mkdir()
            parts[split] = {}
            for modality in ['text', 'images']:
                rows = [{'id': f'{split}-t{i}', 'text': f'{split} text{i}'} for i in range(count)] if modality == 'text' else [{'id': f'p{i:03}', 'text': 'Photograph.', 'image': f'../images/p{i:03}.jpg'} for i in range(start, start + icount)]
                if split == 'heldout':
                    held[modality] = rows
                if split == 'repeat':
                    rows = held[modality][:count if modality == 'text' else icount]
                name = f'{split}/{modality}.jsonl'
                body = b''.join(((json.dumps(r, separators=(',', ':')) + '\n').encode() for r in rows))
                (self.data / name).write_bytes(body)
                files.append(name)
                ids = [r['id'] for r in rows]
                image_hashes = [{'id': r['id'], 'sha256': photos[r['id']]['supplied_sha256']} for r in rows] if modality == 'images' else []
                compact = lambda v: json.dumps(v, separators=(',', ':'), sort_keys=isinstance(v, dict)).encode()
                parts[split][modality] = {'file': name, 'count': len(rows), 'ordered_ids': ids, 'order_sha256': sha(compact(ids)), 'payload_sha256': sha(compact(rows)), 'ordered_image_hashes': image_hashes, 'ordered_image_content_sha256': sha(compact(image_hashes))}
        self.manifest = {'schema_version': 2, 'archival_files': sorted(files), 'partitions': parts, 'photos': photos}
        write_json(self.data / 'manifest.json', self.manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **kwargs):
        with patch.object(archive, 'active_workers', return_value=[]):
            return archive.create_archive(self.run, self.data, self.out, 'a' * 40, self.binary, sha(self.binary.read_bytes()), **kwargs)

    def test_lossless_roundtrip_preserves_failed_and_partial_attempts(self):
        self.create()
        r = archive.verify_archive(self.out)
        self.assertGreater(r['verified_files'], 272)
        m = json.loads((self.out / 'manifest.json').read_text())
        entry = m['payloads']['run']['files']['controlled/a.calls.jsonl']
        self.assertEqual(entry['sha256'], sha((self.run / 'controlled/a.calls.jsonl').read_bytes()))
        self.assertEqual((self.out / 'readable/controlled/a.json').read_bytes(), (self.run / 'controlled/a.json').read_bytes())

    def test_payload_splits_below_limit_and_detects_corrupt_part(self):
        (self.run / 'noise.log').write_bytes(os.urandom(18000))
        self.create(chunk_bytes=1024)
        m = json.loads((self.out / 'manifest.json').read_text())
        parts = m['payloads']['run']['parts']
        self.assertGreater(len(parts), 1)
        self.assertTrue(all((p['bytes'] <= 1024 for p in parts)))
        archive.verify_archive(self.out)
        part = self.out / parts[0]['file']
        part.write_bytes(part.read_bytes() + b'bad')
        with self.assertRaises(ValueError):
            archive.verify_archive(self.out)

    def test_compressed_payload_is_deterministic(self):
        self.create()
        first = json.loads((self.out / 'manifest.json').read_text())['payloads']
        self.out = self.root / 'second'
        self.create()
        second = json.loads((self.out / 'manifest.json').read_text())['payloads']
        for key in ['inputs', 'run']:
            self.assertEqual(first[key]['tar_sha256'], second[key]['tar_sha256'])
            self.assertEqual(first[key]['parts'], second[key]['parts'])

    def test_actual_proc_guard_distinguishes_worker_from_archiver(self):
        proc = self.root / 'proc'
        proc.mkdir()
        for pid, args in [(123, ['/tmp/ld-guided-agreement-frozen', '--output', str(self.run / 'result.json')]), (456, ['python3', 'archive_guided_agreement.py', '--run-root', str(self.run)])]:
            d = proc / str(pid)
            d.mkdir()
            (d / 'cmdline').write_bytes(b'\x00'.join((a.encode() for a in args)) + b'\x00')
            (d / 'cwd').symlink_to(self.root, target_is_directory=True)
        self.assertEqual([p['pid'] for p in archive.active_workers(self.run, proc)], [123])

    def test_external_manifest_pin_also_binds_operational_helper(self):
        self.create()
        pin = sha((self.out / 'manifest.json').read_bytes())
        helper = self.out / 'archive_guided_agreement.py'
        helper.write_bytes(helper.read_bytes() + b'\n# changed\n')
        sums = []
        for p in sorted(self.out.rglob('*')):
            if p.is_file() and p.name != 'SHA256SUMS':
                sums.append(f'{sha(p.read_bytes())}  {p.relative_to(self.out).as_posix()}\n')
        (self.out / 'SHA256SUMS').write_text(''.join(sums))
        with self.assertRaises(ValueError):
            archive.verify_archive(self.out, pin)

    def test_arbitrarily_named_pinned_binary_is_an_active_worker(self):
        proc = self.root / 'proc'
        proc.mkdir()
        d = proc / '123'
        d.mkdir()
        (d / 'cmdline').write_bytes(str(self.binary).encode() + b'\x00--output\x00' + str(self.run / 'result.json').encode() + b'\x00')
        (d / 'cwd').symlink_to(self.root, target_is_directory=True)
        (d / 'exe').symlink_to(self.binary)
        self.assertEqual([p['pid'] for p in archive.active_workers(self.run, proc, binaries=[self.binary])], [123])

    def test_new_or_appended_attempt_after_packing_prevents_finalization(self):
        original = archive.pack

        def changed(*args):
            result = original(*args)
            if args[1] == 'run':
                with (self.run / 'controlled/a.calls.jsonl').open('ab') as file:
                    file.write(b'\nlate charged attempt')
                (self.run / 'controlled/late-attempt.log').write_bytes(b'new evidence')
            return result
        with patch.object(archive, 'pack', side_effect=changed), self.assertRaises(RuntimeError):
            self.create()
        self.assertFalse((self.out / 'manifest.json').exists())

    def test_existing_archive_is_never_overwritten(self):
        self.out.mkdir()
        (self.out / 'keep').write_bytes(b'unchanged')
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual((self.out / 'keep').read_bytes(), b'unchanged')

    def test_active_worker_blocks_before_output_creation(self):
        with patch.object(archive, 'active_workers', return_value=[{'pid': 123, 'command': ['guided_agreement']}]), self.assertRaises(RuntimeError):
            archive.create_archive(self.run, self.data, self.out, 'a' * 40, self.binary, sha(self.binary.read_bytes()))
        self.assertFalse(self.out.exists())

    def test_changed_supplied_input_fails_before_compression(self):
        (self.data / 'images/p000.jpg').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse(self.out.exists())

    def test_transformed_source_is_included_and_hash_checked(self):
        photo = self.manifest['photos']['p000']
        raw = b'larger native source'
        photo['source_sha256'] = sha(raw)
        photo['transform'] = 'downscale'
        (self.data / 'sources/photos').mkdir(parents=True)
        (self.data / 'sources/photos/p000.jpg').write_bytes(raw)
        write_json(self.data / 'manifest.json', self.manifest)
        self.create()
        archive.verify_archive(self.out)
        m = json.loads((self.out / 'manifest.json').read_text())
        self.assertIn('source-evidence/p000.jpg', m['payloads']['inputs']['files'])

    def test_bad_transformed_source_is_rejected(self):
        photo = self.manifest['photos']['p000']
        photo['source_sha256'] = sha(b'expected')
        photo['transform'] = 'downscale'
        (self.data / 'sources/photos').mkdir(parents=True)
        (self.data / 'sources/photos/p000.jpg').write_bytes(b'wrong')
        write_json(self.data / 'manifest.json', self.manifest)
        with self.assertRaises(ValueError):
            self.create()

    def test_manifest_cannot_escape_dataset(self):
        self.manifest['archival_files'][0] = '../outside'
        write_json(self.data / 'manifest.json', self.manifest)
        with self.assertRaises(ValueError):
            self.create()
if __name__ == '__main__':
    unittest.main()
