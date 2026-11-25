from pathlib import Path
import importlib.util,json,tempfile
ST=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('maintenance_under_test',ST/'card_maintenance.py');h=importlib.util.module_from_spec(s);s.loader.exec_module(h);results=[]
def check(name,ok):results.append(dict(case=name,passed=bool(ok)))
with tempfile.TemporaryDirectory() as t:
 op=Path(t)/'operator';(op/'runtime').mkdir(parents=True);calls=[];clock=[1000.0]
 select=lambda:calls.append('select') or dict(status='applied',card_written=True)
 run=lambda legacy,sel=select,active=False,allow=True:h.maintain(op,allow=allow,_legacy=lambda:legacy,_select=sel,_foreground=lambda:active,_clock=lambda:clock[0])
 r=run(dict(status='requires_class_selection'),allow=False);check('default_dry_no_calls',r['status']=='dry' and calls==[] and not (op/'runtime/card-reselection-control').exists())
 r=run(dict(status='applied'));check('same_choice_first_no_model',r['status']=='applied' and calls==[])
 r=run(dict(status='requires_class_selection'),active=True);check('foreground_defers_before_attempt',r['status']=='selection_postponed_for_customer' and calls==[])
 failed=lambda:calls.append('failed_select') or dict(status='class_selection_not_staged')
 r=run(dict(status='requires_class_selection'),failed);check('failed_selection_sets_cooldown',r['class_selection_invoked'] and r['retry_after']==1600 and calls==['failed_select'])
 r=run(dict(status='requires_class_selection'));check('cooldown_no_model',r['status']=='selection_cooldown' and calls==['failed_select'])
 r=run(dict(status='applied'));check('healthy_samechoice_still_refreshes_during_cooldown',r['status']=='applied' and calls==['failed_select'])
 clock[0]=1601;r=run(dict(status='requires_class_selection'));check('retry_success_clears_cooldown',r['status']=='applied' and r['retry_after']==0 and calls==['failed_select','select'])
 def exception():calls.append('exception');raise RuntimeError('SYNTHETIC_PRIVATE_DIAGNOSTIC')
 r=run(dict(status='requires_class_selection'),exception);check('exception_cooldown_and_private_diagnostic',r['status']=='reselection_unavailable' and 'SYNTHETIC_PRIVATE_DIAGNOSTIC' not in json.dumps(r) and (op/'runtime/card-reselection-control/last-error-private.json').exists())
result=dict(passed=sum(x['passed'] for x in results),failed=sum(not x['passed'] for x in results),checks=results,all_legacy_Model_and_live_callbacks_mocked=True,actual_Model_service_market_wallet_DB_operations=0)
(Path(__file__).parent/'maintenance-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
