#!/usr/bin/env python3
"""One explicit recovery after a clean, journaled plan-validation rejection."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time
ROOT = Path('/mnt/disks/data/ld-clustering')
RUN = ROOT/'runs/main-seed42-detached'
assert not Path('/proc/1039704').exists(), 'Original text LD process is still live'
db = sqlite3.connect(f'file:{RUN/"text-ld.sqlite"}?mode=ro',uri=True)
meta = dict(db.execute('select key,value from meta'))
assert meta['run_in_progress']=='0' and meta['timing_complete']=='true'
assert 'completed_count' not in meta
config = json.loads(meta['config'])
assert meta['backend']=='ld' and db.execute('select count(*) from points').fetchone()[0]==607
assert db.execute('pragma integrity_check').fetchall()==[('ok',)]
rows=(RUN/'text-ld.calls.jsonl').read_text().splitlines()
last=json.loads(rows[-1])
assert last['error']=='plan references cluster 25 more than once' and last['usage_available'] is True
assert hashlib.sha256((ROOT/'target/release/ld-clustering').read_bytes()).hexdigest()=='ef1d211d0808a688554f46995cd3370ee98d53b78760dff2fd2026c382c203ee'
history = {'status':'starting','reason':'Clean rejection of conflicting LLM maintenance plan; exact source/binary/config resumed once','original_process_pid':1039704,'last_original_attempt_row':len(rows),'last_original_attempt_recorded_at_unix_ms':last['recorded_at_unix_ms'],'original_meta':meta,'original_journal_sha256':hashlib.sha256((RUN/'text-ld.calls.jsonl').read_bytes()).hexdigest(),'resumed_at_unix_ms':time.time_ns()//1000000,'timing_scope':'SQLite wall_ms sums measured clustering loops; manual pause and CLI validation are excluded. Calendar duration below includes pause and validation.'}
path=RUN/'text-ld-resume-history.json'
with path.open('x') as f: json.dump(history,f,indent=2);f.write('\n')
command=[str(ROOT/'target/release/ld-clustering'),'run','--input',str(ROOT/'data/text.jsonl'),'--database',str(RUN/'text-ld.sqlite'),'--log',str(RUN/'text-ld.calls.jsonl'),'--mode','ld','--task',config['task']]
for key,flag in [('k','--k'),('max_clusters','--max-clusters'),('bootstrap_size','--bootstrap'),('novelty_trigger','--novelty'),('maintenance_interval','--maintenance-interval')]:command += [flag,str(config[key])]
print(json.dumps({'status':'resuming','point_count':607,'pause_since_last_attempt_seconds':(history['resumed_at_unix_ms']-last['recorded_at_unix_ms'])/1000}),flush=True)
start=time.monotonic_ns()
with (RUN/'text-ld.resume1.process.log').open('xb') as output:
    result=subprocess.run(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
history.update(status='terminal',exit_code=result.returncode,finished_at_unix_ms=time.time_ns()//1000000,resume_process_seconds=(time.monotonic_ns()-start)/1e9)
meta2=dict(db.execute('select key,value from meta'))
history['final_meta']=meta2
history['calendar_seconds_from_initial_cli_metadata']=(history['finished_at_unix_ms']-int(meta['started_at_unix_ms']))/1000
history['manual_pause_since_last_attempt_seconds']=(history['resumed_at_unix_ms']-last['recorded_at_unix_ms'])/1000
path.write_text(json.dumps(history,indent=2)+'\n')
print(json.dumps({'status':'terminal','exit_code':result.returncode}),flush=True)
raise SystemExit(result.returncode)
