"""Host-only request binding for an independently pinned read-only public renderer."""

class RequestBoundPublicResponse:
    def __init__(self, execute, renderer, instruction):
        self.execute=execute
        self.renderer=renderer
        self.instruction=instruction

    def __call__(self, *, args, native_context, remaining_seconds):
        if remaining_seconds<=0:
            raise ValueError("public reply deadline exhausted")
        snapshot_for=getattr(self.execute,"snapshot_for",None)
        if not callable(snapshot_for):
            raise ValueError("public reply requires a request-local verified snapshot")
        snapshot=snapshot_for(native_context)
        if (snapshot.get("observed_at")!=native_context.get("observed_at")
            or snapshot.get("valid_until")!=native_context.get("valid_until")):
            raise ValueError("request public snapshot changed")
        return self.renderer(args=args,snapshot=snapshot,timeout=min(3.0,remaining_seconds))


def public_response_factory(renderer, instruction):
    """Bind an audited renderer and advertised tool syntax to each customer request."""
    if not callable(renderer) or not isinstance(instruction,str) or not 1<=len(instruction)<=600:
        raise ValueError("invalid public renderer configuration")
    return lambda execute:RequestBoundPublicResponse(execute,renderer,instruction)

