import json,shlex,tempfile,unittest
from pathlib import Path
from ops.rollout_linux import rebound_seller_config
from ops.seller_service import kit_entrypoint


class RolloutConfigTests(unittest.TestCase):
    def test_updated_supervisor_can_start_old_or_rolled_back_frozen_release(self):
        live=Path('/runtime');kit=Path('/shared/market_kit.py')
        self.assertEqual(kit_entrypoint(live,kit,{'sha256':{'seller_r3.py':'hash'}}),[str(kit)])
        self.assertEqual(kit_entrypoint(live,kit,{'sha256':{'seller_kit.py':'hash'}}),
                         ['/runtime/release/seller_kit.py',str(kit)])
    def test_new_restock_entrypoint_is_rebound_from_stage_to_live_release(self):
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory)/'stage';stage.mkdir();live=Path(directory)/'live'
            original={'harness':'seller','seller':{'cmd':shlex.join(['python',str(stage/'release/seller_r3.py')])},
                      'restock':{'cmd':shlex.join(['python',str(stage/'release/procurement_scheduler.py'),'--execute','--state','{state}'])}}
            (stage/'agent.json').write_text(json.dumps(original))
            result=rebound_seller_config(stage,live)
            self.assertEqual(shlex.split(result['restock']['cmd']),
                             ['python',str(live/'release/procurement_scheduler.py'),'--execute','--state','{state}'])
            self.assertEqual(json.loads((stage/'agent.json').read_text()),original)


class TunnelDomainTests(unittest.TestCase):
    def test_failed_start_can_choose_the_second_provider_domain(self):
        from ops.seller_service import tunnel_url
        urls=['https://a.run.pinggy-free.link','https://b.free.pinggy.net']
        self.assertEqual(tunnel_url(urls),'https://b.free.pinggy.net')
        self.assertEqual(tunnel_url(urls,True),'https://a.run.pinggy-free.link')
    def test_unrelated_url_cannot_masquerade_as_provider_domain(self):
        from ops.seller_service import tunnel_url
        self.assertIsNone(tunnel_url(['https://example.com/.free.pinggy.net','https://a.free.pinggy.net.evil.com','https://u:p@a.free.pinggy.net','http://a.free.pinggy.net']))


class CloudflareRecoveryTests(unittest.TestCase):
    def test_url_discovery_rejects_similar_unrelated_hosts(self):
        from ops.seller_service import cloudflare_url
        self.assertEqual(cloudflare_url('INF | https://real-name.trycloudflare.com |'),'https://real-name.trycloudflare.com')
        self.assertIsNone(cloudflare_url('https://real-name.trycloudflare.com.evil.example'))
        self.assertIsNone(cloudflare_url('https://evil.example/trycloudflare.com'))
    def test_recovery_forwards_only_the_existing_local_api_proxy(self):
        from ops.seller_service import cloudflare_command
        command=cloudflare_command('/home/user/.local/bin/cloudflared',9300)
        self.assertEqual(command[command.index('--url')+1],'http://127.0.0.1:9300')
        self.assertNotIn('--no-tls-verify',command)
