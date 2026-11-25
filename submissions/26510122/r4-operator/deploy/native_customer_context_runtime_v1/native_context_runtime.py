"""Opt-in host composition. Customer requests only use the producer's local cache."""
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import time

from card_source_read_lane import raw_file,safe_directory
from native_customer_context_adapter import CustomerContextAdapter

DEADLINE=3
SUCCESS={"ready","unavailable"}


def atomic(path,data):
    import tempfile
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix=".pending-")
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp,0o400)
        os.replace(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)


def verified_freeze(directory,pin):
    directory=safe_directory(directory)
    raw=raw_file(directory/"MANIFEST.json")
    if sha256(raw).hexdigest()!=pin:
        raise ValueError("native context freeze manifest changed")
    files=json.loads(raw)["file_sha256"]
    for name,digest in files.items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe frozen path")
        path=directory/relative
        if path.resolve()!=path or sha256(raw_file(path)).hexdigest()!=digest:
            raise ValueError("unreviewed runtime file")
    return directory


def read_snapshot(path,clock=time.time):
    safe_directory(path.parent)
    document=json.loads(raw_file(path))
    if (not isinstance(document,dict) or set(document)!={"schema","shop","observed_at","valid_until","units"}
        or document["schema"]!="outseop-r4.customer-offers.v1" or document["shop"]!="outseop-r4"
        or type(document["observed_at"]) is not int or type(document["valid_until"]) is not int
        or not document["observed_at"]<=clock()<document["valid_until"]<=document["observed_at"]+150
        or not isinstance(document["units"],list) or len(document["units"])>200):
        raise ValueError("verified offer cache unavailable")
    return document


class BoundedNative:
    def __init__(self,freeze,kit,scratch,deadline=DEADLINE):
        self.freeze=freeze
        self.kit=kit
        self.scratch=scratch
        self.deadline=deadline

    def __call__(self,base,snapshot):
        raw=json.dumps({"base":base,"snapshot":snapshot},ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
        if len(raw)>1024*1024:
            raise ValueError("native context input exceeds host budget")
        command=[sys.executable,"-I",str(self.freeze/"native_context_worker.py"),
                 str(self.freeze/"builder"),str(self.kit)]
        env={key:os.environ[key] for key in ("PATH","LANG","LC_ALL","TMPDIR") if key in os.environ}
        env["PYTHONIOENCODING"]="utf-8"
        with TemporaryDirectory(prefix="request-",dir=self.scratch) as request_dir:
            process=subprocess.Popen([*command,request_dir],cwd=request_dir,env=env,
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            try:
                output,_=process.communicate(raw,timeout=self.deadline)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise ValueError("native context host deadline exceeded") from None
        if process.returncode or not output or len(output)>8192:
            raise ValueError("native context worker unavailable")
        return json.loads(output)


class AggregateMetrics:
    def __init__(self,path):
        self.path=path
        self.lock=Lock()
        self.values={key:{"count":0,"seconds_sum":0.0,"seconds_max":0.0} for key in SUCCESS}

    def __call__(self,event):
        status=event["status"]
        elapsed=event["extra_seconds"]
        if status not in SUCCESS or type(elapsed) not in (int,float) or not 0<=elapsed<=30:
            return
        with self.lock:
            row=self.values[status]
            row["count"]+=1
            row["seconds_sum"]=round(row["seconds_sum"]+elapsed,4)
            row["seconds_max"]=max(row["seconds_max"],elapsed)
            atomic(self.path,json.dumps({"status_latency":self.values},sort_keys=True).encode())


def factory(operator,freeze):
    state=operator/"runtime/native-customer-context"
    # State setup comes from the independent producer, never from an A2A request.
    safe_directory(state)
    scratch=safe_directory(state/"scratch")
    bidder=BoundedNative(freeze,operator/"kit",scratch)
    metrics=AggregateMetrics(state/"metrics.json")
    return lambda legacy:CustomerContextAdapter(legacy,lambda:read_snapshot(state/"latest.json"),bidder,report=metrics)

