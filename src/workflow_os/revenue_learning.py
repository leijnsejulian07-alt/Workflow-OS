from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .opportunities import OpportunityDecision

LEARNING_POLICY_VERSION = "revenue-learning/1"
MAX_REALIZED_CASH_BONUS = 20.0
REALIZED_CASH_HALF_SATURATION_EUR = 100.0


@dataclass(frozen=True)
class RevenueLearningSignal:
    opportunity_id: str
    base_priority_score: float
    realized_cash_eur: float
    realized_cash_bonus: float
    learned_priority_score: float
    evidence_state: str
    policy_version: str = LEARNING_POLICY_VERSION


def _cash_bonus(realized_cash_eur: float) -> float:
    """Return a bounded evidence bonus from reconciled cash only.

    The saturating curve prevents a single large payout from overwhelming the
    existing opportunity score. Cash can improve ordering among already-safe
    opportunities, but it can never make a rejected/paused/revalidate decision
    executable.
    """

    if realized_cash_eur <= 0:
        return 0.0
    ratio = realized_cash_eur / (realized_cash_eur + REALIZED_CASH_HALF_SATURATION_EUR)
    return round(MAX_REALIZED_CASH_BONUS * ratio, 6)


def learning_signal(decision: OpportunityDecision, ledger: AuditRevenueLedger) -> RevenueLearningSignal:
    """Combine forecast priority with proven cash for an accepted opportunity.

    Fail closed: only an Opportunity Manager ACCEPT decision may receive a
    learned execution score. This function never weakens rights, risk,
    freshness, payment, owner-attention, or economic admission gates.
    """

    if decision.decision != "ACCEPT" or not decision.eligible_for_queue:
        raise ValueError("only ACCEPT queue-eligible opportunities may be ranked for execution")
    if decision.priority_score < 0:
        raise ValueError("priority_score must be non-negative")

    realized = ledger.realized_cash_eur(decision.opportunity_id)
    if realized < 0:
        raise ValueError("realized cash cannot be negative")
    bonus = _cash_bonus(realized)
    learned = round(decision.priority_score + bonus, 6)
    evidence_state = "RECONCILED_CASH" if realized > 0 else "FORECAST_ONLY"
    return RevenueLearningSignal(
        opportunity_id=decision.opportunity_id,
        base_priority_score=decision.priority_score,
        realized_cash_eur=realized,
        realized_cash_bonus=bonus,
        learned_priority_score=learned,
        evidence_state=evidence_state,
    )


def rank_accepted(decisions: list[OpportunityDecision], ledger: AuditRevenueLedger) -> list[RevenueLearningSignal]:
    """Rank only accepted opportunities by learned score, highest first."""

    signals = [learning_signal(decision, ledger) for decision in decisions]
    return sorted(
        signals,
        key=lambda signal: (
            signal.learned_priority_score,
            signal.realized_cash_eur,
            signal.opportunity_id,
        ),
        reverse=True,
    )
