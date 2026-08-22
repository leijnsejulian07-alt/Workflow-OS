from __future__ import annotations
import hashlib, json, sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ALLOWED_STATES={"READY","LEASED","SUCCEEDED","FAILED_RETRYABLE","UNKNOWN","DEAD"}
_MAX_PAYLOAD_BYTES=64*1024

def _id(v:object,name:str,max_len:int)->str:
    if not isinstance(v,str): raise ValueError(f"{name} must be a string")
    x=v.strip()
    if not x or len(x)>max_len or any(ord(c)<32 for c in x): raise ValueError(f"invalid {name}")
    return x

def _ts(v:object,name:str)->str:
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{name} must be an ISO-8601 timestamp")
    try: dt=datetime.fromisoformat(v.strip().replace("Z","+00:00"))
    except ValueError as exc: raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None: raise ValueError(f"{name} must include a timezone offset")
    return dt.astimezone(timezone.utc).isoformat()

def _payload(v:Any)->str:
    s=json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    if len(s.encode())>_MAX_PAYLOAD_BYTES: raise ValueError("job payload exceeds 64 KiB")
    return s

@dataclass(frozen=True)
class JobRecord:
    job_id:int; idempotency_key:str; opportunity_id:str; job_type:str; request_fingerprint:str
    state:str; attempt_count:int; max_attempts:int; available_at:str; lease_expires_at:str|None
    worker_id:str|None; last_error:str|None

class JobQueue:
    """Durable bounded queue. Lost leases never auto-retry because an external effect may have happened."""
    def __init__(self,path:str|Path): self.path=str(path); self._init_schema()
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=5.0); db.row_factory=sqlite3.Row; db.execute("PRAGMA busy_timeout=5000"); return db
    def _init_schema(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
              job_id INTEGER PRIMARY KEY AUTOINCREMENT,
              idempotency_key TEXT NOT NULL UNIQUE,
              opportunity_id TEXT NOT NULL,
              job_type TEXT NOT NULL,
              request_json TEXT NOT NULL,
              request_fingerprint TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('READY','LEASED','SUCCEEDED','FAILED_RETRYABLE','UNKNOWN','DEAD')),
              attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
              max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
              available_at TEXT NOT NULL,
              lease_expires_at TEXT, worker_id TEXT, last_error TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs(state,available_at,job_id);
            """)
    def enqueue(self,*,idempotency_key:object,opportunity_id:object,job_type:object,payload:Any,available_at:object,max_attempts:int=3)->JobRecord:
        key=_id(idempotency_key,"idempotency_key",200); op=_id(opportunity_id,"opportunity_id",200); kind=_id(job_type,"job_type",100)
        if not isinstance(max_attempts,int) or isinstance(max_attempts,bool) or not 1<=max_attempts<=10: raise ValueError("max_attempts must be between 1 and 10")
        available=_ts(available_at,"available_at"); p=_payload(payload); fp=hashlib.sha256(f"{kind}\n{op}\n{p}".encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT * FROM jobs WHERE idempotency_key=?",(key,)).fetchone()
            if row:
                if row["request_fingerprint"]!=fp or row["max_attempts"]!=max_attempts: raise ValueError("idempotency key is already bound to a different job")
                return self._row(row)
            db.execute("INSERT INTO jobs(idempotency_key,opportunity_id,job_type,request_json,request_fingerprint,state,max_attempts,available_at) VALUES(?,?,?,?,?,'READY',?,?)",(key,op,kind,p,fp,max_attempts,available))
            return self._row(db.execute("SELECT * FROM jobs WHERE idempotency_key=?",(key,)).fetchone())
    def claim(self,*,worker_id:object,now:object,lease_seconds:int=300)->JobRecord|None:
        worker=_id(worker_id,"worker_id",200); now_s=_ts(now,"now")
        if not isinstance(lease_seconds,int) or isinstance(lease_seconds,bool) or not 30<=lease_seconds<=3600: raise ValueError("lease_seconds must be between 30 and 3600")
        until=(datetime.fromisoformat(now_s)+timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM jobs WHERE state IN ('READY','FAILED_RETRYABLE') AND available_at<=? AND attempt_count<max_attempts ORDER BY available_at,job_id LIMIT 1",(now_s,)).fetchone()
            if not row: return None
            db.execute("UPDATE jobs SET state='LEASED',attempt_count=attempt_count+1,worker_id=?,lease_expires_at=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(worker,until,row['job_id']))
            return self._row(db.execute("SELECT * FROM jobs WHERE job_id=?",(row['job_id'],)).fetchone())
    def complete(self,job_id:int,*,worker_id:object,now:object)->JobRecord:
        worker=_id(worker_id,"worker_id",200); now_s=_ts(now,"now")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE"); row=self._req(db,job_id)
            if row['state']=='SUCCEEDED': return self._row(row)
            self._owned_live(row,worker,now_s)
            db.execute("UPDATE jobs SET state='SUCCEEDED',worker_id=NULL,lease_expires_at=NULL,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(job_id,))
            return self._row(self._req(db,job_id))
    def fail(self,job_id:int,*,worker_id:object,now:object,retry_safe:bool,error:object,retry_at:object|None=None)->JobRecord:
        worker=_id(worker_id,"worker_id",200); now_s=_ts(now,"now"); msg=_id(error,"error",1000)
        if not isinstance(retry_safe,bool): raise ValueError("retry_safe must be a boolean")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE"); row=self._req(db,job_id); self._owned_live(row,worker,now_s)
            if retry_safe and row['attempt_count']<row['max_attempts']:
                state='FAILED_RETRYABLE'; available=_ts(retry_at,"retry_at") if retry_at is not None else now_s
            elif retry_safe: state='DEAD'; available=row['available_at']
            else: state='UNKNOWN'; available=row['available_at']
            db.execute("UPDATE jobs SET state=?,available_at=?,worker_id=NULL,lease_expires_at=NULL,last_error=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(state,available,msg,job_id))
            return self._row(self._req(db,job_id))
    def expire_lease(self,job_id:int,*,now:object,definitely_not_applied:bool,retry_at:object|None=None)->JobRecord:
        if not isinstance(definitely_not_applied,bool): raise ValueError("definitely_not_applied must be a boolean")
        now_s=_ts(now,"now")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE"); row=self._req(db,job_id)
            if row['state']!='LEASED': raise RuntimeError("only LEASED jobs can expire")
            if not row['lease_expires_at'] or row['lease_expires_at']>now_s: raise RuntimeError("job lease has not expired")
            if definitely_not_applied and row['attempt_count']<row['max_attempts']:
                state='FAILED_RETRYABLE'; available=_ts(retry_at,"retry_at") if retry_at is not None else now_s
            elif definitely_not_applied: state='DEAD'; available=row['available_at']
            else: state='UNKNOWN'; available=row['available_at']
            db.execute("UPDATE jobs SET state=?,available_at=?,worker_id=NULL,lease_expires_at=NULL,last_error='lease expired',updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(state,available,job_id))
            return self._row(self._req(db,job_id))
    def reconcile_unknown_not_applied(self,job_id:int,*,retry_at:object)->JobRecord:
        available=_ts(retry_at,"retry_at")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE"); row=self._req(db,job_id)
            if row['state']!='UNKNOWN': raise RuntimeError("only UNKNOWN jobs require not-applied reconciliation")
            state='FAILED_RETRYABLE' if row['attempt_count']<row['max_attempts'] else 'DEAD'
            db.execute("UPDATE jobs SET state=?,available_at=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(state,available,job_id))
            return self._row(self._req(db,job_id))
    @staticmethod
    def _owned_live(row,worker,now_s):
        if row['state']!='LEASED': raise RuntimeError("job is not leased")
        if row['worker_id']!=worker: raise RuntimeError("job lease belongs to another worker")
        if not row['lease_expires_at'] or row['lease_expires_at']<=now_s: raise RuntimeError("job lease has expired")
    @staticmethod
    def _req(db,job_id):
        if not isinstance(job_id,int) or isinstance(job_id,bool) or job_id<1: raise ValueError("job_id must be a positive integer")
        row=db.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone()
        if not row: raise KeyError(job_id)
        return row
    @staticmethod
    def _row(row):
        state=str(row['state'])
        if state not in _ALLOWED_STATES: raise RuntimeError("invalid persisted job state")
        return JobRecord(int(row['job_id']),str(row['idempotency_key']),str(row['opportunity_id']),str(row['job_type']),str(row['request_fingerprint']),state,int(row['attempt_count']),int(row['max_attempts']),str(row['available_at']),row['lease_expires_at'],row['worker_id'],row['last_error'])
