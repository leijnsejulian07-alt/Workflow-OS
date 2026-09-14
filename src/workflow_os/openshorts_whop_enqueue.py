from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .job_queue import JobQueue, JobRecord
from .openshorts_output_provenance import OpenShortsClipOutput
from .sqlite_lifecycle import managed_connection

_OPENSHORTS_KEY_RE = re.compile(r"^openshorts:([1-9][0-9]*):([0-9a-f]{64})$")


def _source_job_payload(path: str | Path, source_job_id: int) -> tuple[JobRecord, dict[str, Any]]:
    queue = JobQueue(path)
    with managed_connection(sqlite3.connect(str(path), timeout=5.0)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (source_job_id,)).fetchone()
    if row is None:
        raise RuntimeError("OpenShorts source durable job does not exist")
    record = queue._row(row)
    if record.state != "SUCCEEDED" or record.job_type != "produce_and_publish":
        raise RuntimeError("OpenShorts source durable job is not a completed render job")
    try:
        payload = json.loads(str(row["request_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("OpenShorts source durable job payload is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenShorts source durable job payload must be an object")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(
        f"{record.job_type}\n{record.opportunity_id}\n{canonical}".encode("utf-8")
    ).hexdigest()
    if expected != record.request_fingerprint:
        raise RuntimeError("OpenShorts source durable job payload fingerprint mismatch")
    if payload.get("opportunity_id") != record.opportunity_id:
        raise RuntimeError("OpenShorts source durable job opportunity identity mismatch")
    return record, payload


def enqueue_completed_openshorts_whop_jobs(
    *,
    state_db_path: str | Path,
    openshorts_idempotency_key: str,
    outputs: tuple[OpenShortsClipOutput, ...],
    available_at: object,
    max_attempts: int = 3,
) -> tuple[JobRecord, ...]:
    """Create one idempotent `submit_reward` durable job per verified clip output.

    The child job copies the already-verified opportunity snapshot/revenue control
    from the completed render job and adds immutable render provenance. No secrets
    or submission authority are persisted here; the future Whop worker must still
    re-verify the opportunity and runtime credential authority before external I/O.
    """
    if not isinstance(openshorts_idempotency_key, str):
        raise TypeError("openshorts_idempotency_key must be a string")
    clean_key = openshorts_idempotency_key.strip()
    match = _OPENSHORTS_KEY_RE.fullmatch(clean_key)
    if match is None:
        raise ValueError("OpenShorts idempotency key is not bound to a durable render job")
    source_job_id = int(match.group(1))
    source_record, source_payload = _source_job_payload(state_db_path, source_job_id)
    expected_parent_digest = hashlib.sha256(
        f"openshorts-job\n{source_job_id}\n{source_record.request_fingerprint}".encode("utf-8")
    ).hexdigest()
    if match.group(2) != expected_parent_digest:
        raise RuntimeError("OpenShorts idempotency key does not match the source durable job")
    if not outputs:
        raise ValueError("completed OpenShorts output set must not be empty")

    queue = JobQueue(state_db_path)
    enqueued: list[JobRecord] = []
    seen_indexes: set[int] = set()
    for output in outputs:
        if not isinstance(output, OpenShortsClipOutput):
            raise TypeError("outputs must contain OpenShortsClipOutput values")
        if output.idempotency_key != clean_key:
            raise RuntimeError("OpenShorts output is not bound to the source render side effect")
        if output.clip_index in seen_indexes:
            raise ValueError("OpenShorts output clip index is duplicated")
        seen_indexes.add(output.clip_index)

        child_payload = json.loads(json.dumps(source_payload))
        child_payload["upstream_render"] = {
            "source_job_id": source_job_id,
            "source_request_fingerprint": source_record.request_fingerprint,
            "openshorts_idempotency_key": output.idempotency_key,
            "provider_job_id": output.provider_job_id,
            "clip_index": output.clip_index,
            "evidence_sha256": output.evidence_sha256,
            "video_url": output.video_url,
            "download_url": output.download_url,
            "title": output.title,
        }
        digest = hashlib.sha256(
            f"{output.idempotency_key}\n{output.clip_index}\n{output.evidence_sha256}".encode("utf-8")
        ).hexdigest()
        enqueued.append(queue.enqueue(
            idempotency_key=f"whop-submit:{source_job_id}:{digest}",
            opportunity_id=source_record.opportunity_id,
            job_type="submit_reward",
            payload=child_payload,
            available_at=available_at,
            max_attempts=max_attempts,
        ))
    return tuple(enqueued)
