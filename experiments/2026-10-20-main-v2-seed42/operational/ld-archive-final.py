#!/usr/bin/env python3
"""Disposable offline archiver for a pinned complete amended-protocol cohort."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tarfile
from urllib.parse import quote

DATA_SHA = 'f136049b624f62c1cba01cc22475d1634228daa372ef679e393f78ee12fd623b'
EXPECTED = {'text': 1000, 'images': 100}
CALL_FIELDS = ('model', 'request', 'response', 'elapsed_ms', 'usage')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def gzip_exact(source, target):
    before = file_sha(source)
    with open(source, 'rb') as incoming, open(target, 'wb') as outgoing:
        with gzip.GzipFile(filename='', fileobj=outgoing, mode='wb', mtime=0) as zipped:
            shutil.copyfileobj(incoming, zipped)
    require(before == file_sha(source), f'source changed while copying: {source}')
    with gzip.open(target, 'rb') as zipped:
        h = hashlib.sha256()
        for block in iter(lambda: zipped.read(1024 * 1024), b''):
            h.update(block)
    require(before == h.hexdigest(), f'gzip roundtrip differs: {target}')


def pairs(reference, candidate):
    require(len(reference) == len(candidate) and bool(reference), 'empty or unequal partitions')
    counts = Counter()
    for i, j in combinations(range(len(reference)), 2):
        a = reference[i] == reference[j]
        b = candidate[i] == candidate[j]
        counts['tp' if a and b else 'fp' if b else 'fn' if a else 'tn'] += 1
    tp, fp, fn, tn = (counts[k] for k in ('tp', 'fp', 'fn', 'tn'))
    ref, pred, total = tp + fn, tp + fp, tp + fp + fn + tn
    expected = Fraction(ref * pred, total) if total else Fraction(0)
    denominator = Fraction(ref + pred, 2) - expected
    ari = (tp - expected) / denominator if denominator else Fraction(1)
    empty_positive = ref == pred == 0
    return {
        'n': len(reference), 'pair_confusion': dict(zip(('tp', 'fp', 'fn', 'tn'), (tp, fp, fn, tn))),
        'adjusted_rand_index': float(ari), 'adjusted_rand_index_exact': str(ari),
        'pairwise_precision': tp / pred if pred else float(empty_positive),
        'pairwise_recall': tp / ref if ref else float(empty_positive),
        'pairwise_f1': 2 * tp / (ref + pred) if ref + pred else 1.0,
    }


def state(path, expected, backend):
    conn = sqlite3.connect(f'file:{quote(str(path.resolve()), safe="/")}?mode=ro', uri=True)
    try:
        conn.execute('BEGIN')
        require(conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)], f'corrupt SQLite: {path}')
        require(not conn.execute('PRAGMA foreign_key_check').fetchall(), f'foreign key failure: {path}')
        meta = dict(conn.execute('SELECT key,value FROM meta'))
        require(meta.get('backend') == backend, f'wrong backend: {path}')
        require(meta.get('completed_count') == str(expected), f'incomplete run: {path}')
        require(meta.get('run_in_progress') == '0', f'run still active: {path}')
        require(conn.execute('SELECT COUNT(*) FROM reassignment').fetchone()[0] == 0, f'pending reassignment: {path}')
        require(conn.execute('SELECT COUNT(*) FROM points').fetchone()[0] == expected, f'point count: {path}')
        require(conn.execute('SELECT COUNT(*) FROM assignments').fetchone()[0] == expected, f'assignment count: {path}')
        rows = []
        for ident, ordinal, payload, cluster in conn.execute('SELECT p.id,p.ordinal,p.payload,a.cluster_id FROM points p JOIN assignments a ON p.id=a.point_id ORDER BY p.ordinal'):
            item = json.loads(payload)
            require(item['id'] == ident and ordinal == len(rows), f'inconsistent identity/ordinal: {path}')
            rows.append((item, cluster))
        require(len(rows) == expected, f'joined point count: {path}')
        clusters = [{'id': cid, 'name': name, 'description': description, 'active': bool(active)} for cid, name, description, active in conn.execute('SELECT id,name,description,active FROM clusters ORDER BY id')]
        active_ids = {c['id'] for c in clusters if c['active']}
        require(all(cid is None or cid in active_ids for _, cid in rows), f'inactive assignment: {path}')
        config = json.loads(meta['config'])
        require(len(active_ids) <= config['max_clusters'], f'cluster cap: {path}')
        committed = Counter()
        first_plan = None
        committed_refusal_calls = 0
        for payload, in conn.execute('SELECT payload FROM calls ORDER BY id'):
            call = json.loads(payload)
            committed[sha(canonical({k: call[k] for k in CALL_FIELDS}))] += 1
            committed_refusal_calls += call['phase'] in ('assign','reassign') and is_assignment_refusal(call['response'])
            if first_plan is None and call['phase'] == 'plan':
                first_plan = call['request']
        events = [{'id':ident,'kind':kind,'created_at':created,'payload':json.loads(payload)} for ident,kind,payload,created in conn.execute('SELECT id,kind,payload,created_at FROM events ORDER BY id')]
        maintenance = [{'id':e['id'],'created_at':e['created_at'],'plan':e['payload']} for e in events if e['kind']=='maintenance']
        return {'meta': meta, 'rows': rows, 'clusters': clusters, 'committed': committed, 'first_plan': first_plan, 'maintenance': maintenance, 'events':events, 'committed_refusal_calls':committed_refusal_calls}
    finally:
        conn.close()


def labels(run, singleton_other=True):
    return [f'cluster:{cid}' if cid is not None else f'other:{item["id"]}' if singleton_other else 'other' for item, cid in run['rows']]


def verify_metrics(baseline, ld, summary):
    require(baseline['meta']['config'] == ld['meta']['config'], 'configuration differs')
    require(baseline['meta']['input_sha256'] == ld['meta']['input_sha256'], 'input evidence differs')
    require([p for p, _ in baseline['rows']] == [p for p, _ in ld['rows']], 'input identities/order differ')
    ref, pred = labels(baseline), labels(ld)
    result = {'agreement': pairs(ref, pred), 'shared_other_sensitivity': pairs(labels(baseline, False), labels(ld, False))}
    truth = [p.get('label') for p, _ in baseline['rows']]
    if all(v is not None for v in truth):
        result['dataset_label_agreement'] = {'baseline': pairs(truth, ref), 'ld': pairs(truth, pred)}
    for field in ('agreement', 'shared_other_sensitivity'):
        check_score(result[field], summary[field])
    for arm, score in result.get('dataset_label_agreement', {}).items():
        check_score(score, summary['dataset_label_agreement'][arm])
    covered = [i for i, ((_, a), (_, b)) in enumerate(zip(baseline['rows'], ld['rows'])) if a is not None and b is not None]
    result['mutually_covered_posthoc'] = pairs([ref[i] for i in covered], [pred[i] for i in covered]) if covered else None
    result['initial_management_requests_identical'] = baseline['first_plan'] == ld['first_plan']
    result['initial_management_request_sha256'] = {arm: sha(canonical(run['first_plan'])) for arm, run in [('baseline', baseline), ('ld', ld)]}
    return result


def check_score(observed, stored):
    for name in ('n', 'adjusted_rand_index', 'pairwise_precision', 'pairwise_recall', 'pairwise_f1'):
        require(math.isclose(observed[name], stored[name], rel_tol=0.0, abs_tol=1e-12), f'independent metric mismatch: {name}')


def priced_usage(row):
    if not row['usage_available']:
        return None
    u = row['response']['usage']
    n, o = u['input_tokens'], u['output_tokens']
    details = u.get('input_tokens_details', {})
    cached, write = details.get('cached_tokens', 0), details.get('cache_write_tokens', 0)
    require(0 <= cached <= n and 0 <= write <= n - cached, 'invalid token categories')
    im = Decimal(2) if n > 272000 else Decimal(1)
    om = Decimal('1.5') if n > 272000 else Decimal(1)
    if row['model'] == 'gpt-6-luna':
        dollars = Decimal(n) * Decimal('.1') * im / 1000000
    else:
        require(row['model'] == 'gpt-6.1-sol', 'unrecognized model in ledger')
        dollars = ((Decimal(n-cached-write)*2 + Decimal(cached)*Decimal('.1') + Decimal(write)*Decimal('2.5'))*im + Decimal(o)*10*om)/1000000
    require(abs(dollars - Decimal(str(row['usage']['cost_usd']))) < Decimal('0.000000000001'), 'stored price differs from independent Decimal calculation')
    return dollars


def audit_journal(path, role, run, ledger):
    totals = defaultdict(lambda: {'attempts': 0, 'known_recorded_cost_usd': Decimal(0), 'unknown_usage_attempts': 0, 'request_ms': 0})
    success = Counter()
    failed = []
    refusals = []
    previous = None
    with open(path) as incoming:
        header = json.loads(next(incoming))
        require(header['type'] == 'ld-clustering-journal' and header['schema_version'] == 1 and header['run_id'] == run['meta']['journal_run_id'], 'journal/database identity mismatch')
        for line_number, line in enumerate(incoming, 2):
            if not line.strip():
                continue
            row = json.loads(line)
            require('error' in row and isinstance(row.get('usage_available'), bool), 'missing attempt outcome')
            verify_retry_boundary(previous,row,role,line_number)
            previous=row
            component = 'planner' if row['phase'] == 'plan' else 'assignment_including_reassignment'
            require(row['phase'] in ('plan', 'assign'), 'unknown provider phase')
            detected_refusal = is_assignment_refusal(row['response'])
            require(isinstance(row.get('refusal'),bool) and row['refusal'] == detected_refusal, f'journal refusal marker differs from raw response: {role} line {line_number}')
            dollars = priced_usage(row)
            part = totals[component]
            part['attempts'] += 1
            part['request_ms'] += row['elapsed_ms']
            if dollars is None:
                require(row['error'] is not None, 'successful attempt missing usage')
                part['unknown_usage_attempts'] += 1
            else:
                part['known_recorded_cost_usd'] += dollars
            record = {k: row.get(k) for k in ('phase','model','attempt','error','refusal','http_status','usage_available','recorded_at_unix_ms','elapsed_ms','usage')}
            record.update({'role': role, 'source_jsonl_line': line_number, 'provider_usage': row['response'].get('usage') if isinstance(row['response'],dict) else None, 'known_recomputed_cost_usd': str(dollars) if dollars is not None else None, 'request_canonical_sha256': sha(canonical(row['request'])), 'response_canonical_sha256': sha(canonical(row['response']))})
            ledger.write(canonical(record) + b'\n')
            if detected_refusal:
                refusals.append(record)
            if row['error'] is None:
                success[sha(canonical({k: row[k] for k in CALL_FIELDS}))] += 1
            else:
                failed.append(record)
    require(not (run['committed'] - success), f'committed calls missing from journal: {role}')
    return {'components': {k: {**v, 'known_recorded_cost_usd': str(v['known_recorded_cost_usd'])} for k, v in totals.items()}, 'failed_attempts': failed, 'unknown_usage_source_jsonl_lines': [r['source_jsonl_line'] for r in failed if not r['usage_available']], 'successful_attempts': sum(success.values()), 'committed_successful_calls': sum(run['committed'].values()), 'uncommitted_successful_attempts': sum((success-run['committed']).values()), 'raw_assignment_refusal_attempts':sum(r['phase']=='assign' for r in refusals), 'assignment_refusal_calls':sum(r['phase']=='assign' and r['error'] is None for r in refusals), 'refusal_attempts':refusals}


def partitions(run):
    result = []
    for cluster in run['clusters']:
        members = [item for item, cid in run['rows'] if cid == cluster['id']]
        result.append({**cluster, 'count': len(members), 'dataset_label_counts': dict(Counter(p.get('label') for p in members))})
    assignments = [{'ordinal': i, 'id': p['id'], 'text': p['text'], 'image_file': f'images/{p["id"]}.png' if p.get('image') else None, 'dataset_label': p.get('label'), 'cluster_id': cid} for i, (p, cid) in enumerate(run['rows'])]
    return {'clusters': result, 'assignments': assignments, 'maintenance': run['maintenance'], 'events':run['events']}


def inventory(directory):
    files = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or path.name in ('manifest.json', 'SHA256SUMS'):
            continue
        entry = {'path': path.relative_to(directory).as_posix(), 'bytes': path.stat().st_size, 'sha256': file_sha(path)}
        if path.suffix == '.gz':
            h = hashlib.sha256();size = 0
            with gzip.open(path, 'rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    h.update(block);size += len(block)
            entry.update(uncompressed_bytes=size, uncompressed_sha256=h.hexdigest())
        files.append(entry)
    return files


def pinned_inputs(directory):
    manifest_path = directory/'dataset-manifest.json'
    require(file_sha(manifest_path) == DATA_SHA, 'dataset manifest differs from fixed pin')
    manifest = json.loads(manifest_path.read_text())
    result = {}
    with tarfile.open(directory/'inputs.tar.gz','r:gz') as archive:
        members = {member.name:member for member in archive.getmembers()}
        expected_members = {'inputs/text.jsonl','inputs/images.jsonl'}
        for dataset, expected in EXPECTED.items():
            raw = archive.extractfile(f'inputs/{dataset}.jsonl').read()
            items = [json.loads(line) for line in raw.splitlines() if line.strip()]
            require(len(items) == expected, f'archived input count differs: {dataset}')
            ids = [item['id'] for item in items]
            require(len(set(ids)) == expected and ids == manifest[dataset]['ordered_ids'], f'archived input IDs/order differ: {dataset}')
            order_hash = sha(json.dumps(ids,ensure_ascii=False,separators=(',',':')).encode())
            require(order_hash == manifest[dataset]['order_sha256'], f'ordered input hash differs: {dataset}')
            h = hashlib.sha256(b'ld-clustering-input-v1\0')
            h.update(len(raw).to_bytes(8,'little'));h.update(raw)
            for item in items:
                if item.get('image'):
                    name = f'inputs/images/{item["id"]}.png';expected_members.add(name)
                    pixels = archive.extractfile(name).read()
                    require(sha(pixels) == manifest['images']['png_sha256_by_id'][item['id']], f'PNG pin differs: {item["id"]}')
                    h.update(b'local-image\0');h.update(len(pixels).to_bytes(8,'little'));h.update(pixels)
            result[dataset] = {'items':items,'input_sha256':h.hexdigest(),'order_sha256':order_hash}
        require(set(members) == expected_members and all(m.isfile() for m in members.values()), 'unexpected or missing archived input member')
    return result


def bind_inputs(run, pinned, role):
    require([item for item,_ in run['rows']] == pinned['items'], f'persisted items differ from frozen inputs: {role}')
    require(run['meta']['input_sha256'] == pinned['input_sha256'], f'input fingerprint differs from frozen byte recipe: {role}')


def verify_archive(directory, binary):
    manifest = json.loads((directory/'manifest.json').read_text())
    require(manifest['status'] == 'complete', 'archive is not a complete cohort')
    pins=validate_pins({'runtime_source':manifest['runtime_source_commit'],'launch_head':manifest['launch_checkout_commit'],'binary_sha256':manifest['binary_sha256']})
    require(file_sha(binary)==pins['binary_sha256'], 'verification binary differs from archived measured executable')
    require(manifest['dataset_manifest_sha256']==DATA_SHA, 'archive advertises different dataset pins')
    for line in (directory/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        require(file_sha(directory/name) == digest, f'SHA256SUMS mismatch: {name}')
    for entry in manifest['files']:
        path = directory/entry['path']
        require(path.stat().st_size == entry['bytes'] and file_sha(path) == entry['sha256'], f'archive checksum mismatch: {path}')
        if path.suffix == '.gz':
            h = hashlib.sha256();size = 0
            with gzip.open(path, 'rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    h.update(block);size += len(block)
            require(size == entry['uncompressed_bytes'] and h.hexdigest() == entry['uncompressed_sha256'], f'decompressed checksum mismatch: {path}')
    pinned = pinned_inputs(directory)
    with tempfile.TemporaryDirectory(prefix='ld-archive-verify-') as temporary:
        work = Path(temporary)
        for dataset, expected in EXPECTED.items():
            states = {};costs = {};histories = {}
            for arm in ('llm', 'ld'):
                for suffix in ('sqlite', 'calls.jsonl'):
                    name = f'{dataset}-{arm}.{suffix}'
                    with gzip.open(directory/f'{name}.gz', 'rb') as incoming, open(work/name, 'wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                states[arm] = state(work/f'{dataset}-{arm}.sqlite', expected, arm)
                role=f'{dataset}-{arm}'
                bind_inputs(states[arm], pinned[dataset], role)
                with open(os.devnull,'wb') as ledger:
                    costs[arm]=audit_journal(work/f'{role}.calls.jsonl',role,states[arm],ledger)
                histories[arm]=verify_run_history(states[arm],role,costs[arm])
            target = work/f'{dataset}-results.json'
            compare(binary, work, dataset, expected, target)
            observed = json.loads(target.read_text());saved = json.loads((directory/target.name).read_text())
            require(observed == saved, f'relocated comparison differs: {dataset}')
            verify_metrics(states['llm'], states['ld'], saved)
            for arm,key in [('llm','baseline'),('ld','ld')]:
                check_measurement(saved[key],costs[arm],histories[arm],f'{dataset}-{arm}')
    return {'archive': str(directory), 'verified': True, 'sample_counts': EXPECTED, 'manifest_sha256': file_sha(directory/'manifest.json')}


def compare(binary, directory, dataset, expected, output):
    command = [str(binary), 'compare', '--baseline', str(directory/f'{dataset}-llm.sqlite'), '--baseline-log', str(directory/f'{dataset}-llm.calls.jsonl'), '--ld', str(directory/f'{dataset}-ld.sqlite'), '--ld-log', str(directory/f'{dataset}-ld.calls.jsonl'), '--expected', str(expected), '--output', str(output)]
    env = os.environ.copy();env.pop('OPENAI_API_KEY', None)
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, env=env)


def observe_service(unit):
    command = ['systemctl','--user','show',unit,'--property=LoadState,ActiveState,SubState,MainPID,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp']
    observed = subprocess.run(command, capture_output=True, text=True)
    fields = dict(line.split('=',1) for line in observed.stdout.splitlines() if '=' in line)
    if observed.returncode or fields.get('LoadState') == 'not-found':
        return {'unit':unit,'observation':'collected_or_unobservable','Result':None,'terminal_result_known':False,'show_exit_code':observed.returncode,'show_stderr':observed.stderr.strip(),'raw_properties':fields}
    require(fields.get('ActiveState') in ('inactive','failed') and fields.get('MainPID') == '0', f'service still live: {unit}')
    return {**fields,'unit':unit,'observation':'present_terminal','terminal_result_known':bool(fields.get('ExecMainExitTimestamp')),'show_exit_code':observed.returncode}


def live_primary_processes(run):
    expected = {(run/f'{dataset}-{arm}.sqlite').resolve() for dataset in EXPECTED for arm in ('llm','ld')}
    live = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            argv = proc.joinpath('cmdline').read_bytes().decode(errors='replace').split('\0')
            if len(argv) < 2 or argv[1] != 'run':
                continue
            values = [argv[i+1] for i,arg in enumerate(argv[:-1]) if arg == '--database'] + [arg.split('=',1)[1] for arg in argv if arg.startswith('--database=')]
            cwd = proc.joinpath('cwd').resolve()
            for value in values:
                database = (cwd/Path(value)).resolve()
                if database in expected:
                    live.append({'pid':int(proc.name),'database':database.name})
        except (FileNotFoundError,ProcessLookupError,PermissionError):
            continue
    return live



def validate_pins(pins):
    for name, size in [('runtime_source',40),('launch_head',40),('binary_sha256',64)]:
        require(isinstance(pins.get(name),str) and re.fullmatch(f'[0-9a-f]{{{size}}}',pins[name]) is not None, f'explicit full {name} pin required')
    return pins


def load_resume_histories(run, paths, declared_services=(), observed_roles=()):
    paths = [p.resolve() for p in paths]
    discovered = [p.resolve() for p in run.iterdir() if p.is_file() and 'resume' in p.name.lower()]
    if not paths:
        require(not discovered and not declared_services and not observed_roles, 'observed or declared recovery requires explicit resume provenance')
        return {}, []
    require(len(paths) == len(set(paths)), 'duplicate resume history path')
    histories = {}
    for path in paths:
        value = json.loads(path.read_text())
        if isinstance(value,dict) and 'resumed_at_unix_ms' in value:
            events = [{'role':value.get('role',path.name.split('-resume-history')[0]),'kind':'resume','history':value}]
        elif isinstance(value,dict):
            events = value.get('events',[])
        else:
            events = value
        require(isinstance(events,list) and bool(events), 'resume history must contain nonempty resume events')
        for event in events:
            require(isinstance(event,dict) and event.get('kind','resume') == 'resume', 'resume history requires a resume event')
            role = event.get('role')
            require(role in {f'{d}-{a}' for d in EXPECTED for a in ('llm','ld')}, 'resume event has no recognized role')
            require(role not in histories, 'duplicate role: multiple recoveries require an explicit history-chain verifier')
            history = event.get('history',event)
            require(history.get('status') == 'terminal' and history.get('exit_code') == 0, f'resume supervisor has not recorded successful terminal state: {role}')
            require(isinstance(history.get('resumed_at_unix_ms'),int), f'resume timestamp missing: {role}')
            histories[role] = history
    require(set(observed_roles) <= set(histories), 'observed recovery lacks role-specific resume provenance')
    discovered_histories = {p for p in discovered if 'resume-history' in p.name and p.suffix == '.json'}
    require(discovered_histories <= set(paths), 'observed resume history was omitted')
    return histories, paths


def is_assignment_refusal(response):
    if not isinstance(response,dict):
        return False
    answers=response.get('answers')
    if isinstance(answers,list) and any(isinstance(answer,dict) and answer.get('type')=='refusal' for answer in answers):
        return True
    output=response.get('output')
    if not isinstance(output,list):
        return False
    return any(isinstance(part,dict) and part.get('type')=='refusal'
        for message in output if isinstance(message,dict) and isinstance(message.get('content'),list)
        for part in message['content'])


def verify_retry_boundary(previous,row,role,line_number):
    attempt=row.get('attempt')
    require(isinstance(attempt,int) and not isinstance(attempt,bool) and 1<=attempt<=3, f'attempt outside maximum3: {role} line {line_number}')
    if attempt>1:
        require(previous is not None and previous['error'] is not None and previous['attempt']==attempt-1, f'retry has no immediately preceding failed attempt: {role} line {line_number}')
        require((row['phase'],row['model'],canonical(row['request']))==(previous['phase'],previous['model'],canonical(previous['request'])), f'retry request changed: {role} line {line_number}')

def verify_run_history(run, role, costs=None):
    starts = [e for e in run['events'] if e['kind']=='run_start']
    finishes = [e for e in run['events'] if e['kind']=='run_finish']
    require(bool(starts), f'amended runtime has no run-start provenance: {role}')
    require([e['payload']['session'] for e in starts] == list(range(1,len(starts)+1)), f'nonconsecutive run sessions: {role}')
    require(len(finishes)==len(starts), f'unclosed run sessions require explicit incomplete archive: {role}')
    require([e['payload']['session'] for e in finishes] == list(range(1,len(starts)+1)), f'run finish sessions differ: {role}')
    elapsed = 0
    previous_finish = 0
    for start,finish in zip(starts,finishes):
        a,b = start['payload'],finish['payload']
        require(previous_finish < start['id'] < finish['id'], f'overlapping run sessions: {role}')
        require(a['prior_wall_ms']==elapsed and isinstance(a['saved_count'],int) and 0<=a['saved_count']<=len(run['rows']), f'run start prefix or timing differs: {role}')
        require(isinstance(a['started_at_unix_ms'],int) and a['started_at_unix_ms']>0, f'run start epoch missing: {role}')
        require(isinstance(b['elapsed_ms'],int) and b['elapsed_ms']>=0 and isinstance(b['success'],bool), f'run finish outcome malformed: {role}')
        require((b['error'] is None)==b['success'], f'run error/success disagreement: {role}')
        elapsed += b['elapsed_ms'];previous_finish=finish['id']
    require(starts[0]['payload']['saved_count']==0 and starts[0]['payload']['prior_wall_ms']==0, f'first session was not a fresh arm: {role}')
    require(finishes[-1]['payload']['success'], f'last invocation failed: {role}')
    require(elapsed==int(run['meta']['wall_ms']), f'active loop sum differs: {role}')
    if len(starts)==1:
        require(run['meta'].get('cost_history_complete') != 'false', f'clean arm has interrupted cost history: {role}')
        require(run['meta'].get('timing_complete') == 'true', f'clean arm has incomplete timing: {role}')
    refusals = [e for e in run['events'] if e['kind']=='assignment_refusal']
    ids = {item['id'] for item,_ in run['rows']}
    require(all(e['payload'].get('point_id') in ids and e['payload'].get('phase') in ('assign','reassign') for e in refusals), f'refusal event points or phase differ: {role}')
    require(len(refusals)==run['committed_refusal_calls'], f'committed refusal calls differ from persisted refusal events: {role}')
    if costs is not None:
        require(costs['assignment_refusal_calls']>=len(refusals), f'persisted refusal event missing accepted journal call: {role}')
    return {'run_sessions':len(starts),'timing_scope':'uninterrupted_loop' if len(starts)==1 else 'cumulative_active_loops','active_loop_ms':elapsed,'clean_single_invocation':len(starts)==1,'assignment_refusal_events':refusals}


def check_measurement(summary, costs, history, role):
    require(summary['calls']==sum(c['attempts'] for c in costs['components'].values()), f'Rust/independent attempt count differs: {role}')
    require(summary['error_calls']==len(costs['failed_attempts']), f'Rust/independent error count differs: {role}')
    require(summary['unknown_usage_calls']==len(costs['unknown_usage_source_jsonl_lines']), f'Rust/independent unknown usage count differs: {role}')
    require(summary['committed_success_calls']==costs['committed_successful_calls'] and summary['uncommitted_success_calls']==costs['uncommitted_successful_attempts'], f'Rust/independent committed attempt coverage differs: {role}')
    require(summary['assignment_refusal_calls']==costs['assignment_refusal_calls'], f'Rust/raw refusal count differs: {role}')
    require(summary['run_sessions']==history['run_sessions'], f'Rust/independent session count differs: {role}')
    require(summary['timing_scope']==history['timing_scope'], f'Rust/independent timing scope differs: {role}')
    require(abs(sum(Decimal(c['known_recorded_cost_usd']) for c in costs['components'].values())-Decimal(str(summary['cost_usd'])))<Decimal('0.000000001'),f'cost sum mismatch: {role}')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('/mnt/disks/data/ld-clustering'))
    parser.add_argument('--run', type=Path, default=Path('runs/main-v2-seed42'))
    parser.add_argument('--output', type=Path, default=Path('experiments/2026-10-20-main-v2-seed42'))
    parser.add_argument('--prior', type=Path, default=Path('experiments/2026-10-20-main-seed42'))
    parser.add_argument('--binary', type=Path, default=Path('target/release/ld-clustering'))
    parser.add_argument('--service', help='Primary user-systemd supervisor unit; required for creation')
    parser.add_argument('--runtime-source', help='Full frozen Rust runtime commit')
    parser.add_argument('--launch-head', help='Full launch checkout commit')
    parser.add_argument('--binary-sha256', help='Exact measured executable SHA-256')
    parser.add_argument('--resume-service', action='append', default=[], help='Additional resume unit that must be terminal; repeatable')
    parser.add_argument('--verify-only', type=Path)
    parser.add_argument('--resume-history', type=Path, action='append', default=[], help='External recovery history; required when recovery is declared or observed, repeatable')
    parser.add_argument('--operational', type=Path, action='append', default=[], help='Additional credential-free supervisor/waiter script or log to retain; repeatable')
    args = parser.parse_args()
    repo = args.repo.resolve()
    resolve = lambda p: p.resolve() if p.is_absolute() else (repo/p).resolve()
    binary = resolve(args.binary)
    supplied = {'runtime_source':args.runtime_source,'launch_head':args.launch_head,'binary_sha256':args.binary_sha256}
    if args.verify_only:
        directory = resolve(args.verify_only)
        manifest = json.loads((directory/'manifest.json').read_text())
        pins = validate_pins({'runtime_source':manifest['runtime_source_commit'],'launch_head':manifest['launch_checkout_commit'],'binary_sha256':manifest['binary_sha256']})
        require(all(value is None or value==pins[name] for name,value in supplied.items()), 'supplied pins differ from archived pins')
        require(file_sha(binary)==pins['binary_sha256'], 'binary differs from archived measured executable')
        print(json.dumps(verify_archive(directory,binary),indent=2));return
    pins = validate_pins(supplied)
    SOURCE,LAUNCH_HEAD,BINARY_SHA = pins['runtime_source'],pins['launch_head'],pins['binary_sha256']
    require(file_sha(binary)==BINARY_SHA, 'binary differs from frozen measured executable')
    require(args.service is not None, 'supply the primary --service unit')
    run, output, prior = (resolve(p) for p in (args.run,args.output,args.prior))
    require(not output.exists(), 'refusing to overwrite any existing archive')
    live = live_primary_processes(run)
    require(not live, f'primary/resume processes still live: {live}')
    properties = observe_service(args.service)
    resume_services = {unit:observe_service(unit) for unit in args.resume_service}
    launch_head = (run/'source-commit.txt').read_text().strip()
    require(launch_head == LAUNCH_HEAD, 'launch checkout pin differs')
    subprocess.run(['git','diff','--exit-code',SOURCE,launch_head,'--','src','Cargo.toml','Cargo.lock','scripts/benchmark.sh'],cwd=repo,check=True,stdout=subprocess.DEVNULL)
    require((run/'binary-sha256.txt').read_text().split()[0] == BINARY_SHA, 'recorded binary pin differs')
    require(file_sha(run/'dataset-manifest.json') == DATA_SHA, 'dataset pin differs')
    subprocess.run(['git','diff','--exit-code',SOURCE,'--','src','Cargo.toml','Cargo.lock','scripts/benchmark.sh'],cwd=repo,check=True,stdout=subprocess.DEVNULL)
    states = {}
    for dataset, expected in EXPECTED.items():
        for arm in ('llm','ld'):
            path = run/f'{dataset}-{arm}.sqlite'
            require(not Path(str(path)+'-wal').exists(), f'WAL sidecar exists; snapshot explicitly before archive: {path}')
            states[f'{dataset}-{arm}'] = state(path, expected, arm)
    pinned = pinned_inputs(prior)
    for role, run_state in states.items():
        bind_inputs(run_state, pinned[role.split('-')[0]], role)
    histories = {role:verify_run_history(run_state,role) for role,run_state in states.items()}
    observed_roles = [role for role,history in histories.items() if history['run_sessions']>1]
    histories_by_role,resume_paths = load_resume_histories(run,[resolve(p) for p in args.resume_history],args.resume_service,observed_roles)
    resumed_roles = set(histories_by_role)
    require(resumed_roles==set(observed_roles), 'declared recovery differs from persisted run sessions')
    for role, history in histories_by_role.items():
        require(int(history['original_meta']['wall_ms']) <= int(states[role]['meta']['wall_ms']), f'resume active time decreased: {role}')
        with open(run/f'{role}.calls.jsonl','rb') as source:
            prefix = b''.join(next(source) for _ in range(history['last_original_attempt_row']))
        require(sha(prefix) == history['original_journal_sha256'], f'original journal prefix changed across resume: {role}')
        last_original = json.loads(prefix.splitlines()[-1])
        require(last_original['recorded_at_unix_ms'] == history['last_original_attempt_recorded_at_unix_ms'] and last_original['error'] is not None, f'resume error boundary differs: {role}')
        for key in ('config','backend','input_sha256','journal_run_id'):
            require(history['original_meta'][key] == states[role]['meta'][key], f'resume provenance differs for {role}: {key}')
        if 'final_meta' in history:
            require(history['final_meta']['wall_ms'] == states[role]['meta']['wall_ms'], f'resume final timing differs: {role}')
    previous = json.loads((prior/'manifest.json').read_text())
    old_files = {entry['path']:entry for entry in previous['files']}
    shared = ['inputs.tar.gz','pricing.json','licenses/ATTRIBUTION.txt','licenses/clinc-CC-BY-3.0.txt','licenses/fashion-MIT.txt']
    for name in shared:
        require(file_sha(prior/name) == old_files[name]['sha256'], f'prior immutable file mismatch: {name}')
    require(file_sha(prior/'dataset-manifest.json') == DATA_SHA, 'prior inputs use another dataset')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ld-archive-stage-', dir=output.parent) as temporary:
        stage = Path(temporary)
        for name in shared:
            target = stage/name;target.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(prior/name,target)
        for name in ('source-commit.txt','binary-sha256.txt','launched-at.txt','dataset-manifest.json'):
            shutil.copyfile(run/name, stage/name)
        (stage/'runtime-source-commit.txt').write_text(SOURCE+'\n')
        if resume_paths:
            destination = stage/'resume-history';destination.mkdir()
            for index,resume_path in enumerate(resume_paths):
                shutil.copyfile(resume_path,destination/f'{index+1}-{resume_path.name}')
        write_json(stage/'resume-provenance.json',{'externally_resumed_roles':sorted(resumed_roles),'external_histories':[f'resume-history/{i+1}-{path.name}' for i,path in enumerate(resume_paths)],'run_sessions':{role:history['run_sessions'] for role,history in histories.items()},'no_resume_basis':'Exactly one ordered successful start/finish event per arm, saved_count0/prior_wall_ms0; no declared or observed resume sidecars/units' if not resumed_roles else None})
        keys = [os.environ[name].encode() for name in ('OPENAI_API_KEY',) if os.environ.get(name)]
        primary_names = {f'{role}.{suffix}' for role in states for suffix in ('sqlite','calls.jsonl','process.log')} | {'source-commit.txt','binary-sha256.txt','launched-at.txt','dataset-manifest.json'}
        operational = [p for p in run.iterdir() if p.is_file() and p.name not in primary_names] + [resolve(p) for p in args.operational] + [Path(__file__).resolve()]
        for source in operational:
            require(not any(key in source.read_bytes() for key in keys), f'configured credential found in operational file {source.name}')
            destination = stage/'operational'/source.name
            destination.parent.mkdir(exist_ok=True)
            if destination.exists():
                require(file_sha(source) == file_sha(destination), f'operational filename collision: {source.name}')
            else:
                before = file_sha(source);shutil.copyfile(source,destination)
                require(before == file_sha(source) == file_sha(destination), f'operational file changed during copy: {source.name}')
        source_hashes = {}
        for role in states:
            for suffix in ('sqlite','calls.jsonl','process.log'):
                source = run/f'{role}.{suffix}'
                require(not any(key in source.read_bytes() for key in keys), f'configured credential found in {source.name}')
                source_hashes[source.name] = file_sha(source)
                gzip_exact(source, stage/f'{source.name}.gz')
        metrics = {};costs = {}
        with open(stage/'attempt-ledger.jsonl.gz','wb') as raw_ledger:
            with gzip.GzipFile(filename='',fileobj=raw_ledger,mode='wb',mtime=0) as ledger:
                ledger.write(canonical({'type':'ld-clustering-attempt-ledger','schema_version':1,'source_line_numbers':'1-based original JSONL including header','hash_format':'SHA-256 of sorted-key compact UTF-8 JSON'})+b'\n')
                for role, run_state in states.items():
                    costs[role] = audit_journal(run/f'{role}.calls.jsonl', role, run_state, ledger)
                    verify_run_history(run_state,role,costs[role])
        for dataset, expected in EXPECTED.items():
            result = stage/f'{dataset}-results.json'
            compare(binary, run, dataset, expected, result)
            summary = json.loads(result.read_text())
            metrics[dataset] = verify_metrics(states[f'{dataset}-llm'], states[f'{dataset}-ld'], summary)
            metrics[dataset]['pinned_input_sha256'] = pinned[dataset]['input_sha256']
            metrics[dataset]['pinned_order_sha256'] = pinned[dataset]['order_sha256']
            write_json(stage/f'{dataset}-partitions.json',{arm:partitions(states[f'{dataset}-{arm}']) for arm in ('llm','ld')})
            for arm, key in [('llm','baseline'),('ld','ld')]:
                role = f'{dataset}-{arm}'
                check_measurement(summary[key],costs[role],histories[role],role)
        for name, before in source_hashes.items():
            require(file_sha(run/name) == before, f'run changed during archival: {name}')
        write_json(stage/'independent-verification.json',{'method':'Enumerate every unordered point pair; exact rational ARI; independent Decimal token pricing. Other is a unique singleton per rejected point in primary metrics. Covered-only scores are post hoc diagnostics.', 'experiments':metrics})
        write_json(stage/'attempt-outcome.json',{'status':'complete','supervisor':properties,'resume_supervisors':resume_services,'runs':{role:{'expected_points':EXPECTED[role.split('-')[0]],'persisted_points':len(s['rows']),'pending_reassignments':0,'complete_assignments':True,'timing_complete':s['meta'].get('timing_complete')=='true','wall_seconds':int(s['meta']['wall_ms'])/1000,'active_loop_seconds':int(s['meta']['wall_ms'])/1000,'externally_resumed':role in resumed_roles,'timing_basis':'summed measured active loops; external downtime excluded' if role in resumed_roles else 'single measured clustering loop','uninterrupted_elapsed_time_proven':role not in resumed_roles and s['meta'].get('timing_complete')=='true','calendar_seconds_from_initial_cli_metadata':histories_by_role.get(role,{}).get('calendar_seconds_from_initial_cli_metadata'),'manual_pause_since_last_attempt_seconds':histories_by_role.get(role,{}).get('manual_pause_since_last_attempt_seconds'),'journal_run_id':s['meta']['journal_run_id'],'run_sessions':histories[role]['run_sessions'],'timing_scope':histories[role]['timing_scope'],**costs[role]} for role,s in states.items()}})
        write_json(stage/'refusal-history.json',{'basis':'Accepted typed assignment refusal maps to Other and stops paging; planner refusal remains an error. Refusal count is per accepted model request, not distinct points or final Other points.','runs':{role:{'assignment_refusal_calls':costs[role]['assignment_refusal_calls'],'raw_refusal_attempts':costs[role]['refusal_attempts'],'persisted_assignment_refusal_events':histories[role]['assignment_refusal_events']} for role in states}})
        write_json(stage/'cost-split.json',{'basis':'Known token-priced costs from reported usage, not invoices. Assignment includes maintenance reassignment. Missing usage is unknown, not zero. Decimal strings preserve independent sums. All attempts retain exact source JSONL row indices.', 'runs':costs})
        write_json(stage/'runtime.json',{'archive_verification_host':platform.platform(),'architecture':platform.machine(),'archiver_python':platform.python_version(),'archiver_sha256':file_sha(Path(__file__)),'service':properties,'resume_services':resume_services,'runtime_source_commit':SOURCE,'launch_checkout_commit':launch_head,'archive_parent_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'concurrency':'Four initial arms launched concurrently; each arm sequential, per frozen scripts/benchmark.sh. External resumes are listed separately and may overlap a different subset of arms. Shared external API conditions vary during execution.','run_history':histories,'raw_source_sha256':source_hashes,'configs':{role:json.loads(s['meta']['config']) for role,s in states.items()}})
        (stage/'README.md').write_text(f'''# Main amended-protocol seed-42 cohort\n\nAll four primary streams finished: 1,000 text and 100 image points per arm.\nFrozen runtime source: https://github.com/eob/ld-clustering/tree/{SOURCE}\nFrozen binary SHA-256: `{BINARY_SHA}`.\nDataset manifest SHA-256: `{DATA_SHA}`.\n`source-commit.txt` preserves launch checkout `{LAUNCH_HEAD}`;\n`runtime-source-commit.txt` identifies the actual runtime commit above. Later\ndocumentation/provenance commits are identified separately in `runtime.json` and\ndo not change measured runtime source.\n\nRaw SQLite states, exact request journals and process logs are compressed without\nchanging their decompressed bytes. Gzip timestamps are zero. Inputs, pricing and\nupstream notices are byte-identical to the verified earlier archive. Source code\nis BSD-3-Clause; CLINC150 remains CC BY 3.0 and Fashion-MNIST remains MIT.\n\n`text-results.json` and `images-results.json` come from the frozen Rust compare\ncommand. `independent-verification.json` enumerates every unordered pair instead\nof using its contingency-table implementation, and verifies primary, shared-Other\nand dataset-label scores. Mutually-covered scores are explicitly post hoc and do\nnot replace the full-population results. `*-partitions.json` provides readable\ncluster definitions, evaluation labels, point assignments and maintenance plans.\n\n`attempt-ledger.jsonl.gz` indexes every observed API attempt. `attempt-outcome.json`\nand `cost-split.json` retain all failures and the original 1-based JSONL row numbers\nfor missing usage. Known token-priced costs are not invoices; attempts without\nreported usage have unknown cost. Read each result's `cost_complete` and\n`timing_complete` before reporting efficiency ratios. `resume-provenance.json` records clean invocation proof or links byte-preserved\nexternal recovery histories. For resumed roles the Rust `wall_seconds` field is\nthe sum of measured active-loop segments; external downtime is excluded. It is\nnot uninterrupted start-to-finish elapsed time, even if `timing_complete` remains\ntrue after a graceful failure. `attempt-outcome.json` labels this distinction. Planning costs include\nbootstrap and later management. Assignment costs include all reassignment.\n\nThe initial manager can produce different catalogs for identical prompts; these\nare independent evolving systems, not an assignment-only experiment. Both original-protocol cohorts remain separately archived as interrupted text\nexperiments with complete image replicates. This cohort uses accepted assignment\nrefusal-to-Other handling and at most three same-body attempts for completed invalid\nmanager plans; all attempts remain recorded. No frozen-catalog control is mixed into this cohort. Operational Python files\nunder `operational/` supervise processes, wait, or archive and verify evidence; the clusterer runtime\nand model protocol remain the frozen Rust implementation.\n\nVerify `sha256sum -c SHA256SUMS`, decompress the four SQLite states and request\njournals to a scratch directory, and run the frozen Rust `compare` command there\nwith `--expected 1000` for text and `--expected 100` for images. Comparison does\nnot access the historical image or journal paths embedded in database metadata.\nThe archived JSONL inputs preserve original paths and bytes; use `prepare` from\nthe frozen source to regenerate local paths for a new paid run. Dataset ordered\nIDs and PNG hashes remain location independent.\n\nThe archive manifest hashes every payload; SHA256SUMS also covers the manifest.\nPublish links to the immutable Git commit containing this directory. Runtime\nsource and archived evidence may live at different commits. Collected systemd units are recorded as collected/unobservable, with unknown\nterminal Result rather than an assumed success. Completion is checked against\nall four database markers, terminal resume history and absence of matching\n/proc run processes. The original supervisor may have failed before a separate\nresume finished. This archive step and both comparison verifiers make no API calls.\n''')
        manifest = {'schema_version':1,'status':'complete','complete_experiments':['text','images'],'pending_experiments':[],'incomplete_experiments':[],'source_code_commit':SOURCE,'runtime_source_commit':SOURCE,'launch_checkout_commit':launch_head,'archive_checkout_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'binary_sha256':BINARY_SHA,'dataset_manifest_sha256':DATA_SHA,'input_archive_sha256':file_sha(stage/'inputs.tar.gz'),'supervision_service':args.service,'protocol_amendment':{'typed_assignment_refusal':'Other and stop paging','invalid_completed_manager_plan':'same-body bounded retry within maximum3 total attempts; no fallback'},'known_usage_only_costs':True,'externally_resumed_roles':sorted(resumed_roles),'timing_note':'Resumed roles report summed active-loop seconds, not uninterrupted elapsed time; see resume-provenance.json and attempt-outcome.json','files':inventory(stage)}
        write_json(stage/'manifest.json',manifest)
        checksums = ''.join(f'{file_sha(p)}  {p.relative_to(stage).as_posix()}\n' for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='SHA256SUMS')
        (stage/'SHA256SUMS').write_text(checksums)
        report = verify_archive(stage,binary)
        os.replace(stage,output)
        report['archive'] = str(output)
        print(json.dumps(report,indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Archive refused: {error}',file=sys.stderr)
        sys.exit(1)
