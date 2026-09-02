from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

PAPER_LEARNING_POLICY_VERSION = "alpaca-paper-learning/1"
ALLOWED_PAPER_PROVIDER = "alpaca"
ALLOWED_PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
MAX_ID_CHARS = 128
MAX_REGIMES = 16
MAX_REGIME_CHARS = 64


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _bounded_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_ID_CHARS:
        raise ValueError(f"{field} is required and bounded")
    return cleaned


def _finite(value: float, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _sha256(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("evidence_sha256 must be a lowercase sha256 digest")
    if value.lower() != value:
        raise ValueError("evidence_sha256 must be a lowercase sha256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("evidence_sha256 must be a lowercase sha256 digest") from exc
    return value


@dataclass(frozen=True)
class PaperLearningPolicy:
    min_validation_trades: int = 50
    min_validation_days: int = 14
    min_market_regimes: int = 2
    max_drawdown_pct: float = 8.0
    max_execution_error_rate: float = 0.02
    min_green_windows_for_funded_ready: int = 3
    min_total_oos_days_for_funded_ready: int = 30
    policy_version: str = PAPER_LEARNING_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != PAPER_LEARNING_POLICY_VERSION:
            raise ValueError("paper learning policy version mismatch")
        if not 1 <= self.min_validation_trades <= 1_000_000:
            raise ValueError("min_validation_trades is invalid")
        if not 1 <= self.min_validation_days <= 3650:
            raise ValueError("min_validation_days is invalid")
        if not 1 <= self.min_market_regimes <= MAX_REGIMES:
            raise ValueError("min_market_regimes is invalid")
        if not 0 < self.max_drawdown_pct <= 100:
            raise ValueError("max_drawdown_pct is invalid")
        if not 0 <= self.max_execution_error_rate <= 1:
            raise ValueError("max_execution_error_rate is invalid")
        if not 1 <= self.min_green_windows_for_funded_ready <= 100:
            raise ValueError("min_green_windows_for_funded_ready is invalid")
        if not 1 <= self.min_total_oos_days_for_funded_ready <= 3650:
            raise ValueError("min_total_oos_days_for_funded_ready is invalid")


@dataclass(frozen=True)
class PaperStrategyWindow:
    strategy_id: str
    strategy_family: str
    strategy_version: str
    provider: str
    endpoint: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    trade_count: int
    net_pnl_eur: float
    modeled_fees_eur: float
    modeled_slippage_eur: float
    max_drawdown_pct: float
    execution_error_count: int
    ambiguous_side_effect_count: int
    market_regimes: tuple[str, ...]
    evidence_sha256: str
    observed_at: str
    proves_received_cash: bool = False
    may_enter_live_execution: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _bounded_text(self.strategy_id, field="strategy_id"))
        object.__setattr__(self, "strategy_family", _bounded_text(self.strategy_family, field="strategy_family"))
        object.__setattr__(self, "strategy_version", _bounded_text(self.strategy_version, field="strategy_version"))
        if self.provider != ALLOWED_PAPER_PROVIDER:
            raise ValueError("paper provider is not allowlisted")
        if self.endpoint != ALLOWED_PAPER_ENDPOINT:
            raise ValueError("only the Alpaca paper endpoint is allowed")
        train_start = _utc(self.train_start)
        train_end = _utc(self.train_end)
        validation_start = _utc(self.validation_start)
        validation_end = _utc(self.validation_end)
        _utc(self.observed_at)
        if not train_start < train_end <= validation_start < validation_end:
            raise ValueError("train and validation windows must be chronological and non-overlapping")
        if not isinstance(self.trade_count, int) or isinstance(self.trade_count, bool) or self.trade_count < 0:
            raise ValueError("trade_count is invalid")
        if not isinstance(self.execution_error_count, int) or isinstance(self.execution_error_count, bool) or self.execution_error_count < 0:
            raise ValueError("execution_error_count is invalid")
        if not isinstance(self.ambiguous_side_effect_count, int) or isinstance(self.ambiguous_side_effect_count, bool) or self.ambiguous_side_effect_count < 0:
            raise ValueError("ambiguous_side_effect_count is invalid")
        for field in ("net_pnl_eur", "modeled_fees_eur", "modeled_slippage_eur", "max_drawdown_pct"):
            value = _finite(getattr(self, field), field=field)
            object.__setattr__(self, field, value)
        if self.modeled_fees_eur < 0 or self.modeled_slippage_eur < 0:
            raise ValueError("modeled costs must be nonnegative")
        if not 0 <= self.max_drawdown_pct <= 100:
            raise ValueError("max_drawdown_pct must be between 0 and 100")
        if not isinstance(self.market_regimes, tuple) or not 1 <= len(self.market_regimes) <= MAX_REGIMES:
            raise ValueError("market_regimes are invalid")
        normalized = []
        for regime in self.market_regimes:
            if not isinstance(regime, str):
                raise ValueError("market_regimes are invalid")
            value = regime.strip().lower()
            if not value or len(value) > MAX_REGIME_CHARS:
                raise ValueError("market_regimes are invalid")
            normalized.append(value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("market_regimes must be unique")
        object.__setattr__(self, "market_regimes", tuple(normalized))
        object.__setattr__(self, "evidence_sha256", _sha256(self.evidence_sha256))
        if self.proves_received_cash:
            raise ValueError("paper trading may never prove received cash")
        if self.may_enter_live_execution:
            raise ValueError("paper evidence may never grant live execution")

    @property
    def validation_days(self) -> int:
        return max(0, (_utc(self.validation_end) - _utc(self.validation_start)).days)

    @property
    def execution_error_rate(self) -> float:
        denominator = max(1, self.trade_count + self.execution_error_count)
        return self.execution_error_count / denominator

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["market_regimes"] = list(self.market_regimes)
        material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PaperLearningDecision:
    strategy_id: str
    strategy_family: str
    strategy_version: str
    state: str
    action: str
    reasons: tuple[str, ...]
    window_fingerprint: str
    may_continue_paper: bool = True
    may_enter_live_execution: bool = False
    proves_received_cash: bool = False
    policy_version: str = PAPER_LEARNING_POLICY_VERSION


@dataclass(frozen=True)
class FundedReadinessDecision:
    state: str
    reasons: tuple[str, ...]
    qualifying_window_fingerprints: tuple[str, ...]
    may_purchase_funded_account: bool = False
    may_request_live_credentials: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = PAPER_LEARNING_POLICY_VERSION


def evaluate_paper_window(window: PaperStrategyWindow, policy: PaperLearningPolicy | None = None) -> PaperLearningDecision:
    policy = policy or PaperLearningPolicy()
    reasons: list[str] = []
    hard_failures: list[str] = []
    if window.ambiguous_side_effect_count:
        hard_failures.append("UNRESOLVED_AMBIGUOUS_SIDE_EFFECTS")
    if window.net_pnl_eur <= 0:
        hard_failures.append("NON_POSITIVE_NET_PAPER_PNL")
    if window.max_drawdown_pct > policy.max_drawdown_pct:
        hard_failures.append("PAPER_DRAWDOWN_TOO_HIGH")
    if window.execution_error_rate > policy.max_execution_error_rate:
        hard_failures.append("EXECUTION_ERROR_RATE_TOO_HIGH")
    if hard_failures:
        return PaperLearningDecision(
            strategy_id=window.strategy_id,
            strategy_family=window.strategy_family,
            strategy_version=window.strategy_version,
            state="PAPER_RED",
            action="PAUSE_OR_REPLACE_STRATEGY",
            reasons=tuple(hard_failures),
            window_fingerprint=window.fingerprint(),
        )
    if window.trade_count < policy.min_validation_trades:
        reasons.append("INSUFFICIENT_OOS_TRADES")
    if window.validation_days < policy.min_validation_days:
        reasons.append("INSUFFICIENT_OOS_DURATION")
    if len(window.market_regimes) < policy.min_market_regimes:
        reasons.append("INSUFFICIENT_MARKET_REGIME_COVERAGE")
    if reasons:
        return PaperLearningDecision(
            strategy_id=window.strategy_id,
            strategy_family=window.strategy_family,
            strategy_version=window.strategy_version,
            state="PAPER_AMBER",
            action="CONTINUE_PAPER_VALIDATION",
            reasons=tuple(reasons),
            window_fingerprint=window.fingerprint(),
        )
    return PaperLearningDecision(
        strategy_id=window.strategy_id,
        strategy_family=window.strategy_family,
        strategy_version=window.strategy_version,
        state="PAPER_GREEN",
        action="KEEP_AS_INCUMBENT_CANDIDATE",
        reasons=("POSITIVE_NET_OOS_AFTER_MODELED_COSTS", "PAPER_ONLY_NOT_LIVE_AUTHORITY"),
        window_fingerprint=window.fingerprint(),
    )


def choose_strategy_action(
    *,
    incumbent: PaperLearningDecision,
    challenger: PaperLearningDecision | None,
) -> str:
    if incumbent.state == "PAPER_GREEN":
        if challenger is not None and challenger.state == "PAPER_GREEN":
            return "KEEP_INCUMBENT_UNTIL_SEPARATE_COMPARATIVE_EVIDENCE"
        return "KEEP_INCUMBENT"
    if challenger is not None and challenger.state == "PAPER_GREEN":
        return "PROMOTE_CHALLENGER_FOR_NEXT_PAPER_WINDOW"
    if incumbent.state == "PAPER_RED":
        return "EXPLORE_DIFFERENT_STRATEGY_FAMILY"
    return "CONTINUE_CURRENT_PAPER_VALIDATION"


def evaluate_funded_readiness(
    windows: Iterable[PaperStrategyWindow],
    policy: PaperLearningPolicy | None = None,
) -> FundedReadinessDecision:
    policy = policy or PaperLearningPolicy()
    ordered = sorted(windows, key=lambda w: _utc(w.validation_start))
    if not ordered:
        return FundedReadinessDecision("PAPER_RED", ("NO_PAPER_EVIDENCE",), ())
    decisions = [evaluate_paper_window(window, policy) for window in ordered]
    green = [(window, decision) for window, decision in zip(ordered, decisions) if decision.state == "PAPER_GREEN"]
    if len(green) < policy.min_green_windows_for_funded_ready:
        state = "PAPER_AMBER" if green else "PAPER_RED"
        return FundedReadinessDecision(state, ("INSUFFICIENT_SUSTAINED_GREEN_WINDOWS",), tuple(d.window_fingerprint for _, d in green))
    selected = green[-policy.min_green_windows_for_funded_ready:]
    strategy_ids = {window.strategy_id for window, _ in selected}
    if len(strategy_ids) != 1:
        return FundedReadinessDecision("PAPER_AMBER", ("GREEN_WINDOWS_NOT_FROM_ONE_STABLE_STRATEGY",), tuple(d.window_fingerprint for _, d in selected))
    for previous, current in zip(selected, selected[1:]):
        if _utc(previous[0].validation_end) > _utc(current[0].validation_start):
            return FundedReadinessDecision("PAPER_AMBER", ("QUALIFYING_OOS_WINDOWS_OVERLAP",), tuple(d.window_fingerprint for _, d in selected))
    total_days = sum(window.validation_days for window, _ in selected)
    if total_days < policy.min_total_oos_days_for_funded_ready:
        return FundedReadinessDecision("PAPER_AMBER", ("INSUFFICIENT_TOTAL_OOS_DURATION",), tuple(d.window_fingerprint for _, d in selected))
    regimes = set().union(*(set(window.market_regimes) for window, _ in selected))
    if len(regimes) < policy.min_market_regimes:
        return FundedReadinessDecision("PAPER_AMBER", ("INSUFFICIENT_SUSTAINED_REGIME_COVERAGE",), tuple(d.window_fingerprint for _, d in selected))
    return FundedReadinessDecision(
        "FUNDED_READY",
        ("SUSTAINED_NON_OVERLAPPING_OOS_PAPER_EVIDENCE", "OWNER_DECISION_REQUIRED_BEFORE_ANY_FUNDED_PURCHASE"),
        tuple(d.window_fingerprint for _, d in selected),
    )
