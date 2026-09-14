from __future__ import annotations

import hashlib
import ipaddress
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from .adapters.openshorts_hosted import OpenShortsWebhookEvent
from .openshorts_execution import OpenShortsTerminalEvidence
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection

_MAX_CLIPS = 16
_MAX_URL_CHARS = 4096
_MAX_TITLE_CHARS = 500
_HOSTED_API_BASE = "https://api.openshorts.app"


@dataclass(frozen=True)
class OpenShortsClipOutput:
    idempotency_key: str
    provider_job_id: str
    clip_index: int
    video_url: str
    download_url: str
    title: str
    evidence_sha256: str


class OpenShortsOutputProvenanceStore:
    """Immutable public clip outputs bound to authenticated terminal evidence."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(sqlite3.connect(self.path, timeout=5.0)) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS openshorts_output_provenance (
                    idempotency_key TEXT NOT NULL,
                    provider_job_id TEXT NOT NULL,
                    clip_index INTEGER NOT NULL CHECK(clip_index >= 0),
                    video_url TEXT NOT NULL,
                    download_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    PRIMARY KEY(idempotency_key, clip_index),
                    UNIQUE(provider_job_id, clip_index)
                );
                """
            )

    def record_many(self, outputs: tuple[OpenShortsClipOutput, ...]) -> tuple[OpenShortsClipOutput, ...]:
        if not outputs:
            raise ValueError("completed OpenShorts job produced no clips")
        with managed_connection(sqlite3.connect(self.path, timeout=5.0)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            for output in outputs:
                row = db.execute(
                    "SELECT * FROM openshorts_output_provenance WHERE idempotency_key=? AND clip_index=?",
                    (output.idempotency_key, output.clip_index),
                ).fetchone()
                if row is not None:
                    if _row(row) != output:
                        raise ValueError("OpenShorts clip output provenance is immutable")
                    continue
                try:
                    db.execute(
                        """INSERT INTO openshorts_output_provenance(
                            idempotency_key,provider_job_id,clip_index,video_url,download_url,title,evidence_sha256
                        ) VALUES(?,?,?,?,?,?,?)""",
                        (
                            output.idempotency_key,
                            output.provider_job_id,
                            output.clip_index,
                            output.video_url,
                            output.download_url,
                            output.title,
                            output.evidence_sha256,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("OpenShorts clip output conflicts with existing provenance") from exc
        return outputs

    def list_for(self, idempotency_key: str) -> tuple[OpenShortsClipOutput, ...]:
        with managed_connection(sqlite3.connect(self.path, timeout=5.0)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM openshorts_output_provenance WHERE idempotency_key=? ORDER BY clip_index",
                (idempotency_key,),
            ).fetchall()
        return tuple(_row(row) for row in rows)


def _row(row: sqlite3.Row) -> OpenShortsClipOutput:
    return OpenShortsClipOutput(
        idempotency_key=str(row["idempotency_key"]),
        provider_job_id=str(row["provider_job_id"]),
        clip_index=int(row["clip_index"]),
        video_url=str(row["video_url"]),
        download_url=str(row["download_url"]),
        title=str(row["title"]),
        evidence_sha256=str(row["evidence_sha256"]),
    )


def _public_https(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a public https URL")
    url = value.strip()
    if not url or len(url) > _MAX_URL_CHARS:
        raise ValueError(f"{name} must be a public https URL")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path
        or parsed.fragment
    ):
        raise ValueError(f"{name} must use a normal public https origin")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError(f"{name} cannot target a local/private host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    ):
        raise ValueError(f"{name} cannot target a local/private host")
    return url


def _hosted_status_url(value: object, *, name: str) -> str:
    if isinstance(value, str) and value.startswith("/") and not value.startswith("//"):
        value = f"{_HOSTED_API_BASE}{value}"
    return _public_https(value, name=name)


def _confirmed_dispatch(ledger: SideEffectLedger, terminal_evidence: OpenShortsTerminalEvidence) -> None:
    record = ledger.get(terminal_evidence.idempotency_key)
    if (
        record is None
        or record.state != "SUCCEEDED"
        or record.action != "openshorts.process"
        or record.external_reference != terminal_evidence.provider_job_id
    ):
        raise RuntimeError("clip outputs are not bound to a confirmed OpenShorts dispatch")


def _outputs_from_clips(
    *,
    terminal_evidence: OpenShortsTerminalEvidence,
    clips: object,
    implicit_indexes: bool,
    hosted_status_urls: bool,
) -> tuple[OpenShortsClipOutput, ...]:
    if not isinstance(clips, list) or not clips or len(clips) > _MAX_CLIPS:
        raise ValueError("completed OpenShorts evidence has an invalid clip count")
    outputs: list[OpenShortsClipOutput] = []
    seen_indexes: set[int] = set()
    seen_urls: set[str] = set()
    for fallback_index, clip in enumerate(clips):
        if not isinstance(clip, Mapping):
            raise ValueError("completed OpenShorts evidence contains malformed clip data")
        index = clip.get("index", fallback_index if implicit_indexes else None)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index in seen_indexes:
            raise ValueError("OpenShorts clip index is invalid or duplicated")
        url_parser = _hosted_status_url if hosted_status_urls else _public_https
        video_url = url_parser(clip.get("video_url"), name="video_url")
        raw_download_url = clip.get("download_url")
        if raw_download_url is None and hosted_status_urls:
            raw_download_url = clip.get("video_url")
        download_url = url_parser(raw_download_url, name="download_url")
        if video_url in seen_urls or download_url in seen_urls:
            raise ValueError("OpenShorts clip URLs must be unique")
        title = clip.get("title")
        if title is None:
            title = clip.get("video_title_for_youtube_short") or ""
        if not isinstance(title, str) or len(title.strip()) > _MAX_TITLE_CHARS:
            raise ValueError("OpenShorts clip title is invalid")
        seen_indexes.add(index)
        seen_urls.update((video_url, download_url))
        outputs.append(OpenShortsClipOutput(
            idempotency_key=terminal_evidence.idempotency_key,
            provider_job_id=terminal_evidence.provider_job_id,
            clip_index=index,
            video_url=video_url,
            download_url=download_url,
            title=title.strip(),
            evidence_sha256=terminal_evidence.evidence_sha256,
        ))
    outputs.sort(key=lambda item: item.clip_index)
    return tuple(outputs)


def record_completed_clip_outputs(
    *,
    ledger: SideEffectLedger,
    store: OpenShortsOutputProvenanceStore,
    terminal_evidence: OpenShortsTerminalEvidence,
    webhook_event: OpenShortsWebhookEvent,
) -> tuple[OpenShortsClipOutput, ...]:
    """Persist signed completed webhook clip URLs matching durable dispatch evidence."""
    if terminal_evidence.terminal_state != "COMPLETED" or terminal_evidence.source != "webhook":
        raise RuntimeError("clip outputs require completed signed webhook terminal evidence")
    if webhook_event.event != "job.completed":
        raise RuntimeError("clip outputs require a completed webhook event")
    if webhook_event.body_sha256 != terminal_evidence.evidence_sha256:
        raise RuntimeError("webhook body does not match durable terminal evidence")
    if webhook_event.job_id != terminal_evidence.provider_job_id:
        raise RuntimeError("webhook job does not match durable terminal evidence")
    _confirmed_dispatch(ledger, terminal_evidence)
    outputs = _outputs_from_clips(
        terminal_evidence=terminal_evidence,
        clips=webhook_event.payload.get("clips"),
        implicit_indexes=False,
        hosted_status_urls=False,
    )
    return store.record_many(outputs)


def record_completed_status_clip_outputs(
    *,
    ledger: SideEffectLedger,
    store: OpenShortsOutputProvenanceStore,
    terminal_evidence: OpenShortsTerminalEvidence,
    status_payload: Mapping[str, object],
) -> tuple[OpenShortsClipOutput, ...]:
    """Persist clips from the exact authenticated status payload bound by evidence hash."""
    if terminal_evidence.terminal_state != "COMPLETED" or terminal_evidence.source != "status_api":
        raise RuntimeError("status clip outputs require completed status-api terminal evidence")
    payload = dict(status_payload)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != terminal_evidence.evidence_sha256:
        raise RuntimeError("status payload does not match durable terminal evidence")
    payload_job_id = payload.get("job_id")
    if payload_job_id is not None and str(payload_job_id).strip() != terminal_evidence.provider_job_id:
        raise RuntimeError("status job does not match durable terminal evidence")
    if str(payload.get("status") or "").strip().lower() != "completed":
        raise RuntimeError("status clip outputs require a completed provider status")
    _confirmed_dispatch(ledger, terminal_evidence)
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("completed OpenShorts status omitted result data")
    outputs = _outputs_from_clips(
        terminal_evidence=terminal_evidence,
        clips=result.get("clips"),
        implicit_indexes=True,
        hosted_status_urls=True,
    )
    return store.record_many(outputs)
