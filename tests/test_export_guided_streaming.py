import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import struct
import sqlite3
import sys


class ExportStreamingTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/export_guided_streaming.py'
        if path.exists():
            spec = importlib.util.spec_from_file_location('export_stream', path)
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def test_terminal_stream_exporter_is_available(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/export_guided_streaming.py'
        self.assertTrue(path.is_file(), 'audited terminal stream report exporter is missing')
        spec = importlib.util.spec_from_file_location('export_stream', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.export_publication))

    def fixture(self):
        protocol = {'modalities': {key: {'expected_count': n} for key, n in [('text', 1000), ('images', 100)]}, 'dataset_manifest_sha256': '1' * 64}
        audit = {'schema_version': 1, 'status': 'verified', 'source_commit': 'a' * 40, 'binary': {'sha256': 'b' * 64}, 'arms': {}, 'comparisons': [], 'cost_summary': {'known_cost_usd': '1.0000000', 'total_cost_usd': '1.0000000', 'cost_complete': True}}
        for modality, n in [('text', 1000), ('images', 100)]:
            for policy in ['original', 'contextual']:
                for backend in ['llm', 'ld']:
                    audit['arms'][f'{modality}-{policy}-{backend}'] = {
                        'complete': True, 'exit_code': 0, 'persisted_count': n, 'expected_count': n,
                        'pending_reassignments': 0, 'coverage': 0.8, 'calls': 123, 'error_calls': 0,
                        'retry_attempts': 0, 'raw_refusal_attempts': 2,
                        'known_cost_usd': '0.1250000', 'total_cost_usd': '0.1250000', 'cost_complete': True,
                        'measurement': {'wall_seconds': 120.25, 'timing_complete': True},
                        'reassignment': {'evaluations': 12, 'id_moves': 3, 'unchanged': 9, 'origin_unknown': 0},
                        'catalog': [{'id': 2, 'name': 'Synthetic category', 'description': 'Synthetic membership.', 'extra': 'excluded'}],
                    }
                score = {'n': n, 'adjusted_rand_index': 0.4321, 'pairwise_precision': 0.5, 'pairwise_recall': 0.6, 'pairwise_f1': 0.5454}
                audit['comparisons'].append({'modality': modality, 'policy': policy, 'complete': True,
                    'comparison': {'agreement': score, 'shared_other_sensitivity': {**score, 'adjusted_rand_index': 0.5678},
                                   'assigned_other': {'both_named': n * 7 // 10, 'baseline_named_ld_other': n // 10, 'baseline_other_ld_named': n // 10, 'both_other': n // 10}}})
        return audit, protocol

    def convert(self, audit, protocol):
        return self.module.publication(audit, protocol, {'fixture': True}, '2026-10-21T00:00:00Z', '2026-10-21T01:00:00+00:00')

    def test_complete_export_copies_audited_scores_coverage_work_and_exact_cost_text(self):
        audit, protocol = self.fixture()
        result = self.convert(audit, protocol)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['modalities'][0]['original']['comparison'], audit['comparisons'][0]['comparison'])
        arm = result['modalities'][1]['contextual']['ld']
        self.assertEqual(arm['known_cost_usd'], '0.1250000')
        self.assertEqual(arm['reassignment'], {'evaluations': 12, 'id_moves': 3, 'unchanged': 9, 'origin_unknown': 0})
        self.assertEqual(arm['coverage'], 0.8)
        self.assertNotIn('extra', arm['catalog'][0])
        self.assertEqual(audit, self.fixture()[0], 'export must not mutate evidence')

    def test_terminal_partial_arm_keeps_missing_comparison_and_cost_unavailable(self):
        audit, protocol = self.fixture()
        audit['status'] = 'verified_with_partial_streams'
        arm = audit['arms']['text-contextual-llm']
        arm.update(complete=False, exit_code=1, persisted_count=24, pending_reassignments=8, coverage=None, cost_complete=False, total_cost_usd=None)
        arm['measurement']['timing_complete'] = False
        audit['comparisons'][1].update(complete=False, comparison=None)
        audit['cost_summary'].update(cost_complete=False, total_cost_usd=None)
        result = self.convert(audit, protocol)
        self.assertEqual(result['status'], 'partial')
        condition = result['modalities'][0]['contextual']
        self.assertIsNone(condition['comparison'])
        self.assertIsNone(condition['llm']['coverage'])
        self.assertIsNone(result['accounting']['total_cost_usd'])
        self.assertEqual(condition['llm']['persisted_count'], 24)
        arm['coverage'] = 0.5
        with self.assertRaisesRegex(ValueError, 'partial prefix'):
            self.convert(audit, protocol)

    def test_subset_scores_and_rejection_counts_cannot_replace_full_denominator(self):
        audit, protocol = self.fixture()
        audit['comparisons'][0]['comparison']['agreement']['n'] = 100
        with self.assertRaisesRegex(ValueError, 'full registered'):
            self.convert(audit, protocol)
        audit, protocol = self.fixture()
        audit['comparisons'][0]['comparison']['assigned_other']['both_other'] -= 1
        with self.assertRaisesRegex(ValueError, 'full denominator'):
            self.convert(audit, protocol)

    def test_missing_state_stays_unknown_instead_of_inventing_zero_work(self):
        audit, protocol = self.fixture()
        audit['status'] = 'verified_with_partial_streams'
        audit['arms']['images-original-ld'] = {
            'complete': False, 'exit_code': 1, 'persisted_count': None, 'expected_count': 100,
            'measurement': None, 'catalog': None, 'coverage': None,
            'known_cost_usd': '0', 'total_cost_usd': None, 'cost_complete': False,
            'unknown_dispatch_history': True,
        }
        audit['comparisons'][2].update(complete=False, comparison=None)
        audit['cost_summary'].update(cost_complete=False, total_cost_usd=None)
        result = self.convert(audit, protocol)
        arm = result['modalities'][1]['original']['ld']
        self.assertTrue(arm['unknown_dispatch_history'])
        self.assertIsNone(arm['calls'])
        self.assertIsNone(arm['persisted_count'])
        self.assertIsNone(arm['reassignment'])
        self.assertIsNone(arm['catalog'])
        self.assertIsNone(result['modalities'][1]['original']['comparison'])

    def test_contradictory_completion_cost_and_work_are_rejected(self):
        audit, protocol = self.fixture()
        for mutate, error in [
            (lambda x: x['arms']['images-original-ld'].update(pending_reassignments=1), 'complete arm'),
            (lambda x: x['cost_summary'].update(total_cost_usd=None), 'cost/total'),
            (lambda x: x['arms']['text-original-llm']['reassignment'].update(id_moves=4), 'reassignment accounting'),
        ]:
            bad = copy.deepcopy(audit)
            mutate(bad)
            with self.assertRaisesRegex(ValueError, error):
                self.convert(bad, protocol)

    def disk_fixture(self, root):
        audit, protocol = self.fixture()
        stage, archive = root / 'stage', root / 'archive'
        (stage / 'preregistration').mkdir(parents=True)
        archive.mkdir()
        (stage / 'preregistration/protocol.json').write_text(json.dumps(protocol))
        (stage / 'run-plan.json').write_text(json.dumps({'source_commit': 'a' * 40, 'binary_sha256': 'b' * 64}))
        (stage / 'launched-at.txt').write_text('2026-10-21T00:00:00Z\n')
        (stage / 'finished-at.txt').write_text('2026-10-21T01:00:00Z\n')
        (stage / 'raw.jsonl').write_text('synthetic raw fixture\n')
        pin = lambda p: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
        audit['evidence_files'] = {str(p.relative_to(stage)): pin(p) for p in stage.rglob('*') if p.is_file()}
        audit_path = stage / 'independent-audit.json'
        audit_path.write_text(json.dumps(audit))
        manifest = {'payloads': {'run': {'files': {str(p.relative_to(stage)): pin(p) for p in stage.rglob('*') if p.is_file()}}},
                    'primary_runtime': {'source_commit': 'a' * 40, 'binary_sha256': 'b' * 64}, 'dataset_manifest_sha256': '1' * 64}
        manifest_path = archive / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest))
        return stage, audit_path, archive, pin(manifest_path)['sha256']

    def test_raw_evidence_audit_and_archive_are_bound_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, manifest = self.disk_fixture(Path(directory))
            args = (stage, audit, archive, manifest, 'c' * 40)
            result = self.module.export_publication(*args)
            self.assertEqual(result['source']['runtime_commit'], 'a' * 40)
            self.assertEqual(result['source']['commit'], 'c' * 40)
            self.assertEqual(result['source']['manifest_sha256'], manifest)
            (stage / 'raw.jsonl').write_text('changed\n')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                self.module.export_publication(*args)

    def test_wrong_archive_pin_or_changed_audit_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, manifest = self.disk_fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'manifest pin'):
                self.module.export_publication(stage, audit, archive, 'f' * 64, 'c' * 40)
            audit.write_text(audit.read_text() + '\n')
            with self.assertRaisesRegex(ValueError, 'archived audit'):
                self.module.export_publication(stage, audit, archive, manifest, 'c' * 40)

    def photo_fixture(self, root):
        stage, audit_path, archive, _ = self.disk_fixture(root)
        audit = json.loads(audit_path.read_text())
        data = root / 'data'
        (data / 'images').mkdir(parents=True)
        folder = stage / 'qualitative/photos'
        folder.mkdir(parents=True)
        identities = dict(zip('ABCD', ['images-original-ld', 'images-contextual-ld', 'images-contextual-llm', 'images-original-llm']))
        catalogs = {letter: audit['arms'][arm]['catalog'] for letter, arm in identities.items()}
        for catalog in catalogs.values():
            for category in catalog:
                category.pop('extra', None)
        packet = {'schema_version': 1, 'catalogs': catalogs, 'cases': []}
        review = {'schema_version': 1, 'blinded': True, 'cases': []}
        selection = {'schema_version': 1, 'asset_url_prefix': '/goofing/ld-clustering/streaming', 'selection_note': 'Synthetic post hoc selected examples, not an accuracy sample.', 'cases': []}
        manifest = {'photos': {}}
        pins = []
        for i in range(4):
            item, case = f'fixture-photo-{i}', f'case-{i}'
            # Synthetic JPEG frame envelope; never a public photograph.
            body = b'\xff\xd8\xff\xfe\x00\x03' + bytes([i]) + b'\xff\xc0\x00\x11\x08' + struct.pack('>HH', 512, 640) + b'\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9'
            (data / 'images' / f'{item}.jpg').write_bytes(body)
            digest = hashlib.sha256(body).hexdigest()
            photo = {'supplied_sha256': digest, 'supplied_width': 640, 'supplied_height': 512, 'native_width': 1280, 'native_height': 1024, 'inspection': 'natural_color_photograph', 'transform': 'Exact synthetic supplied bytes; test-only.', 'metadata': {'Title': 'Credit-only title', 'Author': 'Fixture author', 'AuthorProfileURL': 'https://example.org/author', 'OriginalLandingURL': 'https://example.org/photo', 'License': 'https://creativecommons.org/licenses/by/2.0/'}}
            manifest['photos'][item] = photo
            base = {'case_id': case, 'item_id': item, 'image_sha256': digest}
            packet['cases'].append({**base, 'assignments': {letter: 2 if letter != 'B' else None for letter in 'ABCD'}})
            assessments = {letter: {'assigned_cluster_id': 2 if letter != 'B' else None, 'assigned_category': 'Synthetic category' if letter != 'B' else 'Other', 'fit': 'supported' if letter != 'B' else 'plausible', 'reason': f'Literal reviewed reason for {letter}.', 'severity': 'none', 'nearest_alternative': None} for letter in 'ABCD'}
            review['cases'].append({**base, 'visible_subject': 'Literal reviewed subject.', 'literal_evidence': ['Literal pixel evidence, not the credit title.'], 'themes': ['catalog gap'], 'uncertainty': ['No human truth claim.'], 'assessments': assessments})
            selection['cases'].append({'item_id': item, 'alt_evidence_index': 0})
            pins.append(base)
        for letter, arm in identities.items():
            (stage / arm).mkdir()
            database = sqlite3.connect(stage / arm / 'state.sqlite')
            database.execute('CREATE TABLE assignments(point_id TEXT PRIMARY KEY, cluster_id INTEGER)')
            database.executemany('INSERT INTO assignments VALUES(?,?)', [(f'fixture-photo-{i}', 2 if letter != 'B' else None) for i in range(4)])
            database.commit()
            database.close()
        write = lambda path, value: path.write_text(json.dumps(value))
        write(data / 'manifest.json', manifest)
        packet_hash = hashlib.sha256(json.dumps(packet).encode()).hexdigest()
        review['packet_sha256'] = packet_hash
        write(folder / 'blinded-input.json', packet)
        write(folder / 'review.json', review)
        selection['review_sha256'] = hashlib.sha256((folder / 'review.json').read_bytes()).hexdigest()
        write(folder / 'report-selection.json', selection)
        write(folder / 'unblinding-and-selection.json', {'schema_version': 1, 'catalog_identity': identities, 'selection': {item['item_id']: {'selection': 'test-only'} for item in pins}})
        write(folder / 'provenance.json', {'schema_version': 1, 'packet_sha256': packet_hash, 'reviewer': 'Codex same-family synthetic fixture', 'blinded_at_review': True, 'unblinding_read': False, 'human_validation': False, 'population_accuracy_claim': False, 'experiment_model_api_calls': 0, 'coding_harness_compute_in_experiment_ledger': False, 'reviewed_image_count': 4, 'reviewed_images': pins})
        protocol = json.loads((stage / 'preregistration/protocol.json').read_text())
        protocol['dataset_manifest_sha256'] = hashlib.sha256((data / 'manifest.json').read_bytes()).hexdigest()
        write(stage / 'preregistration/protocol.json', protocol)
        audit['input_files'] = {str(path.relative_to(data)): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size} for path in data.rglob('*') if path.is_file()}
        write(audit_path, audit)
        return stage, audit_path, archive, self.repin(stage, audit_path, archive, protocol['dataset_manifest_sha256']), data

    def repin(self, stage, audit_path, archive, dataset_hash=None):
        pin = lambda path: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
        audit = json.loads(audit_path.read_text())
        audit['evidence_files'] = {str(path.relative_to(stage)): pin(path) for path in stage.rglob('*') if path.is_file() and path != audit_path}
        audit_path.write_text(json.dumps(audit))
        manifest_path = archive / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['payloads']['run']['files'] = {str(path.relative_to(stage)): pin(path) for path in stage.rglob('*') if path.is_file()}
        if dataset_hash: manifest['dataset_manifest_sha256'] = dataset_hash
        manifest_path.write_text(json.dumps(manifest))
        return pin(manifest_path)['sha256']

    def test_optional_photos_preserve_bound_review_choices_and_exact_licensed_jpegs(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, manifest, data = self.photo_fixture(Path(directory))
            assets = Path(directory) / 'assets'
            result = self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data, asset_dir=assets)
            photos = result['photo_review']
            self.assertEqual(len(photos['examples']), 4)
            example = photos['examples'][0]
            self.assertEqual(example['image']['alt'], 'Literal pixel evidence, not the credit title.')
            self.assertEqual([a['arm'] for a in example['assignments']], ['images-original-ld', 'images-contextual-ld', 'images-contextual-llm', 'images-original-llm'])
            self.assertIsNone(example['assignments'][1]['cluster_id'])
            self.assertEqual(example['assignments'][1]['category'], 'Other')
            self.assertEqual(example['assignments'][0]['reason'], 'Literal reviewed reason for A.')
            for i, example in enumerate(photos['examples']):
                self.assertEqual((assets / f'input-{i+1:02}.jpg').read_bytes(), (data / 'images' / f'fixture-photo-{i}.jpg').read_bytes())
            self.assertIn('CC BY 2.0', (assets / 'ATTRIBUTION.txt').read_text())
            self.assertIn('outside', (assets / 'ATTRIBUTION.txt').read_text())

    def test_photo_helper_replay_preserves_fresh_evidence_with_bytecode_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, audit, archive, manifest, data = self.photo_fixture(root)
            helper_dir = root / 'frozen-reproduction'
            helper_dir.mkdir()
            helper = Path(__file__).resolve().parents[1] / 'scripts/export_guided_agreement.py'
            (helper_dir / helper.name).write_bytes(helper.read_bytes())
            snapshot = {str(path.relative_to(helper_dir)): path.read_bytes() for path in helper_dir.rglob('*') if path.is_file()}
            original_file, original_flag = self.module.__file__, sys.dont_write_bytecode
            try:
                self.module.__file__ = str(helper_dir / 'export_guided_streaming.py')
                sys.dont_write_bytecode = False
                self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data, asset_dir=root / 'assets')
            finally:
                self.module.__file__, sys.dont_write_bytecode = original_file, original_flag
            after = {str(path.relative_to(helper_dir)): path.read_bytes() for path in helper_dir.rglob('*') if path.is_file()}
            self.assertFalse((helper_dir / '__pycache__').exists(), 'helper replay wrote bytecode into immutable evidence')
            self.assertEqual(after, snapshot)

    def test_selected_photo_assignment_must_match_audited_database(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, _, data = self.photo_fixture(Path(directory))
            database = sqlite3.connect(stage / 'images-original-ld/state.sqlite')
            database.execute("UPDATE assignments SET cluster_id=NULL WHERE point_id='fixture-photo-0'")
            database.commit()
            database.close()
            manifest = self.repin(stage, audit, archive)
            assets = Path(directory) / 'assets'
            with self.assertRaisesRegex(ValueError, 'assignment differs from audited database'):
                self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data, asset_dir=assets)
            self.assertFalse(assets.exists())

    def test_photo_review_seals_assignments_and_audited_inventory_are_required(self):
        for failure in ('changed review', 'missing index', 'wrong assignment', 'wrong identity', 'wrong alt'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                stage, audit, archive, manifest, data = self.photo_fixture(Path(directory))
                folder = stage / 'qualitative/photos'
                if failure in ('changed review', 'wrong assignment'):
                    review = json.loads((folder / 'review.json').read_text())
                    review['cases'][0]['assessments']['A']['assigned_cluster_id'] = None
                    (folder / 'review.json').write_text(json.dumps(review))
                    if failure == 'wrong assignment':
                        selection = json.loads((folder / 'report-selection.json').read_text())
                        selection['review_sha256'] = hashlib.sha256((folder / 'review.json').read_bytes()).hexdigest()
                        (folder / 'report-selection.json').write_text(json.dumps(selection))
                    manifest = self.repin(stage, audit, archive)
                    error = 'sealed photo review' if failure == 'changed review' else 'reviewed photo assignment'
                elif failure == 'wrong identity':
                    key = json.loads((folder / 'unblinding-and-selection.json').read_text())
                    key['catalog_identity']['A'] = key['catalog_identity']['B']
                    (folder / 'unblinding-and-selection.json').write_text(json.dumps(key))
                    manifest = self.repin(stage, audit, archive)
                    error = 'catalog identities'
                elif failure == 'wrong alt':
                    selection = json.loads((folder / 'report-selection.json').read_text())
                    selection['cases'][0]['alt_evidence_index'] = 8
                    (folder / 'report-selection.json').write_text(json.dumps(selection))
                    manifest = self.repin(stage, audit, archive)
                    error = 'alt evidence index'
                else:
                    value = json.loads(audit.read_text())
                    del value['evidence_files']['qualitative/photos/provenance.json']
                    audit.write_text(json.dumps(value))
                    archived = json.loads((archive / 'manifest.json').read_text())
                    archived['payloads']['run']['files']['independent-audit.json'] = {'sha256': hashlib.sha256(audit.read_bytes()).hexdigest(), 'bytes': audit.stat().st_size}
                    (archive / 'manifest.json').write_text(json.dumps(archived))
                    manifest = hashlib.sha256((archive / 'manifest.json').read_bytes()).hexdigest()
                    error = 'not audited'
                assets = Path(directory) / 'assets'
                with self.assertRaisesRegex(ValueError, error):
                    self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data, asset_dir=assets)
                self.assertFalse(assets.exists())

    def test_photo_bytes_dimensions_aspect_native_license_and_credits_are_checked(self):
        mutations = [({'supplied_width': 641}, 'dimensions'), ({'native_width': 1100}, 'aspect'), ({'native_width': 100, 'native_height': 100}, 'upscaling'), ({'metadata.License': 'all rights reserved'}, 'license'), ({'metadata.Author': ''}, 'attribution'), ({'metadata.OriginalLandingURL': 'javascript:invalid'}, 'URL')]
        for changes, error in mutations:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                stage, audit, archive, _, data = self.photo_fixture(Path(directory))
                manifest = json.loads((data / 'manifest.json').read_text())
                photo = manifest['photos']['fixture-photo-0']
                for key, value in changes.items():
                    if key.startswith('metadata.'): photo['metadata'][key.split('.')[1]] = value
                    else: photo[key] = value
                (data / 'manifest.json').write_text(json.dumps(manifest))
                digest = hashlib.sha256((data / 'manifest.json').read_bytes()).hexdigest()
                protocol = json.loads((stage / 'preregistration/protocol.json').read_text())
                protocol['dataset_manifest_sha256'] = digest
                (stage / 'preregistration/protocol.json').write_text(json.dumps(protocol))
                pin = self.repin(stage, audit, archive, digest)
                with self.assertRaisesRegex(ValueError, error):
                    self.module.export_publication(stage, audit, archive, pin, 'c' * 40, data_root=data, asset_dir=Path(directory) / 'assets')
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, manifest, data = self.photo_fixture(Path(directory))
            (data / 'images/fixture-photo-0.jpg').write_bytes(b'changed bytes')
            with self.assertRaisesRegex(ValueError, 'audited input'):
                self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data, asset_dir=Path(directory) / 'assets')

    def test_photo_opt_in_and_fresh_output_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, manifest, data = self.photo_fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'supplied together'):
                self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data)
            assets = Path(directory) / 'assets'
            assets.mkdir()
            (assets / 'keep.txt').write_text('preserve')
            with self.assertRaisesRegex(ValueError, 'fresh'):
                self.module.export_publication(stage, audit, archive, manifest, 'c' * 40, data_root=data, asset_dir=assets)
            self.assertEqual((assets / 'keep.txt').read_text(), 'preserve')

    def test_optional_common_named_subset_copies_posthoc_metrics_without_changing_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, audit, archive, _ = self.disk_fixture(Path(directory))
            (stage / 'posthoc').mkdir()
            (stage / 'reproduction').mkdir()
            helper = b'# Frozen synthetic verifier fixture\n'
            (stage / 'reproduction/verify_guided_streaming.py').write_bytes(helper)
            (stage / 'reproduction/analyze_common_named.py').write_text('# Frozen synthetic analysis fixture\n')
            subset = {'schema_version': 1, 'status': 'complete', 'scope': 'post_hoc_common_named_subset', 'modality': 'images', 'full_n': 100, 'conditional_n': 2, 'selected_item_ids': ['test-only-1', 'test-only-2'], 'source_commit': 'a' * 40, 'verifier_sha256': hashlib.sha256(helper).hexdigest(), 'partition_by_policy': {policy: {'n': 2, 'adjusted_rand_index': 0.123456789} for policy in ('original', 'contextual')}, 'selection_note': 'Post hoc conditional fixture; not primary or accuracy.'}
            path = stage / 'posthoc/images-common-named.json'
            path.write_text(json.dumps(subset))
            manifest = self.repin(stage, audit, archive)
            result = self.module.export_publication(stage, audit, archive, manifest, 'c' * 40)
            self.assertEqual(result['modalities'][1]['common_named_subset'], subset)
            self.assertEqual(result['modalities'][1]['original']['comparison']['agreement']['n'], 100)
            for field, value, error in [('full_n', 25, 'scope'), ('conditional_n', 3, 'denominator'), ('selected_item_ids', ['same', 'same'], 'denominator'), ('partition_by_policy', {policy: {'n': 100} for policy in ('original', 'contextual')}, 'score denominator'), ('verifier_sha256', 'f' * 64, 'helper pin'), ('source_commit', 'b' * 40, 'source/helper pin')]:
                bad = {**subset, field: value}
                path.write_text(json.dumps(bad))
                manifest = self.repin(stage, audit, archive)
                with self.assertRaisesRegex(ValueError, error):
                    self.module.export_publication(stage, audit, archive, manifest, 'c' * 40)
            subset.update(conditional_n=0, selected_item_ids=[], partition_by_policy={'original': None, 'contextual': None})
            path.write_text(json.dumps(subset))
            manifest = self.repin(stage, audit, archive)
            result = self.module.export_publication(stage, audit, archive, manifest, 'c' * 40)
            self.assertIsNone(result['modalities'][1]['common_named_subset']['partition_by_policy']['original'])


if __name__ == '__main__':
    unittest.main()
