"""Optional settlement-worker activation. The generated tool owns all award decisions."""
import json
import os
from pathlib import Path
import stat
import sys

from first_purchase_bonus_feed_host import drain
from first_purchase_bonus_sdk_host import ToolInvocation,checked_file

VERSION=4
PINS={'forge.json': '7610eff7384e7cf09ac1497c185de8b5471df3c2a596cd4632e339a660e19a6e', 'logic.py': '0ac466eb47f8a237829ae034dab949b964c372dc4327591ce92a07b965902887', 'permission.yml': 'cfd251fd481d8705400fda25e115f846de6bd0f024af469793451f54e8c0cf3f', 'test.py': '4e96436705fb98cde7a812f2981d0e131a6abcf02b6f2ed464e864bf2c632102'}
TERMINAL={"granted","already_awarded","ineligible","budget_exhausted"}
SAFE_STATUS=TERMINAL|{"inactive","defer","incompatible","unavailable","unverified_history"}


def result_schema(result):
    if not isinstance(result,dict) or not isinstance(result.get("status"),str) or result["status"] not in SAFE_STATUS:
        raise ValueError("unrecognized bonus result")
    if result["status"]=="granted":
        if (set(result)!={"status","credits"} or type(result["credits"]) is not int
                or not 1<=result["credits"]<=5000):
            raise ValueError("invalid bonus completion shape")
    elif set(result)!={"status"}:
        raise ValueError("invalid bonus result shape")
    return result["status"]


def after_sync_for(root,activation):
    root=Path(root)
    root_dir=root/".kit"
    control=root_dir/"first-purchase-bonus-activation.json"
    if activation.absolute()!=control or control.resolve(strict=True)!=control:
        raise ValueError("unexpected bonus activation path")
    info=control.lstat()
    if info.st_mode&0o077:
        raise ValueError("bonus activation must be private")
    cfg=json.loads(checked_file(control,1024))
    if (not isinstance(cfg,dict) or set(cfg)!={"initial_event_cursor","tool_version"} or
        cfg["tool_version"]!=VERSION or type(cfg["initial_event_cursor"]) is not int
        or cfg["initial_event_cursor"]<0):
        raise ValueError("unreviewed bonus activation")
    operator=root.parent/"r4-operator"
    from managed_launcher import verify_kit
    verify_kit(operator)
    sys.path.insert(0,str(operator/"kit"))
    try:
        import agent_kit as official
    finally:
        sys.path.pop(0)
    runner=ToolInvocation(official,root,PINS,VERSION,result_schema)
    state=root_dir/"first-purchase-bonus"
    state.mkdir(mode=0o700,exist_ok=True)
    info=state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError("unprotected bonus state")
    checkpoint=state/"checkpoint.json"

    def after_sync(db):
        return drain(db,checkpoint,runner,TERMINAL.__contains__,initial_cursor=cfg["initial_event_cursor"])

    return after_sync

