"""Synthetic matched inference apparatus. Not a market trading tool."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def parse(raw):
    if not isinstance(raw,str):return None
    try:
        clean=raw.strip()
        if clean.startswith('```'):clean=clean.removeprefix('```').removeprefix('json').removesuffix('```').strip()
        obj=json.loads(clean)
    except ValueError:return None
    if not isinstance(obj,dict) or obj.get('action') not in ('contact_shop','request_checkout','request_evidence','ask_question','decline','contact_shop_again'):
        return None
    return {k:obj.get(k) for k in ('action','selected_shop','questions','public_reason')}


def main():
    q=argparse.ArgumentParser();q.add_argument('--operator',type=Path,required=True);q.add_argument('--inputs',type=Path,required=True);q.add_argument('--output',type=Path,required=True);a=q.parse_args()
    op=a.operator.resolve();inputs=a.inputs.resolve();output=a.output.resolve();os.umask(0o077);output.mkdir(mode=0o700,exist_ok=True)
    assignments=json.loads((inputs/'allocation_private_to_runner.json').read_text())['assignments']
    selected=[r for r in assignments if r['pair'] in ('H01','H02','H03','H04')]
    assert len(selected)==24
    allocation={r['call_id']:r for r in selected}
    calls=[json.loads(l) for l in (inputs/'model_calls_blinded.jsonl').read_text().splitlines()]
    calls=[r for r in calls if r['call_id'] in allocation]
    plan={'synthetic_only':True,'first_four_complete_pairs_per_study':True,'call_ids':[r['call_id'] for r in calls],
          'input_sha256':hashlib.sha256((inputs/'model_calls_blinded.jsonl').read_bytes()).hexdigest(),
          'model':'market classroom endpoint; upstream identity not exposed','fixed_max_tokens':350,
          'followup_rule':'proof_timing asks_evidence or question gets identical saved synthetic evidence once'}
    planfile=output/'plan.json'
    if planfile.exists():assert json.loads(planfile.read_text())==plan
    else:planfile.write_text(json.dumps(plan,indent=2)+'\n')
    sys.path.insert(0,str(op/'kit'));import agent_kit as official
    token=(op.parent/'round-4/.kit/worker-token').read_text().strip()
    model=official.Model({'llm':{'base':'market'}},'https://market.ourolabs.ai',{'tokens':{'shop':token}})
    results=[]
    for row in calls:
        dest=output/(row['call_id']+'.json')
        if dest.exists():results.append(json.loads(dest.read_text()));continue
        meta=allocation[row['call_id']]
        messages=[dict(row['messages'][0],content=official.WORLD+'\n\n'+row['messages'][0]['content']),*row['messages'][1:]]
        record={'call_id':row['call_id'],'study':meta['study'],'pair':meta['pair'],'condition':meta['condition'],'cohort':meta['cohort'],'target_shop':meta.get('target_shop'),'turns':[]}
        for turn in range(2):
            start=time.time()
            try:
                raw=model.complete(messages,max_tokens=350,timeout=35);decision=parse(raw)
                result={'seconds':round(time.time()-start,3),'decision':decision,'parse_valid':decision is not None,'raw_private':raw}
            except Exception as error:
                result={'seconds':round(time.time()-start,3),'error_type':type(error).__name__,'parse_valid':False}
            record['turns'].append(result)
            if (turn or meta['study']!='proof_timing' or not result.get('decision')
                    or result['decision']['action'] not in ('request_evidence','ask_question')):break
            messages += [{'role':'assistant','content':raw},{'role':'user','content':json.dumps({'requested_evidence':meta['followup_evidence'],'notice':'These flags are synthetic scenario facts, not actual cryptographic verification.'},ensure_ascii=False)}]
        dest.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');results.append(record)
        print(json.dumps({'completed':len(results),'total':len(calls),'study':meta['study'],'valid':all(t.get('parse_valid') for t in record['turns'])}),flush=True)
    summary={'synthetic_only':True,'real_customer_visits':0,'real_transactions':0,'completed':len(results),'results':[]}
    for study in ('entry_order','proof_timing','refund_receipt'):
        group=[r for r in results if r['study']==study]
        for condition in sorted({r['condition'] for r in group}):
            chosen=[r for r in group if r['condition']==condition];final=[r['turns'][-1].get('decision') for r in chosen]
            summary['results'].append({'study':study,'condition':condition,'cases':len(chosen),'invalid_or_transport_failures':sum(d is None for d in final),
                'first_contact_target_selections':sum(bool(d and d['selected_shop']==r.get('target_shop')) for d,r in zip(final,chosen)) if study=='entry_order' else None,
                'request_checkout':sum(bool(d and d['action']=='request_checkout') for d in final),'extra_turns':sum(len(r['turns'])-1 for r in chosen),
                'decline':sum(bool(d and d['action']=='decline') for d in final)})
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
