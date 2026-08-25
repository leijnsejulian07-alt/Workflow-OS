from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

PROVIDER_RULE_POLICY_VERSION = "trading-provider-rules/1"
AUTOMATION_STATES = {"ALLOWED", "CONDITIONAL", "PROHIBITED", "UNKNOWN"}
EXECUTION_ACCESS_STATES = {"VERIFIED", "UNVERIFIED"}
MAX_SOURCE_URLS = 16
MAX_TEXT = 128


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _nonnegative(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def _sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digest = value.strip()
    if len(digest) != 64 or digest.lower() != digest:
        return None
    try:
        int(digest, 16)
    except ValueError:
        return None
    return digest


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _bounded_text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required")
    text = value.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError(f"{name} is required and bounded")
    return text


def _source_urls(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_SOURCE_URLS:
        raise ValueError("official_source_urls are required and bounded")
    urls: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("official_source_urls must contain strings")
        text = item.strip()
        parsed = urlparse(text)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("official_source_urls must be credential-free HTTPS URLs")
        if len(text) > 2048:
            raise ValueError("official_source_urls are too long")
        urls.append(text)
    if len(set(urls)) != len(urls):
        raise ValueError("official_source_urls must be unique")
    return tuple(urls)


def _string_set(value: object, *, name: str, max_items: int = 64) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > max_items:
        raise ValueError(f"{name} is invalid")
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{name} must contain strings")
        text = item.strip().upper()
        if not text or len(text) > MAX_TEXT:
            raise ValueError(f"{name} contains an invalid value")
        output.append(text)
    if len(set(output)) != len(output):
        raise ValueError(f"{name} must be unique")
    return tuple(output)


@dataclass(frozen=True)
class ProviderRuleEvidence:
    provider: str
    program: str
    account_size: float
    account_currency: str
    purchase_cost: float
    rule_version: str
    checked_at: str
    official_source_urls: tuple[str, ...]
    evidence_sha256: str
    automation_state: str
    automation_requires_written_approval: bool
    execution_access_state: str
    daily_loss_limit: float
    max_drawdown: float
    max_position_contracts: float
    payout_share_pct: float
    prohibited_strategies: tuple[str, ...]
    restricted_times: tuple[str, ...]
    production_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["official_source_urls"] = list(self.official_source_urls)
        data["prohibited_strategies"] = list(self.prohibited_strategies)
        data["restricted_times"] = list(self.restricted_times)
        return data


@dataclass(frozen=True)
class ProviderReadinessDecision:
    provider: str
    program: str
    decision: str
    reasons: tuple[str, ...]
    may_simulate: bool
    may_prepare_live_execution: bool
    rules_checked_at: str
    policy_version: str = PROVIDER_RULE_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def normalize_provider_rule_evidence(raw: dict[str, Any]) -> ProviderRuleEvidence:
    provider = _bounded_text(raw.get("provider"), name="provider")
    program = _bounded_text(raw.get("program"), name="program")
    currency = _bounded_text(raw.get("account_currency"), name="account_currency").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("account_currency must be a three-letter code")

    account_size = _positive(raw.get("account_size"))
    purchase_cost = _nonnegative(raw.get("purchase_cost"))
    daily_loss = _positive(raw.get("daily_loss_limit"))
    max_drawdown = _positive(raw.get("max_drawdown"))
    max_position = _positive(raw.get("max_position_contracts"))
    payout_share = _nonnegative(raw.get("payout_share_pct"))
    if None in (account_size, purchase_cost, daily_loss, max_drawdown, max_position, payout_share):
        raise ValueError("provider economics and risk limits must be finite and valid")
    assert payout_share is not None
    if payout_share > 100:
        raise ValueError("payout_share_pct must be <= 100")

    rule_version = _bounded_text(raw.get("rule_version"), name="rule_version")
    checked = _timestamp(raw.get("checked_at"))
    if checked is None:
        raise ValueError("checked_at must be timezone-aware")
    source_urls = _source_urls(raw.get("official_source_urls"))
    evidence_sha256 = _sha256(raw.get("evidence_sha256"))
    if evidence_sha256 is None:
        raise ValueError("evidence_sha256 is invalid")

    automation_state = raw.get("automation_state")
    execution_access_state = raw.get("execution_access_state")
    if automation_state not in AUTOMATION_STATES:
        raise ValueError("automation_state is invalid")
    if execution_access_state not in EXECUTION_ACCESS_STATES:
        raise ValueError("execution_access_state is invalid")

    approval_required = raw.get("automation_requires_written_approval", False)
    production_enabled = raw.get("production_enabled", False)
    if not isinstance(approval_required, bool) or not isinstance(production_enabled, bool):
        raise ValueError("provider capability flags must be boolean")

    return ProviderRuleEvidence(
        provider=provider,
        program=program,
        account_size=account_size,
        account_currency=currency,
        purchase_cost=purchase_cost,
        rule_version=rule_version,
        checked_at=checked.isoformat(),
        official_source_urls=source_urls,
        evidence_sha256=evidence_sha256,
        automation_state=automation_state,
        automation_requires_written_approval=approval_required,
        execution_access_state=execution_access_state,
        daily_loss_limit=daily_loss,
        max_drawdown=max_drawdown,
        max_position_contracts=max_position,
        payout_share_pct=payout_share,
        prohibited_strategies=_string_set(raw.get("prohibited_strategies", []), name="prohibited_strategies"),
        restricted_times=_string_set(raw.get("restricted_times", []), name="restricted_times"),
        production_enabled=production_enabled,
    )


def assess_provider_readiness(
    evidence: ProviderRuleEvidence,
    *,
    now: datetime | None = None,
    max_rule_age: timedelta = timedelta(days=7),
    written_automation_approval_verified: bool = False,
) -> ProviderReadinessDecision:
    """Evaluate provider rules only. This never authorizes or emits an order."""
    if max_rule_age <= timedelta(0) or max_rule_age > timedelta(days=90):
        raise ValueError("max_rule_age must be > 0 and <= 90 days")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    observed_now = observed_now.astimezone(timezone.utc)
    checked = datetime.fromisoformat(evidence.checked_at).astimezone(timezone.utc)

    reasons: list[str] = []
    if checked > observed_now + timedelta(minutes=5):
        reasons.append("RULE_EVIDENCE_FROM_FUTURE")
    if observed_now - checked > max_rule_age:
        reasons.append("RULE_EVIDENCE_STALE")
    if evidence.automation_state in {"PROHIBITED", "UNKNOWN"}:
        reasons.append("AUTOMATION_NOT_ALLOWED_OR_UNKNOWN")
    if evidence.automation_state == "CONDITIONAL" and (
        evidence.automation_requires_written_approval and not written_automation_approval_verified
    ):
        reasons.append("WRITTEN_AUTOMATION_APPROVAL_NOT_VERIFIED")
    if evidence.execution_access_state != "VERIFIED":
        reasons.append("OFFICIAL_EXECUTION_ACCESS_NOT_VERIFIED")
    if not evidence.production_enabled:
        reasons.append("LIVE_TRADING_NOT_EXPLICITLY_ENABLED")

    if reasons:
        return ProviderReadinessDecision(
            provider=evidence.provider,
            program=evidence.program,
            decision="HOLD",
            reasons=tuple(reasons),
            may_simulate=True,
            may_prepare_live_execution=False,
            rules_checked_at=evidence.checked_at,
        )

    return ProviderReadinessDecision(
        provider=evidence.provider,
        program=evidence.program,
        decision="PREPARE_ONLY",
        reasons=("PROVIDER_RULE_GATES_PASSED", "ORDER_EXECUTION_NOT_AUTHORIZED_BY_PROVIDER_PROFILE"),
        may_simulate=True,
        may_prepare_live_execution=True,
        rules_checked_at=evidence.checked_at,
    )
