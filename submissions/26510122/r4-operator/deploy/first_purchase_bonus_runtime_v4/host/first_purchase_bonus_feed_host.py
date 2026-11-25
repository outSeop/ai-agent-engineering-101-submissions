"""Schedule the generated bonus tool from committed internal settlement events."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from tempfile import mkstemp


def rows_after(db,cursor,limit=12):
    """Return only opaque event sequence and sale identifiers."""
    if db.in_transaction:
        raise ValueError("bonus feed requires a committed ledger view")
    return db.execute(
        """SELECT id,reference FROM event
           WHERE kind='settled_and_earned' AND id>?
           ORDER BY id LIMIT ?""",
        (cursor,limit),
    ).fetchall()


@contextmanager
def exclusive(path):
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:
            raise ValueError("unsafe bonus worker lock")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def read_cursor(path,initial_cursor):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:
        return initial_cursor
    with os.fdopen(fd,"rb") as stream:
        info=os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
            or info.st_nlink!=1 or info.st_mode&0o077 or info.st_size>256):
            raise ValueError("unsafe bonus worker checkpoint")
        data=json.loads(stream.read(257))
    if not isinstance(data,dict) or set(data)!={"settlement_event"} or type(data["settlement_event"]) is not int:
        raise ValueError("unexpected bonus checkpoint")
    if data["settlement_event"]<initial_cursor:
        raise ValueError("bonus checkpoint predates reviewed activation")
    return data["settlement_event"]


def write_cursor(path,cursor):
    fd,temporary=mkstemp(prefix=".bonus-checkpoint-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump({"settlement_event":cursor},stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def drain(db,checkpoint,invoke,terminal,*,initial_cursor=0,limit=12):
    """Deliver IDs to a trusted tool. Only recognized terminal outcomes advance the cursor."""
    if type(initial_cursor) is not int or initial_cursor<0 or type(limit) is not int or not 1<=limit<=32:
        raise ValueError("invalid bonus worker limit")
    if checkpoint.parent.resolve(strict=True)!=checkpoint.parent:
        raise ValueError("unsafe bonus worker state directory")
    parent=checkpoint.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or parent.st_mode&0o077):
        raise ValueError("unsafe bonus worker state directory")
    with exclusive(checkpoint.with_suffix(".lock")):
        cursor=read_cursor(checkpoint,initial_cursor)
        processed=0
        for sequence,sale_id in rows_after(db,cursor,limit):
            result=invoke(sale_id)
            if not terminal(result):
                return {"processed":processed,"deferred":True}
            write_cursor(checkpoint,sequence)
            processed+=1
    return {"processed":processed,"deferred":False}

