from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

TRADING_ACCOUNT_HEALTH_POLICY_VERSION = "trading-account-health/1"


def _bounded_text(value: object, name: str, limit: int = 200) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required")
    text = value.strip()
    if not text or len(text) > limit:
        raise ValueError(f"{name} is required and bounded")
    return text


def _nonnegative(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _positive(value: object, name: str) -> float:
    number = _nonnegative(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradingAccountTelemetry:
    account_id: str
    provider: str
    program: str
    observed_at: datetime
    api_contract_version_expected: str
    api_contract_version_observed: str
    provider_rules_version_expected: str
    provider_rules_version_observed: str
    provider_rules_observed_at: datetime
    reconciliation_healthy: bool
    unresolved_unknown_side_effects: int
    current_drawdown: float
    max_drawdown: float
    realized_daily_loss: float
    daily_loss_limit: float
    observed_slippage_bps: float
    slippage_limit_bps: float
    production_enabled: bool


@dataclass(frozen=True)
class TradingAccountHealthDecision:
    account_health: str
    automatic_pause: bool
    reasons: tuple[str, ...]
    rules_fresh: bool
    reconciliation_healthy: bool
    policy_version: str = TRADING_ACCOUNT_HEALTH_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def evaluate_trading_account_health(
    *,
    telemetry: TradingAccountTelemetry,
    now: datetime,
    max_rule_age_seconds: int = 86_400,
) -> TradingAccountHealthDecision:
    """Compute fail-closed health for a bound funded-account runtime.

    This monitor never sends an order, changes credentials, or enables production.
    Any material API/rule drift, unresolved ambiguous side effect, reconciliation
    failure, abnormal slippage, or exhausted loss/drawdown budget automatically
    pauses the account. The result is intended to feed TradingRiskSnapshot.
    """

    _bounded_text(telemetry.account_id, "account_id")
    _bounded_text(telemetry.provider, "provider")
    _bounded_text(telemetry.program, "program")
    expected_api = _bounded_text(
        telemetry.api_contract_version_expected, "api_contract_version_expected"
    )
    observed_api = _bounded_text(
        telemetry.api_contract_version_observed, "api_contract_version_observed"
    )
    expected_rules = _bounded_text(
        telemetry.provider_rules_version_expected, "provider_rules_version_expected"
    )
    observed_rules = _bounded_text(
        telemetry.provider_rules_version_observed, "provider_rules_version_observed"
    )

    observed_at = _utc(telemetry.observed_at, "observed_at")
    rules_observed_at = _utc(
        telemetry.provider_rules_observed_at, "provider_rules_observed_at"
    )
    current_time = _utc(now, "now")
    if observed_at > current_time:
        raise ValueError("observed_at cannot be in the future")
    if rules_observed_at > current_time:
        raise ValueError("provider_rules_observed_at cannot be in the future")
    if not isinstance(max_rule_age_seconds, int) or max_rule_age_seconds <= 0:
        raise ValueError("max_rule_age_seconds must be a positive integer")
    if not isinstance(telemetry.unresolved_unknown_side_effects, int) or telemetry.unresolved_unknown_side_effects < 0:
        raise ValueError("unresolved_unknown_side_effects must be a nonnegative integer")

    drawdown = _nonnegative(telemetry.current_drawdown, "current_drawdown")
    max_drawdown = _positive(telemetry.max_drawdown, "max_drawdown")
    daily_loss = _nonnegative(telemetry.realized_daily_loss, "realized_daily_loss")
    daily_loss_limit = _positive(telemetry.daily_loss_limit, "daily_loss_limit")
    slippage = _nonnegative(telemetry.observed_slippage_bps, "observed_slippage_bps")
    slippage_limit = _positive(telemetry.slippage_limit_bps, "slippage_limit_bps")

    rules_fresh = (
        expected_rules == observed_rules
        and (current_time - rules_observed_at).total_seconds() <= max_rule_age_seconds
    )
    reconciliation_healthy = (
        telemetry.reconciliation_healthy
        and telemetry.unresolved_unknown_side_effects == 0
    )

    reasons: list[str] = []
    if expected_api != observed_api:
        reasons.append("API_CONTRACT_MISMATCH")
    if expected_rules != observed_rules:
        reasons.append("PROVIDER_RULE_VERSION_MISMATCH")
    elif not rules_fresh:
        reasons.append("PROVIDER_RULES_STALE")
    if not telemetry.reconciliation_healthy:
        reasons.append("RECONCILIATION_UNHEALTHY")
    if telemetry.unresolved_unknown_side_effects > 0:
        reasons.append("UNRESOLVED_UNKNOWN_SIDE_EFFECTS")
    if slippage > slippage_limit:
        reasons.append("ABNORMAL_SLIPPAGE")
    if daily_loss >= daily_loss_limit:
        reasons.append("DAILY_LOSS_LIMIT_REACHED")
    if drawdown >= max_drawdown:
        reasons.append("MAX_DRAWDOWN_REACHED")
    if not telemetry.production_enabled:
        reasons.append("LIVE_TRADING_NOT_EXPLICITLY_ENABLED")

    if reasons:
        return TradingAccountHealthDecision(
            account_health="PAUSED",
            automatic_pause=True,
            reasons=tuple(reasons),
            rules_fresh=rules_fresh,
            reconciliation_healthy=reconciliation_healthy,
        )

    return TradingAccountHealthDecision(
        account_health="HEALTHY",
        automatic_pause=False,
        reasons=(),
        rules_fresh=True,
        reconciliation_healthy=True,
    )
