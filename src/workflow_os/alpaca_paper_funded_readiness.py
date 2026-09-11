from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .alpaca_paper_equity import AlpacaPaperEquityCurve
from .alpaca_paper_fill_provenance import (
    AlpacaPaperClosedPositionFillProvenance,
    verify_alpaca_paper_curve_fill_provenance,
)
from .alpaca_paper_learning_adapter import (
    AlpacaPaperLearningContext,
    evaluate_alpaca_paper_equity_curve,
)
from .alpaca_paper_runtime import AlpacaPaperStrategyPolicy
from .audit import AuditRevenueLedger
from .trading_paper_learning import FundedReadinessDecision, PaperLearningPolicy

ALPACA_PAPER_FUNDED_READINESS_POLICY_VERSION = "alpaca-paper-funded-readiness/3"


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


@dataclass(frozen=True, init=False)
class AlpacaPaperValidationWindow:
    audit_ledger: AuditRevenueLedger
    strategy_policy: AlpacaPaperStrategyPolicy
    curve: AlpacaPaperEquityCurve
    context: AlpacaPaperLearningContext
    train_start: str
    train_end: str
    fill_provenance: tuple[AlpacaPaperClosedPositionFillProvenance, ...]
    policy_version: str = ALPACA_PAPER_FUNDED_READINESS_POLICY_VERSION

    @classmethod
    def _from_verified_provenance(
        cls,
        *,
        audit_ledger: AuditRevenueLedger,
        strategy_policy: AlpacaPaperStrategyPolicy,
        curve: AlpacaPaperEquityCurve,
        context: AlpacaPaperLearningContext,
        train_start: str,
        train_end: str,
        fill_provenance: tuple[AlpacaPaperClosedPositionFillProvenance, ...],
    ) -> AlpacaPaperValidationWindow:
        if not isinstance(audit_ledger, AuditRevenueLedger):
            raise TypeError("audit_ledger must be AuditRevenueLedger")
        if not isinstance(strategy_policy, AlpacaPaperStrategyPolicy):
            raise TypeError("strategy_policy must be AlpacaPaperStrategyPolicy")
        if not isinstance(curve, AlpacaPaperEquityCurve):
            raise TypeError("curve must be AlpacaPaperEquityCurve")
        if not isinstance(context, AlpacaPaperLearningContext):
            raise TypeError("context must be AlpacaPaperLearningContext")
        if not isinstance(fill_provenance, tuple):
            raise TypeError("fill_provenance must be a tuple")
        train_start_utc = _utc(train_start, field="train_start")
        train_end_utc = _utc(train_end, field="train_end")
        validation_start = _utc(context.validation_start, field="validation_start")
        validation_end = _utc(context.validation_end, field="validation_end")
        if not train_start_utc < train_end_utc <= validation_start < validation_end:
            raise ValueError("train and validation windows must be chronological and non-overlapping")
        if len(fill_provenance) != len(curve.points):
            raise ValueError("fill provenance must map exactly once to every equity point")

        expected_pairs = tuple(
            (point.opening_client_order_id, point.closing_client_order_id)
            for point in curve.points
        )
        actual_pairs: list[tuple[str, str]] = []
        for provenance in fill_provenance:
            if not isinstance(provenance, AlpacaPaperClosedPositionFillProvenance):
                raise TypeError("fill_provenance contains an invalid value")
            actual_pairs.append(
                (provenance.opening_client_order_id, provenance.closing_client_order_id)
            )
            opening = _utc(provenance.opening_filled_at, field="opening_filled_at")
            closing = _utc(provenance.closing_filled_at, field="closing_filled_at")
            if not validation_start <= opening < closing < validation_end:
                raise ValueError("paper position fills fall outside its validation window")
        if tuple(actual_pairs) != expected_pairs:
            raise ValueError("fill provenance order pairs do not match the paper equity curve")

        instance = object.__new__(cls)
        object.__setattr__(instance, "audit_ledger", audit_ledger)
        object.__setattr__(instance, "strategy_policy", strategy_policy)
        object.__setattr__(instance, "curve", curve)
        object.__setattr__(instance, "context", context)
        object.__setattr__(instance, "train_start", train_start)
        object.__setattr__(instance, "train_end", train_end)
        object.__setattr__(instance, "fill_provenance", fill_provenance)
        object.__setattr__(instance, "policy_version", ALPACA_PAPER_FUNDED_READINESS_POLICY_VERSION)
        return instance

    @property
    def validation_start_utc(self) -> datetime:
        return _utc(self.context.validation_start, field="validation_start")

    @property
    def validation_end_utc(self) -> datetime:
        return _utc(self.context.validation_end, field="validation_end")

    @property
    def validation_days(self) -> int:
        return max(0, (self.validation_end_utc - self.validation_start_utc).days)


def build_alpaca_paper_validation_window(
    *,
    audit_ledger: AuditRevenueLedger,
    strategy_policy: AlpacaPaperStrategyPolicy,
    curve: AlpacaPaperEquityCurve,
    context: AlpacaPaperLearningContext,
    train_start: str,
    train_end: str,
) -> AlpacaPaperValidationWindow:
    """Build an OOS window only from immutable paper execution provenance."""
    provenance = verify_alpaca_paper_curve_fill_provenance(
        audit_ledger=audit_ledger,
        strategy_policy=strategy_policy,
        curve=curve,
    )
    return AlpacaPaperValidationWindow._from_verified_provenance(
        audit_ledger=audit_ledger,
        strategy_policy=strategy_policy,
        curve=curve,
        context=context,
        train_start=train_start,
        train_end=train_end,
        fill_provenance=provenance,
    )


def _reverify_window_provenance(window: AlpacaPaperValidationWindow) -> None:
    """Re-bind a stored window to its immutable ledger before any readiness decision.

    Python callers can technically reach underscore-prefixed helpers or manufacture
    objects in-process. Readiness therefore never trusts the stored provenance tuple
    as authority: it is recomputed from the attached immutable audit ledger and exact
    strategy policy on every evaluation.
    """
    provenance = verify_alpaca_paper_curve_fill_provenance(
        audit_ledger=window.audit_ledger,
        strategy_policy=window.strategy_policy,
        curve=window.curve,
    )
    if provenance != window.fill_provenance:
        raise ValueError("validation window provenance does not match immutable ledger evidence")


def evaluate_alpaca_funded_readiness(
    windows: tuple[AlpacaPaperValidationWindow, ...],
    policy: PaperLearningPolicy | None = None,
) -> FundedReadinessDecision:
    """Evaluate sustained execution-derived Alpaca paper evidence only.

    This function never purchases a funded account, requests live credentials, or
    grants live execution authority. Every window is reverified against immutable
    ledger evidence before evaluation, so caller-forged stored provenance cannot
    qualify for PAPER_GREEN or FUNDED_READY.
    """
    if not isinstance(windows, tuple):
        raise TypeError("windows must be a tuple")
    policy = policy or PaperLearningPolicy()
    if not windows:
        return FundedReadinessDecision("PAPER_RED", ("NO_PAPER_EVIDENCE",), ())
    if any(not isinstance(window, AlpacaPaperValidationWindow) for window in windows):
        raise TypeError("windows must contain AlpacaPaperValidationWindow values")

    for window in windows:
        _reverify_window_provenance(window)

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
