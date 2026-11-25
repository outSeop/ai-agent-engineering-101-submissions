from pathlib import Path
import json,time
ROOT=Path(__file__).resolve().parent
prefix=(ROOT/'ordinary_toolbox_qa.py').read_text().split('\nwith Fake() as f:',1)[0];ns={'__file__':str(ROOT/'ordinary_toolbox_qa.py')};exec(compile(prefix,'unchanged_external_fixture','exec'),ns)
Fake=ns['Fake'];doc=ns['doc'];row=ns['row'];checks=[]
def ck(name,ok,observed=None):checks.append({'case':name,'passed':bool(ok),'observed':observed})
with Fake() as f:
 d=doc([row('sel'+str(i),name='가'*2800 if i==0 else '선택') if i%2==0 else row('excluded'+str(i),sku='G00000002') for i in range(200)]);f.write(d)
 original={'op':'context','skus':['G00000001']+['G'+format(i+100,'08x') for i in range(199)],'min_remaining_seconds':60};first=f.call(original);cursor=first['next_args'];ck('large_filtered_first_is_fragment','row_fragment' in first and first['total_count']==100)
 changed=dict(cursor,min_remaining_seconds=61);ck('fragment_minimum_substitution_rejected',f.call(changed)=={'error':'cursor_filters_changed'})
 changed=dict(cursor,skus=['G00000002']);ck('fragment_SKU_substitution_rejected',f.call(changed)=={'error':'cursor_filters_changed'})
 changed=dict(cursor);del changed['skus'];ck('fragment_filter_removal_rejected',f.call(changed)=={'error':'cursor_filters_changed'})
 changed=dict(cursor,filter_digest=True);ck('fragment_bool_digest_rejected',f.call(changed)=={'error':'invalid_args'})
 changed=dict(cursor,query_as_of=int(time.time())+50);ck('fragment_future_query_rejected',f.call(changed)=={'error':'invalid_args'})
 changed=dict(cursor,snapshot='0'*64);ck('fragment_wrong_snapshot_rejected',f.call(changed)=={'error':'snapshot_changed'})
 # Identical source bytes may be re-read; next_args as-is keeps full query and row identity.
 args=original;selected=[];parts={};maxchars=0;pages=0;filters_retained=True;completefrags=0
 for _ in range(300):
  page=f.call(args);assert 'error' not in page,page;pages+=1;maxchars=max(maxchars,len(json.dumps(page,ensure_ascii=True)));selected+=page['units']
  if 'row_fragment' in page:
   frag=page['row_fragment'];acc=parts.setdefault(frag['unit_index'],[]);assert frag['offset']==sum(map(len,acc));acc.append(frag['text'])
   if frag['complete']:selected.append(json.loads(''.join(acc)));completefrags+=1
  args=page['next_args']
  if args is None:break
  filters_retained &= args['skus']==original['skus'] and args['min_remaining_seconds']==60 and args['filter_digest']==cursor['filter_digest'] and args['query_as_of']==cursor['query_as_of']
 ck('fragment_next_args_alone_preserves_filter_every_page',filters_retained and args is None)
 ck('fragment_full_100_no_missing_duplicate_or_other_SKU',[x['unit_ref'] for x in selected]==['sel'+str(i) for i in range(0,200,2)] and all(x['sku']=='G00000001' for x in selected),{'pages':pages,'units':len(selected),'complete_fragmented_rows':completefrags})
 ck('fragment_name_exact_after_reassembly',selected[0]['name']=='가'*2800)
 ck('all_combined_pages_within5400',maxchars<=5400,{'max_json_chars':maxchars})
 # Change the real synthetic file after obtaining a cursor; no claimed authority from its hash.
 f.write(d);first=f.call(original);mutated=json.loads(json.dumps(d));mutated['units'][0]['price_credits']=1;f.write(mutated);ck('fragment_file_swap_rejected',f.call(first['next_args'])=={'error':'snapshot_changed'})
with Fake() as f:
 t=int(time.time());d=doc([row('expires-during-fragment',name='가'*2800,expires_at=t+2)]);f.write(d);first=f.call();assert 'row_fragment' in first and first['row_fragment']['as_of']<t+2,first
 time.sleep(max(0,t+2-time.time())+0.03);o=f.call(first['next_args']);ck('unit_expiring_during_fragment_explicit_error',o=={'error':'fragment_unit_expired'},o)
with Fake() as f:
 t=int(time.time());d=doc([row('short',expires_at=t+2)]+[row('long'+str(i)) for i in range(199)]);f.write(d);first=f.call({'op':'context','min_remaining_seconds':1});assert first['next_args'] is not None and first['total_count']==200
 time.sleep(max(0,t+2-time.time())+0.03);o=f.call(first['next_args']);ck('filter_eligibility_time_change_explicit_error',o=={'error':'filter_results_changed'},o)
result={'source_version':2,'ordinary_official_Toolbox_call':True,'manual_testing_flag':False,'synthetic_Fake_only':True,'checks':checks,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'production_cache_card_DB_changed':False,'actual_market_model_calls':0,'source_authentication_claim':False,'checkout_or_finance_fixed_claim':False}
(ROOT/'continuation-qa-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'failed':result['failed'],'failures':[x for x in checks if not x['passed']]},ensure_ascii=False))
