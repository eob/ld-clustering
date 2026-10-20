#!/usr/bin/env python3
"""Run the preselected assignment control only after the primary cohort exits cleanly."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time

ROOT = Path('/mnt/disks/data/ld-clustering')
MAIN = ROOT / 'runs/main-v2-seed42'
OUT = ROOT / 'runs/frozen-images-v2-seed42'
PID = 1128943
START = Path(f'/proc/{PID}/stat').read_text().split()[21]
EXPECTED_BINARY = '8a59bbf1e8dbd991960d6bc76046d0e15e245cfc5a50ab724dd201a62e9e9160'
CONTROL_BINARY = ROOT / 'target/release/examples/frozen_catalog'
CONTROL_HASH = '35e0db257343ed1083bf2ef7187f4e0736985f288ddcf70426dfdd4afbac27ff'
assert hashlib.sha256(CONTROL_BINARY.read_bytes()).hexdigest() == CONTROL_HASH
CATALOG_HASH = hashlib.sha256((OUT / 'catalog.json').read_bytes()).hexdigest()

print(json.dumps({'status':'waiting_for_primary','primary_pid':PID,'control_binary_sha256':CONTROL_HASH,'catalog_sha256':CATALOG_HASH}), flush=True)
while True:
    try:
        observed_start = Path(f'/proc/{PID}/stat').read_text().split()[21]
    except FileNotFoundError:
        break
    assert observed_start == START, 'Primary PID was reused'
    time.sleep(15)

assert hashlib.sha256((ROOT/'target/release/ld-clustering').read_bytes()).hexdigest() == EXPECTED_BINARY
assert hashlib.sha256(CONTROL_BINARY.read_bytes()).hexdigest() == CONTROL_HASH
assert hashlib.sha256((OUT/'catalog.json').read_bytes()).hexdigest() == CATALOG_HASH
for dataset, expected in [('text',1000), ('images',100)]:
    for mode in ['llm','ld']:
        db = sqlite3.connect(f'file:{MAIN / (dataset+"-"+mode+".sqlite")}?mode=ro', uri=True)
        meta = dict(db.execute('select key,value from meta'))
        assert meta.get('completed_count') == str(expected), (dataset, mode, 'incomplete primary')
        assert meta.get('run_in_progress') == '0' and meta.get('timing_complete') == 'true', (dataset, mode, 'unclean primary')
        assert db.execute('select count(*) from points').fetchone()[0] == expected
        assert db.execute('select count(*) from assignments').fetchone()[0] == expected
        assert db.execute('select count(*) from reassignment').fetchone()[0] == 0
        assert db.execute('pragma integrity_check').fetchall() == [('ok',)]
        assert db.execute('pragma foreign_key_check').fetchall() == []
        assert meta.get('cost_history_complete') != 'false', (dataset, mode, 'terminal invocation error')
        starts=[json.loads(row[0]) for row in db.execute("select payload from events where kind='run_start' order by id")]
        finishes=[json.loads(row[0]) for row in db.execute("select payload from events where kind='run_finish' order by id")]
        assert len(starts)==len(finishes)==1, (dataset,mode,'primary was resumed')
        assert starts[0]['session']==finishes[0]['session']==1 and starts[0]['saved_count']==starts[0]['prior_wall_ms']==0
        assert finishes[0]['success'] is True and finishes[0]['elapsed_ms']==int(meta['wall_ms'])
        db.close()
for mode in ['llm','ld']:
    for suffix in ['.json','.calls.jsonl','.progress.jsonl','.process.log']:
        assert not (OUT / (mode+suffix)).exists(), 'Control artifacts must be fresh'
(OUT/'launched-at.txt').write_text(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+'\n')
children = []
def stop(signum, frame):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        child.wait()
    raise SystemExit(128+signum)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
handles = []
try:
    for mode in ['llm','ld']:
        output = open(OUT/(mode+'.process.log'),'xb')
        handles.append(output)
        child = subprocess.Popen([str(CONTROL_BINARY),'--input',str(ROOT/'data/images.jsonl'),'--catalog',str(OUT/'catalog.json'),'--mode',mode,'--k','8','--expected','100','--log',str(OUT/(mode+'.calls.jsonl')),'--output',str(OUT/(mode+'.json'))],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
        children.append(child)
        print(json.dumps({'mode':mode,'pid':child.pid,'status':'started'}),flush=True)
    codes = [child.wait() for child in children]
    print(json.dumps({'status':'terminal','exit_codes':codes}),flush=True)
    raise SystemExit(int(any(codes)))
finally:
    for handle in handles:
        handle.close()
