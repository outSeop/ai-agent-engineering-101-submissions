"""Stable router launcher. It never creates a wallet, calls a Model or starts Mind."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_front_edge import protected,reviewed_front,verify,load
from task_state import TaskStateDB
from flat_router import FlatRouter

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator',type=Path,required=True)
    parser.add_argument('--edge-manifest-sha',required=True)
    parser.add_argument('--serve',action='store_true')
    args=parser.parse_args();os.umask(0o077)
    reviewed_front(args.edge_manifest_sha)
    folder=Path(__file__).resolve().parent;meta=json.loads(protected(folder/'MANIFEST.json'))
    op=args.operator.resolve(strict=True)
    config=load('router_verified_config',folder/'config.py').load_pinned(folder,meta,operator=op)
    verify(op,config.runtime_path,config.runtime_manifest_sha256,config)
    if config.new_port!=18812 or tuple(e.port for e in config.edges)!=(18806,18807,18808,18809,18810):
        raise ValueError('reviewed stable worker/legacy topology required')
    if not args.serve:
        print(json.dumps({'status':'router_sources_verified_only','wallet_Model_network_calls':0}));return
    state=TaskStateDB(op/'runtime/a2a-host/state.sqlite3')
    app=FlatRouter(state,worker_port=18812,legacy_ports=range(18805,18811),
        trace=op/'runtime/a2a-host/router-trace-private.jsonl',
        status_file=op/'runtime/a2a-host/router-status.json')
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=18811,log_level='warning',access_log=False,timeout_keep_alive=5)
if __name__=='__main__':main()
