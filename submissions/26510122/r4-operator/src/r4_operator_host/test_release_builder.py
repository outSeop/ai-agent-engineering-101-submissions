"""Packaging-only regressions: no agent code, services, credentials or network."""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
import importlib.util,json,sys,unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('release_builder_under_test',HERE/'release_builder.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

def write(path,raw):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    path.write_bytes(raw);path.chmod(0o600)

def setup_fixture(root):
    root=Path(root);base=root/'deploy/base';basefiles={'public_catalogue_protocol.py':b'BASE = 1\n','catalogue/logic.py':b'UNCHANGED_CATALOGUE = True\n'}
    for name,raw in basefiles.items():write(base/name,raw)
    base_manifest=b.encode({'file_sha256':{name:b.digest(raw) for name,raw in basefiles.items()}});write(base/'MANIFEST.json',base_manifest)
    override=root/'src/protocol.py';write(override,b'BASE = 2\n')
    def source(path):return {'source':str(path.relative_to(root)),'sha256':b.digest(path.read_bytes())}
    front={}
    for name in ['config.py','admission_gate.py','front_edge_app.py','run_front_edge.py','transition_guard.py']:
        path=root/'src/front'/name;write(path,b'pass\n');front[name]=source(path)
    native={};blobs={'logic.py':b'def run(args,kit): return {}\n','test.py':b'pass\n','permission.yml':b'permission: {}\n'}
    blobs['forge.json']=b.encode({'tool':'semantic_candidates','version':7,'sha256':{name:b.digest(raw) for name,raw in blobs.items()}})
    for name,raw in blobs.items():
        path=root/'deploy/native'/name;write(path,raw);native[name]=source(path)
    data={'schema':'r4-host-release.v1','builder_sha256':b.digest(Path(b.__file__).read_bytes()),'runtime_base':{'source':'deploy/base','manifest_sha256':b.digest(base_manifest)},'runtime_overrides':{'public_catalogue_protocol.py':source(override)},'native_semantic':{'tool':'semantic_candidates','version':7,'files':native},'front_sources':front,'front_binding':{'new_port':18810}}
    path=root/'deploy/release_specs/test.json';write(path,b.encode(data));return path,data,blobs

class ReleaseTests(unittest.TestCase):
    def fixture(self):
        directory=TemporaryDirectory(prefix='r4-package-only-');self.addCleanup(directory.cleanup)
        root=Path(directory.name);return root,*setup_fixture(root)
    def test_repeatable_copy_preserves_native_assets_and_reuses_without_rewrite(self):
        root,path,data,blobs=self.fixture();pin=b.digest(path.read_bytes());first=b.build(root,path,pin)
        target=Path(first['runtime_path']);inode=(target/'public_catalogue_protocol.py').stat().st_ino
        second=b.build(root,path,pin)
        self.assertTrue(second['reused']);self.assertEqual(inode,(target/'public_catalogue_protocol.py').stat().st_ino)
        self.assertEqual((target/'public_catalogue_protocol.py').read_bytes(),b'BASE = 2\n')
        for name,raw in blobs.items():self.assertEqual((target/'semantic'/name).read_bytes(),raw)
        config=json.loads((Path(first['front_path'])/'RUNTIME-BINDING.json').read_bytes())
        self.assertEqual(config['runtime_manifest_sha256'],first['runtime_manifest_sha256'])
        self.assertEqual(config['runtime_path'],first['runtime_path'])
        self.assertEqual(json.loads((target/'MANIFEST.json').read_bytes())['semantic_original_forge_sha256'],b.digest(blobs['forge.json']))
    def test_same_spec_builds_under_two_distinct_operator_roots(self):
        left,lp,ld,lb=self.fixture();right,rp,rd,rb=self.fixture()
        self.assertNotEqual(left,right);self.assertEqual(lp.read_bytes(),rp.read_bytes())
        a=b.build(left,lp,b.digest(lp.read_bytes()));z=b.build(right,rp,b.digest(rp.read_bytes()))
        self.assertEqual(a['release_id'],z['release_id'])
        for root,receipt in ((left,a),(right,z)):
            runtime=Path(receipt['runtime_path']);context=json.loads((runtime/'HOST-CONTEXT.json').read_bytes())
            self.assertEqual(context['operator_root'],str(root));self.assertEqual(context['base_protocol'],'deploy/base/public_catalogue_protocol.py')
            self.assertEqual((runtime/'semantic/logic.py').read_bytes(),lb['logic.py'])
        # Local absolute bindings are intentionally materialized, not source identity.
        self.assertNotEqual(a['runtime_manifest_sha256'],z['runtime_manifest_sha256'])
    def test_source_or_existing_release_tamper_is_rejected(self):
        root,path,data,blobs=self.fixture();pin=b.digest(path.read_bytes());receipt=b.build(root,path,pin)
        override=root/'src/protocol.py';write(override,b'UNREVIEWED = True\n')
        with self.assertRaises(ValueError):b.build(root,path,pin)
        write(override,b'BASE = 2\n');target=Path(receipt['runtime_path'])/'public_catalogue_protocol.py';target.chmod(0o600);write(target,b'DRIFT = True\n');target.chmod(0o400)
        with self.assertRaises(ValueError):b.build(root,path,pin)
    def test_escape_and_native_business_override_are_rejected(self):
        for destination in ['../outside.py','catalogue/logic.py']:
            root,path,data,blobs=self.fixture();record=data['runtime_overrides'].pop('public_catalogue_protocol.py');data['runtime_overrides'][destination]=record;write(path,b.encode(data))
            with self.assertRaises(ValueError):b.build(root,path,b.digest(path.read_bytes()))
            self.assertEqual((root/'deploy/base/catalogue/logic.py').read_bytes(),b'UNCHANGED_CATALOGUE = True\n')
        root,path,data,blobs=self.fixture();data['runtime_overrides']['public_catalogue_protocol.py']['source']='../outside.key';write(path,b.encode(data))
        with self.assertRaises(ValueError):b.build(root,path,b.digest(path.read_bytes()))

    def test_v2_exact_extra_native_and_new_host_extension(self):
        root,path,data,blobs=self.fixture()
        data.update(schema='r4-host-release.v2',runtime_extensions={},native_tools={})
        host=root/'src/extra_host.py';write(host,b'EXTRA_HOST = True\n')
        data['runtime_extensions']['extra_host.py']={'source':'src/extra_host.py','sha256':b.digest(host.read_bytes())}
        extra={k:v for k,v in blobs.items() if k!='forge.json'}
        extra['forge.json']=b.encode({'tool':'extra_read','version':1,'sha256':{n:b.digest(v) for n,v in extra.items()}})
        pins={}
        for name,raw in extra.items():
            target=root/'deploy/extra'/name;write(target,raw);pins[name]={'source':str(target.relative_to(root)),'sha256':b.digest(raw)}
        data['native_tools']['extra_read']={'tool':'extra_read','version':1,'files':pins};write(path,b.encode(data))
        receipt=b.build(root,path,b.digest(path.read_bytes()));runtime=Path(receipt['runtime_path'])
        self.assertEqual((runtime/'extra_host.py').read_bytes(),host.read_bytes())
        for name,raw in extra.items():self.assertEqual((runtime/'extra_read'/name).read_bytes(),raw)
        for name,raw in blobs.items():self.assertEqual((runtime/'semantic'/name).read_bytes(),raw)
        context=json.loads((runtime/'HOST-CONTEXT.json').read_bytes());self.assertEqual(context['native_tools']['extra_read']['directory'],'extra_read')
        self.assertEqual(context['native_tools']['extra_read']['files'],{n:b.digest(v) for n,v in extra.items()})
    def test_v2_refuses_native_collision_and_provenance_drift(self):
        for tool,forge_tool in [('catalogue','catalogue'),('extra_read','wrong_tool')]:
            root,path,data,blobs=self.fixture();data.update(schema='r4-host-release.v2',runtime_extensions={},native_tools={})
            extra={k:v for k,v in blobs.items() if k!='forge.json'};extra['forge.json']=b.encode({'tool':forge_tool,'version':1,'sha256':{n:b.digest(v) for n,v in extra.items()}})
            pins={}
            for name,raw in extra.items():
                target=root/'deploy/extra'/name;write(target,raw);pins[name]={'source':str(target.relative_to(root)),'sha256':b.digest(raw)}
            data['native_tools'][tool]={'tool':tool,'version':1,'files':pins};write(path,b.encode(data))
            with self.assertRaises(ValueError):b.build(root,path,b.digest(path.read_bytes()))

if __name__=='__main__':unittest.main()
