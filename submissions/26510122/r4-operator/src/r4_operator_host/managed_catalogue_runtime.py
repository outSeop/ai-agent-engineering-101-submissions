"""Round 4 operator boundary. Authored by OpenAI Codex GPT-6.2 Sol."""
from contextvars import ContextVar
from public_product_continuity import PublicContinuity
import json
from hashlib import sha256

from broker import Broker, Trace, class_context
import dispatcher as dispatcher
from threading import Lock
from time import monotonic, time
import secrets

from marketing_runtime import MarketingCoordinator, FORUM_TOOL
from marketing_card import build_card
from stock_runtime import StockCoordinator, STOCK_TOOL

PUBLIC_DISPATCH = "a2a_info"
MODEL_INFO = "shop_info"
PERMISSION_ERROR = "blocked by operator policy"
CARD_HANDOFF_GUARD_FILES = {
    "permission.yml":"599f987876a750c3349e57b754e2b5c2085a1a9b21e9f290f58ec5ab10e5821b",
    "logic.py":"cb3c5a6e5c6ca36fb329e4b2279c2b718a304386665707ecaf9a7e21eb887dc2",
    "test.py":"bde98d730b945e0adc85c7802f36eb3155521ac79ff7c63f2d2b7234c536e60c",
}


def card_publisher_allowed(tool):
    perm = tool.get("perm",{})
    if any(perm.get(k) for k in ("wallet","exec","handles","identity","network")):
        return False
    if perm.get("write")==["card.json"]:
        return True
    if perm.get("write")!=["card_handoff_selftest"] or perm.get("pay_limit",0)!=0:
        return False
    directory = tool.get("dir")
    if directory is None:
        return False
    try:
        manifest = json.loads((directory/"forge.json").read_bytes())
        return (
            (manifest.get("tool"),manifest.get("version"),manifest.get("sha256"))
                == ("publish_shop_info",1,CARD_HANDOFF_GUARD_FILES)
            and all(sha256((directory/file).read_bytes()).hexdigest()==digest
                    for file,digest in CARD_HANDOFF_GUARD_FILES.items())
        )
    except (OSError,TypeError,ValueError,AttributeError):
        return False

FALLBACK = {"reply": "상점 자동 응답을 사용할 수 없습니다. 잠시 뒤 다시 문의해 주세요.",
            "state": "completed"}


class RequestAuthority:
    def __init__(self, toolbox):
        self.toolbox = toolbox
        self.used = False
        self.lock = Lock()

    def consume(self, toolbox):
        with self.lock:
            if self.toolbox is not toolbox or self.used:
                return False
            self.used = True
            return True


def managed_classes(official, *, enable_stock=False, stock_lines=10, native_customer_context_factory=None,
                    public_response_factory=None, public_phase_report=None, bounded_customer_model=False,
                    catalogue_source_factory=None, forum_validator=None):
    """Inject an in-process Python capability. No request arg is trusted as origin."""
    request_scope = ContextVar("r4_a2a_scope", default=None)
    permit = ContextVar("r4_a2a_permit", default=None)
    message_id = ContextVar("r4_message_id", default=None)
    activity_lock = Lock()
    active_customers = 0
    public_product_context = PublicContinuity()

    def customer_active():
        with activity_lock:
            return active_customers>0

    class ManagedToolbox(official.Toolbox):
        def bind_decision_model(self, model, agent):
            class DecisionModel:
                def complete(_, messages, *, timeout=52):
                    return model.complete(class_context(official, messages, agent), max_tokens=800 if catalogue_source_factory is not None else 700, timeout=min(timeout,52))
            self.decision_model = DecisionModel()

        def decision_tool(self, details):
            answer = super().call(PUBLIC_DISPATCH, {"_broker": details})
            return answer["result"] if answer.get("ok") else {"outcome": "tool_unavailable"}

        def stock_executor(self, args):
            if not enable_stock:
                return {"status":"stock_disabled"}
            if args.get("action")=="context":
                args = dict(args,line_cap=stock_lines)
            result = super().run(STOCK_TOOL,"call",args)
            return result["result"] if result.get("ok") else {"status":"stock_tool_unavailable"}

        def forum_executor(self, args):
            if not enable_stock or FORUM_TOOL not in self.tools:
                return {"status":"forum_disabled"}
            result = super().run(FORUM_TOOL, "call", args)
            return result["result"] if result.get("ok") else {"status":"forum_tool_unavailable"}

        def refresh_public_card(self):
            if customer_active():
                return
            current=time()
            if current < getattr(self,"next_card_refresh",0):
                return
            self.next_card_refresh=current+120
            view=self.decision_tool({"action":"context"})
            if view.get("outcome")!="context":
                return
            public=build_card(view.get("inventory",[]),now=current)
            result=super().call("publish_shop_info",public)
            if result.get("ok") and result.get("result",{}).get("status")=="published":
                self.next_card_refresh=current+600

        def public_answer(self, args):
            nonlocal active_customers
            started = monotonic()
            ref = secrets.token_hex(12)
            result_kind = "unavailable"
            status = {"model_used":False}
            path = self.root / ".kit/transport-metrics.jsonl"

            def metric(event, **fields):
                try:
                    Trace.append(path, {"at":time(),"event":event,"internal_ref":ref,**fields})
                except OSError:
                    pass

            with activity_lock:
                active_customers += 1
            try:
                metric("request_start")
                out = self._public_answer(args,status)
                result = out.get("result") or {}
                data = result.get("data") or {}
                result_kind = ("checkout" if "checkout_jwt" in data else "wait" if "wait_voucher" in data
                               else "response" if out.get("ok") and result.get("reply") else "unavailable")
                return out
            finally:
                with activity_lock:
                    active_customers -= 1
                metric("request_end",seconds=round(monotonic()-started,4),result_kind=result_kind,
                       model_decision_used=status["model_used"])

        def _public_answer(self, args, status):
            text = args.get("text", "")
            command = dispatcher.parse(text)[0]
            # Structured benefits and private profile commands bypass semantic
            # interpretation. Only request text is accepted from the SDK.
            if command in ("balance", "wait", "paid", "cancel", "profile"):
                return super().call(PUBLIC_DISPATCH, {"text": text, "task_id": message_id.get()})
            trace = Trace(self.root / ".kit/decision-trace-private.jsonl", self.root / ".kit/decision-trace-review.jsonl")
            execute = self.decision_tool
            options={}
            if catalogue_source_factory is not None:
                catalogue=catalogue_source_factory(execute)
                if getattr(catalogue,"prepared",False):
                    options.update(catalogue=catalogue,max_steps=1,seconds=40,model_seconds=30)
                else:
                    options.update(catalogue=catalogue,max_steps=3,seconds=65,model_seconds=35)
            elif native_customer_context_factory is not None:
                execute = native_customer_context_factory(execute)
            if bounded_customer_model and catalogue_source_factory is None:
                options.update(max_steps=2,seconds=55,model_seconds=25)
            if public_response_factory is not None and catalogue_source_factory is None:
                options["public_response_adapter"]=public_response_factory(execute)
            if public_phase_report is not None:
                options["phase_report"]=public_phase_report
            request = Broker(execute, self.decision_model, trace, **options)
            try:
                task_id, context_id = args.get("task_id"), args.get("context_id")
                continuity = {} if catalogue_source_factory is None else {
                    "remembered": public_product_context.current(task_id, context_id),
                    "remember": lambda facts: public_product_context.remember(task_id, context_id, facts),
                }
                answer = request.handle(text, transport_id=message_id.get(), **continuity)
                return {"ok": True, "result": answer}
            finally:
                status["model_used"] = request.model_used

        def validate(self):
            info = self.tools.get(MODEL_INFO)
            dispatcher = self.tools.get(PUBLIC_DISPATCH)
            if not info or not dispatcher:
                raise RuntimeError("forged shop_info and a2a_info are required")
            if (info["perm"].get("wallet") or info["perm"].get("write") or info["perm"].get("exec")
                    or info["perm"].get("handles")
                    or set(info["perm"].get("network", [])) != {"market.ourolabs.ai"}
                    or set(info["perm"].get("identity", [])) != {"shop"}):
                raise RuntimeError("shop_info permissions differ from read-only policy")
            if (set(dispatcher["perm"].get("wallet", [])) != {"sign", "sign_jwt"}
                    or dispatcher["perm"].get("exec")
                    or set(dispatcher["perm"].get("handles", [])) != {"a2a"}
                    or [name for name, tool in self.tools.items() if "a2a" in tool["perm"].get("handles", [])] != [PUBLIC_DISPATCH]
                    or super().handler("a2a") != PUBLIC_DISPATCH):
                raise RuntimeError("unexpected public dispatcher permissions or selection")
            if enable_stock:
                tool=self.tools.get(STOCK_TOOL)
                perm=tool["perm"] if tool else {}
                if (set(perm.get("wallet",[]))!={"pay"} or perm.get("exec") or perm.get("handles")
                        or set(perm.get("identity",[]))!={"shop"}
                        or perm.get("pay_limit")!=1000000
                        or perm.get("write")!=["state/r4-benefits"]
                        or set(perm.get("network",[]))!={"market.ourolabs.ai","rpc-testnet.maroo.io"}):
                    raise RuntimeError("unexpected background procurement permissions")

            if FORUM_TOOL in self.tools:
                forum=self.tools[FORUM_TOOL]
                perm=forum["perm"]
                if (perm.get("wallet") or perm.get("exec") or perm.get("handles")
                        or set(perm.get("identity",[]))!={"shop"}
                        or perm.get("write")!=["state/r4-benefits"]):
                    raise RuntimeError("unexpected forum publication permissions")
                if set(perm.get("network",[]))!={"market.ourolabs.ai"}:
                    if forum_validator is None or forum_validator(self, forum) is not True:
                        raise RuntimeError("unexpected forum publication permissions")
                publisher=self.tools.get("publish_shop_info",{})
                if not card_publisher_allowed(publisher):
                    raise RuntimeError("unexpected card publication permissions")

        def listing(self):
            if MODEL_INFO not in self.tools:
                return "(no public lookup tool is available)"
            info = self.tools[MODEL_INFO]
            return f"- {MODEL_INFO}: {info['description']}"

        def forge(self, args):
            return PERMISSION_ERROR

        def read(self, name):
            return PERMISSION_ERROR

        def handler(self, kind):
            if kind != "a2a" or request_scope.get() is not self:
                return None
            if super().handler(kind) != PUBLIC_DISPATCH:
                return None
            permit.set(RequestAuthority(self))
            return PUBLIC_DISPATCH

        def call(self, name, args):
            if name == MODEL_INFO:
                # Discard arbitrary model arguments, including text and fake
                # A2A identifiers. The implementation receives no secret.
                try:
                    return super().call(name, {})
                except Exception:
                    return {"ok": False, "error": "public inventory service unavailable"}
            if name == PUBLIC_DISPATCH:
                authority = permit.get()
                if (request_scope.get() is self and authority is not None
                        and authority.consume(self)):
                    try:
                        return self.public_answer(args)
                    except Exception:
                        return {"ok": True, "result": dict(FALLBACK)}
            return {"ok": False, "error": PERMISSION_ERROR}

    class ModelTools:
        def __init__(self, toolbox):
            self._toolbox = toolbox

        @property
        def tools(self):
            return {MODEL_INFO: None} if MODEL_INFO in self._toolbox.tools else {}

        def listing(self):
            return self._toolbox.listing()

        def call(self, name, args):
            if name != MODEL_INFO:
                return {"ok": False, "error": PERMISSION_ERROR}
            return self._toolbox.call(name, {})

        def read(self, name):
            return PERMISSION_ERROR

        def forge(self, args):
            return PERMISSION_ERROR

    class ManagedMind(official.Mind):
        def __init__(self, root, agent, model, toolbox, ctx, roles):
            toolbox.bind_decision_model(model, agent)
            super().__init__(root, agent, model, ModelTools(toolbox), ctx, roles)
            self.marketing_coordinator = None
            self.stock_coordinator = None
            if enable_stock:
                class StockModel:
                    def complete(_, messages):
                        context=[dict(messages[0],content=official.WORLD+chr(10)*2+messages[0]["content"]),*messages[1:]]
                        return model.complete(context,max_tokens=550,timeout=42)
                self.stock_coordinator=StockCoordinator(toolbox.stock_executor,StockModel(),customer_active=customer_active)
                if FORUM_TOOL in toolbox.tools:
                    class MarketingModel:
                        def complete(_, messages):
                            context=[dict(messages[0],content=official.WORLD+chr(10)*2+messages[0]["content"]),*messages[1:]]
                            return model.complete(context,max_tokens=280,timeout=25)
                    self.marketing_coordinator=MarketingCoordinator(toolbox.forum_executor,MarketingModel(),customer_active=customer_active)
                    self.refresh_public_card=toolbox.refresh_public_card

        def loop(self):
            if self.stock_coordinator:
                # The official launcher already runs Mind.loop on its own
                # thread. With stock enabled this is the only periodic model path.
                if self.marketing_coordinator:
                    return self.marketing_coordinator.loop(self.stock_coordinator,maintenance=self.refresh_public_card)
                return self.stock_coordinator.loop()
            return super().loop()

        def deliver(self, event):
            # A2A success bypasses Mind entirely. Even an SDK, process or tool
            # failure must not cause private messages to enter Model context.
            if event.kind == "a2a":
                event.answer = dict(FALLBACK)
                event.done.set()
                return event
            return super().deliver(event)

    def managed_app(root, name, mind, toolbox, public):
        toolbox.validate()
        original = official_app(root, name, mind, toolbox, public)

        async def app(scope, receive, send):
            if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/":
                return await original(scope, receive, send)
            initial = []
            size = 0
            while True:
                part = await receive()
                initial.append(part)
                if part["type"] != "http.request":
                    break
                size += len(part.get("body", b""))
                if size > 65536:
                    await send({"type": "http.response.start", "status": 413, "headers": []})
                    await send({"type": "http.response.body", "body": b"request too large"})
                    return
                if not part.get("more_body"):
                    break
            transport_id = None
            try:
                payload = json.loads(b"".join(part.get("body", b"") for part in initial))
                if payload["method"] in ("SendMessage", "message/send"):
                    message = payload["params"]["message"]
                    transport_id = message.get("messageId") or message.get("message_id")
            except (ValueError, KeyError, TypeError, AttributeError):
                pass

            async def replay():
                return initial.pop(0) if initial else await receive()

            scope_token = request_scope.set(toolbox)
            permit_token = permit.set(None)
            message_token = message_id.set(transport_id)
            try:
                return await original(scope, replay, send)
            finally:
                message_id.reset(message_token)
                permit.reset(permit_token)
                request_scope.reset(scope_token)

        return app

    official_app = official.agent_app
    return ManagedToolbox, ManagedMind, managed_app

