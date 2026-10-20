#!/usr/bin/env python3
"""Offline final narrative evidence from a verified complete LD archive only."""
from collections import Counter
from decimal import Decimal
import argparse
import importlib.util
import hashlib
import json
import math
from pathlib import Path


def require(ok,message):
    if not ok:raise ValueError(message)

OPERATIONS=('create','rename','merge','split','retire')


def summarize_arm(measurement,cost,partition,expected):
    require(measurement['sample_count']==expected,'sample count differs')
    assignments=partition['assignments'];ids=[p['id'] for p in assignments]
    require(len(assignments)==expected and len(set(ids))==expected,'incomplete or duplicate partition identities')
    clusters=partition['clusters'];active={c['id']:c for c in clusters if c['active']}
    named=Counter(p['cluster_id'] for p in assignments if p['cluster_id'] is not None)
    require(set(named)<=set(active),'assignment references inactive cluster')
    require(all(c['count']==named.get(c['id'],0) for c in clusters),'cluster membership counts differ')
    require(len(active)==measurement['cluster_count'],'active cluster count differs')
    other=expected-sum(named.values())
    require(math.isclose(measurement['coverage'],(expected-other)/expected,abs_tol=1e-12,rel_tol=0),'coverage differs')
    components=cost['components'];require(set(components)<={'planner','assignment_including_reassignment'},'unknown cost component')
    empty={'attempts':0,'known_recorded_cost_usd':'0','unknown_usage_attempts':0}
    parts={name:components.get(name,empty) for name in ('planner','assignment_including_reassignment')}
    dollars={name:Decimal(part['known_recorded_cost_usd']) for name,part in parts.items()}
    require(all(value.is_finite() and value>=0 for value in dollars.values()),'invalid cost value')
    total=sum(dollars.values());require(abs(total-Decimal(str(measurement['cost_usd'])))<Decimal('1e-9'),'component cost sum differs from frozen comparison')
    require(sum(part['attempts'] for part in parts.values())==measurement['calls'],'component call sum differs')
    unknown=sum(part['unknown_usage_attempts'] for part in parts.values())
    require(unknown==measurement['unknown_usage_calls']==len(cost['unknown_usage_source_jsonl_lines']),'unknown cost counts differ')
    require(cost['assignment_refusal_calls']==measurement['assignment_refusal_calls'],'refusal call count differs')
    events=partition['events'];refusals=[e['payload'] for e in events if e['kind']=='assignment_refusal']
    refused_ids={e['point_id'] for e in refusals}
    require(refused_ids<=set(ids) and all(e['phase'] in ('assign','reassign') for e in refusals),'refusal events differ from persisted points')
    require(len(refusals)<=measurement['assignment_refusal_calls'],'refusal events exceed accepted model calls')
    reviews=[e['payload']['operations'] for e in events if e['kind']=='maintenance']
    operations=Counter(op['op'] for plan in reviews for op in plan)
    require(set(operations)<=set(OPERATIONS),'unknown maintenance operation')
    require(len(reviews)<=parts['planner']['attempts'],'applied reviews exceed planner requests')
    final_other={p['id'] for p in assignments if p['cluster_id'] is None}
    component=lambda name:{'known_recorded_usd':str(dollars[name]),'fraction_of_known_cost':float(dollars[name]/total) if total else None,'attempts':parts[name]['attempts'],'unknown_usage_attempts':parts[name]['unknown_usage_attempts']}
    return {
      'sample_count':expected,'known_cost_usd':str(total),'cost_complete':measurement['cost_complete'],
      'planning':component('planner'),'assignment_including_reassignment':component('assignment_including_reassignment'),
      'fractions_basis':'Fractions use known recorded subtotal; missing charges can change full-cost fractions.',
      'wall_seconds':measurement['wall_seconds'],'timing_complete':measurement['timing_complete'],'timing_scope':measurement['timing_scope'],
      'active_clusters':len(active),'nonempty_active_clusters':len(named),'named_points':expected-other,'other_points':other,'coverage':measurement['coverage'],
      'active_cluster_definitions':[{'id':c['id'],'name':c['name'],'description':c.get('description'),'count':c['count'],'dataset_label_counts':c.get('dataset_label_counts')} for c in clusters if c['active']],
      'refusals':{'accepted_requests':measurement['assignment_refusal_calls'],'persisted_events':len(refusals),'distinct_event_points':len(refused_ids),'events_by_phase':dict(Counter(e['phase'] for e in refusals)),'distinct_event_points_final_other':len(refused_ids&final_other),'distinct_event_points_final_named':len(refused_ids-final_other),'note':'Accepted refusal requests can revisit one point; later maintenance can change its final assignment. Distinct points come from persisted refusal events.'},
      'maintenance':{'applied_reviews':len(reviews),'nonempty_reviews':sum(bool(plan) for plan in reviews),'empty_reviews':sum(not plan for plan in reviews),'operation_counts':{op:operations[op] for op in OPERATIONS},'reassignment_events':sum(e['kind']=='reassign' for e in events),'reassignment_note':'Each event records queued re-evaluation and persistence; membership can remain unchanged.'},
      'calls':measurement['calls'],'recorded_failed_attempts':len(cost['failed_attempts']),'unknown_usage_calls':unknown,'unknown_usage_source_jsonl_lines':cost['unknown_usage_source_jsonl_lines']}


def comparison_ratios(baseline,ld):
    divide=lambda a,b:a/b if math.isfinite(a) and math.isfinite(b) and a>0 and b>0 else None
    return {
      'baseline_over_ld_cost':divide(baseline['cost_usd'],ld['cost_usd']) if baseline['cost_complete'] and ld['cost_complete'] else None,
      'baseline_over_ld_uninterrupted_processing_time':divide(baseline['wall_seconds'],ld['wall_seconds']) if all(arm['timing_complete'] and arm['timing_scope']=='uninterrupted_loop' for arm in (baseline,ld)) else None,
      'cost_note':'Total cost ratio is withheld whenever either complete-cost flag is false; known subtotals are not complete charges.',
      'time_note':'Time ratio requires two complete uninterrupted loops; cumulative active-loop time excludes downtime.'}


def analyze(archive,binary,verifier_path=None):
    manifest_path=archive/'manifest.json';manifest_raw=manifest_path.read_bytes();manifest=json.loads(manifest_raw)
    require(manifest.get('status')=='complete' and set(manifest.get('complete_experiments',[]))=={'text','images'},'analysis requires a complete two-experiment immutable archive')
    expected_files={entry['path']:entry['sha256'] for entry in manifest['files']}
    verifier_path=verifier_path or archive/'operational/ld-archive-final.py'
    verifier_raw=verifier_path.read_bytes()
    require(hashlib.sha256(verifier_raw).hexdigest()==expected_files['operational/ld-archive-final.py'],'verifier bytes differ from immutable archive')
    spec=importlib.util.spec_from_file_location('ld_archive_verifier',verifier_path);verifier=importlib.util.module_from_spec(spec)
    # Execute the verified bytes without reading/writing archive __pycache__ files.
    exec(compile(verifier_raw,str(verifier_path),'exec'),verifier.__dict__)
    verified=verifier.verify_archive(archive,binary)
    manifest_sha=hashlib.sha256(manifest_raw).hexdigest();require(verified['manifest_sha256']==manifest_sha,'archive manifest changed during verification');result={}
    def read_json(name):
        raw=(archive/name).read_bytes();require(hashlib.sha256(raw).hexdigest()==expected_files[name],f'archive payload differs: {name}');return json.loads(raw)
    costs=read_json('cost-split.json')['runs']
    for dataset,expected in [('text',1000),('images',100)]:
        raw=read_json(f'{dataset}-results.json');partitions=read_json(f'{dataset}-partitions.json')
        require(raw['status']=='complete' and raw['expected_count']==expected,'result completion differs')
        arms={arm:summarize_arm(raw[key],costs[f'{dataset}-{arm}'],partitions[arm],expected) for arm,key in [('llm','baseline'),('ld','ld')]}
        labels=lambda arm:[f'cluster:{p["cluster_id"]}' if p['cluster_id'] is not None else f'other:{p["id"]}' for p in partitions[arm]['assignments']]
        require([p['id'] for p in partitions['llm']['assignments']]==[p['id'] for p in partitions['ld']['assignments']],'partition identity order differs')
        agreement=verifier.pairs(labels('llm'),labels('ld'));verifier.check_score(agreement,raw['agreement'])
        result[dataset]={'expected_per_arm':expected,'arms':arms,'agreement':agreement,'shared_other_sensitivity':raw['shared_other_sensitivity'],'secondary_dataset_label_agreement':raw.get('dataset_label_agreement'),'ratios':comparison_ratios(raw['baseline'],raw['ld'])}
    require(verifier.file_sha(manifest_path)==manifest_sha,'archive changed during analysis')
    return {'status':'verified_complete','archive':str(archive),'manifest_sha256':manifest_sha,'runtime_source_commit':manifest['runtime_source_commit'],'launch_checkout_commit':manifest['launch_checkout_commit'],'measured_binary_sha256':manifest['binary_sha256'],'archive_verification':verified,'experiments':result,'caveats':[
      'Primary results compare two independent evolving systems, including stochastic manager/catalog differences, rather than isolated assignment accuracy.',
      'The LLM baseline is a reference, not ground truth; dataset labels are separate diagnostics and original out-of-scope labels need not mean semantically unclusterable.',
      'Headline pair metrics make every Other point a singleton. Coverage, refusal calls and distinct refusal-event points describe different outcomes.',
      'One shuffled order and one run per arm do not establish general accuracy, cost or latency; 28x28 clothing images are not general photographs.',
      'Planning covers bootstrap and maintenance; assignment covers ordinary and maintenance reassignment, with all recorded charged attempts included.',
      'Costs are token-priced known recorded usage, not invoices. Unknown usage remains unknown; planning fractions are fractions of the known subtotal.',
      'Animation operations are illustrative. Only operation counts from persisted maintenance events describe what these runs actually did.',
      'The separately archived post-hoc frozen-catalog diagnostic is excluded from all primary costs, times and agreement here.']}


def markdown(report):
    pct=lambda x:'—' if x is None else f'{100*x:.1f}%'
    lines=[f"Verified complete archive: {report['archive']}",f"Runtime `{report['runtime_source_commit']}`; manifest SHA-256 `{report['manifest_sha256']}`.",'', '| Input / arm | Known API USD | Planning USD (% known) | Assign + reassign USD (% known) | Cost complete | Loop seconds | Active / nonempty | Named / all | Refusal calls / distinct points | Reviews / empty |','| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for dataset,experiment in report['experiments'].items():
        for arm,s in experiment['arms'].items():
            p,a=s['planning'],s['assignment_including_reassignment'];r=s['refusals'];m=s['maintenance']
            lines.append(f"| {dataset} / {arm} | {s['known_cost_usd']} | {p['known_recorded_usd']} ({pct(p['fraction_of_known_cost'])}) | {a['known_recorded_usd']} ({pct(a['fraction_of_known_cost'])}) | {s['cost_complete']} | {s['wall_seconds']:.3f} | {s['active_clusters']} / {s['nonempty_active_clusters']} | {s['named_points']} / {s['sample_count']} | {r['accepted_requests']} / {r['distinct_event_points']} | {m['applied_reviews']} / {m['empty_reviews']} |")
    for dataset,e in report['experiments'].items():
        q=e['agreement'];r=e['ratios'];pairs=q['pair_confusion'];cost='unavailable (incomplete/zero cost)' if r['baseline_over_ld_cost'] is None else f"{r['baseline_over_ld_cost']:.3f}x";time='unavailable (incomplete/cumulative/zero time)' if r['baseline_over_ld_uninterrupted_processing_time'] is None else f"{r['baseline_over_ld_uninterrupted_processing_time']:.3f}x"
        lines+=['',f"{dataset}: ARI {q['adjusted_rand_index']:.6f}; pair precision {q['pairwise_precision']:.6f}, recall {q['pairwise_recall']:.6f}, F1 {q['pairwise_f1']:.6f}; TP/FP/FN/TN {pairs['tp']}/{pairs['fp']}/{pairs['fn']}/{pairs['tn']}. Baseline / LD cost ratio: {cost}; uninterrupted processing ratio: {time}."]
        for arm,s in e['arms'].items():
            ops=', '.join(f'{op}={n}' for op,n in s['maintenance']['operation_counts'].items());lines.append(f"{dataset}/{arm}: applied operations {ops}; reassignment events={s['maintenance']['reassignment_events']}; unknown-usage journal lines={s['unknown_usage_source_jsonl_lines']}; distinct refusal-event points finally Other/named={s['refusals']['distinct_event_points_final_other']}/{s['refusals']['distinct_event_points_final_named']}.")
    return '\n'.join(lines+['']+[f'- {c}' for c in report['caveats']])+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--binary',type=Path,default=Path('/tmp/ld-clustering-v2-frozen'));parser.add_argument('--verifier',type=Path,help='Optional exact byte-identical copy of the archived offline verifier');parser.add_argument('--format',choices=['markdown','json'],default='markdown');args=parser.parse_args()
    report=analyze(args.archive.resolve(),args.binary.resolve(),args.verifier.resolve() if args.verifier else None);print(markdown(report) if args.format=='markdown' else json.dumps(report,indent=2),end='' if args.format=='markdown' else '\n')


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit(f'Analysis refused: {error}')
