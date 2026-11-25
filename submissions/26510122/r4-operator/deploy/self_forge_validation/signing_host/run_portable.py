"""Reproduce externally authored host tests with ephemeral keys, mocked pay and loopback HTTP only."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--operator',type=Path,required=True,help='Existing operator kit path; no live keys/state copied');parser.add_argument('--output',type=Path,required=True,help='New test-result directory');args=parser.parse_args();operator=args.operator.resolve(strict=True);here=Path(__file__).resolve().parent
 expected={'serialized_signer.py':'07d2eeb0f4e4d3f635035928135fc978120e93450695f27a4b94f2bfcc40e7f8','test_serialized_signer.py':'e6ababe4a840c1552eba82e6751405f5ecb4fa719f291f0c8263b78a5b1f5e6e'};assert (operator/'kit').is_dir();args.output.mkdir(parents=True,exist_ok=False)
 with tempfile.TemporaryDirectory(prefix='serialized-signer-mock-only-') as temp:
  op=Path(temp)/'operator';host=op/'runtime/synthetic-session/agent-work/host';host.mkdir(parents=True);(op/'kit').symlink_to(operator/'kit',target_is_directory=True)
  for name,digest in expected.items():
   data=(here/name).read_bytes();assert hashlib.sha256(data).hexdigest()==digest;(host/name).write_bytes(data)
  # Exact private layout depth preserves the ORIGINAL test's HERE.parents[3] op resolution.
  p=subprocess.run([sys.executable,str(host/'test_serialized_signer.py')],text=True,capture_output=True,timeout=120);(args.output/'runner.stdout.txt').write_text(p.stdout);(args.output/'runner.stderr.txt').write_text(p.stderr)
  for name in ['serialized-signer-final.log','serialized-signer-final-summary.json']:
   source=host/'validation'/name
   if source.exists():(args.output/name).write_bytes(source.read_bytes())
  assert p.returncode==0,'Mock tests failed; see output logs'
  summary=json.loads((args.output/'serialized-signer-final-summary.json').read_text());print(json.dumps(summary));assert summary['tests']==12 and summary['failures']==summary['errors']==0
if __name__=='__main__':main()
