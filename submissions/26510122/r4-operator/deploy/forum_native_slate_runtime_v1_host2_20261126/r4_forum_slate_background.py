"""Optional launcher-only binding of the reviewed slate to background marketing."""
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from types import SimpleNamespace

RELEASE="forum_native_slate_runtime_v1_host2_20261126"
PIN="c68e4460fc51c4bf239d9403766955b62c931ab77408ab0a61ff6347aadef8a5"
OLD_HINT="현재 재고에 C등급이 있으면 등급을 명시한 빠른 판매 후보로 우선 고려한다."
BALANCED_HINT=("명시적 소포장 A/B와 임박 C, 서로 다른 카테고리를 공정하게 고려한다. "
               "recent_public_post_mix는 조회된 자기 공개글의 집계이며 현재 메뉴만 실제 후보로 삼고 최근 편중을 고려한다. "
               "포장 구분이 unknown이면 수량을 추정하지 않는다.")


def read_pinned(bundle):
    if bundle.resolve(strict=True)!=bundle:
        raise ValueError("untrusted forum slate path")
    raw=(bundle/"MANIFEST.json").read_bytes()
    if sha256(raw).hexdigest()!=PIN:
        raise ValueError("unreviewed forum slate manifest")
    files=json.loads(raw)["file_sha256"]
    for leaf,pin in files.items():
        path=bundle/leaf
        if path.resolve(strict=True)!=path or sha256(path.read_bytes()).hexdigest()!=pin:
            raise ValueError("forum slate artifact drift")
    return files


class ExistingShopRead:
    """Expose the original shop inventory read identity without signer methods."""
    def __init__(self,context):
        self.name=context["name"]
        self.market=context["market"]
        self.shop_url=context["shop_url"]
        self.context=context

    def address(self,role):
        if role!="shop":
            raise ValueError("unexpected forum role")
        return self.context["addresses"][role]

    def token(self,role):
        if role!="shop":
            raise ValueError("unexpected forum role")
        return self.context["tokens"][role]


def install_mind(official,mind,operator):
    bundle=operator/"deploy"/RELEASE
    files=read_pinned(bundle)
    path=bundle/"host/r4_forum_slate_host.py"
    spec=spec_from_file_location("r4_verified_forum_slate",path)
    module=module_from_spec(spec)
    spec.loader.exec_module(module)
    prefix="tools/"+module.NAME+"/"
    pins={name.removeprefix(prefix):pin for name,pin in files.items() if name.startswith(prefix)}
    source=bundle/"tools"/module.NAME
    sdk=SimpleNamespace(Toolbox=official.Toolbox)

    class MarketingSlateMind(mind):
        def __init__(self,root,agent,model,toolbox,ctx,roles):
            super().__init__(root,agent,model,toolbox,ctx,roles)
            coordinator=self.marketing_coordinator
            if coordinator is None:
                return
            coordinator.execute=module.bind(sdk,Path(root),source,pins,ExistingShopRead(ctx),coordinator.execute)
            previous=coordinator.model

            class BalancedModel:
                def complete(self,messages):
                    first=messages[0]
                    content=first["content"].replace(OLD_HINT,BALANCED_HINT)+" 판정 JSON에는 표시된 action, sku, grade, 필요 시 thread만 넣는다."
                    return previous.complete([{**first,"content":content},*messages[1:]])

            coordinator.model=BalancedModel()

    return MarketingSlateMind
