import hashlib
import json
import os
import signal
import time
import uuid
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_auto_research.py'
launcher = types.ModuleType('auto_research_launcher')
launcher.__file__ = str(SCRIPT)
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), 'exec'), launcher.__dict__)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


FAKE = r'''#!/usr/bin/env python3
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
source=Path(os.environ['FAKE_SOURCE'])
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
if sys.argv[1]=='source-pins':
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
 files=json.loads((source/'source-files.json').read_text())
 print(json.dumps(dict(commit=commit,committed_sources_verified=True,executable_sha256=sha(__file__),embedded_file_sha256={p:sha(source/p) for p in files})));sys.exit(0)
a=dict(zip(sys.argv[2::2],sys.argv[3::2])) if '--dry-run' not in sys.argv else dict(zip(sys.argv[2:-1:2],sys.argv[3:-1:2]))
if '--dry-run' in sys.argv:
 import struct
 raw=Path(a['--input']).read_bytes();digest=hashlib.sha256(b'ld-clustering-input-v1\0'+struct.pack('<Q',len(raw))+raw)
 print(json.dumps(dict(dry_run=True,input_sha256=digest.hexdigest(),catalog_sha256=sha(a['--catalog']),protocol_sha256=sha(a['--protocol']),effective_order=json.loads(Path(a['--order']).read_text()),order_file_sha256=sha(a['--order']),k=int(a['--k']),mode=a['--mode'],stage=a['--stage'],expected_count=int(a['--expected']))));sys.exit(0)
assert os.environ.get('OPENAI_API_KEY')=='literal-dummy-no-api-fixture'
assert (Path.cwd()/'registrations/calibration/registration.json').is_file()
output=Path(a['--output']);output.parent.mkdir(parents=True,exist_ok=True)
if os.environ.get('FAKE_TREE')=='1':
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(3600)'],start_new_session=True)
 write=Path(os.environ['FAKE_EVENTS']);write.mkdir(exist_ok=True)
 (write/(str(os.getpid())+'.json')).write_text(json.dumps(dict(pid=os.getpid(),child=child.pid,mode=a['--mode'])))
 if os.environ.get('FAKE_DAMAGE_SOURCE')=='1':(source/'src/provider.rs').write_text('changed runtime fixture')
 stopping=False
 def stop(signum,frame):
  global stopping
  stopping=True
 signal.signal(signal.SIGTERM,stop)
 while not stopping:time.sleep(.02)
 child.terminate();child.wait();sys.exit(143)
output.write_text(json.dumps(dict(schema_version=1,experiment='guidance-auto-research',status='complete',expected_count=int(a['--expected']),processed_count=int(a['--expected']),measurement=dict(cost_complete=True,cost_history_complete=True))))
Path(a['--log']).write_text('preserved fake journal\n');Path(a['--output']).with_suffix('.progress.jsonl').write_text('preserved fake progress\n')
'''


class Fixture:
    def __init__(self, root, repetitions=1):
        self.root=root;self.repo=root/'repo';self.run=root/'run';self.fixtures=self.repo/'experiments/study'
        self.repo.mkdir();self.run.mkdir();self.fixtures.mkdir(parents=True)
        (self.repo/'scripts').mkdir();(self.repo/'scripts/run_auto_research.py').write_bytes(SCRIPT.read_bytes())
        source_names=['src/agreement.rs','src/agreement_metrics.rs','src/agreement_review.rs','src/provider.rs','src/types.rs','src/lib.rs','examples/guided_agreement.rs','Cargo.toml','Cargo.lock','src/auto_research.rs','examples/auto_research.rs']
        for name in source_names:
            path=self.repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('frozen fixture '+name)
        write(self.repo/'source-files.json',source_names)
        self.binary=root/'fake-auto';self.binary.write_text(FAKE);self.binary.chmod(0o755)
        self.old_env=dict(os.environ);os.environ['FAKE_SOURCE']=str(self.repo)
        os.environ['OPENAI_API_KEY']='literal-dummy-no-api-fixture'
        items=[dict(id='opaque-one',text='Classify this evidence.')]
        inp=self.run/'calibration/items.jsonl';inp.parent.mkdir();inp.write_text(json.dumps(items[0])+'\n')
        design=dict(schema_version=1,design_id='short-v1',modality='text',task='Classify the subject.',definitions=[dict(id=11,name='One',description='Membership.')],provenance=dict(origin='constructed',evidence_ids=[]))
        write(self.run/'calibration/design.json',design);write(self.run/'calibration/order.json',[11])
        self.conditions=[]
        for index,mode in [(index,mode) for index in range(repetitions) for mode in ('llm','ld')]:
            id='calibration-'+str(index)+'-'+mode
            self.conditions.append(dict(id=id,kind='classification',command='classify',phase='calibration',round=1,stage='calibration',modality='text',mode=mode,k=8,expected_count=1,role='synthetic_calibration',input='calibration/items.jsonl',input_jsonl_sha256=sha(inp),input_sha256=None,catalog='calibration/design.json',catalog_sha256=sha(self.run/'calibration/design.json'),order='calibration/order.json',order_file_sha256=sha(self.run/'calibration/order.json'),protocol='preregistration/protocol.json',output=id+'.json',log=id+'.calls.jsonl',progress=id+'.progress.jsonl'))
        registry=dict(schema_version=1,experiment='guidance-auto-research',conditions=self.conditions,comparisons=[],phase_order=['calibration'])
        write(self.fixtures/'conditions.json',registry)
        prior=dict(schema_version=1,partitions={})
        write(self.run/'preregistration/prior-dataset-manifest.json',prior)
        dataset=dict(schema_version=3,experiment='guidance-auto-research',partitions={},photos={},prior_dataset_manifest_sha256=sha(self.run/'preregistration/prior-dataset-manifest.json'))
        write(self.run/'preregistration/dataset-manifest.json',dataset)
        protocol=dict(schema_version=1,experiment='guidance-auto-research',conditions_sha256=sha(self.fixtures/'conditions.json'),data=dict(dataset_manifest_sha256=sha(self.run/'preregistration/dataset-manifest.json')),fixed_fixture_sha256={},runtime_registration=dict(concurrency=dict(maximum_sol_workers=2,maximum_native_workers=2,maximum_total_workers=4)))
        write(self.fixtures/'protocol.json',protocol)
        for name in ('protocol.json','conditions.json'):
            (self.run/'preregistration'/name).write_bytes((self.fixtures/name).read_bytes())
        for name in ['v2-text']+[f'guided-{split}-{m}' for split in ('discovery','heldout','streaming') for m in ('text','images')]:
            p=self.run/'prior-inputs'/(name+'.jsonl');p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(dict(id=name,text='Prior '+name))+'\n')
        prior['partitions']={split:{m:dict(jsonl_sha256=sha(self.run/'prior-inputs'/(f'guided-{split}-{m}.jsonl'))) for m in ('text','images')} for split in ('discovery','heldout','streaming')}
        write(self.run/'preregistration/prior-dataset-manifest.json',prior)
        dataset['prior_dataset_manifest_sha256']=sha(self.run/'preregistration/prior-dataset-manifest.json')
        dataset['previous_text_sha256']=sha(self.run/'prior-inputs/v2-text.jsonl')
        write(self.run/'preregistration/dataset-manifest.json',dataset)
        protocol['data']['dataset_manifest_sha256']=sha(self.run/'preregistration/dataset-manifest.json')
        write(self.fixtures/'protocol.json',protocol)
        (self.run/'preregistration/protocol.json').write_bytes((self.fixtures/'protocol.json').read_bytes())
        subprocess.run(['git','init','-q','-b','feat-fixture'],cwd=self.repo,check=True)
        subprocess.run(['git','add','.'],cwd=self.repo,check=True)
        subprocess.run(['git','-c','user.name=Offline','-c','user.email=offline@example.invalid','-c','commit.gpgsign=false','commit','-qm','Freeze fixture'],cwd=self.repo,check=True)
        self.args=types.SimpleNamespace(run_root=self.run,source_repo=self.repo,fixtures=self.fixtures,binary=self.binary,phase='calibration',mode='plan',adaptive_registration=None,systemd_unit=None)
    def close(self):
        os.environ.clear();os.environ.update(self.old_env)


class LauncherTests(unittest.TestCase):
    def test_plan_is_read_only_and_binds_all_registered_arms_and_input_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp))
            try:
                before={str(p.relative_to(f.run)):p.read_bytes() for p in f.run.rglob('*') if p.is_file()}
                plan=launcher.prepare(f.args)
                self.assertEqual(len(plan['conditions']),2)
                self.assertEqual(plan['conditions'][0]['input']['ordered_ids'],['opaque-one'])
                self.assertEqual(plan['conditions'][0]['kind'],'classify')
                self.assertEqual(before,{str(p.relative_to(f.run)):p.read_bytes() for p in f.run.rglob('*') if p.is_file()})
            finally:f.close()

    def test_changed_fixed_bytes_and_existing_arm_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp))
            try:
                (f.run/'calibration/design.json').write_text('{}')
                with self.assertRaises(ValueError):launcher.prepare(f.args)
            finally:f.close()

    def test_existing_arm_and_changed_runtime_refuse_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp))
            try:
                path=f.run/f.conditions[0]['output'];path.write_text('previous evidence')
                with self.assertRaises(ValueError):launcher.prepare(f.args)
                self.assertEqual(path.read_text(),'previous evidence')
                path.unlink()
                (f.repo/'src/provider.rs').write_text('changed runtime')
                with self.assertRaises(ValueError):launcher.prepare(f.args)
                self.assertFalse((f.run/'registrations').exists())
            finally:f.close()

    def test_boundary_generation_binds_text_labels_images_and_exact_sealed_selection(self):
        for modality in ('text','images'):
            with self.subTest(modality=modality), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                old=dict(id='old',text='Old evidence',label='old-label')
                dev=dict(id='selected',text='Development evidence',label='dev-label')
                photos={}
                if modality=='images':
                    for name,row in [('old',old),('selected',dev)]:
                        image=root/'images'/(name+'.jpg');image.parent.mkdir(exist_ok=True);image.write_bytes(b'\xff\xd8\xff'+name.encode())
                        row['image']='../images/'+name+'.jpg'
                        photos[name]=dict(supplied_sha256=sha(image))
                    dev['image']='../../images/selected.jpg'
                old_path=root/'discovery'/(modality+'.jsonl');old_path.parent.mkdir();old_path.write_text(json.dumps(old)+'\n')
                dev_path=root/'inputs/development'/(modality+'.jsonl');dev_path.parent.mkdir(parents=True);dev_path.write_text(json.dumps(dev)+'\n')
                write(root/'preregistration/dataset-manifest.json',dict(partitions=dict(development={modality:dict(jsonl_sha256=sha(dev_path))}),photos=photos))
                write(root/'preregistration/prior-dataset-manifest.json',dict(partitions=dict(discovery={modality:dict(jsonl_sha256=sha(old_path))}),photos=photos))
                catalog=dict(definitions=[dict(id=11,name='One',description='Membership')])
                case=dict(case_id='case',text=dev['text'],pairs=[dict(catalog=catalog['definitions'])])
                if modality=='images':case.update(image='images/selected.jpg',image_sha256=photos['selected']['supplied_sha256'])
                write(root/'packet.json',dict(phase='development',modality=modality,cases=[case]))
                write(root/'key.json',dict(phase='development',modality=modality,keys=[dict(case_id='case',item_id='selected')]))
                refs=[dict(role='key:'+modality,path='key.json'),dict(role='packet:'+modality,path='packet.json')]
                combined=[dict(old),dict(dev)]
                if modality=='images':combined[1]['image']='../images/selected.jpg'
                combined_path=root/'generation'/(modality+'.jsonl');combined_path.parent.mkdir()
                def run(rows):
                    combined_path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                    frozen,actual,_=launcher.input_pin(root,str(combined_path.relative_to(root)),modality)
                    launcher.validate_boundary_evidence(root,modality,actual,frozen,refs,catalog)
                run(combined)
                for field in ('text','label'):
                    changed=[dict(row) for row in combined];changed[1][field]='changed under same ID'
                    with self.assertRaises(ValueError):run(changed)
                write(root/'key.json',dict(phase='development',modality=modality,keys=[]))
                with self.assertRaises(ValueError):run(combined)
                write(root/'key.json',dict(phase='development',modality=modality,keys=[dict(case_id='case',item_id='selected')]))
                if modality=='images':
                    (root/'images/selected.jpg').write_bytes(b'changed photograph under same ID')
                    with self.assertRaises(ValueError):run(combined)

    def test_successful_phase_registers_before_dispatch_and_cannot_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp))
            try:
                # Unrelated offline tooling may change while the paid runtime stays frozen.
                (f.repo/'scripts/offline-postprocess.py').write_text('unrelated draft')
                plan=launcher.prepare(f.args)
                with mock.patch.object(launcher,'containment',return_value=dict(fixture=True)):
                    self.assertEqual(launcher.execute(plan,f.args),0)
                folder=f.run/'registrations/calibration'
                receipt=read_json(folder/'supervisor-terminal.json')
                self.assertEqual(receipt['status'],'complete')
                self.assertEqual(len(receipt['conditions']),2)
                self.assertTrue(all(row['successful'] for row in receipt['conditions']))
                self.assertEqual((f.run/f.conditions[0]['log']).read_text(),'preserved fake journal\n')
                with self.assertRaises(ValueError):launcher.prepare(f.args)
            finally:f.close()

    def test_run_requires_declared_systemd_containment_before_creating_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(Path(tmp))
            try:
                plan=launcher.prepare(f.args)
                with self.assertRaises(ValueError):launcher.execute(plan,f.args)
                self.assertFalse((f.run/'registrations').exists())
            finally:f.close()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        result=subprocess.run(['systemctl','--user','show-environment'],capture_output=True)
        if result.returncode:
            self.skipTest('user systemd bus unavailable; run lifecycle fixtures on production Linux host')

    def wait_for(self, predicate):
        deadline=time.monotonic()+60
        while True:
            result=predicate()
            if result:
                return result
            if time.monotonic()>deadline:
                self.fail('fixture failed to reach its required process state (watchdog, not a performance assertion)')
            time.sleep(.03)

    def lifecycle(self, violent, damage=False):
        with tempfile.TemporaryDirectory(prefix='auto-launcher-tree-') as tmp:
            f=Fixture(Path(tmp),repetitions=4)
            unit='auto-launcher-fixture-'+uuid.uuid4().hex+'.service'
            events=Path(tmp)/'events'
            processes=[]
            try:
                command=['systemd-run','--user','--quiet','--unit',unit,'--service-type=exec',
                    '--property=KillMode=control-group','--property=RemainAfterExit=yes',
                    '--property=TimeoutStopSec=10s','--setenv=PYTHONDONTWRITEBYTECODE=1',
                    '--setenv=FAKE_SOURCE='+str(f.repo),'--setenv=FAKE_TREE=1',
                    '--setenv=FAKE_EVENTS='+str(events),'--setenv=FAKE_DAMAGE_SOURCE='+('1' if damage else '0'),
                    '--setenv=OPENAI_API_KEY=literal-dummy-no-api-fixture',
                    'python3',str(SCRIPT),'run','--run-root',str(f.run),'--source-repo',str(f.repo),
                    '--fixtures',str(f.fixtures),'--binary',str(f.binary),'--phase','calibration',
                    '--systemd-unit',unit]
                subprocess.run(command,check=True,capture_output=True)
                self.wait_for(lambda: events.exists() and (len(list(events.glob('*.json')))>=1 if damage else len(list(events.glob('*.json')))==4))
                ready=[json.loads(path.read_text()) for path in events.glob('*.json')]
                if not damage:self.assertEqual(sorted(row['mode'] for row in ready),['ld','ld','llm','llm'])
                processes=[pid for row in ready for pid in (row['pid'],row['child'])]
                main=int(subprocess.check_output(['systemctl','--user','show',unit,'--property=MainPID','--value'],text=True).strip())
                if not damage:self.assertGreater(main,0)
                if not damage:os.kill(main,signal.SIGKILL if violent else signal.SIGTERM)
                terminal=f.run/'registrations/calibration/supervisor-terminal.json'
                if not violent:
                    self.wait_for(terminal.exists)
                    value=read_json(terminal)
                    self.assertEqual(value['status'],'failed')
                    started=len(list((terminal.parent/'started').glob('*.json')))
                    self.assertEqual(len(value['conditions']),started)
                    self.assertEqual(len(value['not_started']),8-started)
                    self.assertGreater(started,0)
                    if damage:self.assertIn('source',value['error'])
                    self.assertTrue(all(row['in_flight_completion_unknown'] and not row['cost_complete'] for row in value['conditions']))
                    self.assertEqual(len(list((terminal.parent/'terminal').glob('*.json'))),started)
                self.wait_for(lambda: all(not Path('/proc',str(pid)).exists() for pid in processes))
                self.assertTrue((f.run/'registrations/calibration/registration.json').exists())
                if violent:
                    self.assertFalse(terminal.exists(),'violent death must not fabricate a clean terminal receipt')
            finally:
                subprocess.run(['systemctl','--user','stop',unit],capture_output=True)
                subprocess.run(['systemctl','--user','reset-failed',unit],capture_output=True)
                for pid in processes:
                    if Path('/proc',str(pid)).exists():
                        try:os.kill(pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                f.close()

    def test_graceful_supervisor_stop_reaps_separate_session_descendants_and_bounds_workers(self):
        self.lifecycle(False)

    def test_exception_cleanup_keeps_terminal_receipt_for_every_started_child(self):
        self.lifecycle(False, damage=True)

    def test_violent_supervisor_death_is_contained_by_systemd_control_group(self):
        self.lifecycle(True)


def read_json(path):
    return json.loads(path.read_bytes())


if __name__=='__main__':unittest.main()
