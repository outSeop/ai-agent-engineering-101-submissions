"""Independent probes for the first class-authored candidate; no real RPC/payments."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ALICE='0x'+'1'*40
ATTACKER='0x'+'2'*40
TX='0x'+'a'*64


def evaluate(source):
    spec=importlib.util.spec_from_file_location('class_candidate_probe',source)
    candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)
    payments=[]
    uncertain=False
    def pay(to,wei,data_hex,role='shop'):
        payments.append((to,wei,data_hex,role))
        if uncertain:raise TimeoutError('synthetic response lost after send')
        return '0x'+'b'*64
    kit=SimpleNamespace(testing=False,pay=pay)
    def rpc(method,params):
        if method=='eth_getTransactionReceipt':
            return {'status':'0x1','transactionHash':TX,'from':ALICE,'to':'0x'+'3'*40}
        if method=='eth_getTransactionByHash':
            return {'hash':TX,'from':ALICE,'to':'0x'+'3'*40,'value':hex(10**16),'input':'0x'+'4'*64}
        raise AssertionError('unexpected RPC '+method)
    candidate.rpc=rpc
    base={'approval':True,'recipient':ALICE,'refund_credits':10,'original_tx':TX,
          'original_receipt':{'status':1,'from':ALICE,'value':10**16},
          'ledger':{'broken':True,'tx_hash':TX,'item':'synthetic-sku','order':'synthetic-order','shop':'outseop-r4'},
          'evidence':{'delivered':True,'early_issue':True,'hours_after_sale':2},
          'duplicate_refund':False,'promised_gas_limit':210,'gas_credits':0,'credit_wei':10**15}
    result=[]
    a=deepcopy(base);a['recipient']=ATTACKER;a['original_receipt']['from']=ATTACKER
    payments.clear();reply=candidate.run(a,kit)
    result.append({'case':'caller_cannot_substitute_original_payer','passed':not payments,
                   'observed_payment_attempts':len(payments),'candidate_approved':reply.get('approved')})
    payments.clear();candidate.run(deepcopy(base),kit);candidate.run(deepcopy(base),kit)
    result.append({'case':'same_original_payment_is_refunded_at_most_once','passed':len(payments)==1,
                   'observed_payment_attempts':len(payments)})
    payments.clear();uncertain=True;candidate.run(deepcopy(base),kit);candidate.run(deepcopy(base),kit);uncertain=False
    result.append({'case':'uncertain_send_never_blindly_repeats','passed':len(payments)==1,
                   'observed_payment_attempts':len(payments)})
    a=deepcopy(base);a['gas_credits']=-1;payments.clear();candidate.run(a,kit)
    result.append({'case':'negative_expense_is_rejected','passed':not payments,'observed_payment_attempts':len(payments)})
    a=deepcopy(base);a['evidence']={'delivered':False,'seller_fault':True};a['ledger']['broken']=False
    payments.clear();reply=candidate.run(a,kit)
    result.append({'case':'verified_seller_fault_nondelivery_is_reviewable','passed':reply.get('reason') not in ('delivery_not_established','ledger_evidence_invalid'),
                   'candidate_reason':reply.get('reason')})
    return {'source':str(source),'synthetic_only':True,'real_network_calls':0,'real_payments':0,
            'passed':sum(r['passed'] for r in result),'total':len(result),'cases':result}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('candidate',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=evaluate(args.candidate.resolve());args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
