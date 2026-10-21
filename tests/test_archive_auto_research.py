"""Offline archive lifecycle witnesses; fixtures contain no model calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve()
SCRIPT = HERE.with_name('archive_auto_research.py')
if not SCRIPT.is_file():
    SCRIPT = HERE.parents[1] / 'scripts/archive_auto_research.py'


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run, self.data, self.out = [self.root / name for name in ('run', 'data', 'archive')]
        self.run.mkdir()
        self.data.mkdir()
        self.binary = self.root / 'frozen-runtime'
        self.binary.write_bytes(b'\x7fELFsynthetic frozen executable')
        self.source = 'a' * 40
        (self.run / 'calls.jsonl').write_bytes(b'{"error":"HTTP503","usage":null}\npartial-final-attempt')
        write_json(self.run / 'result.json', {'status': 'failed', 'measurement': {'cost_complete': False}})
        (self.run / 'source-commit.txt').write_text(self.source + '\n')
        (self.run / 'binary-sha256.txt').write_text(sha(self.binary.read_bytes()) + '\n')
        self.runtime = {'commit': self.source, 'executable_sha256': sha(self.binary.read_bytes()),
                        'committed_sources_verified': True, 'embedded_file_sha256': {'src/runtime.rs': 'c' * 64}}
        write_json(self.run / 'preregistration/runtime-source-pins.json', self.runtime)
        (self.run / 'dispatcher.lock').write_bytes(b'')
        self.phase = self.run / 'registrations/synthetic-phase'
        registration = {'conditions': [{'id': 'synthetic-condition'}]}
        write_json(self.phase / 'registration.json', registration)
        write_json(self.phase / 'supervisor-start.json', {'pid': 123, 'started_at_utc': 'synthetic-start', 'containment': {'fixture': True}})
        self.terminal = {'status': 'failed', 'finished_at_utc': 'synthetic-finish',
            'conditions': [{'id': 'synthetic-condition', 'successful': False}], 'not_started': [],
            'containment': {'fixture': True}, 'registration_sha256': sha((self.phase / 'registration.json').read_bytes())}
        write_json(self.phase / 'supervisor-terminal.json', self.terminal)
        selected = ['manifest.json'] + [f'provenance/selected-{i:03}.bin' for i in range(396)]
        for i, name in enumerate(selected[1:]):
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f'synthetic selected evidence {i}'.encode())
        manifest = {'schema_version': 3, 'experiment': 'guidance-auto-research', 'archival_files': selected}
        write_json(self.data / 'manifest.json', manifest)
        self.manifest_sha = sha((self.data / 'manifest.json').read_bytes())
        self.gate = 'validation/auto-dataset-independent-audit.json'
        self.inventory = {name: sha((self.data / name).read_bytes()) for name in selected}
        write_json(self.run / self.gate, {'schema_version': 1, 'status': 'passed', 'manifest_sha256': self.manifest_sha,
            'archival_file_count': 397, 'artifact_sha256': self.inventory,
            'artifact_inventory': [{'file': name, 'sha256': digest, 'bytes': (self.data / name).stat().st_size}
                                   for name, digest in self.inventory.items()]})
        self.gate_sha = sha((self.run / self.gate).read_bytes())

    def tearDown(self):
        self.temporary.cleanup()

    def module(self):
        self.assertTrue(SCRIPT.is_file(), 'separate schema3 auto-research archive helper is missing')
        module = types.ModuleType('archive_auto_research')
        module.__file__ = str(SCRIPT)
        exec(compile(SCRIPT.read_bytes(), str(SCRIPT), 'exec'), module.__dict__)
        return module

    def create(self, archive, **kwargs):
        with patch.object(archive, 'active_workers', return_value=[]):
            return archive.create_archive(self.run, self.data, self.out,
                dataset_manifest_sha256=self.manifest_sha, dataset_gate=self.gate,
                dataset_gate_sha256=self.gate_sha, source_commit=self.source,
                binary=self.binary, binary_sha256=sha(self.binary.read_bytes()), **kwargs)

    def verify(self, archive):
        return archive.verify_archive(self.out, sha((self.out / 'manifest.json').read_bytes()))

    def test_lossless_roundtrip_binds_gate_and_preserves_failed_partial_attempts(self):
        archive = self.module()
        result = self.create(archive)
        self.assertEqual(result['dataset_files'], 397)
        self.assertEqual(result['dataset_gate_sha256'], self.gate_sha)
        self.assertFalse(result['cost_or_metrics_recomputed'])
        manifest = json.loads((self.out / 'manifest.json').read_bytes())
        self.assertEqual(manifest['payloads']['run']['files']['calls.jsonl']['sha256'],
                         sha((self.run / 'calls.jsonl').read_bytes()))
        self.assertEqual(self.verify(archive)['archive_manifest_sha256'], sha((self.out / 'manifest.json').read_bytes()))
        with self.assertRaises(ValueError): archive.verify_archive(self.out, None)

    def test_external_manifest_anchor_rejects_resealed_helper_tampering(self):
        archive = self.module()
        self.create(archive)
        pin = sha((self.out / 'manifest.json').read_bytes())
        helper = self.out / 'archive_auto_research.py'
        helper.write_bytes(helper.read_bytes() + b'\n# tampered\n')
        (self.out / 'SHA256SUMS').write_text(''.join(f'{sha(p.read_bytes())}  {p.relative_to(self.out).as_posix()}\n'
            for p in sorted(self.out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
        with self.assertRaisesRegex(ValueError, 'manifest-pinned|anchor'):
            archive.verify_archive(self.out, pin)

    def test_archived_helper_verifies_standalone_with_its_pinned_generic_helper(self):
        archive = self.module()
        self.create(archive)
        pin = sha((self.out / 'manifest.json').read_bytes())
        result = subprocess.run([sys.executable, str(self.out / 'archive_auto_research.py'),
            'verify', str(self.out), '--manifest-sha256', pin], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['dataset_files'], 397)

    def test_dataset_gate_or_selected_byte_tampering_fails_before_output(self):
        archive = self.module()
        for kind in ('manifest', 'gate', 'selected'):
            with self.subTest(kind=kind):
                path = self.data / 'manifest.json' if kind == 'manifest' else self.run / self.gate if kind == 'gate' else self.data / 'provenance/selected-000.bin'
                before = path.read_bytes()
                path.write_bytes(before + b'changed')
                with self.assertRaises(ValueError): self.create(archive)
                self.assertFalse(self.out.exists())
                path.write_bytes(before)

    def test_existing_archive_and_unsafe_output_never_modify_sources(self):
        archive = self.module()
        self.out.mkdir()
        (self.out / 'keep').write_bytes(b'untouched')
        with self.assertRaises(FileExistsError): self.create(archive)
        self.assertEqual((self.out / 'keep').read_bytes(), b'untouched')
        self.out = self.run / 'nested-archive'
        with self.assertRaises(ValueError): self.create(archive)
        self.assertFalse(self.out.exists())

    def test_active_worker_blocks_before_output_creation(self):
        archive = self.module()
        with patch.object(archive, 'active_workers', return_value=[{'pid': 123}]), self.assertRaises(RuntimeError):
            archive.create_archive(self.run, self.data, self.out, dataset_manifest_sha256=self.manifest_sha,
                dataset_gate=self.gate, dataset_gate_sha256=self.gate_sha, source_commit=self.source,
                binary=self.binary, binary_sha256=sha(self.binary.read_bytes()))
        self.assertFalse(self.out.exists())

    def test_pending_or_locked_dispatcher_blocks_even_with_zero_worker_children(self):
        archive = self.module()
        terminal = self.phase / 'supervisor-terminal.json'
        before = terminal.read_bytes()
        terminal.unlink()
        with self.assertRaises((ValueError, RuntimeError)): self.create(archive)
        self.assertFalse(self.out.exists())
        terminal.write_bytes(before)
        import fcntl
        with (self.run / 'dispatcher.lock').open('r+b') as dispatcher:
            fcntl.flock(dispatcher, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(RuntimeError): self.create(archive)
        self.assertFalse(self.out.exists())

    def test_terminal_receipts_bind_registration_and_cover_every_planned_condition(self):
        archive = self.module()
        for name, changed in [('wrong-hash', {**self.terminal, 'registration_sha256': 'f' * 64}),
                              ('missing-condition', {**self.terminal, 'conditions': []}),
                              ('false-complete', {**self.terminal, 'status': 'complete'})]:
            with self.subTest(name=name):
                write_json(self.phase / 'supervisor-terminal.json', changed)
                with self.assertRaises(ValueError): self.create(archive)
                self.assertFalse(self.out.exists())

    def test_interrupted_receipt_is_retained_without_claiming_success(self):
        archive = self.module()
        write_json(self.phase / 'supervisor-terminal.json', {**self.terminal, 'status': 'interrupted', 'signal': 9})
        self.create(archive)
        manifest = json.loads((self.out / 'manifest.json').read_bytes())
        self.assertEqual(manifest['supervisors']['synthetic-phase']['status'], 'interrupted')

    def test_readable_scientific_mirrors_match_raw_inventory_and_exclude_keys(self):
        archive = self.module()
        write_json(self.run / 'comparisons/synthetic.json', {'n': 1, 'named_id_agreement_count': 0})
        write_json(self.run / 'repeat/synthetic.json', {'experiment': 'guidance-auto-research', 'assignments': []})
        write_json(self.run / 'qualitative/packet.json', {'cases': []})
        write_json(self.run / 'qualitative/key.json', {'secret': 'synthetic-blind-key'})
        self.create(archive)
        mirror = self.out / 'readable/comparisons/synthetic.json'
        self.assertEqual(mirror.read_bytes(), (self.run / 'comparisons/synthetic.json').read_bytes())
        self.assertEqual((self.out / 'readable/repeat/synthetic.json').read_bytes(),
                         (self.run / 'repeat/synthetic.json').read_bytes())
        self.assertFalse((self.out / 'readable/qualitative/key.json').exists())
        manifest = json.loads((self.out / 'manifest.json').read_bytes())
        self.assertIn('qualitative/key.json', manifest['payloads']['run']['files'])
        self.assertEqual(manifest['readable_copies']['readable/comparisons/synthetic.json']['raw_run_path'], 'comparisons/synthetic.json')

    def test_readable_limits_extend_only_explicit_independent_audits(self):
        archive = self.module()
        ordinary, audit = 4 * archive.MIB, 32 * archive.MIB
        self.assertTrue(archive.readable('calibration/analysis.json', ordinary))
        self.assertFalse(archive.readable('calibration/other.json', 1))
        self.assertTrue(archive.readable('validation/final-independent-audit.json', ordinary + 1))
        self.assertTrue(archive.readable('validation/final-independent-audit.json', audit))
        self.assertFalse(archive.readable('validation/final-independent-audit.json', audit + 1))
        for name in ('comparisons/independent-audit.json', 'analysis/large.json',
                     'calibration/analysis.json', 'validation/ordinary.json',
                     'validation/nested/final-independent-audit.json',
                     'validation/final-independent-audit.md'):
            with self.subTest(name=name):
                self.assertFalse(archive.readable(name, ordinary + 1))
        self.assertFalse(archive.readable('qualitative/key.json', 1))
        self.assertFalse(archive.readable('validation/progress-independent-audit.json', 1))

    def test_large_audit_and_calibration_mirrors_remain_bound_to_raw_tar_bytes(self):
        archive = self.module()
        name = 'validation/final-independent-audit.json'
        write_json(self.run / name, {'padding': 'x' * (4 * archive.MIB), 'status': 'verified'})
        write_json(self.run / 'calibration/analysis.json', {'constructed_key_accuracy': 1})
        self.create(archive)
        mirror = self.out / ('readable/' + name)
        self.assertEqual(mirror.read_bytes(), (self.run / name).read_bytes())
        self.assertEqual((self.out / 'readable/calibration/analysis.json').read_bytes(),
                         (self.run / 'calibration/analysis.json').read_bytes())
        # Even a newly anchored manifest/checksum set cannot substitute readable
        # bytes that differ from the independently streamed tar inventory.
        mirror.write_bytes(mirror.read_bytes() + b'changed')
        manifest_path = self.out / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        manifest['archive_files']['readable/' + name] = {
            'sha256': sha(mirror.read_bytes()), 'bytes': mirror.stat().st_size}
        write_json(manifest_path, manifest)
        (self.out / 'SHA256SUMS').write_text(''.join(f'{sha(p.read_bytes())}  {p.relative_to(self.out).as_posix()}\n'
            for p in sorted(self.out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
        with self.assertRaisesRegex(ValueError, 'copy differs from raw tar'):
            self.verify(archive)

    def test_runtime_pair_must_match_the_frozen_run_source_object(self):
        archive = self.module()
        runtime_path = self.run / 'preregistration/runtime-source-pins.json'
        for field, value in [('commit', 'f' * 40), ('executable_sha256', 'f' * 64),
                             ('committed_sources_verified', False)]:
            with self.subTest(field=field):
                self.out = self.root / ('archive-' + field)
                changed = {**self.runtime, field: value}
                write_json(runtime_path, changed)
                with self.assertRaises(ValueError): self.create(archive)
                self.assertFalse(self.out.exists())
        runtime_path.unlink()
        self.out = self.root / 'archive-missing-runtime'
        with self.assertRaises((ValueError, FileNotFoundError)): self.create(archive)

    def test_selected_gate_inventory_is_exact(self):
        archive = self.module()
        gate = json.loads((self.run / self.gate).read_bytes())
        gate['artifact_sha256'].pop('provenance/selected-000.bin')
        write_json(self.run / self.gate, gate)
        self.gate_sha = sha((self.run / self.gate).read_bytes())
        with self.assertRaisesRegex(ValueError, 'inventory'): self.create(archive)
        self.assertFalse(self.out.exists())

    def test_symlinks_and_escaping_gate_are_rejected(self):
        archive = self.module()
        linked = self.run / 'linked-log'
        linked.symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError): self.create(archive)
        linked.unlink()
        selected = self.data / 'provenance/selected-000.bin'
        before = selected.read_bytes()
        selected.unlink()
        outside = self.root / 'outside'
        outside.write_bytes(before)
        selected.symlink_to(outside)
        with self.assertRaises(ValueError): self.create(archive)
        selected.unlink()
        selected.write_bytes(before)
        self.gate = '../outside'
        with self.assertRaises(ValueError): self.create(archive)

    def test_credentials_binaries_and_unselected_acquisition_bulk_are_excluded(self):
        archive = self.module()
        (self.run / '.env').write_text('SYNTHETIC_SECRET=never_archive\n')
        (self.run / '.envrc').write_text('export SYNTHETIC_SECRET=never_archive\n')
        (self.run / 'worker-copy').write_bytes(self.binary.read_bytes())
        (self.run / 'acquisition').mkdir()
        (self.run / 'acquisition/unselected.jpg').write_bytes(b'unselected bulk')
        (self.data / 'acquisition').mkdir()
        (self.data / 'acquisition/unselected.jpg').write_bytes(b'unselected bulk')
        self.create(archive)
        manifest = json.loads((self.out / 'manifest.json').read_bytes())
        self.assertFalse({'.env', '.envrc', 'worker-copy', 'acquisition/unselected.jpg'} & manifest['payloads']['run']['files'].keys())
        self.assertNotIn('acquisition/unselected.jpg', manifest['payloads']['inputs']['files'])
        self.assertEqual(len(manifest['excluded_run_files']), 4)

    def test_late_run_or_dataset_mutation_prevents_manifest_finalization(self):
        archive = self.module()
        for kind in ('run', 'dataset'):
            with self.subTest(kind=kind):
                self.out = self.root / ('archive-' + kind)
                original = archive.pack
                def changed(*args):
                    result = original(*args)
                    if args[1] == 'run':
                        path = self.run / 'calls.jsonl' if kind == 'run' else self.data / 'provenance/selected-000.bin'
                        path.write_bytes(path.read_bytes() + b'late mutation')
                    return result
                with patch.object(archive, 'pack', side_effect=changed), self.assertRaises((ValueError, RuntimeError)):
                    self.create(archive)
                self.assertFalse((self.out / 'manifest.json').exists())

    def test_chunked_payload_corruption_and_extra_archive_file_are_rejected(self):
        archive = self.module()
        (self.run / 'noise.log').write_bytes(os.urandom(14000))
        self.create(archive, chunk_bytes=1024)
        manifest = json.loads((self.out / 'manifest.json').read_bytes())
        parts = manifest['payloads']['run']['parts']
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(p['bytes'] <= 1024 for p in parts))
        pin = sha((self.out / 'manifest.json').read_bytes())
        part = self.out / parts[0]['file']
        before = part.read_bytes()
        part.write_bytes(before + b'corrupt')
        with self.assertRaises(ValueError): archive.verify_archive(self.out, pin)
        part.write_bytes(before)
        (self.out / 'unlisted-file').write_bytes(b'extra')
        with self.assertRaises(ValueError): archive.verify_archive(self.out, pin)


if __name__ == '__main__':
    unittest.main()
