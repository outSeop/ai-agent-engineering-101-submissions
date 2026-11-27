"""HOST entry selection only; reuse the original cache reader binding and business checks."""
from pathlib import Path
from hashlib import sha256
import argparse,importlib.util,json,sys
HERE=Path(__file__).resolve().parent
OPERATOR=HERE.parent.parent
CACHE_MANIFEST_SHA="c55ada0a0df0e56963f0fdea40472cf4320e6ecef5d4b620bbb47da637e99957"
CACHE_BOOTSTRAP_SHA="0bffacbe1e4d7493645ff61f498bb4f2c95f7936522aa72357acfba31572a8d4"
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha',required=True)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('original_args',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    source=OPERATOR/'deploy/price_context_runtime_v8b/price_context_bootstrap.py'
    raw=source.read_bytes()
    if sha256(raw).hexdigest()!=CACHE_BOOTSTRAP_SHA:raise ValueError('original filesystem binding changed')
    spec=importlib.util.spec_from_file_location('_cache_reader_binding_v8b',source)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    exec(compile(raw,str(source),'exec'),module.__dict__)
    manifest_raw=module.checked(HERE/'MANIFEST.json')
    if sha256(manifest_raw).hexdigest()!=args.manifest_sha:raise ValueError('card single-decision manifest changed')
    entries=json.loads(manifest_raw)['file_sha256']
    if 'bootstrap.py' not in entries or 'card_maintenance.py' not in entries:raise ValueError('missing pinned entry')
    for name,pin in entries.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or sha256(module.checked(HERE/relative)).hexdigest()!=pin:raise ValueError('card single-decision dependency changed')
    base,helper=module.prepare('card',CACHE_MANIFEST_SHA)
    base.TARGETS['card']=(HERE.name,'card_maintenance.py',args.manifest_sha,'file_sha256')
    original=args.original_args
    if original[:1]==['--']:original=original[1:]
    result=base.run('card',original,check=args.check)
    if args.check:print(json.dumps({**result,'single_actual_model_completion':True,'source_only':True}))
if __name__=='__main__':main()
