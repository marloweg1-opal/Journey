"""Explicit bounded personal-media task. Reports stay in ignored private storage."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.patrol import live_discover
from core.perception_policy import set_policy, effective_policy
from core.media_recovery import VIDEO, PHOTO, stable_hash, validate_video, validate_photo, exact_groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--roots',nargs='+',required=True)
    parser.add_argument('--logs',nargs='*',default=[])
    parser.add_argument('--tools',type=Path,required=True)
    args = parser.parse_args()
    private = ROOT/'private'/'media_recovery'
    private.mkdir(parents=True,exist_ok=True)
    registry = sqlite3.connect(ROOT/'ark.sqlite')
    occurrences, scopes, reports = [], [], []
    try:
        for root in args.roots:
            policy = effective_policy(registry, root)
            if policy['mode']!='SEALED' or policy['scope'] is None:
                set_policy(registry,root,'SEALED',reason='User personal-media recovery task: structural inspection only',source_id='personal-media-recovery')
            rows, coverage = live_discover(root,max_files=10000,max_entries=30000,max_seconds=10)
            media = [row for row in rows if Path(row['canonical_path']).suffix.lower() in VIDEO|PHOTO]
            scopes.append({'root':root,'coverage':coverage,'files_observed':len(rows),'media_observed':len(media),
                          'media_bytes_observed':sum(r['size_bytes'] for r in media), 'policy':effective_policy(registry,root)})
            for row in media:
                occurrences.append({'path':row['canonical_path'],'source_scope':root,'filename':Path(row['canonical_path']).name,
                    'size_bytes':row['size_bytes'],'observed_modified':row['modified_at'],
                    'date_reliability':'filesystem observation; not asserted capture date',
                    'hash':{'state':'NOT_HASHED'},'validation':{'state':'NOT_VALIDATED'}})
        for report in args.logs:
            path = Path(report)
            if path.suffix.lower()!='.csv' or not path.is_file() or path.stat().st_size>8_000_000:
                continue
            with path.open(encoding='utf-8-sig',errors='replace',newline='') as stream:
                reader = csv.DictReader(stream)
                counts, total = Counter(), 0
                for row in reader:
                    total += 1
                    counts[row.get('Status') or row.get('Class') or 'inventory_row'] += 1
                reports.append({'path':str(path),'fields':reader.fieldnames,'rows':total,'reported_states':dict(counts),
                                'trust':'historical claim, not revalidated recovery proof'})
    finally:
        registry.close()
    # Round-robin source sampling avoids allowing one PhotoRec tree to consume every budget.
    per_scope = defaultdict(list)
    for item in occurrences:
        per_scope[item['source_scope']].append(item)
    candidates=[]
    for index in range(20):
        for items in per_scope.values():
            for kind in (PHOTO,VIDEO):
                eligible=sorted((i for i in items if 0<i['size_bytes']<=64_000_000 and Path(i['path']).suffix.lower() in kind),key=lambda i:(i['size_bytes'],i['path']))
                if index<len(eligible):
                    candidates.append(eligible[index])
    hash_bytes, video_count, photo_count = 0,0,0
    for item in candidates[:64]:
        if hash_bytes+item['size_bytes']>512_000_000:
            continue
        try:
            item['hash']=stable_hash(item['path'])
            hash_bytes+=item['hash'].get('bytes',0)
            extension=Path(item['path']).suffix.lower()
            if extension in VIDEO and video_count<12:
                item['validation']=validate_video(item['path'],args.tools/'ffprobe.exe',args.tools/'ffmpeg.exe')
                video_count+=1
            elif extension in PHOTO and photo_count<12:
                item['validation']=validate_photo(item['path'])
                photo_count+=1
        except OSError as exc:
            item['hash']={'state':'UNREADABLE','reason':str(exc)}
    groups=exact_groups(occurrences)
    capacity={}
    for root in args.roots:
        anchor=Path(root).anchor
        if anchor not in capacity:
            try:
                usage=shutil.disk_usage(anchor)
                capacity[anchor]={'free':usage.free,'total':usage.total}
            except OSError:
                capacity[anchor]={'state':'UNAVAILABLE'}
    total_bytes=sum(i['size_bytes'] for i in occurrences)
    summary={'scopes':scopes,'historical_reports':reports,'occurrences_observed':len(occurrences),
        'bytes_observed':total_bytes,'hashed':sum(i['hash']['state']=='HASHED' for i in occurrences),'hash_bytes':hash_bytes,
        'validation_states':dict(Counter(i['validation']['state'] for i in occurrences)),
        'exact_duplicate_groups':len(groups),'capacity':capacity,'semantic_inspections':0,'managed_mutations':0,
        'authority':'DISCOVER/INVENTORY/VALIDATE/HASH/RELATIONSHIP_ANALYSIS/PLAN only',
        'working_copy_budget_observed_lower_bound':total_bytes,
        'resource_decision':'None required for bounded reconnaissance. Full derivative workspace estimate awaits complete inventory.',
        'next_plan':['Complete structural inventory in bounded resumable batches','Expand hash coverage, retain every occurrence provenance',
          'Validate candidate representatives fully before recovery success claims','Approve a derivative workspace and bounded repair authority before execution',
          'Represent exact duplicates once in a working view, never delete evidence','Use metadata first; subfolder eligibility requires group>=5 and remaining parent>=15']}
    stamp=time.strftime('%Y%m%d_%H%M%S')
    out=private/f'recon-{stamp}.json'
    out.write_text(json.dumps({'summary':summary,'occurrences':occurrences,'exact_duplicate_groups':groups},indent=2),encoding='utf-8')
    (private/'latest_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('occurrences_observed','bytes_observed','hashed','hash_bytes','validation_states','exact_duplicate_groups','semantic_inspections','managed_mutations','resource_decision')},indent=2))
    print('Private evidence:',out)


if __name__=='__main__':
    main()
