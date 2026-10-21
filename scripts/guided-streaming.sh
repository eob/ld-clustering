#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 - "$source_dir" "$@" <<'PY'
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import time

source = Path(sys.argv.pop(1)).resolve()
parser = argparse.ArgumentParser(description='Plan or run eight reserved-stream workers; run makes paid calls.')
parser.add_argument('mode', choices=['plan', 'run'])
for name in ['data', 'run-root', 'binary', 'protocol', 'preflight']:
    parser.add_argument('--'+name, required=True, type=Path)
args = parser.parse_args()
data, root, binary, protocol_path, preflight_path = [p.resolve() for p in [args.data, args.run_root, args.binary, args.protocol, args.preflight]]
stage = root/'streaming'

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        while block := file.read(1024*1024):
            digest.update(block)
    return digest.hexdigest()

def now():
    return datetime.now(timezone.utc).isoformat()

def write_new(path, value):
    with Path(path).open('x') as file:
        file.write(value+'\n')

protocol = json.loads(protocol_path.read_bytes())
preflight = json.loads(preflight_path.read_bytes())
manifest = json.loads((data/'manifest.json').read_bytes())
require(not stage.exists(), 'streaming stage must use a fresh directory')
require(binary.is_file() and os.access(binary, os.X_OK), 'frozen executable required')
require(sha(preflight_path) == protocol['offline_preflight']['artifact_sha256'], 'preflight differs from registered protocol')
require(preflight['status'] == 'offline_preflight_passed' and preflight['api_calls'] == 0, 'offline preflight must pass')
require(sha(data/'manifest.json') == protocol['dataset_manifest_sha256'] == preflight['dataset_manifest_sha256'], 'dataset manifest changed')
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=source, text=True).strip()
require(branch.startswith('feat-'), 'use a dedicated feature branch')
contexts = {}
inspections = {row['modality']: row for row in preflight['modalities']}
arms = []
for modality in ['text', 'images']:
    registered = protocol['modalities'][modality]
    inspected = inspections[modality]
    require(registered['config'] == inspected['config'], 'registered configuration differs from preflight')
    path = data/'streaming'/f'{modality}.jsonl'
    raw = path.read_bytes()
    items = [json.loads(line) for line in raw.splitlines() if line.strip()]
    require(len(items) == registered['expected_count'] == inspected['count'], 'reserved input count differs')
    require([item['id'] for item in items] == manifest['partitions']['streaming'][modality]['ordered_ids'], 'reserved order differs')
    require(sha(path) == registered['jsonl_sha256'] == inspected['jsonl_sha256'], 'reserved JSONL changed')
    digest = hashlib.sha256(b'ld-clustering-input-v1\0'+struct.pack('<Q', len(raw))+raw)
    for item in items:
        if modality == 'images':
            require(item['text'] == 'Photograph.' and item.get('label') is None, 'image metadata leaked into evidence')
            image = (data/'streaming'/item['image']).resolve()
            require(data in image.parents, 'image escapes selected data root')
            payload = image.read_bytes()
            require(hashlib.sha256(payload).hexdigest() == manifest['photos'][item['id']]['supplied_sha256'], 'selected photo changed')
            digest.update(b'local-image\0'+struct.pack('<Q', len(payload))+payload)
        else:
            require(item.get('image') is None, 'unexpected text image')
    require(digest.hexdigest() == registered['input_sha256'] == inspected['input_sha256'], 'reserved fingerprint changed')
    context_record = protocol['manager']['contexts'][modality]
    context_path = protocol_path.parent/context_record['file']
    context = context_path.read_bytes()
    require(0 < len(context) <= 32768 and context.decode('utf-8').strip(), 'invalid frozen UTF-8 context')
    require(sha(context_path) == context_record['sha256'] == inspected['context_sha256'], 'frozen context changed')
    contexts[modality] = context_path
    for policy in ['original', 'contextual']:
        descriptor = protocol['policies']['original']['descriptor'] if policy == 'original' else {
            'policy': 'contextual', 'context_sha256': context_record['sha256'],
            'prompt_revision': protocol['policies']['contextual']['prompt_revision']}
        require(descriptor == next(row['manager_descriptor'] for row in inspected['policies'] if row['manager_descriptor']['policy'] == policy), 'manager identity differs from preflight')
        for backend in ['llm', 'ld']:
            directory = stage/f'{modality}-{policy}-{backend}'
            config = registered['config']
            command = [str(binary), 'run', '--input', str(path), '--database', str(directory/'state.sqlite'),
                '--log', str(directory/'calls.jsonl'), '--mode', backend, '--task', config['task'],
                '--k', str(config['k']), '--max-clusters', str(config['max_clusters']),
                '--bootstrap', str(config['bootstrap_size']), '--novelty', str(config['novelty_trigger']),
                '--maintenance-interval', str(config['maintenance_interval']), '--manager-policy', policy]
            if policy == 'contextual':
                command += ['--manager-context', str(stage/'preregistration'/context_record['file'])]
            arms.append({'name': directory.name, 'modality': modality, 'policy': policy, 'backend': backend,
                'expected_count': registered['expected_count'], 'cwd': str(data/'streaming'), 'argv': command,
                'directory': str(directory), 'input_sha256': registered['input_sha256'], 'manager_descriptor': descriptor})
plan = {'schema_version': 1, 'source_commit': commit, 'binary_sha256': sha(binary),
    'protocol_sha256': sha(protocol_path), 'preflight_sha256': sha(preflight_path),
    'dataset_manifest_sha256': sha(data/'manifest.json'), 'arms': arms}
if args.mode == 'plan':
    print(json.dumps(plan, indent=2))
    sys.exit(0)

require(bool(os.environ.get('OPENAI_API_KEY', '').strip()), 'OPENAI_API_KEY required for paid run')
paths = ['src', 'examples', 'Cargo.toml', 'Cargo.lock', 'scripts/guided-streaming.sh',
    str(protocol_path.relative_to(source)), *(str(path.relative_to(source)) for path in contexts.values())]
dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all', '--', *paths], cwd=source, text=True)
require(not dirty, 'commit the exact runtime, launcher, protocol and contexts before paid calls')
stage.mkdir(parents=True)
preregistration = stage/'preregistration'
preregistration.mkdir()
shutil.copy2(protocol_path, preregistration/'protocol.json')
shutil.copy2(preflight_path, preregistration/'request-preflight.json')
require(sha(preregistration/'protocol.json') == plan['protocol_sha256'], 'protocol changed while copying')
require(sha(preregistration/'request-preflight.json') == plan['preflight_sha256'], 'preflight changed while copying')
for modality, path in contexts.items():
    destination = preregistration/path.name
    shutil.copy2(path, destination)
    require(sha(destination) == protocol['manager']['contexts'][modality]['sha256'], 'context changed while copying')
    destination.chmod(0o444)
write_new(stage/'run-plan.json', json.dumps(plan, indent=2))
write_new(stage/'source-commit.txt', commit)
write_new(stage/'binary-sha256.txt', f"{plan['binary_sha256']}  {binary}")
write_new(stage/'dataset-manifest-sha256.txt', plan['dataset_manifest_sha256'])
write_new(stage/'launched-at.txt', now())
children = {}
interrupted = 0

def stop_children(signum, frame):
    global interrupted
    interrupted = signum
    for process, log, arm in children.values():
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

signal.signal(signal.SIGINT, stop_children)
signal.signal(signal.SIGTERM, stop_children)
result = 0
try:
    for arm in arms:
        require(not interrupted, 'launch interrupted')
        directory = Path(arm['directory'])
        directory.mkdir()
        write_new(directory/'source-commit.txt', commit)
        write_new(directory/'binary-sha256.txt', f"{plan['binary_sha256']}  {binary}")
        write_new(directory/'manager-descriptor.json', json.dumps(arm['manager_descriptor'], indent=2))
        write_new(directory/'input-sha256.txt', arm['input_sha256'])
        write_new(directory/'launched-at.txt', now())
        log = (directory/'process.log').open('xb')
        try:
            process = subprocess.Popen(arm['argv'], cwd=arm['cwd'], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except BaseException:
            log.close()
            raise
        children[process.pid] = (process, log, arm)
    while children:
        for pid, (process, log, arm) in list(children.items()):
            code = process.poll()
            if code is None:
                continue
            log.close()
            directory = Path(arm['directory'])
            write_new(directory/'exit-code.txt', str(code))
            write_new(directory/'finished-at.txt', now())
            result |= code != 0
            del children[pid]
        if children:
            time.sleep(0.25)
finally:
    if children:
        stop_children(signal.SIGTERM, None)
    for process, log, arm in children.values():
        process.wait()
        log.close()
write_new(stage/'supervisor-exit-code.txt', str(int(result)))
write_new(stage/'finished-at.txt', now())
sys.exit(int(result))
PY
