"""Independent synthetic state/authority probes. Candidate source remains unchanged."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import argparse

ALICE='0x'+'1'*40
SHOP='0x'+'3'*40
ATTACKER='0x'+'2'*40
TX='0x'+'a'*64
TX2='0x'+'c'*64
MARKER='0x'+'4'*64


def evaluate(source):
    spec=importlib.util.spec_from_file_location('candidate_state_probe',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    results=[]
    with tempfile.TemporaryDirectory(prefix='r4-synthetic-state-') as temp:
        class Kit:
            testing=False
            def address(self,role):return SHOP
            def pay(self,to,wei,data_hex,role='shop'):
                calls.append((to,wei,data_hex))
                if uncertain:raise TimeoutError('synthetic response lost after send')
                return '0x'+'b'*64
        kit=Kit();calls=[];uncertain=False;receiver=SHOP;barrier=None
        def rpc(method,params):
            tx=params[0]
            if method=='eth_getTransactionByHash':
                if barrier:barrier.wait(timeout=3)
                return {'hash':tx,'from':ALICE,'to':receiver,'value':hex(10**16),'input':MARKER}
            if method=='eth_getTransactionReceipt':return {'status':'0x1','transactionHash':tx,'from':ALICE,'to':receiver}
            raise AssertionError(method)
        module.rpc=rpc
        base={'approval':True,'recipient':ALICE,'refund_credits':10,'original_tx':TX,
            'original_receipt':{'status':1,'from':ALICE,'to':SHOP,'value':10**16},
            'ledger':{'broken':True,'tx_hash':TX,'item':'synthetic-sku','order':'synthetic-order','shop':'outseop-r4','payer':ALICE,'recipient':ALICE},
            'evidence':{'delivered':True,'early_issue':True,'hours_after_sale':2},
            'duplicate_refund':False,'promised_gas_limit':210,'gas_credits':0,'credit_wei':10**15}
        def reset(label):
            nonlocal calls,uncertain,receiver,barrier
            calls=[];uncertain=False;receiver=SHOP;barrier=None;module.STATE=str(Path(temp)/(label+'.json'))
        def run(a):return module.run(deepcopy(a),kit)
        reset('positive');reply=run(base)
        results.append({'case':'positive_control','passed':len(calls)==1 and reply.get('approved') is True,'attempts':len(calls)})
        assert results[0]['passed'],'candidate interface or synthetic positive path not established'
        reset('spoof');a=deepcopy(base);a['recipient']=ATTACKER;a['original_receipt']['from']=ATTACKER;a['ledger'].update(payer=ATTACKER,recipient=ATTACKER);run(a)
        results.append({'case':'recipient_spoof','passed':not calls,'attempts':len(calls)})
        reset('serial');run(base);run(base);results.append({'case':'serial_replay','passed':len(calls)==1,'attempts':len(calls)})
        reset('unknown');uncertain=True;run(base);run(base);results.append({'case':'uncertain_same_payment','passed':len(calls)==1,'attempts':len(calls)})
        reset('wrongreceiver');receiver='0x'+'9'*40;run(base);results.append({'case':'original_payment_not_to_this_shop','passed':not calls,'attempts':len(calls)})
        reset('corruption');run(base);Path(module.STATE).write_text('{corrupted');run(base);results.append({'case':'corrupt_state_fails_closed','passed':len(calls)==1,'attempts':len(calls)})
        reset('concurrent');barrier=threading.Barrier(2)
        def safe_run(_):
            try:return run(base)
            except Exception as error:return {'error':type(error).__name__}
        with ThreadPoolExecutor(max_workers=2) as pool:answers=list(pool.map(safe_run,range(2)))
        results.append({'case':'concurrent_replay','passed':len(calls)==1,'attempts':len(calls),'errors':[a.get('error') for a in answers if a.get('error')]})
        reset('crossunknown');uncertain=True;run(base);a=deepcopy(base);a['original_tx']=TX2;a['ledger'].update(tx_hash=TX2,order='synthetic-order2');run(a)
        results.append({'case':'global_uncertain_payment_gate','passed':len(calls)==1,'attempts':len(calls)})
    return {'source':str(source),'synthetic_only':True,'real_network_calls':0,'real_payments':0,'passed':sum(r['passed'] for r in results),'total':len(results),'cases':results}


def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=evaluate(a.source.resolve());a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
