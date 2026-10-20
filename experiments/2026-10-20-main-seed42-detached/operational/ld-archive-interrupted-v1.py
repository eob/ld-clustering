"""Preserve the terminal, incomplete second pre-amendment cohort without API calls."""
import importlib.util,sqlite3,json,os,shutil,tempfile,io,gzip,subprocess
from pathlib import Path
from collections import Counter
from decimal import Decimal
spec=importlib.util.spec_from_file_location('v1','/tmp/ld-archive-final-v1.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
repo=Path('/mnt/disks/data/ld-clustering');run=repo/'runs/main-seed42-detached';prior=repo/'experiments/2026-10-20-main-seed42';out=repo/'experiments/2026-10-20-main-seed42-detached';binary=Path('/tmp/ld-clustering-v1-frozen')
m.require(not out.exists(),'second archive already exists')
m.require(m.file_sha(binary)==m.BINARY_SHA,'frozen executable changed')
m.require(not m.live_primary_processes(run),'primary/resume CLI is still running')
m.require(m.file_sha(run/'dataset-manifest.json')==m.DATA_SHA,'data manifest changed')
pinned=m.pinned_inputs(prior);old=json.loads((prior/'manifest.json').read_text());old_files={x['path']:x for x in old['files']}
known_key=os.environ.get('OPENAI_API_KEY','').encode();sources={};states={};outcomes={};costs={};all_refusals=[]
with tempfile.TemporaryDirectory(prefix='.ld-interrupted-stage-',dir=out.parent) as temporary:
 stage=Path(temporary)
 for name in ['inputs.tar.gz','pricing.json','licenses/ATTRIBUTION.txt','licenses/clinc-CC-BY-3.0.txt','licenses/fashion-MIT.txt']:
  m.require(m.file_sha(prior/name)==old_files[name]['sha256'],f'prior archive file changed: {name}')
  target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(prior/name,target)
 for name in ['source-commit.txt','binary-sha256.txt','launched-at.txt','dataset-manifest.json']:
  shutil.copyfile(run/name,stage/name)
 (stage/'runtime-source-commit.txt').write_text(m.SOURCE+'\n')
 primary=set()
 for dataset,expected in m.EXPECTED.items():
  for arm in ['llm','ld']:
   role=f'{dataset}-{arm}'
   for suffix in ['sqlite','calls.jsonl','process.log']:
    source=run/f'{role}.{suffix}';primary.add(source.name)
    m.require(not known_key or known_key not in source.read_bytes(),f'configured credential found: {source.name}')
    sources[source.name]=m.file_sha(source);m.gzip_exact(source,stage/f'{source.name}.gz')
   for sidecar in ['-journal','-wal','-shm']:
    source=run/f'{role}.sqlite{sidecar}'
    if source.exists():
     sources[source.name]=m.file_sha(source);m.gzip_exact(source,stage/f'{source.name}.gz')
 # Retain all cohort operational files, including recovery history/logs, without Python caches.
 for source in sorted(run.iterdir()):
  if not source.is_file() or source.name in primary or source.name in ['source-commit.txt','binary-sha256.txt','launched-at.txt','dataset-manifest.json'] or '.sqlite-' in source.name:continue
  m.require(not known_key or known_key not in source.read_bytes(),f'configured credential found: {source.name}')
  target=stage/'operational'/source.name;target.parent.mkdir(exist_ok=True)
  sources[source.name]=m.file_sha(source)
  if source.suffix=='.log':m.gzip_exact(source,Path(str(target)+'.gz'))
  else:shutil.copyfile(source,target)
 for source in [Path('/tmp/ld-archive-final-v1.py'),Path('/tmp/ld-archive-final-v1.README.md'),Path(__file__),repo/'runs/frozen-images-seed42/after-main.py',repo/'runs/frozen-images-seed42/catalog.json',repo/'runs/frozen-images-seed42/catalog-source.json',repo/'runs/frozen-images-seed42/supervisor.log']:
  if not source.exists():continue
  m.require(not known_key or known_key not in source.read_bytes(),f'configured credential found in operational file: {source.name}')
  name=source.name if source.parent!=repo/'runs/frozen-images-seed42' else 'unrun-control-'+source.name
  target=stage/'operational'/name;target.parent.mkdir(exist_ok=True)
  if source.suffix=='.log':m.gzip_exact(source,Path(str(target)+'.gz'))
  else:shutil.copyfile(source,target)
 for dataset,expected in m.EXPECTED.items():
  for arm in ['llm','ld']:
   role=f'{dataset}-{arm}';db=sqlite3.connect(f'file:{run/f"{role}.sqlite"}?mode=ro',uri=True);db.execute('BEGIN')
   meta=dict(db.execute('SELECT key,value FROM meta'));rows=[]
   for ident,ordinal,payload,cid in db.execute('SELECT p.id,p.ordinal,p.payload,a.cluster_id FROM points p JOIN assignments a ON p.id=a.point_id ORDER BY p.ordinal'):
    item=json.loads(payload);m.require(item['id']==ident and ordinal==len(rows),'point identity or ordinal differs');rows.append((item,cid))
   m.require([p for p,c in rows]==pinned[dataset]['items'][:len(rows)],f'persisted prefix differs from pinned data: {role}')
   m.require(meta['input_sha256']==pinned[dataset]['input_sha256'],f'input hash differs: {role}')
   committed=Counter();first_plan=None
   for payload, in db.execute('SELECT payload FROM calls ORDER BY id'):
    call=json.loads(payload);committed[m.sha(m.canonical({k:call[k] for k in m.CALL_FIELDS}))]+=1
    if first_plan is None and call['phase']=='plan':first_plan=call['request']
   clusters=[{'id':cid,'name':name,'description':description,'active':bool(active)} for cid,name,description,active in db.execute('SELECT id,name,description,active FROM clusters ORDER BY id')]
   maintenance=[{'id':eid,'created_at':created,'plan':json.loads(payload)} for eid,payload,created in db.execute("SELECT id,payload,created_at FROM events WHERE kind='maintenance' ORDER BY id")]
   pending=db.execute('SELECT COUNT(*) FROM reassignment').fetchone()[0];npoints=db.execute('SELECT COUNT(*) FROM points').fetchone()[0];nassign=db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0]
   integrity=db.execute('PRAGMA integrity_check').fetchall();foreign=db.execute('PRAGMA foreign_key_check').fetchall();db.close()
   m.require(integrity==[('ok',)] and not foreign,f'raw SQLite integrity failed: {role}')
   states[role]={'meta':meta,'rows':rows,'clusters':clusters,'maintenance':maintenance,'committed':committed,'first_plan':first_plan}
   complete=meta.get('completed_count')==str(expected) and npoints==nassign==expected and pending==0 and meta.get('run_in_progress')=='0'
   inflight=not complete and meta.get('run_in_progress')=='1'
   outcomes[role]={'expected_points':expected,'persisted_points':npoints,'persisted_assignments':nassign,'pending_reassignments':pending,'complete_assignments':complete,'raw_meta':meta,'sqlite_integrity_check':'ok','foreign_key_failures':[],'unrecorded_inflight_request_possible':inflight,'recorded_loop_timing_complete':meta.get('timing_complete')=='true' and meta.get('run_in_progress')=='0','timing_complete':complete and meta.get('timing_complete')=='true','active_loop_seconds':int(meta['wall_ms'])/1000 if 'wall_ms' in meta else None,'timing_scope':'Measured active clustering-loop segments only. Incomplete text is not a 1000-point result; text-LD includes a graceful external resume and excludes downtime.'}
 ledger=io.BytesIO();ledger.write(m.canonical({'type':'ld-clustering-attempt-ledger','schema_version':1,'source_line_numbers':'1-based original JSONL including header','cohort_status':'interrupted'})+b'\n')
 for role,s in states.items():
  costs[role]=m.audit_journal(run/f'{role}.calls.jsonl',role,s,ledger)
  total=sum(Decimal(v['known_recorded_cost_usd']) for v in costs[role]['components'].values())
  unknown=costs[role]['unknown_usage_source_jsonl_lines']
  outcomes[role].update(recorded_attempts=sum(x['attempts'] for x in costs[role]['components'].values()),known_recorded_cost_usd=str(total),unknown_usage_source_jsonl_lines=unknown,cost_complete=not unknown and not outcomes[role]['unrecorded_inflight_request_possible'],failed_attempts=costs[role]['failed_attempts'])
  for line_number,line in enumerate((run/f'{role}.calls.jsonl').open(),1):
   row=json.loads(line)
   if line_number==1:continue
   for answer in row.get('response',{}).get('answers',[]):
    if answer.get('type')=='refusal':
     all_refusals.append({'role':role,'source_jsonl_line':line_number,'attempt':row.get('attempt'),'http_status':row.get('http_status'),'model':row.get('model'),'answer':answer,'error':row.get('error'),'usage_available':row.get('usage_available'),'provider_usage':row['response'].get('usage'),'known_recomputed_cost_usd':str(m.priced_usage(row)) if row['usage_available'] else None,'recorded_at_unix_ms':row.get('recorded_at_unix_ms')})
 with open(stage/'attempt-ledger.jsonl.gz','wb') as raw:
  with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as zipped:zipped.write(ledger.getvalue())
 m.compare(binary,run,'images',100,stage/'images-results.json')
 image_summary=json.loads((stage/'images-results.json').read_text())
 m.write_json(stage/'independent-verification.json',{'status':'interrupted','complete_image_metrics':m.verify_metrics(states['images-llm'],states['images-ld'],image_summary),'text':'No cross-arm text metrics: reference/LD prefixes incomplete and unequal.','pinned_input_checks':'Every persisted point payload matches its frozen input prefix; full input fingerprints and all PNG pins verified.'})
 for dataset in ['images','text']:
  m.write_json(stage/f'{dataset}-partitions.json',{'status':'complete' if dataset=='images' else 'incomplete','expected_count':m.EXPECTED[dataset],**{arm:m.partitions(states[f'{dataset}-{arm}']) for arm in ['llm','ld']}})
 m.write_json(stage/'attempt-outcome.json',{'status':'interrupted','reason':'Protocol amendment after typed native refusal terminated text LD at779; root then explicitly stopped the old primary supervisor and queued control. The waiting control made no calls.','supervisor_exit_status':None,'supervisor_result':'unknown: collected unit is not evidence of success','runs':outcomes})
 m.write_json(stage/'cost-split.json',{'basis':'Known token-priced usage, not invoices. Failed/refused attempts with reported usage are charged in this ledger. Missing usage and unrecorded in-flight requests are unknown, never zero.','runs':costs})
 m.write_json(stage/'native-refusals.json',{'status':'interrupted','context':'The refused item is classification evidence, not an instruction to fill any credit-card field. No handling amendment has been applied to this cohort.','refusals':all_refusals})
 m.write_json(stage/'runtime.json',{'runtime_source_commit':m.SOURCE,'launch_checkout_commit':(run/'source-commit.txt').read_text().strip(),'archive_checkout_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'binary_sha256':m.BINARY_SHA,'local_frozen_executable_copy':'/tmp/ld-clustering-v1-frozen','original_service':m.observe_service('ld-clustering-main-seed42-20261020.service'),'resume_service':m.observe_service('ld-clustering-text-ld-resume1-20261020.service'),'source_hashes':sources})
 (stage/'README.md').write_text('''# Second pre-amendment cohort: interrupted\n\nThis immutable archive retains all four terminal raw states and request journals\nfrom runs/main-seed42-detached. Images completed100points per arm; text did not\ncomplete1000points per arm and is not a headline full experiment. The text-LD\nresume stopped at779 on a typed native refusal, with known reported usage. The\nclassification item requested no real credit-card action. Root stopped the old\nprimary and queued control to amend protocol handling. The original text reference\nmay have had an unrecorded in-flight request; its final cost is unknown.\n\nNative refusals, all journal failures, unknown-usage line numbers and known token\ncharges remain in native-refusals.json, attempt-outcome.json and cost-split.json.\nRaw journal lines retain the original responses. No unknown charge is treated as\nzero. The complete image comparison remains a separate valid replicate, with its\nown two missing-usage HTTP503attempts. No full text comparison is fabricated.\n\nThe original resume history, recovery Python supervisor and unrun control waiter\nare preserved under operational/. Runtime source remains59656c06; source-commit.txt\nis the launch checkoutbdee72c. Later documentation HEADis recorded separately.\nThe frozen executable SHA-256 is retained, with a local exact copy available at\n/tmp/ld-clustering-v1-frozen before any protocol rebuild. Gzip timestamps are zero;\ndecompressed DB/log bytes match the recorded raw source hashes. Inputs, licenses\nand pricing are copied byte-identically from the earlier immutable archive.\n\nSQLite integrity/foreign keys and every persisted frozen input prefix were checked.\nIndependent complete-image all-pair metrics agree with the frozen Rust comparison.\nVerify SHA256SUMS before reading; manifest.json also records decompressed hashes.\nNo model API calls were made during archival. Do not merge this evidence with the\nnew amended-protocol cohort; results must retain their own source/model/protocol pins.\n''')
 for name,digest in sources.items():m.require(m.file_sha(run/name)==digest,f'raw source changed during capture: {name}')
 manifest={'schema_version':1,'status':'interrupted','complete_experiments':['images'],'incomplete_experiments':['text'],'pending_experiments':[],'source_code_commit':m.SOURCE,'runtime_source_commit':m.SOURCE,'launch_checkout_commit':(run/'source-commit.txt').read_text().strip(),'archive_checkout_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'binary_sha256':m.BINARY_SHA,'dataset_manifest_sha256':m.DATA_SHA,'protocol':'original pre-amendment behavior: native refusal terminates assignment; invalid manager plan terminates run','files':m.inventory(stage)}
 m.write_json(stage/'manifest.json',manifest)
 (stage/'SHA256SUMS').write_text(''.join(f'{m.file_sha(p)}  {p.relative_to(stage).as_posix()}\n' for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
 for line in (stage/'SHA256SUMS').read_text().splitlines():
  digest,name=line.split('  ',1);m.require(m.file_sha(stage/name)==digest,f'checksum failed: {name}')
 os.replace(stage,out)
 print(json.dumps({'archive':str(out),'status':'interrupted','manifest_sha256':m.file_sha(out/'manifest.json'),'raw_snapshot_verified':True,'refusals':all_refusals,'outcomes':{role:{k:v for k,v in info.items() if k in ['persisted_points','pending_reassignments','complete_assignments','known_recorded_cost_usd','unknown_usage_source_jsonl_lines','unrecorded_inflight_request_possible']} for role,info in outcomes.items()}},indent=2))
