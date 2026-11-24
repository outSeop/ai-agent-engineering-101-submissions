"""Round 4 operator boundary. Authored by OpenAI Codex GPT-6.2 Sol."""
from contextvars import ContextVar
import json

from broker import Broker, Trace, class_context
import dispatcher as dispatcher
from threading import Lock

PUBLIC_DISPATCH = "a2a_info"
MODEL_INFO = "shop_info"
PERMISSION_ERROR = "blocked by operator policy"
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


def managed_classes(official):
    """Inject an in-process Python capability. No request arg is trusted as origin."""
    request_scope = ContextVar("r4_a2a_scope", default=None)
    permit = ContextVar("r4_a2a_permit", default=None)
    message_id = ContextVar("r4_message_id", default=None)

    class ManagedToolbox(official.Toolbox):
        def bind_decision_model(self, model, agent):
            class DecisionModel:
                def complete(_, messages):
                    return model.complete(class_context(official, messages, agent), max_tokens=700, timeout=52)
            self.decision_model = DecisionModel()

        def decision_tool(self, details):
            answer = super().call(PUBLIC_DISPATCH, {"_broker": details})
            return answer["result"] if answer.get("ok") else {"outcome": "tool_unavailable"}

        def public_answer(self, args):
            text = args.get("text", "")
            command = dispatcher.parse(text)[0]
            # Structured benefits and private profile commands bypass semantic
            # interpretation. Only request text is accepted from the SDK.
            if command in ("balance", "wait", "paid", "cancel", "profile"):
                return super().call(PUBLIC_DISPATCH, {"text": text, "task_id": message_id.get()})
            trace = Trace(self.root / ".kit/decision-trace-private.jsonl", self.root / ".kit/decision-trace-review.jsonl")
            request = Broker(self.decision_tool, self.decision_model, trace)
            return {"ok": True, "result": request.handle(text, transport_id=message_id.get())}

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

