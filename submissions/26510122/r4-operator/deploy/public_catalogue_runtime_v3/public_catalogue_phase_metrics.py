"""Aggregate matched public-catalogue phases with bounded diagnostic labels."""
import json
import math
from threading import Lock
from time import time

from public_catalogue_snapshot_host import atomic


PHASES=("prefetch_seconds","catalogue_seconds","search_seconds","model_seconds","render_seconds",
        "fallback_seconds","legacy_action_seconds","total_seconds")
OUTCOMES={"rendered_public","legacy_public","legacy_direct","catalogue_fallback","model_unavailable","fallback"}
CODES={"none","legacy_context_failed","cache_missing","cache_unprotected","cache_size","cache_schema",
       "cache_capacity","cache_stale","context_failed","search_failed","action_rejected",
       "model_timeout","model_unavailable","invalid_model_action","flow_deadline","render_failed",
       "fallback_denied","fallback_failed","pagination_restart_required","snapshot_changed","query_changed",
       "cursor_mismatch","fallback_not_applicable","no_match","invalid_query","stale_snapshot","output_limit",
       "invalid_snapshot","invalid_args","selection_not_available","context_timeout",
       "search_timeout","render_timeout","fallback_timeout","query_restart_required","selection_ambiguous",
       "selection_unavailable","source_unavailable","unsafe_query_cursor","output_budget","name_unavailable","selection_limit","invalid_public_selection"}


class PhaseMetrics:
    def __init__(self, path):
        self.path=path
        self.rows={}
        self.lock=Lock()

    def __call__(self,event):
        if (set(event)!={*PHASES,"outcome","retries","reason","phase_reasons"}
                or type(event["retries"]) is not int or not 0<=event["retries"]<=3
                or any(type(event[key]) not in (int,float) or not math.isfinite(event[key])
                       or event[key]<0 for key in PHASES)):
            return
        if not isinstance(event["outcome"],str) or not isinstance(event["reason"],str):
            return
        outcome=event["outcome"] if event["outcome"] in OUTCOMES else "fallback"
        reason=event["reason"] if event["reason"] in CODES else "action_rejected"
        supplied=event["phase_reasons"]
        if not isinstance(supplied,dict):
            return
        phase_codes={name:code if isinstance(code,str) and code in CODES else "action_rejected"
                     for name,code in supplied.items() if name in {"prefetch","catalogue","search","model","render","fallback"}}
        with self.lock:
            row=self.rows.setdefault(outcome,{"count":0,"retries_sum":0,"seconds":{},"reasons":{},"phase_reasons":{}})
            row["count"]+=1
            row["retries_sum"]+=event["retries"]
            row["reasons"][reason]=row["reasons"].get(reason,0)+1
            for phase,code in phase_codes.items():
                counts=row["phase_reasons"].setdefault(phase,{})
                counts[code]=counts.get(code,0)+1
            for phase in PHASES:
                elapsed=event[phase]
                metric=row["seconds"].setdefault(phase,{"sum":0,"max":0})
                metric["sum"]=round(metric["sum"]+elapsed,4)
                metric["max"]=max(metric["max"],elapsed)
            atomic(self.path,json.dumps({"observed_at":int(time()),"outcomes":self.rows},sort_keys=True).encode())

