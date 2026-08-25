from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .trading_provider_rules import ProviderRuleEvidence, assess_provider_readiness

PROVIDER_SELECTION_POLICY_VERSION = "trading-provider-selection/1"
SELECTION_STAGES = {"FIRST_ACCOUNT", "REINVEST"}


def _finite_nonnegative(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and nonnegative") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


@dataclass(frozen=True)
class ProviderPurchaseCandidate:
    provider: str
    program: str
    purchase_cost: float
    account_currency: str
    account_size: float
    max_drawdown: float
    payout_share_pct: float
    usable_drawdown_per_cost: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderSelectionDecision:
    decision: str
    reason: str
    stage: str
    reconciled_cash_available: float
    owner_approval_required: bool
    selected: ProviderPurchaseCandidate | None
    eligible_candidates: tuple[ProviderPurchaseCandidate, ...]
    policy_version: str = PROVIDER_SELECTION_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["selected"] = self.selected.to_dict() if self.selected is not None else None
        data["eligible_candidates"] = [candidate.to_dict() for candidate in self.eligible_candidates]
        return data


def _candidate(evidence: ProviderRuleEvidence) -> ProviderPurchaseCandidate:
    payout_weight = evidence.payout_share_pct / 100.0
    effective_drawdown = evidence.max_drawdown * payout_weight
    denominator = evidence.purchase_cost if evidence.purchase_cost > 0 else 1.0
    return ProviderPurchaseCandidate(
        provider=evidence.provider,
        program=evidence.program,
        purchase_cost=evidence.purchase_cost,
        account_currency=evidence.account_currency,
        account_size=evidence.account_size,
        max_drawdown=evidence.max_drawdown,
        payout_share_pct=evidence.payout_share_pct,
        usable_drawdown_per_cost=effective_drawdown / denominator,
    )


def select_provider_purchase(
    provider_evidence: Iterable[ProviderRuleEvidence],
    *,
    reconciled_cash_available: float,
    stage: str,
    written_automation_approval_verified: bool = False,
) -> ProviderSelectionDecision:
    """Rank a funded-account purchase without spending money or authorizing trading.

    Only reconciled cash may fund a reinvestment decision. Simulation/backtest P&L must
    never be passed here as available cash. Provider profiles must already pass their
    fail-closed live-preparation rule gate; a HOLD profile is not purchase-eligible.
    """
    if stage not in SELECTION_STAGES:
        raise ValueError("stage is invalid")
    available = _finite_nonnegative(reconciled_cash_available, name="reconciled_cash_available")

    eligible: list[ProviderPurchaseCandidate] = []
    seen: set[tuple[str, str]] = set()
    for evidence in provider_evidence:
        identity = (evidence.provider.casefold(), evidence.program.casefold())
        if identity in seen:
            raise ValueError("provider/program candidates must be unique")
        seen.add(identity)

        readiness = assess_provider_readiness(
            evidence,
            written_automation_approval_verified=written_automation_approval_verified,
        )
        if readiness.decision != "PREPARE_ONLY":
            continue
        if evidence.purchase_cost > available:
            continue
        eligible.append(_candidate(evidence))

    if not eligible:
        return ProviderSelectionDecision(
            decision="HOLD",
            reason="NO_EVIDENCE_VERIFIED_PROVIDER_WITHIN_RECONCILED_CASH_BUDGET",
            stage=stage,
            reconciled_cash_available=available,
            owner_approval_required=True,
            selected=None,
            eligible_candidates=(),
        )

    if stage == "FIRST_ACCOUNT":
        eligible.sort(
            key=lambda item: (
                item.purchase_cost,
                -item.usable_drawdown_per_cost,
                item.provider.casefold(),
                item.program.casefold(),
            )
        )
        reason = "CHEAPEST_EVIDENCE_VERIFIED_PROVIDER_WITHIN_RECONCILED_CASH_BUDGET"
    else:
        eligible.sort(
            key=lambda item: (
                -item.usable_drawdown_per_cost,
                item.purchase_cost,
                item.provider.casefold(),
                item.program.casefold(),
            )
        )
        reason = "BEST_EVIDENCE_VERIFIED_USABLE_DRAWDOWN_PER_COST_WITHIN_RECONCILED_CASH_BUDGET"

    return ProviderSelectionDecision(
        decision="OWNER_APPROVAL_REQUIRED",
        reason=reason,
        stage=stage,
        reconciled_cash_available=available,
        owner_approval_required=True,
        selected=eligible[0],
        eligible_candidates=tuple(eligible),
    )
