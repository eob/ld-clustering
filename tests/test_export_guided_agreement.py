import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/export_guided_agreement.py'
spec = importlib.util.spec_from_file_location('export_guided_agreement', SCRIPT)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode() + b'\n')
    return sha(path.read_bytes())


def evidence_hash(text, image=None):
    raw = text.encode()
    body = b'blinded-review-evidence-v1\0' + struct.pack('<Q', len(raw)) + raw
    body += b'no-image\0' if image is None else b'image\0' + struct.pack('<Q', len(image)) + image
    return sha(body)


def measured():
    return dict(cost_complete=True, timing_complete=True, cost_usd=0.123456789,
                wall_seconds=10.5, calls=2, error_calls=0, unknown_usage_calls=0,
                unknown_pricing_calls=0, assignment_refusal_calls=0)


def all_other(n):
    return dict(n=n, direct_agreement_count=n, direct_agreement=1, named_id_agreement_count=0, named_id_agreement=0,
        reference_assigned_count=0, candidate_assigned_count=0, reference_coverage=0, candidate_coverage=0,
        reference_refused_points=1, candidate_refused_points=0, jointly_named_agreement=None,
        assigned_other=dict(both_named=0, reference_named_candidate_other=0, reference_other_candidate_named=0, both_other=n),
        categories=[dict(cluster_id=cluster, reference_count=count, candidate_count=count, same_count=count, false_positive_count=0,
            false_negative_count=0, precision=1 if count else None, recall=1 if count else None, f1=1 if count else None) for cluster, count in [(1, 0), (None, n)]],
        confusion=[dict(reference_cluster_id=left, candidate_cluster_id=right, count=n if left is None and right is None else 0) for left in [1, None] for right in [1, None]],
        partition=dict(adjusted_rand_index=1, pairwise_precision=1, pairwise_recall=1, pairwise_f1=1), literal_metric_marker=0.123456789012345)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run, self.data = self.root/'run', self.root/'data'
        self.output, self.assets = self.root/'publication.json', self.root/'assets'
        self.source = dict(commit='b'*40, executable_sha256='c'*64)
        # A synthetic SOF/EOI envelope exercises byte/dimension checks; never a report asset.
        self.jpeg = b'\xff\xd8\xff\xc0\x00\x11\x08' + struct.pack('>HH', 512, 640) + b'\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9'
        self.plan = dict(schema_version=1, seed=2042, text_quotas={'both_other': 10}, images_census=True,
                         shortfall_policy='No reallocation', sampling_method='Frozen fixture', interpretation='Not truth')
        self.manifest = dict(schema_version=2, seed=1042, text_selection='Frozen text selection.',
                             image_selection='Frozen photo selection.', image_transform='No cropping or upscaling.',
                             partitions={}, photos={})
        self.inputs = {}
        for split in ('discovery', 'heldout', 'repeat'):
            self.manifest['partitions'][split] = {}
            for modality in ('text', 'images'):
                n = {'discovery': {'text': 200, 'images': 60}, 'heldout': {'text': 1000, 'images': 100}, 'repeat': {'text': 100, 'images': 25}}[split][modality]
                rows = []
                for i in range(n):
                    point = f'{"heldout" if split == "repeat" else split}-{modality}-{i}'
                    row = dict(id=point, text=f'Frozen input {point}')
                    if modality == 'images':
                        row['image'] = f'../images/{point}.jpg'
                        (self.data/'images').mkdir(exist_ok=True, parents=True)
                        (self.data/'images'/f'{point}.jpg').write_bytes(self.jpeg)
                        self.manifest['photos'][point] = dict(supplied_sha256=sha(self.jpeg), supplied_width=640, supplied_height=512,
                            native_width=1280, native_height=1024, inspection='natural_color_photograph', transform='none; exact supplied JPEG',
                            metadata={'Title': 'Literal credit title', 'Author': 'Fixture photographer', 'AuthorProfileURL': 'https://example.org/author',
                                      'OriginalLandingURL': 'https://example.org/photo', 'License': 'https://creativecommons.org/licenses/by/2.0/'})
                    rows.append(row)
                path = self.data/split/f'{modality}.jsonl'
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = b''.join(compact(row)+b'\n' for row in rows)
                path.write_bytes(raw)
                digest = hashlib.sha256(b'ld-clustering-input-v1\0'+struct.pack('<Q', len(raw))+raw)
                for row in rows:
                    if modality == 'images': digest.update(b'local-image\0'+struct.pack('<Q', len(self.jpeg))+self.jpeg)
                self.inputs[split, modality] = (rows, digest.hexdigest(), sha(raw))
                ids = [row['id'] for row in rows]
                self.manifest['partitions'][split][modality] = dict(file=f'{split}/{modality}.jsonl', count=n, ordered_ids=ids,
                    payload_sha256=sha(compact(rows)), order_sha256=sha(compact(ids)))
        manifest_hash = write(self.data/'manifest.json', self.manifest)
        plan_hash = write(self.run/'preregistration/review-plan.json', self.plan)
        self.protocol = dict(schema_version=1, dataset_manifest_sha256=manifest_hash, review_plan=self.plan,
            review_plan_sha256=plan_hash, classifiers={'llm': {'model': 'gpt-6.1-sol'}, 'ld': {'model': 'gpt-6-luna'}, 'k': 8},
            reviewer={'model': 'gpt-6.1-sol'})
        runtime = dict(source_commit=self.source['commit'], classification_executable_sha256=self.source['executable_sha256'],
            dataset_manifest_sha256=manifest_hash, protocol_sha256=write(self.run/'preregistration/protocol.json', self.protocol))
        write(self.run/'preregistration/runtime.json', runtime)
        self.analysis = dict(schema_version=1, status='complete', review_plan=self.plan,
            review_plan_sha256=sha(compact(self.plan)), review_plan_file_sha256=plan_hash, modalities=[])
        self.analysis_input = dict(schema_version=1, review_plan='preregistration/review-plan.json', cohorts=[])
        self.selection = dict(schema_version=1, published_at='2026-10-21', asset_url_prefix='/goofing/ld-clustering/guidance', modalities={})
        for modality in ('text', 'images'):
            n, repeat_n = (1000, 100) if modality == 'text' else (100, 25)
            direct = dict(stayed_agree=n, gained_agreement=0, lost_agreement=0, stayed_disagree=0,
                original_agreement=1, guided_agreement=1, net_gain_count=0, net_gain_fraction=0)
            named = dict(stayed_agree=0, gained_agreement=0, lost_agreement=0, stayed_disagree=n,
                original_agreement=0, guided_agreement=0, net_gain_count=0, net_gain_fraction=0)
            paired = dict(condition_matched_direct=direct, condition_matched_named=named,
                original_reference_anchored_direct=direct, original_reference_anchored_named=named,
                reference_id_changes=0, candidate_id_changes=0, literal_paired_marker=None)
            analyzed = dict(modality=modality, heldout_count=n, repeat_count=repeat_n, paired=paired)
            paths = dict(modality=modality, items=f'../data/heldout/{modality}.jsonl', repeat_input=f'../data/repeat/{modality}.jsonl')
            original_hash = None
            for condition in ('original', 'guided'):
                prefix = f'{modality}-{condition}'
                discovery = self.inputs['discovery', modality]
                catalog = dict(schema_version=1, status='complete', error=None, stage=condition, modality=modality,
                    task='Literal frozen assignment task.', catalog=[dict(id=1, name='A named category', description=f'{condition} frozen description')],
                    discovery_count=len(discovery[0]), discovery_ids=[r['id'] for r in discovery[0]], discovery_sha256=discovery[1],
                    discovery_jsonl_sha256=discovery[2], parent_catalog_sha256=original_hash, source=self.source, measurement=measured())
                catalog_path = f'catalog/{prefix}.json'
                catalog_hash = write(self.run/catalog_path, catalog)
                if condition == 'original': original_hash = catalog_hash
                path_set = dict(catalog=catalog_path, baseline=f'controlled/{prefix}-llm.json', candidate=f'controlled/{prefix}-ld.json',
                    baseline_repeat=f'repeat/{prefix}-llm.json', candidate_repeat=None, review_bundle=f'review/{prefix}.bundle.json', review_output=f'review/{prefix}.json')
                artifacts, hashes, measurements = {}, {'catalog': catalog_hash, 'candidate_repeat': None}, {'candidate_repeat': None}
                for name, mode, split in [('baseline', 'llm', 'heldout'), ('candidate', 'ld', 'heldout'), ('baseline_repeat', 'llm', 'repeat')]:
                    rows, fingerprint, raw_hash = self.inputs[split, modality]
                    assignments = [dict(id=r['id'], cluster_id=None, refused=(i == 0 and mode == 'llm'), label=None) for i, r in enumerate(rows)]
                    metadata = dict(source=self.source, mode=mode, modality=modality, condition=condition, task=catalog['task'], catalog=catalog['catalog'],
                        catalog_sha256=catalog_hash, expected_count=len(rows), ordered_ids=[r['id'] for r in rows], input_sha256=fingerprint,
                        input_jsonl_sha256=raw_hash, stage='repeat' if split == 'repeat' else 'classify', diagnostic=False, k=8,
                        reverse_catalog_order=False, assignment_model=self.protocol['classifiers'][mode]['model'], management_calls=0,
                        reference_sha256=hashes.get('baseline') if split == 'repeat' else None)
                    artifact = dict(schema_version=1, status='complete', error=None, expected_count=len(rows), processed_count=len(rows),
                        assignments=assignments, metadata=metadata, measurement=measured(), progress_sha256='d'*64)
                    hashes[name] = write(self.run/path_set[name], artifact)
                    artifacts[name], measurements[name] = artifact, artifact['measurement']
                review = self.review_fixture(modality, condition, catalog, artifacts, path_set)
                analyzed[condition] = dict(artifact_sha256=hashes, comparison=all_other(n), baseline_repeat=all_other(repeat_n),
                    candidate_repeat=None, measurements=measurements, review=review)
                paths[condition] = path_set
            self.analysis['modalities'].append(analyzed)
            self.analysis_input['cohorts'].append(paths)
            self.selection['modalities'][modality] = dict(selection_note='Explicit illustrative cases, no representativeness claim.',
                cases=[dict(condition='guided', case_id=f'{modality}-guided-case-0')])
        self.save_analysis()
        write(self.root/'selection.json', self.selection)

    def review_fixture(self, modality, condition, catalog, artifacts, paths):
        rows = self.inputs['heldout', modality][0]
        selected = rows[:10] if modality == 'text' else rows
        cases, keys, outcomes, evidence = [], [], [], {}
        for i, row in enumerate(selected):
            cid = f'{modality}-{condition}-case-{i}'
            item = dict(text=row['text'], image=str((self.data/'images'/f'{row["id"]}.jpg').resolve()) if modality == 'images' else None)
            case = dict(case_id=cid, task=catalog['task'], item=item, catalog=catalog['catalog'], choice_a=None, choice_b=None)
            cases.append(case)
            keys.append(dict(case_id=cid, item_id=row['id'], stratum='both_other', reference_cluster_id=None,
                candidate_cluster_id=None, a_is_reference=(i % 2 == 0), payload_sha256=sha(compact(case))))
            evidence[cid] = evidence_hash(row['text'], self.jpeg if modality == 'images' else None)
            judgment = dict(case_id=cid, a_fit='supported', b_fit='supported', verdict='both_reasonable', severity='none', themes=['catalog_gap'],
                evidence=['Literal reviewed evidence, not an inferred title.'], explanation='Literal automated judgment.', proposed_alternative=None)
            outcomes.append(dict(case_id=cid, raw_response=judgment, judgment=judgment, error=None))
        total = len(selected)
        counts = dict(selected_count=total, attempted_count=total, accepted_count=total, failed_count=0, not_attempted_count=0,
            reference_preferred_count=0, candidate_preferred_count=0, reviewer_reference_unsupported_count=0, reviewer_candidate_unsupported_count=0, both_unsupported_count=0)
        aggregate = dict(plan_sha256=sha(compact(self.plan)), cohort_id=f'{modality}-{condition}', totals=counts, strata={'both_other': counts})
        bundle = dict(schema_version=1, sampling_plan=self.plan, plan_sha256=sha(compact(self.plan)), audit=dict(cohort_id=f'{modality}-{condition}', modality=modality,
            total_input_count=len(rows), catalog_sha256=sha(compact(catalog['catalog'])), reference_assignments_sha256=sha(compact(artifacts['baseline']['assignments'])),
            candidate_assignments_sha256=sha(compact(artifacts['candidate']['assignments'])), strata=[dict(stratum='both_other', eligible_count=len(rows), selected_count=total)], keys=keys), cases=cases, evidence_sha256=evidence)
        bundle_hash = write(self.run/paths['review_bundle'], bundle)
        artifact = dict(status='complete', error=None, metadata=dict(source=self.source, model='gpt-6.1-sol', stage='blinded_review', bundle_sha256=bundle_hash,
            plan_sha256=bundle['plan_sha256'], selected_count=total), outcomes=outcomes, aggregate=aggregate, measurement=measured())
        output_hash = write(self.run/paths['review_output'], artifact)
        return dict(bundle_sha256=bundle_hash, selected_count=total, complete=True, output_sha256=output_hash, aggregate=aggregate, measurement=artifact['measurement'])

    def save_analysis(self):
        self.analysis['manifest_sha256'] = write(self.run/'analysis-input.json', self.analysis_input)
        write(self.run/'analysis.json', self.analysis)

    def export(self):
        return exporter.export_publication(str(self.run), str(self.data), str(self.root/'selection.json'), 'a'*40, 'f'*64, str(self.output), str(self.assets))

    def tearDown(self):
        self.temp.cleanup()

    def test_copies_literal_metrics_null_refusal_pins_and_exact_selected_jpeg(self):
        self.export()
        result = json.loads(self.output.read_bytes())
        for modality in result['modalities']:
            analyzed = next(x for x in self.analysis['modalities'] if x['modality'] == modality['modality'])
            self.assertEqual(modality['guided']['comparison'], analyzed['guided']['comparison'])
            self.assertEqual(modality['paired'], analyzed['paired'])
            self.assertIsNone(modality['guided']['comparison']['jointly_named_agreement'])
            self.assertIsNone(modality['guided']['candidate_repeat'])
            self.assertEqual(modality['examples'][0]['text'], f'Frozen input heldout-{modality["modality"]}-0')
        self.assertEqual(result['source']['runtime_commit'], 'b'*40)
        self.assertEqual(result['source']['commit'], 'a'*40)
        self.assertEqual(result['source']['review_plan_sha256'], self.analysis['review_plan_file_sha256'])
        self.assertNotEqual(result['source']['review_plan_sha256'], self.analysis['review_plan_sha256'])
        self.assertEqual(result['modalities'][0]['guided']['comparison']['reference_refused_points'], 1)
        photo = result['modalities'][1]['examples'][0]['image']
        self.assertEqual(photo['alt'], 'Literal reviewed evidence, not an inferred title.')
        self.assertEqual(photo['title'], 'Literal credit title')
        self.assertEqual((self.assets/Path(photo['src']).name).read_bytes(), self.jpeg)
        self.assertEqual(len(list(self.assets.glob('*.jpg'))), 1)
        self.assertIn('Fixture photographer', (self.assets/'ATTRIBUTION.txt').read_text())
        self.assertNotIn(str(self.root), self.output.read_text())

    def test_raw_plan_file_pin_and_typed_plan_pin_are_validated_separately(self):
        protocol_path = self.run/'preregistration/protocol.json'
        runtime_path = self.run/'preregistration/runtime.json'
        original_runtime = json.loads(runtime_path.read_bytes())
        original_analysis = copy.deepcopy(self.analysis)
        for changed in ('raw_pin', 'typed_pin', 'plan_object'):
            with self.subTest(changed=changed):
                protocol = copy.deepcopy(self.protocol)
                self.analysis = copy.deepcopy(original_analysis)
                if changed == 'raw_pin':
                    protocol['review_plan_sha256'] = self.analysis['review_plan_sha256']
                elif changed == 'typed_pin':
                    self.analysis['review_plan_sha256'] = self.analysis['review_plan_file_sha256']
                else:
                    protocol['review_plan']['seed'] += 1
                runtime = copy.deepcopy(original_runtime)
                runtime['protocol_sha256'] = write(protocol_path, protocol)
                write(runtime_path, runtime)
                self.save_analysis()
                with self.assertRaisesRegex(ValueError, 'review plan hash'):
                    self.export()
                self.assertFalse(self.output.exists())
                self.assertFalse(self.assets.exists())

    def test_rejects_incomplete_or_changed_primary_catalog_and_analysis_bindings(self):
        path = self.run/'controlled/text-original-llm.json'
        artifact = json.loads(path.read_bytes())
        artifact['status'] = 'running'
        write(path, artifact)
        with self.assertRaisesRegex(ValueError, 'hash|incomplete'): self.export()
        self.analysis['modalities'][0]['original']['artifact_sha256']['baseline'] = sha(path.read_bytes())
        self.save_analysis()
        with self.assertRaisesRegex(ValueError, 'incomplete artifact'): self.export()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.assets.exists())

    def test_refuses_unknown_selection_and_missing_modality_without_writes(self):
        self.selection['modalities']['text']['cases'][0]['case_id'] = 'not-reviewed'
        write(self.root/'selection.json', self.selection)
        with self.assertRaisesRegex(ValueError, 'case|selection'): self.export()
        del self.selection['modalities']['images']
        write(self.root/'selection.json', self.selection)
        with self.assertRaisesRegex(ValueError, 'both modalities'): self.export()
        self.assertFalse(self.assets.exists())

    def test_unknown_cost_and_failed_review_are_retained_but_selected_case_must_be_accepted(self):
        paths = self.analysis_input['cohorts'][0]['guided']
        artifact = json.loads((self.run/paths['review_output']).read_bytes())
        artifact['status'], artifact['error'] = 'failed', 'synthetic parser failure'
        artifact['outcomes'][1]['judgment'] = None
        artifact['outcomes'][1]['error'] = 'invalid response'
        artifact['outcomes'] = artifact['outcomes'][:2]
        counts = artifact['aggregate']['totals']
        counts.update(attempted_count=2, accepted_count=1, failed_count=1, not_attempted_count=8)
        artifact['aggregate']['strata']['both_other'] = counts
        artifact['measurement'].update(cost_complete=False, timing_complete=False, unknown_usage_calls=1)
        review = self.analysis['modalities'][0]['guided']['review']
        review.update(complete=False, output_sha256=write(self.run/paths['review_output'], artifact), aggregate=artifact['aggregate'], measurement=artifact['measurement'])
        self.analysis['status'] = 'reviews_incomplete'
        self.save_analysis()
        self.export()
        result = json.loads(self.output.read_bytes())
        self.assertFalse(result['modalities'][0]['guided']['review']['complete'])
        self.assertEqual(result['modalities'][0]['guided']['review']['aggregate']['totals']['not_attempted_count'], 8)
        self.assertFalse(result['modalities'][0]['guided']['review']['measurement']['cost_complete'])
        self.output.unlink()
        shutil.rmtree(self.assets)
        self.selection['modalities']['text']['cases'][0]['case_id'] = 'text-guided-case-1'
        write(self.root/'selection.json', self.selection)
        with self.assertRaisesRegex(ValueError, 'no accepted review'): self.export()
        self.assertFalse(self.output.exists())

    def test_changed_image_hash_is_rejected_before_creating_output(self):
        path = self.data/'images/heldout-images-0.jpg'
        path.write_bytes(self.jpeg+b'changed')
        with self.assertRaisesRegex(ValueError, 'image|photo|hash'): self.export()
        self.assertFalse(self.output.exists())

    def test_photo_dimensions_native_size_license_and_attribution_are_checked(self):
        original = copy.deepcopy(self.manifest)
        for changes, message in [({'supplied_width': 641}, 'dimensions'), ({'native_width': 100, 'native_height': 100}, 'native'),
                                 ({'metadata': {**original['photos']['heldout-images-0']['metadata'], 'License': 'all rights reserved'}}, 'license'),
                                 ({'metadata': {**original['photos']['heldout-images-0']['metadata'], 'Author': ''}}, 'attribution')]:
            with self.subTest(changes=changes):
                manifest = copy.deepcopy(original)
                manifest['photos']['heldout-images-0'].update(changes)
                digest = write(self.data/'manifest.json', manifest)
                protocol = copy.deepcopy(self.protocol)
                protocol['dataset_manifest_sha256'] = digest
                runtime = json.loads((self.run/'preregistration/runtime.json').read_bytes())
                runtime.update(dataset_manifest_sha256=digest, protocol_sha256=write(self.run/'preregistration/protocol.json', protocol))
                write(self.run/'preregistration/runtime.json', runtime)
                with self.assertRaisesRegex(ValueError, message): self.export()
                self.assertFalse(self.assets.exists())

    def test_fixed_catalog_identity_and_refused_assignment_cannot_silently_change(self):
        path = self.run/'catalog/text-guided.json'
        original = path.read_bytes()
        catalog = json.loads(original)
        catalog['catalog'][0]['name'] = 'Changed identity'
        self.analysis['modalities'][0]['guided']['artifact_sha256']['catalog'] = write(path, catalog)
        self.save_analysis()
        with self.assertRaisesRegex(ValueError, 'IDs/names/order'): self.export()
        path.write_bytes(original)
        self.analysis['modalities'][0]['guided']['artifact_sha256']['catalog'] = sha(original)
        path = self.run/'controlled/text-original-llm.json'
        artifact = json.loads(path.read_bytes())
        artifact['assignments'][0]['cluster_id'] = 1
        self.analysis['modalities'][0]['original']['artifact_sha256']['baseline'] = write(path, artifact)
        self.save_analysis()
        with self.assertRaisesRegex(ValueError, 'refused assignment'): self.export()

    def test_accepted_judgment_and_displayed_choices_stay_bound_to_raw_evidence(self):
        paths = self.analysis_input['cohorts'][1]['guided']
        output_path, bundle_path = self.run/paths['review_output'], self.run/paths['review_bundle']
        artifact, bundle = json.loads(output_path.read_bytes()), json.loads(bundle_path.read_bytes())
        saved = copy.deepcopy(artifact)
        artifact['outcomes'][0]['judgment'].pop('a_fit')
        artifact['outcomes'][0]['raw_response'] = artifact['outcomes'][0]['judgment']
        self.analysis['modalities'][1]['guided']['review']['output_sha256'] = write(output_path, artifact)
        self.save_analysis()
        with self.assertRaisesRegex(ValueError, 'judgment fields'): self.export()
        bundle['cases'][0]['choice_a'] = 1
        bundle['audit']['keys'][0]['payload_sha256'] = sha(compact(bundle['cases'][0]))
        digest = write(bundle_path, bundle)
        saved['metadata']['bundle_sha256'] = digest
        self.analysis['modalities'][1]['guided']['review'].update(bundle_sha256=digest, output_sha256=write(output_path, saved))
        self.save_analysis()
        with self.assertRaisesRegex(ValueError, 'displayed choices'): self.export()

    def test_fresh_paths_preserve_existing_json_and_assets(self):
        self.output.write_bytes(b'keep existing JSON')
        with self.assertRaisesRegex(ValueError, 'fresh'): self.export()
        self.assertEqual(self.output.read_bytes(), b'keep existing JSON')
        self.output.unlink()
        self.assets.mkdir()
        (self.assets/'keep.txt').write_bytes(b'keep existing assets')
        with self.assertRaisesRegex(ValueError, 'fresh'): self.export()
        self.assertEqual((self.assets/'keep.txt').read_bytes(), b'keep existing assets')

    def test_cli_accepts_ordinary_string_arguments_without_provider_or_build_tools(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--run-root', str(self.run), '--data-root', str(self.data),
            '--selection', str(self.root/'selection.json'), '--repository-commit', 'a'*40, '--archive-manifest-sha256', 'f'*64,
            '--output', str(self.output), '--asset-dir', str(self.assets)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'status': 'exported', 'modalities': 2, 'selected_examples': 2})

    def test_unknown_primary_cost_and_nullable_proposed_other_are_copied_without_defaults(self):
        paths = self.analysis_input['cohorts'][0]['guided']
        path = self.run/paths['candidate']
        artifact = json.loads(path.read_bytes())
        artifact['measurement'].update(cost_complete=False, unknown_usage_calls=1, error_calls=1)
        summary = self.analysis['modalities'][0]['guided']
        summary['artifact_sha256']['candidate'] = write(path, artifact)
        summary['measurements']['candidate'] = artifact['measurement']
        path = self.run/paths['review_output']
        review = json.loads(path.read_bytes())
        judgment = review['outcomes'][0]['judgment']
        judgment['proposed_alternative'] = {'cluster_id': None, 'reason': 'Literal recorded Other explanation.'}
        review['outcomes'][0]['raw_response'] = judgment
        summary['review']['output_sha256'] = write(path, review)
        self.save_analysis()
        self.export()
        result = json.loads(self.output.read_bytes())['modalities'][0]
        self.assertEqual(result['guided']['measurements']['candidate'], artifact['measurement'])
        self.assertEqual(result['examples'][0]['judgment']['proposed_alternative'], judgment['proposed_alternative'])


if __name__ == '__main__':
    unittest.main()
