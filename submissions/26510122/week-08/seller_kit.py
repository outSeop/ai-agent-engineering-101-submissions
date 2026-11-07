"""Load the shared official kit read-only and attach supply observability."""
import importlib.util
import json
import re
import time
from pathlib import Path
import sys
from procurement_transport import instrument


def instrument_registration(kit,*,sleep=time.sleep):
    """Keep a newly opened URL alive for bounded retries of card timeouts only.

    Official join regenerates its own signature on each attempt. No checkout,
    supply, authentication refusal or other 4xx is retried by this wrapper.
    """
    if getattr(kit.Market,'_card_retry_installed',False):return
    join=kit.Market.join
    def with_retry(self,role,*args,**kwargs):
        for attempt in range(4):
            try:return join(self,role,*args,**kwargs)
            except SystemExit as error:
                match=re.fullmatch(r'\[market\] join as shop failed: 400 (.+)',str(error))
                try:reason=json.loads(match[1]).get('error','') if match else ''
                except ValueError:reason=''
                transient=(role=='shop' and reason.startswith('cannot read an agent card at ')
                    and reason.endswith(('(TimeoutError)','(ConnectTimeout)','(ReadTimeout)')))
                if not transient or attempt==3:raise
                kit.log(f'[market] card check timed out; retrying the same shop URL in 15 s (attempt {attempt+2}/4)')
                sleep(15)
    kit.Market.join=with_retry;kit.Market._card_retry_installed=True


def main():
    path=Path(sys.argv[1]).resolve();sys.argv.pop(1)
    spec=importlib.util.spec_from_file_location('observed_official_market_kit',path)
    kit=importlib.util.module_from_spec(spec);sys.modules[spec.name]=kit
    spec.loader.exec_module(kit)
    instrument(kit);instrument_registration(kit);kit.main()


if __name__=='__main__':main()
