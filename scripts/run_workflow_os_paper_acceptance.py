#!/usr/bin/env python3
"""Run a completely offline, restart-safe acceptance exercise for an existing revenue worker.

The *production* OpenShorts -> Whop submission worker, queues and ledgers are used.
Technical QC, credentials and HTTPS are replaced by in-process fakes; no real
platform accounts, media downloads, publications, network I/O or payments occur.

One command:
    python scripts/run_workflow_os_paper_acceptance.py [--output-dir PATH]

Each phase runs in a SEPARATE Python process against the same SQLite database.
Persistent JSONL proof and a terminal summary are written in a new run folder.
A simulated pre-dispatch credential failure is safe to retry; an ambiguous
transport failure MUST NOT be blindly retried after restarting.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_output_provenance import (
    OpenShortsClipOutput, OpenShortsOutputProvenanceStore,
)
from workflow_os.openshorts_output_qc import OpenShortsOutputQCEvidence
from workflow_os.side_effects import SideEffectLedger
from workflow_os.sqlite_lifecycle import managed_connection
from workflow_os.submit_reward_openshorts_whop_worker import (
    run_submit_reward_openshorts_whop_once,
)
from workflow_os.whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger


BATCH_FINGERPRINT = "b" * 64
REQUEST_FINGERPRINT = "c" * 64
EVIDENCE_FINGERPRINT = "d" * 64
_FAKE_RESPONSE_ID = "btys_paperonly123"
_BOUNTY = "bnty_worker1"
_PHASES = (
    "seed", "local_failure", "restart_success", "no_duplicate",
    "ambiguous_failure", "unknown_after_restart", "verify",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _db_path(run_dir: Path) -> Path:
    return run_dir / "paper-only.sqlite"


def _append_event(run_dir: Path, event: dict[str, object]) -> None:
    """Durably append a small audit event, without credential or HTTP payload data."""
    event = {"time": _now(), **event}
    with (run_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _stores(db_path: Path):
    # Re-instantiated for EVERY subprocess: no in-memory queue state survives.
    return (
        JobQueue(db_path),
        SideEffectLedger(db_path),
        OpenShortsOutputProvenanceStore(db_path),
        DurableWhopBountyBindingLedger(db_path),
        WhopBountySubmissionProvenanceLedger(db_path),
    )


class _FakeResponse:
    def __init__(self) -> None:
        self.body = io.BytesIO(
            json.dumps({"id": _FAKE_RESPONSE_ID, "bounty_id": _BOUNTY, "status": "submitted"}).encode()
        )

    def getcode(self) -> int:
        return 201

    def read(self, size: int = -1) -> bytes:
        return self.body.read(size)

    def close(self) -> None:
        self.body.close()


class _NoNetworkOpener:
    """NEVER invokes urllib, socket or the real Internet."""

    def __init__(self, *, ambiguous: bool = False) -> None:
        self.calls = 0
        self.ambiguous = ambiguous

    def open(self, request, timeout):  # noqa: ANN001
        # A fake provider response does not constitute an actual submission.
        if request.full_url != "https://api.whop.com/api/v1/bounty_submissions":
            raise AssertionError("unexpected endpoint")
        self.calls += 1
        if self.ambiguous:
            raise URLError("simulated unknown transport outcome")
        return _FakeResponse()


class _FakeCredentials:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable

    def lease(self, _reference):  # noqa: ANN001
        if self.unavailable:
            raise RuntimeError("simulated credential provider unavailable BEFORE dispatch")
        return CredentialLease("offline-smoke-credential-never-sent")


def _fake_qc(output, **_kwargs) -> OpenShortsOutputQCEvidence:  # noqa: ANN001
    # This is deliberately NOT a real media verification or permission to post.
    return OpenShortsOutputQCEvidence(
        idempotency_key=output.idempotency_key,
        provider_job_id=output.provider_job_id,
        clip_index=output.clip_index,
        provider_evidence_sha256=output.evidence_sha256,
        media_sha256="e" * 64,
        media_type="video/mp4",
        size_bytes=1234,
        duration_ms=15000,
        width=1080,
        height=1920,
        video_codec="h264",
        has_audio=True,
    )


def _seed(queue: JobQueue, outputs: OpenShortsOutputProvenanceStore, scenario: str) -> None:
    source_job_id = 7 if scenario == "success" else 8
    key = f"openshorts:{source_job_id}:" + ("a" * 64)
    opportunity = {
        "opportunity_id": f"opp-paper-{scenario}",
        "source_platform": "whop_bounties",
        "campaign_id": _BOUNTY,
        "bounty_type": "workforce",
        "machine_submission_verified": True,
        "zero_touch_execution_enabled": True,
        "rights_verification_state": "VERIFIED",
        "account_authorized": True,
        "worker_identity_verified": True,
        "campaign_requirements_verified": True,
        "deliverable_requirements_verified": True,
        "disclosure_satisfied": True,
    }
    output = OpenShortsClipOutput(
        idempotency_key=key,
        provider_job_id=f"provider-paper-{scenario}",
        clip_index=0,
        video_url="https://cdn.example.com/paper-clip.mp4",
        download_url="https://cdn.example.com/paper-clip.mp4?download=1",
        title="offline simulation only",
        evidence_sha256=EVIDENCE_FINGERPRINT,
    )
    outputs.record_many((output,))
    queue.enqueue(
        idempotency_key=f"paper-only:{scenario}",
        opportunity_id=opportunity["opportunity_id"],
        job_type="submit_reward",
        payload={
            "opportunity_id": opportunity["opportunity_id"],
            "batch_fingerprint": BATCH_FINGERPRINT,
            "opportunity_snapshot": opportunity,
            "opportunity_snapshot_sha256": _canonical_hash(opportunity),
            "revenue_control": {"opportunity_id": opportunity["opportunity_id"], "may_schedule": True},
            "batch_slot": 1,
            "upstream_render": {
                "source_job_id": source_job_id,
                "source_request_fingerprint": REQUEST_FINGERPRINT,
                "openshorts_idempotency_key": key,
                "provider_job_id": output.provider_job_id,
                "clip_index": 0,
                "evidence_sha256": output.evidence_sha256,
                "video_url": output.video_url,
            },
        },
        available_at=_now(),
        max_attempts=3,
    )


def _invoke(run_dir: Path, *, unavailable: bool = False, ambiguous: bool = False):
    queue, effects, outputs, bindings, provenance = _stores(_db_path(run_dir))
    opener = _NoNetworkOpener(ambiguous=ambiguous)
    result = run_submit_reward_openshorts_whop_once(
        queue=queue,
        side_effect_ledger=effects,
        output_store=outputs,
        binding_ledger=bindings,
        provenance_ledger=provenance,
        credential_ref=CredentialRef(
            platform="whop", account_id="paper-synthetic-account", secret_name="user_token",
        ),
        credential_provider=_FakeCredentials(unavailable=unavailable),
        transport=WhopBountyHttpTransport(opener=opener, timeout_seconds=2),
        worker_id="offline-paper-worker",
        now=_now(),
        workspace_root=run_dir,
        allowed_download_hosts=("cdn.example.com",),
        credential_authority_verified=True,  # SYNTHETIC evidence, never a live authority
        qc_verifier=_fake_qc,
    )
    return result, opener.calls


def _rows(db_path: Path) -> dict[str, dict[str, object]]:
    with managed_connection(sqlite3.connect(db_path, timeout=5)) as conn:
        records = conn.execute(
            "SELECT idempotency_key, state, attempt_count FROM jobs ORDER BY job_id"
        ).fetchall()
    return {str(k): {"state": str(s), "attempt_count": int(n)} for k, s, n in records}


def _effects(db_path: Path) -> list[tuple[str, int]]:
    with managed_connection(sqlite3.connect(db_path, timeout=5)) as conn:
        return [(str(s), int(n)) for s, n in conn.execute(
            "SELECT state, attempt_count FROM side_effects ORDER BY rowid"
        ).fetchall()]


def _phase(run_dir: Path, phase: str) -> dict[str, object]:
    if phase == "seed":
        queue, _effects_store, outputs, _binding_store, _prov = _stores(_db_path(run_dir))
        _seed(queue, outputs, "success")
        result = {"phase": phase, "prepared_jobs": 1, "http_calls": 0}
    elif phase == "local_failure":
        worker, calls = _invoke(run_dir, unavailable=True)
        # External execution did NOT begin: retry is authorized.
        if not worker.attempted or worker.execution.execution.job.state != "FAILED_RETRYABLE":
            raise AssertionError("credential pre-dispatch failure was not safely retryable")
        if worker.execution.execution.side_effect.state != "RESERVED" or calls != 0:
            raise AssertionError("credential preflight unexpectedly made an external attempt")
        result = {"phase": phase, "job_state": "FAILED_RETRYABLE", "effect_state": "RESERVED", "http_calls": calls}
    elif phase == "restart_success":
        worker, calls = _invoke(run_dir)
        if not worker.attempted or worker.execution.execution.job.state != "SUCCEEDED":
            raise AssertionError("restarted worker failed to complete retryable job")
        if worker.execution.execution.side_effect.state != "SUCCEEDED" or calls != 1:
            raise AssertionError("simulated submission did not close with one confirmed response")
        if worker.execution.provenance is None:
            raise AssertionError("confirmed submission lacks durable payout provenance")
        result = {"phase": phase, "job_state": "SUCCEEDED", "effect_state": "SUCCEEDED", "http_calls": calls}
    elif phase == "no_duplicate":
        worker, calls = _invoke(run_dir)
        if worker.attempted or calls:
            raise AssertionError("successful job was resubmitted")
        result = {"phase": phase, "attempted": False, "http_calls": calls}
    elif phase == "ambiguous_failure":
        queue, _effects_store, outputs, _binding_store, _prov = _stores(_db_path(run_dir))
        _seed(queue, outputs, "unknown")
        worker, calls = _invoke(run_dir, ambiguous=True)
        if not worker.attempted or worker.execution.execution.job.state != "UNKNOWN":
            raise AssertionError("ambiguous outcome must fail closed as UNKNOWN")
        if worker.execution.execution.side_effect.state != "UNKNOWN" or calls != 1:
            raise AssertionError("ambiguous effect was not persisted")
        result = {"phase": phase, "job_state": "UNKNOWN", "effect_state": "UNKNOWN", "http_calls": calls}
    elif phase == "unknown_after_restart":
        worker, calls = _invoke(run_dir)
        if worker.attempted or calls:
            raise AssertionError("UNKNOWN job was blindly retried after restart")
        result = {"phase": phase, "attempted": False, "http_calls": calls}
    elif phase == "verify":
        rows = _rows(_db_path(run_dir))
        effects = _effects(_db_path(run_dir))
        expected = {
            "paper-only:success": {"state": "SUCCEEDED", "attempt_count": 2},
            "paper-only:unknown": {"state": "UNKNOWN", "attempt_count": 1},
        }
        if rows != expected or sorted(effects) != [("SUCCEEDED", 1), ("UNKNOWN", 1)]:
            raise AssertionError(f"durable SQLite outcome mismatch: jobs={rows}, effects={effects}")
        # Fake credential is transient; neither SQLite nor logs may contain it.
        if b"offline-smoke-credential-never-sent" in _db_path(run_dir).read_bytes():
            raise AssertionError("synthetic credential leaked to durable storage")
        result = {"phase": phase, "durable_jobs": rows, "durable_effects": effects, "http_calls": 0}
    else:
        raise ValueError("unknown phase")
    _append_event(run_dir, result)
    return result


def _clean_subprocess_env() -> dict[str, str]:
    """Do not propagate provider credentials or ambient PYTHONPATH to smoke workers."""
    allow = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allow}
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_all(output_dir: Path) -> dict[str, object]:
    base = output_dir.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    run_dir = base / ("paper-" + secrets.token_hex(8))
    run_dir.mkdir(mode=0o700)  # collision fails closed; never overwrite other runs
    steps: list[dict[str, object]] = []
    for phase in _PHASES:
        # Process exits between EVERY phase: genuine restart/reopen test, not just
        # objects instantiated twice in one interpreter.
        cp = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_phase", phase, "--_run-dir", str(run_dir)],
            cwd=str(ROOT),
            env=_clean_subprocess_env(),
            timeout=30,
            capture_output=True,
            text=True,
            check=False,
        )
        if cp.returncode:
            problem = {
                "phase": phase, "exit_code": cp.returncode,
                "stderr": cp.stderr[-1500:].strip(),
            }
            _append_event(run_dir, {"failure": problem})
            raise RuntimeError(f"offline phase failed: {json.dumps(problem, sort_keys=True)}")
        step = json.loads(cp.stdout.strip())
        if step.get("phase") != phase:
            raise RuntimeError(f"unexpected child response in {phase}")
        steps.append(step)
    summary = {
        "mode": "SYNTHETIC_OFFLINE_ONLY",
        "offline_acceptance_passed": True,
        "test_mode_ready": False,  # Does NOT claim real accounts, live API, or unattended install
        "run_dir": str(run_dir),
        "sqlite": str(_db_path(run_dir)),
        "events": str(run_dir / "events.jsonl"),
        "phases": len(steps),
        "steps": steps,
    }
    path = run_dir / "summary.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(tempfile.gettempdir()) / "workflow-os-paper-acceptance",
        help="Parent folder for NEW, isolated, synthetic-only run directories",
    )
    parser.add_argument("--_phase", choices=_PHASES, help=argparse.SUPPRESS)
    parser.add_argument("--_run-dir", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._phase is not None:
        if args._run_dir is None:
            parser.error("internal phase requires --_run-dir")
        result = _phase(args._run_dir, args._phase)
    else:
        if args._run_dir is not None:
            parser.error("--_run-dir is for internal phases only")
        result = _run_all(args.output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
