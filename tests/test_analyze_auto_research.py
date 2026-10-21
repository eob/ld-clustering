"""Offline witnesses for preregistered selection and bounded blind sampling."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import types
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/analyze_auto_research.py'
analysis = types.ModuleType('analysis')
analysis.__file__ = str(SCRIPT)
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), 'exec'), analysis.__dict__)


def metrics(n=200, named=150, direct=160, sol=190, ld=180):
    return dict(n=n, named_id_agreement_count=named, direct_agreement_count=direct,
                reference_assigned_count=sol, candidate_assigned_count=ld)


class SelectionTests(unittest.TestCase):
    def test_shared_other_gain_without_named_gain_is_not_adopted(self):
        result = analysis.choose(metrics(), {'compact': metrics(direct=170)})
        self.assertEqual(result['status'], 'NOT_ADOPTED')
        self.assertEqual(result['adopted'], 'baseline')
        self.assertEqual(result['challenger'], 'compact')
        self.assertFalse(result['ranking'][0]['checks']['named_improved'])

    def test_coverage_gate_uses_integer_two_percentage_points_for_each_backend(self):
        # Four points are allowed at n200, no point is allowed at n40.
        for n, baseline_sol, baseline_ld, allowed in [(200, 190, 180, 4), (40, 38, 36, 0)]:
            baseline = metrics(n=n, named=n-12, direct=n-10, sol=baseline_sol, ld=baseline_ld)
            for backend in ('sol', 'ld'):
                for loss in (allowed, allowed+1):
                    kwargs = dict(n=n, named=n-11, direct=n-9, sol=baseline_sol, ld=baseline_ld)
                    kwargs[backend] -= loss
                    result = analysis.choose(baseline, {'compact': metrics(**kwargs)})
                    self.assertEqual(result['status'], 'ADOPTED' if loss == allowed else 'NOT_ADOPTED')

    def test_eligible_rank_tie_and_no_candidate_failure_are_explicit(self):
        baseline = metrics()
        compact = metrics(named=151, direct=161)
        boundary = copy.deepcopy(compact)
        result = analysis.choose(baseline, {'boundary': boundary, 'compact': compact})
        self.assertEqual(result['challenger'], 'compact')
        boundary['named_id_agreement_count'] += 1
        result = analysis.choose(baseline, {'compact': compact, 'boundary': boundary})
        self.assertEqual(result['challenger'], 'boundary')
        self.assertEqual(analysis.choose(baseline, {})['status'], 'selection_unavailable')
        self.assertEqual(analysis.choose(None, {'compact': compact})['status'], 'selection_unavailable')
        with self.assertRaisesRegex(ValueError, 'cohort'):
            analysis.choose(baseline, {'compact': metrics(n=199)})

    def test_sampler_is_bounded_deterministic_and_does_not_reallocate_short_strata(self):
        assignments = {'a': (11,29), 'b':(None,11), 'c':(11,None), 'd':(11,11), 'e':(None,None), 'f':(29,29)}
        quotas = dict(different_named=3, sol_named_native_other=0, sol_other_native_named=1, equal_named=1, both_other=1)
        first, counts = analysis.sample_review('development','text',assignments,quotas)
        second, _ = analysis.sample_review('development','text',dict(reversed(list(assignments.items()))),quotas)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertEqual(counts['different_named'],dict(available=1,quota=3,selected=1))
        self.assertNotIn('c',first)
        self.assertNotEqual(analysis.review_rank('development','text','case','a'),analysis.review_rank('confirmation','text','case','a'))


class BoundPacketTests(unittest.TestCase):
    def fixture(self, root, modality='text'):
        def write(relative, value):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value) + '\n')
            return path
        definitions = [dict(id=11, name='One', description='First membership.'),
                       dict(id=29, name='Two', description='Second membership.')]
        plan = {phase: {mode: dict(different_named=1, sol_named_native_other=0,
            sol_other_native_named=0, equal_named=0, both_other=0) for mode in ['text','images']}
            for phase in ['development','confirmation']}
        write('preregistration/review-plan.json', plan)
        prompt = root / 'prompts/blinded-review.md'
        prompt.parent.mkdir(parents=True)
        prompt.write_text('Judge each assignment against its own definitions.\n')
        key = dict(answers=[dict(id='cal-1', expected_cluster_id=11)])
        write('calibration/golden-key.json', key)
        conditions = dict(conditions=[dict(id='synthetic-calibration', phase='calibration',
            output='calibration/synthetic.json', description_style='short', cyclic_order=0, mode='llm')])
        write('preregistration/conditions.json', conditions)
        audited_files = []
        for phase, stem, role in [('development', f'r2-{modality}-compact', 'compact'),
                                  ('confirmation', f'confirmation-{modality}-challenger', 'challenger'),
                                  ('confirmation', f'confirmation-{modality}-baseline', 'baseline')]:
            for mode, choice in [('llm',11), ('ld',29)]:
                relative = f'{phase}/{stem}-{mode}.json'
                write(relative, dict(assignments=[dict(id='SOURCE_POINT_ID', cluster_id=choice)]))
                audited_files.append(relative)
            relative = f'catalogs/{role}-{modality}.json'
            own = copy.deepcopy(definitions)
            if role == 'baseline': own[0]['description'] = 'Original membership.'
            write(relative, dict(design=dict(definitions=own)))
            audited_files.append(relative)
            item = dict(id='SOURCE_POINT_ID', text='Constructed request.', label='HIDDEN_GROUND_TRUTH')
            if modality == 'images':
                item.update(text='Photograph.', image='../images/secret-source-name.jpg')
                image = root / 'inputs/images/secret-source-name.jpg'
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(b'\xff\xd8synthetic-exact-image-bytes\xff\xd9')
                audited_files.append('inputs/images/secret-source-name.jpg')
            relative = f'inputs/{phase}/{modality}.jsonl'
            write(relative, item)
            audited_files.append(relative)
        write('calibration/synthetic.json', dict(status='complete', metadata=dict(effective_order=[11,29]),
            assignments=[dict(id='cal-1', cluster_id=11)]))
        audited_files.append('calibration/synthetic.json')
        fixed = {relative: analysis.sha(root / (f'preregistration/{relative}' if relative in
            ['review-plan.json','conditions.json'] else relative)) for relative in
            ['review-plan.json','conditions.json','prompts/blinded-review.md','calibration/golden-key.json']}
        protocol = dict(schema_version=1, experiment='guidance-auto-research',
            fixed_fixture_sha256=fixed, review_plan_sha256=fixed['review-plan.json'])
        write('preregistration/protocol.json', protocol)
        audited_files.append('preregistration/protocol.json')
        audit = dict(experiment='guidance-auto-research', status='verified',
            protocol_sha256=analysis.sha(root / 'preregistration/protocol.json'), dataset_manifest_sha256='d'*64,
            evidence_files={relative:analysis.sha(root / relative) for relative in set(audited_files)},
            comparisons={f'r2-{modality}-compact':metrics(n=1, named=0, direct=0, sol=1, ld=1),
                f'confirmation-{modality}-challenger':dict(n=1),f'confirmation-{modality}-baseline':dict(n=1)})
        return audit

    def test_registered_fixture_changes_are_rejected_before_packet_or_accuracy_output(self):
        for relative in ['preregistration/review-plan.json','prompts/blinded-review.md',
                         'calibration/golden-key.json','preregistration/conditions.json']:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); audit = self.fixture(root)
                path = root / relative
                if relative.endswith('review-plan.json'):
                    value = analysis.read(path);value['development']['text']['different_named']=0
                    path.write_text(json.dumps(value))
                elif relative.endswith('golden-key.json'):
                    path.write_text(json.dumps(dict(answers=[dict(id='cal-1',expected_cluster_id=29)])))
                elif relative.endswith('conditions.json'):
                    value=analysis.read(path);value['conditions'][0]['description_style']='Changed style'
                    path.write_text(json.dumps(value))
                else: path.write_text('Changed unregistered reviewer instruction.\n')
                with self.assertRaises(ValueError):
                    if 'golden-key' in relative or 'conditions.json' in relative: analysis.calibration(root,audit)
                    else: analysis.packet(root,audit,'development','text',root/'packet')
                self.assertFalse((root/'packet').exists())

    def test_every_arm_catalog_and_input_read_requires_an_audited_or_fixed_pin(self):
        for relative in ['development/r2-text-compact-llm.json','catalogs/compact-text.json','inputs/development/text.jsonl']:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);audit=self.fixture(root);audit['evidence_files'].pop(relative)
                with self.assertRaises(ValueError): analysis.packet(root,audit,'development','text',root/'packet')
                self.assertFalse((root/'packet').exists())

    def test_protocol_itself_must_match_the_audited_protocol_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);audit=self.fixture(root);audit['protocol_sha256']='f'*64
            with self.assertRaises(ValueError): analysis.packet(root,audit,'development','text',root/'packet')

    def test_packet_uses_neutral_images_and_separate_blind_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);audit=self.fixture(root,'images');out=root/'packet'
            result=analysis.packet(root,audit,'development','images',out)
            packet=analysis.read(out/'packet.json');key=analysis.read(out/'key.json')
            self.assertEqual(result['selected'],1)
            wire=json.dumps(packet)
            for secret in ['SOURCE_POINT_ID','HIDDEN_GROUND_TRUTH','secret-source-name','"llm"','"ld"']:
                self.assertNotIn(secret,wire)
            case=packet['cases'][0];image=root/case['image']
            self.assertEqual(image.read_bytes(),(root/'inputs/images/secret-source-name.jpg').read_bytes())
            self.assertEqual(case['image_sha256'],analysis.sha(image))
            self.assertEqual(key['keys'][0]['item_id'],'SOURCE_POINT_ID')

    def test_confirmation_assignments_each_keep_their_own_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);audit=self.fixture(root)
            analysis.packet(root,audit,'confirmation','text',root/'packet')
            case=analysis.read(root/'packet/packet.json')['cases'][0]
            self.assertEqual(case['pairs'][0]['catalog'][0]['description'],'First membership.')
            self.assertEqual(case['pairs'][1]['catalog'][0]['description'],'Original membership.')

    def test_selection_rejects_confirmation_comparisons_even_without_confirmation_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);audit=self.fixture(root)
            shutil.rmtree(root/'confirmation')
            path=root/'audit.json';path.write_text(json.dumps(audit))
            with self.assertRaises(ValueError): analysis.select(root,audit,path,root/'selection.json')

    def test_selection_copies_the_audited_wrapper_bytes_without_reserialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);audit=self.fixture(root)
            shutil.rmtree(root/'confirmation')
            audit['evidence_files']={name:pin for name,pin in audit['evidence_files'].items()
                                     if not name.startswith('confirmation/')}
            audit['comparisons']={'r2-text-baseline':metrics(),
                                  'r2-text-compact':metrics(named=151,direct=161)}
            (root/'catalogs/challenger-text.json').unlink()
            audit['evidence_files'].pop('catalogs/challenger-text.json')
            source=root/'catalogs/compact-text.json'
            original=source.read_bytes()+b'  \n'
            source.write_bytes(original);audit['evidence_files']['catalogs/compact-text.json']=analysis.sha(source)
            path=root/'audit.json';path.write_text(json.dumps(audit))
            result=analysis.select(root,audit,path,root/'selection/selection.json')
            self.assertEqual((root/'catalogs/challenger-text.json').read_bytes(),original)
            self.assertEqual(result['modalities']['text']['challenger_catalog']['sha256'],analysis.sha(source))
            self.assertEqual(result['modalities']['text']['status'],'ADOPTED')


if __name__ == '__main__':
    unittest.main()
