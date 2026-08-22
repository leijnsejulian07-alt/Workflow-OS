from __future__ import annotations
import hashlib
import json
from typing import Any
from .experiment_ledger import ExperimentLedger
from .job_queue import JobQueue, JobRecord
from .ledger import OpportunityLedger
from .opportunity_snapshot import snapshot_opportunity
from .reconciliation import RevenueReconciliationLedger
from .scaling_control import revenue_controlled_queue_candidates


def _id(value: object, name: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = value.strip()
    if not text or len(text) > max_len or any(ord(ch) < 32 for ch in text):
        raise ValueError(f"invalid {name}")
    return text


def _directive(candidate: dict[str, Any]) -> dict[str, Any]:
    directive = candidate.get("revenue_control")
    if not isinstance(directive, dict):
        raise RuntimeError("controlled candidate is missing revenue_control")
    action = directive.get("action")
    if action not in {"EXPERIMENT", "KEEP", "SCALE"}:
        raise RuntimeError("controlled candidate has unsupported scheduling action")
    if directive.get("may_schedule") is not True:
        raise RuntimeError("controlled candidate is not schedulable")
    max_new_jobs = directive.get("max_new_jobs")
    if not isinstance(max_new_jobs, int) or isinstance(max_new_jobs, bool) or not 1 <= max_new_jobs <= 4:
        raise RuntimeError("controlled candidate has invalid max_new_jobs")
    sample_count = directive.get("sample_count")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 0:
        raise RuntimeError("controlled candidate has invalid sample_count")
    return directive


def _batch_fingerprint(opportunity_id: str, directive: dict[str, Any], snapshot_sha256: str | None = None) -> str:
    economics = {
        "opportunity_id": opportunity_id,
        "action": directive.get("action"),
        "sample_count": directive.get("sample_count"),
        "realized_cash_eur": directive.get("realized_cash_eur"),
        "reconciled_cost_eur": directive.get("reconciled_cost_eur"),
        "realized_profit_eur": directive.get("realized_profit_eur"),
        "policy_version": directive.get("policy_version"),
        "opportunity_snapshot_sha256": snapshot_sha256,
    }
    encoded = json.dumps(economics, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def enqueue_controlled_candidates(
    jobs: JobQueue,
    candidates: list[dict[str, Any]],
    *,
    scheduled_at: str,
    job_type: str = "produce_and_publish",
    max_attempts: int = 3,
) -> list[JobRecord]:
    """Persist controlled work with deterministic reconciled-economics identity."""
    kind = _id(job_type, "job_type", 100)
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    queued: list[JobRecord] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("controlled candidate must be an object")
        opportunity_id = _id(candidate.get("opportunity_id"), "opportunity_id", 200)
        if candidate.get("decision") != "ACCEPT" or candidate.get("eligible_for_queue") is not True:
            raise RuntimeError("controlled candidate is not upstream eligible")
        directive = _directive(candidate)
        snapshot = candidate.get("opportunity_snapshot")
        snapshot_sha = candidate.get("opportunity_snapshot_sha256")
        if (snapshot is None) != (snapshot_sha is None):
            raise RuntimeError("opportunity snapshot and digest must be provided together")
        if snapshot is not None:
            if not isinstance(snapshot, dict):
                raise RuntimeError("opportunity snapshot must be an object")
            if snapshot.get("opportunity_id") != opportunity_id:
                raise RuntimeError("opportunity snapshot identity mismatch")
            encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
            expected = hashlib.sha256(encoded).hexdigest()
            if snapshot_sha != expected:
                raise RuntimeError("opportunity snapshot digest mismatch")
        batch = _batch_fingerprint(opportunity_id, directive, snapshot_sha)
        for slot in range(1, directive["max_new_jobs"] + 1):
            payload = {
                "opportunity_id": opportunity_id,
                "revenue_control": dict(directive),
                "batch_fingerprint": batch,
                "batch_slot": slot,
            }
            if snapshot is not None:
                payload["opportunity_snapshot"] = snapshot
                payload["opportunity_snapshot_sha256"] = snapshot_sha
            queued.append(jobs.enqueue(
                idempotency_key=f"revenue:{batch}:{slot}",
                opportunity_id=opportunity_id,
                job_type=kind,
                payload=payload,
                available_at=scheduled_at,
                max_attempts=max_attempts,
            ))
    return queued


def schedule_revenue_controlled_jobs(
    opportunities: OpportunityLedger,
    reconciliation: RevenueReconciliationLedger,
    experiments: ExperimentLedger,
    jobs: JobQueue,
    *,
    scheduled_at: str,
    candidate_limit: int = 50,
    job_type: str = "produce_and_publish",
    max_attempts: int = 3,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> list[JobRecord]:
    """Evaluate policy, snapshot normalized opportunities, then durably enqueue work."""
    candidates = revenue_controlled_queue_candidates(
        opportunities,
        reconciliation,
        experiments,
        reserved_at=scheduled_at,
        limit=candidate_limit,
        experiment_jobs=experiment_jobs,
        keep_jobs=keep_jobs,
        scale_jobs=scale_jobs,
        min_samples_to_scale=min_samples_to_scale,
        min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
    )
    materialized: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("controlled candidate must be an object")
        opportunity_id = _id(candidate.get("opportunity_id"), "opportunity_id", 200)
        snapshot = snapshot_opportunity(opportunities, opportunity_id)
        enriched = dict(candidate)
        enriched["opportunity_snapshot"] = snapshot.payload
        enriched["opportunity_snapshot_sha256"] = snapshot.sha256
        materialized.append(enriched)
    return enqueue_controlled_candidates(
        jobs,
        materialized,
        scheduled_at=scheduled_at,
        job_type=job_type,
        max_attempts=max_attempts,
    )
