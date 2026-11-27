"""First stable-router migration. Existing services and tunnel are never restarted.

After any persistent current task exists, reversing to the legacy listener is
forbidden. Future recovery uses the same router, worker port and private DB.
"""
import argparse,json,os,pwd,subprocess,time
from pathlib import Path
import transition_guard as legacy
from run_front_edge import reviewed_front,protected,load

ROUTER_UNIT='ourolabs-market-r4-router.service'
ROUTER_PORT='18811'
ROUTER_MARKER='r4-flat-router-v1'

def owner_command(op,args):
    uid=op.stat().st_uid;name=pwd.getpwuid(uid).pw_name
    command=['/usr/sbin/runuser','-u',name,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(uid),
             'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(uid)+'/bus',*map(str,args)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=15)
    if result.returncode:raise ValueError('owner-scoped HOST operation failed')
    return result.stdout

def state_operation(op,folder,*,enable=None):
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from task_state import TaskStateDB;d=TaskStateDB(sys.argv[2]);"
    if enable is not None:code+='d.set_maintenance('+repr(enable)+');'
    code+="print(json.dumps({'maintenance':d.maintenance_enabled(),'stats':d.route_stats()}))"
    return json.loads(owner_command(op,[op/'.venv/bin/python','-B','-c',code,folder,op/'runtime/a2a-host/state.sqlite3']))

def router_pid(op):
    raw=owner_command(op,['systemctl','--user','show',ROUTER_UNIT,'-p','MainPID','--value']).strip()
    if not raw.isdigit():raise ValueError('stable router PID unavailable')
    return int(raw)

def preserve(op,folder,pin,engine_pid,expected_router):
    legacy.preserve_processes(engine_pid)
    if router_pid(op)!=expected_router or not legacy.pid_alive(expected_router):raise ValueError('stable router process changed')
    command=(Path('/proc')/str(expected_router)/'cmdline').read_bytes().split(b'\0')
    if str(folder/'run_flat_router.py').encode() not in command or b'--edge-manifest-sha' not in command or command[command.index(b'--edge-manifest-sha')+1]!=pin.encode():
        raise ValueError('router exact launcher changed')

def router_card(url):
    actual,headers=legacy.card('http://127.0.0.1:18811/.well-known/agent-card.json')
    origin,_=legacy.card('http://127.0.0.1:18805/.well-known/agent-card.json')
    if not legacy.equal_identity(origin,actual) or headers.get('x-r4-edge')!=ROUTER_MARKER:
        raise ValueError('router direct original card mismatch')
    interfaces=origin.get('supportedInterfaces',[])
    if len(interfaces)!=1 or interfaces[0].get('url','').rstrip('/')!=url.rstrip('/') or not legacy.pending_matches(url):
        raise ValueError('preserved public URL or pending checkout changed')
    return origin

def postcheck(url):
    deadline=time.monotonic()+20
    for attempt in range(3):
        origin=router_card(url);actual,headers=legacy.card(url.rstrip('/')+'/.well-known/agent-card.json',timeout=3)
        if not legacy.equal_identity(origin,actual):raise ValueError('public identity changed')
        if headers.get('x-r4-edge')==ROUTER_MARKER and legacy.equal_card(origin,actual):return
        if time.monotonic()+6>=deadline:break
        time.sleep(6)
    raise ValueError('public router marker or current description did not converge')

def activate_new_router(op,folder,url,check):
    state=state_operation(op,folder)
    if not state['maintenance'] or state['stats']['current'] or state['stats']['tasks']:
        raise ValueError('initial migration requires closed pristine current engine')
    if state['stats']['legacy']<41 or state['stats']['snapshots']<41:raise ValueError('legacy route inventory incomplete')
    legacy.idle10();check();router_card(url)
    legacy.replace('18810',ROUTER_PORT)
    try:
        postcheck(url);check()
    except Exception:
        state=state_operation(op,folder)
        if state['maintenance'] and state['stats']['current']==0 and state['stats']['tasks']==0:
            legacy.replace(ROUTER_PORT,'18810')
        raise
    state=state_operation(op,folder,enable=False)
    return state

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator',type=Path,required=True)
    parser.add_argument('--package-manifest-sha',required=True)
    parser.add_argument('--expected-engine-pid',type=int,required=True)
    parser.add_argument('--expected-router-pid',type=int,required=True)
    parser.add_argument('--expected-public-url',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();op=args.operator.resolve(strict=True)
    if os.geteuid()!=0 or not args.expected_public_url.startswith('https://'):raise ValueError('root and preserved HTTPS URL required')
    legacy.verify_package(args.package_manifest_sha);folder=Path(__file__).resolve().parent
    meta=json.loads((folder/'MANIFEST.json').read_bytes())
    config=load('flat_guard_config',folder/'config.py').load_pinned(folder,meta,operator=op)
    if config.new_port!=18812 or config.old_proxy_port!=18810:raise ValueError('fixed stable migration required')
    legacy.configure(config,args.package_manifest_sha)
    legacy.NEW_PORT=ROUTER_PORT
    legacy.verify_preserved_fronts()
    check=lambda:preserve(op,folder,args.package_manifest_sha,args.expected_engine_pid,args.expected_router_pid)
    check();router_card(args.expected_public_url)
    state=state_operation(op,folder);target=legacy.chain()
    if not args.apply:
        print(json.dumps({'status':'inspected_only','rule_target':int(target),**state}));return
    if target==ROUTER_PORT:
        postcheck(args.expected_public_url);check()
        if state['maintenance']:raise ValueError('router is already installed but closed; inspect and explicitly recover forward')
        print(json.dumps({'status':'stable_router_already_active',**state}));return
    state=activate_new_router(op,folder,args.expected_public_url,check)
    print(json.dumps({'status':'stable_router_verified_and_current_engine_open','old_process_changes':0,**state}))
if __name__=='__main__':main()
