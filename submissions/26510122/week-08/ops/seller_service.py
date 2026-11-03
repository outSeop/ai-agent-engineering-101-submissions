"""Seller-only service with a frozen release and renewable public tunnel.

Prepare once from reviewed source. Running the service never reloads unfinished
buyer work. Private keys stay in their existing location through local symlinks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
FILES=('seller_r3.py','harness.py','market_memory.py','newsvendor_tool.py','context_compaction.py',
       'inventory_observation.py','replenishment_plan.py','restock.py','buyer_identity.py','counterparty_memory.py')
STOP=False


def log(message):print(time.strftime('%Y-%m-%d %H:%M:%S')+' '+message,flush=True)


def prepare(runtime,keys):
    runtime.mkdir(parents=True,exist_ok=True)
    release=runtime/'release';release.mkdir(exist_ok=False)
    digests={}
    for name in FILES:
        shutil.copy2(ROOT/name,release/name)
        digests[name]=hashlib.sha256((release/name).read_bytes()).hexdigest()
    logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    if not (runtime/'logs').exists():(runtime/'logs').symlink_to(logs,target_is_directory=True)
    for name in ('shop_key.pem','buyer_key.pem'):
        source=(keys/name).resolve()
        if not source.is_file():raise FileNotFoundError(f'Existing market key is missing: {name}')
        dest=runtime/name
        if not dest.exists():dest.symlink_to(source)
        elif dest.resolve()!=source:raise ValueError('Runtime has a different key source')
    python=ROOT/'.venv/bin/python'
    config={'harness':'Frozen seller-only Round 3 release; buyer and roleplay are not enabled',
            'seller':{'cmd':shlex.join([str(python),str(release/'seller_r3.py'),'--port','{port}'])},
            'restock':{'cmd':shlex.join([str(python),str(release/'restock.py'),'--state','{state}'])}}
    (runtime/'agent.json').write_text(json.dumps(config,indent=2))
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    (runtime/'release.json').write_text(json.dumps({'source_commit':commit,'sha256':digests,'prepared_at':time.time()},indent=2))
    log(f'Prepared frozen seller-only release: {runtime}')


def stop(proc):
    if proc is None or proc.poll() is not None:return
    try:os.killpg(proc.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait(timeout=5)


def run(args):
    global STOP
    def finish(*_):
        global STOP
        STOP=True
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    runtime=args.runtime
    manifest=json.loads((runtime/'release.json').read_text())
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((runtime/'release'/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Frozen release integrity changed')
    config=json.loads((runtime/'agent.json').read_text())
    if set(config)-{'harness','seller','restock'}:raise ValueError('Seller-only runtime contains buyer hooks')
    if not args.owner_file.is_file():raise FileNotFoundError('Existing market owner credential is missing')
    kit=ROOT.parents[2]/'scripts/market_kit.py'
    env=os.environ.copy()
    env['PATH']=f"{Path.home()/'.local/bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{env.get('PATH','')}"
    env['MARKET_OWNER']=args.owner_file.read_text().strip()
    env['PYTHONUNBUFFERED']='1'
    while not STOP:
        ssh=market=None
        try:
            with (ROOT/'logs/seller-r3-tunnel.log').open('a') as ssh_log, \
                 (ROOT/'logs/seller-r3-kit-console.log').open('a') as kit_log:
                ssh=subprocess.Popen(['/usr/bin/ssh','-p','443','-tt','-o','BatchMode=yes','-o','ConnectTimeout=8',
                    '-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=20','-o','ServerAliveCountMax=3',
                    '-o','StrictHostKeyChecking=accept-new','-o',f'UserKnownHostsFile={runtime/"known_hosts"}',
                    f'-R0:127.0.0.1:{args.port}',f'-L{args.debug_port}:localhost:4300','free.pinggy.io'],
                    stdin=subprocess.PIPE,stdout=ssh_log,stderr=subprocess.STDOUT,start_new_session=True)
                until=time.monotonic()+40;url=None
                while not STOP and ssh.poll() is None and time.monotonic()<until:
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{args.debug_port}/urls',timeout=2) as response:
                            urls=json.load(response).get('urls',[])
                        url=next((u for suffix in ('.free.pinggy.net','.run.pinggy-free.link') for u in urls
                                  if isinstance(u,str) and u.startswith('https://') and suffix in u),None)
                        if url:break
                    except (OSError,ValueError):pass
                    time.sleep(1)
                if STOP:break
                if not url:raise RuntimeError('Public tunnel did not become ready')
                log(f'Tunnel ready: {url}')
                market=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(kit),'join','--dir',str(runtime),
                    '--market','https://market.ourolabs.ai','--name','outseop-26510122','--port',str(args.port),
                    '--public-url',url,'--shop-only'],cwd=runtime,env=env,
                    stdout=kit_log,stderr=subprocess.STDOUT,start_new_session=True)
                status={'supervisor_pid':os.getpid(),'kit_pid':market.pid,'tunnel_pid':ssh.pid,'url':url,
                        'source_commit':manifest['source_commit'],'started_at':time.time(),'buyer_enabled':False}
                (runtime/'running.json').write_text(json.dumps(status,indent=2))
                until=time.monotonic()+55*60
                while not STOP and ssh.poll() is None and market.poll() is None and time.monotonic()<until:time.sleep(2)
                log(f'Renew/exit: tunnel={ssh.poll()}, kit={market.poll()}')
        except Exception as error:log(f'Service cycle failed: {type(error).__name__}: {error}')
        finally:stop(market);stop(ssh)
        for _ in range(15):
            if STOP:break
            time.sleep(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path,default=ROOT/'state/seller-runtime')
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--keys-dir',type=Path)
    parser.add_argument('--owner-file',type=Path,default=Path.home()/'.config/ourolabs-market/owner-code')
    parser.add_argument('--port',type=int,default=9300);parser.add_argument('--debug-port',type=int,default=9437)
    args=parser.parse_args();args.runtime=args.runtime.resolve()
    if args.prepare_only:
        if not args.keys_dir:parser.error('--keys-dir required for preparation')
        prepare(args.runtime,args.keys_dir)
    else:run(args)
