from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .adapters.openshorts_hosted import OpenShortsHostedTransport
from .job_queue import JobQueue
from .openshorts_worker_cycle import OpenShortsWorkerCycleResult, run_bounded_openshorts_worker_cycle
from .side_effects import SideEffectLedger


@dataclass(frozen=True)
class OpenShortsRuntimeConfig:
    state_db_path: str
    worker_id: str
    webhook_url: str
    allowed_source_hosts: tuple[str, ...]
    allowed_webhook_hosts: tuple[str, ...]
    api_key: str
    webhook_secret: str
    max_jobs: int
    lease_seconds: int


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"missing required runtime setting: {name}")
    return value.strip()


def _authority(env: Mapping[str, str], name: str) -> None:
    if _required(env, name) != "verified":
        raise RuntimeError(f"{name} must be exactly 'verified'")


def _bounded_int(env: Mapping[str, str], name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _host_list(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = _required(env, name)
    hosts: list[str] = []
    for item in raw.split(","):
        host = item.strip().lower().rstrip(".")
        if (
            not host
            or len(host) > 253
            or ":" in host
            or "/" in host
            or "@" in host
            or host.startswith(".")
            or host.endswith(".")
            or "*" in host
        ):
            raise RuntimeError(f"{name} contains an invalid host")
        if host not in hosts:
            hosts.append(host)
    if not hosts or len(hosts) > 16:
        raise RuntimeError(f"{name} must contain between 1 and 16 explicit hosts")
    return tuple(hosts)


def _validated_webhook_url(value: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
        or host not in allowed_hosts
    ):
        raise RuntimeError("WORKFLOW_OS_OPENSHORTS_WEBHOOK_URL must be an allowlisted https URL")
    return value


def load_openshorts_runtime_config(env: Mapping[str, str] | None = None) -> OpenShortsRuntimeConfig:
    source = os.environ if env is None else env
    _authority(source, "WORKFLOW_OS_OPENSHORTS_CREDENTIAL_AUTHORITY")
    _authority(source, "WORKFLOW_OS_OPENSHORTS_COST_AUTHORITY")

    db_path = _required(source, "WORKFLOW_OS_OPENSHORTS_STATE_DB")
    path = Path(db_path).expanduser()
    if not path.is_absolute():
        raise RuntimeError("WORKFLOW_OS_OPENSHORTS_STATE_DB must be an absolute path")

    worker_id = _required(source, "WORKFLOW_OS_OPENSHORTS_WORKER_ID")
    if len(worker_id) > 200 or any(ord(ch) < 32 for ch in worker_id):
        raise RuntimeError("WORKFLOW_OS_OPENSHORTS_WORKER_ID is invalid")

    allowed_source_hosts = _host_list(source, "WORKFLOW_OS_OPENSHORTS_ALLOWED_SOURCE_HOSTS")
    allowed_webhook_hosts = _host_list(source, "WORKFLOW_OS_OPENSHORTS_ALLOWED_WEBHOOK_HOSTS")
    webhook_url = _validated_webhook_url(
        _required(source, "WORKFLOW_OS_OPENSHORTS_WEBHOOK_URL"),
        allowed_webhook_hosts,
    )

    api_key = _required(source, "OPENSHORTS_API_KEY")
    if not api_key.startswith("osk_") or not 12 <= len(api_key) <= 512 or any(ch.isspace() for ch in api_key):
        raise RuntimeError("OPENSHORTS_API_KEY is malformed")

    webhook_secret = _required(source, "WORKFLOW_OS_OPENSHORTS_WEBHOOK_SECRET")
    if not 32 <= len(webhook_secret) <= 512 or any(ord(ch) < 33 or ord(ch) == 127 for ch in webhook_secret):
        raise RuntimeError("WORKFLOW_OS_OPENSHORTS_WEBHOOK_SECRET is malformed")

    return OpenShortsRuntimeConfig(
        state_db_path=str(path),
        worker_id=worker_id,
        webhook_url=webhook_url,
        allowed_source_hosts=allowed_source_hosts,
        allowed_webhook_hosts=allowed_webhook_hosts,
        api_key=api_key,
        webhook_secret=webhook_secret,
        max_jobs=_bounded_int(source, "WORKFLOW_OS_OPENSHORTS_MAX_JOBS", default=1, minimum=1, maximum=4),
        lease_seconds=_bounded_int(source, "WORKFLOW_OS_OPENSHORTS_LEASE_SECONDS", default=300, minimum=30, maximum=3600),
    )


def run_openshorts_runtime_once(
    config: OpenShortsRuntimeConfig,
    *,
    now: str | None = None,
    transport: OpenShortsHostedTransport | None = None,
) -> OpenShortsWorkerCycleResult:
    if not isinstance(config, OpenShortsRuntimeConfig):
        raise TypeError("config must be OpenShortsRuntimeConfig")
    timestamp = now or datetime.now(timezone.utc).isoformat()
    runtime_transport = transport or OpenShortsHostedTransport()
    queue = JobQueue(config.state_db_path)
    ledger = SideEffectLedger(config.state_db_path)
    return run_bounded_openshorts_worker_cycle(
        max_jobs=config.max_jobs,
        queue=queue,
        side_effect_ledger=ledger,
        worker_id=config.worker_id,
        now=timestamp,
        webhook_url=config.webhook_url,
        allowed_source_hosts=config.allowed_source_hosts,
        allowed_webhook_hosts=config.allowed_webhook_hosts,
        credential_authority_verified=True,
        cost_authority_verified=True,
        transport=runtime_transport,
        api_key=config.api_key,
        webhook_secret=config.webhook_secret,
        lease_seconds=config.lease_seconds,
    )


def main() -> int:
    result = run_openshorts_runtime_once(load_openshorts_runtime_config())
    print(json.dumps({
        "attempted": result.attempted,
        "completed": result.completed,
        "stopped_on_empty_queue": result.stopped_on_empty_queue,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
