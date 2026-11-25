"""Explicit future canary entry. Default: source-plan only, no Model or writes.

Root must install native bundles and complete the reviewed legacy fence first.
This script is not installed or run against production by its QA author.
"""
import argparse,json,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
WORK=HERE
sys.path.insert(0,str(HERE.parent))
sys.path.insert(0,str(WORK))
from card_apply_canary_host import apply_verified_stage,rollback_current,verify_bundles,read,sha


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator',required=True,type=Path)
    parser.add_argument('--session',type=Path)
    parser.add_argument('--replace-text-file',type=Path)
    parser.add_argument('--policy-anchors',type=Path)
    parser.add_argument('--intent',type=Path)
    parser.add_argument('--run-controller',action='store_true')
    parser.add_argument('--allow-apply',action='store_true')
    parser.add_argument('--rollback-event')
    parser.add_argument('--allow-rollback',action='store_true')
    args=parser.parse_args(argv)
    if args.allow_apply and not args.run_controller:parser.error('--allow-apply requires --run-controller')
    if args.allow_rollback and not args.rollback_event:parser.error('--allow-rollback requires --rollback-event')
    if args.rollback_event and (args.run_controller or args.allow_apply):parser.error('rollback and new controller run are separate')
    op=args.operator.resolve(strict=True);root=op.parent/'round-4'
    pins=verify_bundles(root)
    if not args.run_controller and not args.rollback_event:
        result={'status':'source_plan_only','native_bundles':list(pins),'card_sha256':sha(read(root/'card.json')),'model_called':False,'writes_performed':False,
                'precondition':'Root has installed exact bundles and completed reviewed legacy-writer fence; no live action by this plan.'}
        print(json.dumps(result));return result
    sys.path.insert(0,str(op/'kit'));import agent_kit as official
    if args.rollback_event:
        result=rollback_current(root=root,official=official,event_id=args.rollback_event,allow_rollback=args.allow_rollback)
        print(json.dumps(result));return result
    if not all((args.session,args.replace_text_file,args.policy_anchors)):parser.error('controller requires session, replacement span, reviewed policy anchors')
    policies=json.loads(read(args.policy_anchors.absolute()))
    from card_stage_recheck_controller import main as controller_main
    session=args.session.absolute();result={}
    def continuation(*,origin,original_view_raw,fresh_view_raw,before_card_raw):
        nonlocal result
        result=apply_verified_stage(root=root,official=official,stage_directory=session/'card_update_stage',origin=origin,
             original_view_raw=original_view_raw,fresh_view_raw=fresh_view_raw,before_card_raw=before_card_raw,policy_anchors=policies,allow_apply=args.allow_apply)
        return result
    command=['--operator',str(op),'--session',str(session),'--replace-text-file',str(args.replace_text_file.absolute())]
    if args.intent:command+=['--intent',str(args.intent.absolute())]
    controller_main(command,continuation=continuation)
    if not result:result={'status':'no_verified_same_run_stage','applied_live':False}
    # Separate result prevents a stage-only summary from implying no callback action.
    with (session/'canary-host-result.json').open('x') as stream:json.dump(result,stream);stream.write('\n')
    print(json.dumps(result));return result

if __name__=='__main__':main()
