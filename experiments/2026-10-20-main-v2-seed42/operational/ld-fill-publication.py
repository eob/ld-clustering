#!/usr/bin/env python3
"""Map already-verified complete archived evidence into the website DTO; no API calls."""
import argparse,datetime,hashlib,json,pathlib,re,subprocess
p=argparse.ArgumentParser()
p.add_argument('--repo',type=pathlib.Path,default=pathlib.Path('/mnt/disks/data/ld-clustering'))
p.add_argument('--site',type=pathlib.Path,default=pathlib.Path('/mnt/disks/data/kaya-web/feat-ld-clustering-report'))
p.add_argument('--commit',required=True)
p.add_argument('--published-at',required=True)
a=p.parse_args()
assert re.fullmatch('[0-9a-f]{40}',a.commit)
assert datetime.datetime.fromisoformat(a.published_at.replace('Z','+00:00')).tzinfo
primary='experiments/2026-10-20-main-v2-seed42'
control='experiments/2026-10-20-frozen-images-v2-seed42'
read=lambda path:json.loads(path.read_text())
def git_blob(path):
 return subprocess.check_output(['git','show',f'{a.commit}:{path}'],cwd=a.repo)
manifests={run:json.loads(git_blob(f'{run}/manifest.json')) for run in (primary,control)}
def archived(run,name):
 raw=git_blob(f'{run}/{name}')
 entry=next(entry for entry in manifests[run]['files'] if entry['path']==name)
 assert hashlib.sha256(raw).hexdigest()==entry['sha256'],f'payload differs from committed manifest: {run}/{name}'
 return json.loads(raw)
manifest=manifests[primary]
assert manifest['status']=='complete'
assert manifest['runtime_source_commit']=='9ba8ac4ec759f3b48bdb83fa02a9bd7bba16ea8c'
assert manifest['binary_sha256']=='8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160'
assert manifest['externally_resumed_roles']==[]
# Bind publication to an existing immutable commit that contains both archives.
for run in (primary,control):
 for name in ('manifest.json','SHA256SUMS'):
  committed=git_blob(f'{run}/{name}')
  assert committed==(a.repo/run/name).read_bytes(),f'commit does not bind {run}/{name}'
path=a.site/'apps/edwardbenson/app/goofing/ld-clustering/publication.json'
data=read(path)
fields=('cost_complete','timing_complete','timing_scope','sample_count','wall_seconds','cost_usd','calls','error_calls','unknown_usage_calls','assignment_calls','assignment_refusal_calls','maintenance_calls','input_tokens','output_tokens','cluster_count','coverage')
for experiment in data['experiments']:
 result=archived(primary,f"{experiment['id']}-results.json")
 assert result['status']=='complete' and result['expected_count']==experiment['count']
 assert result['config']['k']==8 and result['config']['max_clusters']==16
 for mode in ('baseline','ld'):
  arm=result[mode]
  assert arm['sample_count']==experiment['count'] and arm['run_sessions']==1
  assert arm['timing_complete'] and arm['timing_scope']=='uninterrupted_loop'
  experiment[mode]={k:arm[k] for k in fields}
 experiment['agreement']={k:result['agreement'][k] for k in ('adjusted_rand_index','pairwise_precision','pairwise_recall','pairwise_f1')}
 experiment['agreement']['shared_other_ari']=result['shared_other_sensitivity']['adjusted_rand_index']
 experiment['status']='complete'
summary=archived(control,'independent-results.json')
assert summary['status']=='complete' and summary['expected_per_arm']==100
cat_manifest=manifests[control]
assert cat_manifest['status']=='complete' and cat_manifest['experiment']=='post-hoc-frozen-catalog-images'
assert cat_manifest['control_source_commit']==manifest['runtime_source_commit']
assert cat_manifest['control_binary_sha256']=='35e0db257343ed1083bf2ef7187f4e0736985f288ddcf70426dfdd4afbac27ff'
assert cat_manifest['expected_per_arm']==100 and cat_manifest['catalog_cluster_count']==11 and cat_manifest['k']==8
cat_hash=cat_manifest['catalog_sha256']
assert cat_hash=='7f0950b69ea360d694fd6d5dc58b30d74e89d69fbc172ad88757499161d16942'
frozen={'status':'complete','count':100,'catalog_cluster_count':11,'catalog_sha256':cat_hash,'run_path':control}
for label,mode in (('baseline','llm'),('ld','ld')):
 output=archived(control,f'{mode}.json')
 assert output['status']=='complete' and output['processed_count']==100 and output['timing_complete']
 measurement=output['measurement']
 usage=measurement['usage']
 verified=summary['runs'][mode]
 for field in ('calls','error_calls','unknown_usage_calls','assignment_refusal_calls'):
  assert measurement[field]==verified[field],f'control summary differs: {mode}/{field}'
 assert measurement['cost_complete']==(verified['unknown_usage_calls']==0)
 assert abs(measurement['cost_usd']-float(verified['known_recorded_cost_usd']))<1e-9
 assert output['wall_seconds']==verified['wall_seconds'] and output['coverage']==verified['coverage']
 frozen[label]={'cost_complete':measurement['cost_complete'],'timing_complete':True,'timing_scope':'uninterrupted_loop','sample_count':100,'wall_seconds':output['wall_seconds'],'cost_usd':measurement['cost_usd'],'calls':measurement['calls'],'error_calls':measurement['error_calls'],'unknown_usage_calls':measurement['unknown_usage_calls'],'assignment_calls':measurement['calls'],'assignment_refusal_calls':measurement['assignment_refusal_calls'],'maintenance_calls':0,'input_tokens':usage['input_tokens'],'output_tokens':usage['output_tokens'],'cluster_count':11,'coverage':output['coverage']}
frozen['agreement']={k:summary['metrics']['agreement'][k] for k in ('adjusted_rand_index','pairwise_precision','pairwise_recall','pairwise_f1')}
frozen['agreement']['shared_other_ari']=summary['metrics']['shared_other_sensitivity']['adjusted_rand_index']
frozen['agreement']['direct_assignment_agreement']=summary['metrics']['direct_id_agreement']['fraction']
data.update(status='complete',published_at=a.published_at,frozen_catalog_control=frozen)
data['source'].update(commit=a.commit,run_path=primary,manifest_sha256=hashlib.sha256(git_blob(f'{primary}/manifest.json')).hexdigest(),runtime_commit=manifest['runtime_source_commit'],executable_sha256=manifest['binary_sha256'])
path.write_text(json.dumps(data,indent=2)+'\n')
print('Mapped verified primary and separate fixed-catalog artifacts to',path)
