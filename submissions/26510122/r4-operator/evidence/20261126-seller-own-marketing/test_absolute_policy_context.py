"""Exercise the actual legacy offer and publisher with both SDK working directories."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from hashlib import sha256
import json
import os
import sqlite3
import sys

from r4_forum_slate_absolute_policy_host_candidate import bind_policy_path, full_options

operator=Path(sys.argv[1]).resolve()
legacy_path=operator.parent/"round-4/codex-r4/forum.py"
sys.path[:0]=[str(legacy_path.parent),str(operator/"kit")]
spec=spec_from_file_location("legacy_regression",legacy_path)
legacy=module_from_spec(spec)
spec.loader.exec_module(legacy)
policy=legacy.shop.price_policy
prior_path=policy.POLICY_PATH
prior_cwd=Path.cwd()
now=100000
sku="Gdeadbeef"
item={"sku":sku,"unit":"G76543210","grade":"B","name":"합성상품 2팩","category":"food",
      "cost":10000,"list_price":21000,"cert":{}}
def blocked_post(*args):
    raise AssertionError("fixture must never call remote publish")
market=SimpleNamespace(chain=lambda:(None,450,420,None),inventory=lambda:[item],forum=lambda:[],
                       shop_url="https://example.invalid",post=blocked_post)
with TemporaryDirectory() as temp:
    root=Path(temp).resolve()
    prod=root/"prod"
    (prod/"codex-r4").mkdir(parents=True)
    op=root/"op"
    op.mkdir()
    config=prod/"codex-r4/launch-price-policy.json"
    config.write_text(json.dumps({"policy_id":"test","starts_at":now-100,"ends_at":now+100,
                                  "total_loss_credits":50000,"per_deal_bps":500}))
    original=config.read_bytes()
    db=sqlite3.connect(":memory:")
    db.row_factory=sqlite3.Row
    db.executescript(legacy.shop.SCHEMA+legacy.SCHEMA)
    try:
        os.chdir(prod)
        expected=legacy.stock_offers(db,market,now)[0]
        fingerprint=legacy.offer_fingerprint(expected,None)
        os.chdir(op)
        old=legacy.stock_offers(db,market,now)[0]
        assert expected["price"] != old["price"]
        db.execute("INSERT INTO forum_publication(id,shop,round,thread,sku,content,anchor,status,created,post,fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   ("test",legacy.shop.SHOP,4,None,sku,"fixture",0,"posted",now-10000,1,fingerprint))
        db.commit()
        assert full_options(db,market,legacy,now)["items"][0]["price"]==old["price"]
        bind_policy_path(prod,policy)
        got=legacy.stock_offers(db,market,now)[0]
        assert got==expected and legacy.offer_fingerprint(got,None)==fingerprint
        assert full_options(db,market,legacy,now)["items"]==[]
        os.chdir(prod)
        assert legacy.forum_publish(db,market,now,{"action":"spotlight","sku":sku,"grade":"B"})=={"status":"duplicate_content"}
        assert config.read_bytes()==original
        path=prod/"codex-r4/copy.json"
        path.write_bytes(original)
        config.unlink()
        config.symlink_to(path)
        try:
            bind_policy_path(prod,policy)
        except ValueError:
            pass
        else:
            raise AssertionError("symlink policy accepted")
    finally:
        os.chdir(prior_cwd)
        policy.POLICY_PATH=prior_path
        db.close()
print(json.dumps({"actual_legacy_price":True,"mismatch_reproduced_before":True,"exact_fingerprint_agreement_after":True,
                  "old_duplicate_no_longer_eligible":True,"publisher_duplicate_content":True,"symlink_rejected":True,"actual_post":0}))
