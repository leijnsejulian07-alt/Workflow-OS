from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .alpaca_paper_equity import AlpacaPaperEquityCurve
from .alpaca_paper_learning_adapter import (
    AlpacaPaperLearningContext,
    evaluate_alpaca_paper_equity_curve,
)
from .trading_paper_learning import FundedReadinessDecision, PaperLearningPolicy

ALPACA_PAPER_FUNDED_READINESS_POLICY_VERSION = "alpaca-paper-funded-readiness/1"


def _utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AlpacaPaperValidationWindow:
    curve: AlpacaPaperEquityCurve
    context: AlpacaPaperLearningContext
    train_start: str
    train_end: str
    policy_version: str = ALPACA_PAPER_FUNDED_READINESS_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != ALPACA_PAPER_FUNDED_READINESS_POLICY_VERSION:
            raise ValueError("alpaca paper funded readiness policy version mismatch")
        if not isinstance(self.curve, AlpacaPaperEquityCurve):
            raise TypeError("curve must be AlpacaPaperEquityCurve")
        if not isinstance(self.context, AlpacaPaperLearningContext):
            raise TypeError("context must be AlpacaPaperLearningContext")
        train_start = _utc(self.train_start, field="train_start")
        train_end = _utc(self.train_end, field="train_end")
        validation_start = _utc(self.context.validation_start, field="validation_start")
        validation_end = _utc(self.context.validation_end, field="validation_end")
        if not train_start < train_end <= validation_start < validation_end:
            raise ValueError("train and validation windows must be chronological and non-overlapping")
        for point in self.curve.points:
            occurred = _utc(point.occurred_at, field="equity_point.occurred_at")
            if occurred < validation_start or occurred >= validation_end:
                raise ValueError("paper equity point falls outside its validation window")

    @property
    def validation_start_utc(self) -> datetime:
        return _utc(self.context.validation_start, field="validation_start")

    @property
    def validation_end_utc(self) -> datetime:
        return _utc(self.context.validation_end, field="validation_end")

    @property
    def validation_days(self) -> int:
        return max(0, (self.validation_end_utc - self.validation_start_utc).days)


def evaluate_alpaca_funded_readiness(
    windows: tuple[AlpacaPaperValidationWindow, ...],
    policy: PaperLearningPolicy | None = None,
) -> FundedReadinessDecision:
    """Evaluate sustained execution-derived Alpaca paper evidence only.

    This function never purchases a funded account, requests live credentials, or
    grants live execution authority. It only emits evidence-only readiness state.
    All qualifying windows must use one exact strategy-policy fingerprint and must
    be strictly chronological, non-overlapping out-of-sample validation windows.
    """
    if not isinstance(windows, tuple):
        raise TypeError("windows must be a tuple")
    policy = policy or PaperLearningPolicy()
    if not windows:
        return FundedReadinessDecision("PAPER_RED", ("NO_PAPER_EVIDENCE",), ())
    if any(not isinstance(window, AlpacaPaperValidationWindow) for window in windows):
        raise TypeError("windows must contain AlpacaPaperValidationWindow values")

    ordered = tuple(sorted(windows, key=lambda item: item.validation_start_utc))
    first_curve = ordered[0].curve
    stable_strategy_id = first_curve.strategy_id
    stable_policy_fingerprint = first_curve.strategy_policy_fingerprint
    stable_strategy_version = ordered[0].context.strategy_version

    for previous, current in zip(ordered, ordered[1:]):
        if previous.validation_end_utc > current.validation_start_utc:
            return FundedReadinessDecision(
                "PAPER_AMBER",
                ("QUALIFYING_OOS_WINDOWS_OVERLAP",),
                (),
            )

    for window in ordered:
        if window.curve.strategy_id != stable_strategy_id:
            return FundedReadinessDecision(
                "PAPER_AMBER",
                ("GREEN_WINDOWS_NOT_FROM_ONE_STABLE_STRATEGY",),
                (),
            )
        if window.curve.strategy_policy_fingerprint != stable_policy_fingerprint:
            return FundedReadinessDecision(
                "PAPER_AMBER",
                ("GREEN_WINDOWS_NOT_FROM_ONE_EXACT_STRATEGY_POLICY",),
                (),
            )
        if window.context.strategy_version != stable_strategy_version:
            return FundedReadinessDecision(
                "PAPER_AMBER",
                ("GREEN_WINDOWS_NOT_FROM_ONE_STABLE_STRATEGY_VERSION",),
                (),
            )

    decisions = tuple(
        evaluate_alpaca_paper_equity_curve(
            curve=window.curve,
            context=window.context,
            policy=policy,
        )
        for window in ordered
    )
    red = tuple(decision for decision in decisions if decision.state == "PAPER_RED")
    if red:
        reasons = tuple(dict.fromkeys(reason for decision in red for reason in decision.reasons))
        return FundedReadinessDecision("PAPER_RED", reasons, ())

    green_pairs = tuple(
        (window, decision)
        for window, decision in zip(ordered, decisions)
        if decision.state == "PAPER_GREEN"
    )
    green_fingerprints = tuple(decision.window_fingerprint for _, decision in green_pairs)
    if len(green_pairs) < policy.min_green_windows_for_funded_ready:
        state = "PAPER_AMBER" if green_pairs else "PAPER_RED"
        return FundedReadinessDecision(
            state,
            ("INSUFFICIENT_SUSTAINED_GREEN_WINDOWS",),
            green_fingerprints,
        )

    selected = green_pairs[-policy.min_green_windows_for_funded_ready :]
    total_days = sum(window.validation_days for window, _ in selected)
    selected_fingerprints = tuple(decision.window_fingerprint for _, decision in selected)
    if total_days < policy.min_total_oos_days_for_funded_ready:
        return FundedReadinessDecision(
            "PAPER_AMBER",
            ("INSUFFICIENT_TOTAL_OOS_DURATION",),
            selected_fingerprints,
        )

    regimes = set().union(*(set(window.context.market_regimes) for window, _ in selected))
    if len(regimes) < policy.min_market_regimes:
        return FundedReadinessDecision(
            "PAPER_AMBER",
            ("INSUFFICIENT_SUSTAINED_REGIME_COVERAGE",),
            selected_fingerprints,
        )

    return FundedReadinessDecision(
        "FUNDED_READY",
        (
            "SUSTAINED_NON_OVERLAPPING_EXECUTION_DERIVED_OOS_PAPER_EVIDENCE",
            "OWNER_DECISION_REQUIRED_BEFORE_ANY_FUNDED_PURCHASE",
        ),
        selected_fingerprints,
        may_purchase_funded_account=False,
        may_request_live_credentials=False,
        may_enter_live_execution=False,
    )
