from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from .durable_worker import VerifiedLeasedOpportunityJob
from .openshorts_job_preparation import PreparedOpenShortsProcessing, prepare_durable_openshorts_processing
from .side_effects import SideEffectLedger


def _normalized_hosts(values: Iterable[str], *, label: str) -> frozenset[str]:
    hosts: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{label} entries must be strings")
        host = value.strip().rstrip(".").lower()
        if not host or len(host) > 253 or "/" in host or ":" in host or "@" in host:
            raise ValueError(f"invalid {label} host")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError(f"{label} must not contain IP literals")
        hosts.add(host)
    if not hosts:
        raise ValueError(f"{label} must not be empty")
    return frozenset(hosts)


def _verified_https_url(value: object, *, allowed_hosts: frozenset[str], label: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} must be a string")
    candidate = value.strip()
    if not candidate or len(candidate) > 2048 or any(ord(ch) < 32 for ch in candidate):
        raise RuntimeError(f"{label} is invalid")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise RuntimeError(f"{label} must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError(f"{label} must not contain credentials")
    try:
        if parsed.port not in (None, 443):
            raise RuntimeError(f"{label} must use the default HTTPS port")
    except ValueError as exc:
        raise RuntimeError(f"{label} contains an invalid port") from exc
    host = parsed.hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise RuntimeError(f"{label} must not use an IP literal")
    if host not in allowed_hosts:
        raise RuntimeError(f"{label} host is not allowlisted")
    return candidate


def prepare_verified_durable_openshorts_job(
    verified_job: VerifiedLeasedOpportunityJob,
    *,
    webhook_url: str,
    allowed_source_hosts: Iterable[str],
    allowed_webhook_hosts: Iterable[str],
    credential_authority_verified: bool,
    cost_authority_verified: bool,
    ledger: SideEffectLedger,
    captions: bool = True,
    auto_hook: bool = True,
    max_attempts: int = 2,
) -> PreparedOpenShortsProcessing:
    """Resolve verified job-owned runtime config and reserve OpenShorts fail closed.

    Source identity comes only from the verified durable opportunity snapshot. Exactly
    one source asset is required so a replay cannot silently choose a different asset.
    Deployment-level webhook and host allowlists remain explicit authority inputs.
    """
    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")

    source_hosts = _normalized_hosts(allowed_source_hosts, label="allowed_source_hosts")
    webhook_hosts = _normalized_hosts(allowed_webhook_hosts, label="allowed_webhook_hosts")

    assets = verified_job.opportunity.get("source_assets")
    if not isinstance(assets, list) or len(assets) != 1:
        raise RuntimeError("OpenShorts requires exactly one verified source asset")
    source_url = _verified_https_url(assets[0], allowed_hosts=source_hosts, label="source asset")
    verified_webhook = _verified_https_url(webhook_url, allowed_hosts=webhook_hosts, label="webhook URL")

    return prepare_durable_openshorts_processing(
        verified_job,
        source_url=source_url,
        webhook_url=verified_webhook,
        credential_authority_verified=credential_authority_verified,
        cost_authority_verified=cost_authority_verified,
        ledger=ledger,
        captions=captions,
        auto_hook=auto_hook,
        max_attempts=max_attempts,
    )
