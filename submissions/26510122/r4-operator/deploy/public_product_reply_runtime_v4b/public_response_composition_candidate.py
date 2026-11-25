"""Host wiring for the opt-in customer public reply route."""
from hashlib import sha256
import math
import time

from bounded_public_renderer_host import BoundedPublicRenderer, instruction_from
from card_source_read_lane import raw_file, safe_directory
from native_context_runtime import atomic, factory as native_factory
from request_bound_public_response_adapter import public_response_factory
from threading import Lock


PHASES = ("prefetch_seconds", "model_seconds", "render_seconds", "legacy_action_seconds", "total_seconds")
OUTCOMES = {"rendered_public", "legacy_public", "legacy_direct", "model_unavailable", "fallback"}


class PhaseMetrics:
    def __init__(self, path):
        self.path = path
        self.lock = Lock()
        self.rows = {}

    def __call__(self, event):
        if set(event) != {*PHASES, "outcome", "retries"}:
            return
        if (type(event["retries"]) is not int or not 0 <= event["retries"] <= 2
                or any(type(event[key]) not in (int, float) or not math.isfinite(event[key])
                       or event[key] < 0 for key in PHASES)):
            return
        outcome = event["outcome"] if event["outcome"] in OUTCOMES else "fallback"
        with self.lock:
            row = self.rows.setdefault(outcome, {"count": 0, "retries_sum": 0, "seconds": {}})
            row["count"] += 1
            row["retries_sum"] += event["retries"]
            for phase in PHASES:
                metric = row["seconds"].setdefault(phase, {"sum": 0, "max": 0})
                elapsed = event[phase]
                metric["sum"] = round(metric["sum"] + elapsed, 4)
                metric["max"] = max(metric["max"], elapsed)
            import json
            atomic(self.path, json.dumps({"observed_at": int(time.time()), "outcomes": self.rows},
                                         sort_keys=True).encode())


def managed_options(operator, freeze, official, renderer_pins, *, check=False):
    state = operator / "runtime/native-customer-context"
    source = freeze / "renderer"
    instruction = instruction_from(source, renderer_pins, official)
    if check:
        # Checking provenance does not depend on a running producer or read its cache.
        return {}
    scratch = safe_directory(safe_directory(state) / "scratch")
    renderer = BoundedPublicRenderer(source, operator / "kit", scratch, renderer_pins)
    return {
        "native_customer_context_factory": native_factory(operator, freeze),
        "public_response_factory": public_response_factory(renderer, instruction),
        "public_phase_report": PhaseMetrics(state / "public-response-metrics.json"),
        "bounded_customer_model": True,
    }

