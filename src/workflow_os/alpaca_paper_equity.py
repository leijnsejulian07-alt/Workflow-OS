from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .alpaca_paper_evidence import _policy_fingerprint
from .alpaca_paper_position_accounting import ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION
from .alpaca_paper_position_evidence import ALPACA_PAPER_POSITION_EVIDENCE_POLICY_VERSION
from .alpaca_paper_runtime import AlpacaPaperStrategyPolicy
from .audit import AuditRevenueLedger

ALPACA_PAPER_EQUITY_POLICY_VERSION = "alpaca-paper-equity/1"
_POSITION_EVENT_TYPE = "trading.alpaca_paper_closed_position"


@dataclass(frozen=True)
class AlpacaPaperEquityPoint:
    occurred_at: str
    symbol: str
    opening_client_order_id: str
    closing_client_order_id: str
    paper_realized_pnl_usd: Decimal
    cumulative_pnl_usd: Decimal
    equity_usd: Decimal
    drawdown_pct: Decimal


@dataclass(frozen=True)
class AlpacaPaperEquityCurve:
    strategy_id: str
    strategy_policy_fingerprint: str
    starting_equity_usd: Decimal
    ending_equity_usd: Decimal
    net_paper_pnl_usd: Decimal
    modeled_execution_costs_usd: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    points: tuple[AlpacaPaperEquityPoint, ...]
    proves_received_cash: bool = False
    proves_realized_cash_pnl: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_EQUITY_POLICY_VERSION


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a positive decimal") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a positive finite decimal")
    return number


def _finite_decimal(value: object, *, field: str, nonnegative: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not number.is_finite() or (nonnegative and number < 0):
        raise ValueError(f"{field} must be a finite decimal")
    return number


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("position evidence timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("position evidence timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("position evidence timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _read_position_events(audit_ledger: AuditRevenueLedger, *, strategy_id: str) -> list[sqlite3.Row]:
    if not audit_ledger.verify_audit_chain():
        raise ValueError("audit chain verification failed")
    db = sqlite3.connect(audit_ledger.path, timeout=5.0)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(
            """
            SELECT occurred_at, event_json
            FROM audit_events
            WHERE event_type=? AND subject_id=?
            ORDER BY occurred_at ASC, id ASC
            """,
            (_POSITION_EVENT_TYPE, strategy_id),
        ).fetchall()
    finally:
        db.close()


def build_alpaca_paper_equity_curve(
    *,
    audit_ledger: AuditRevenueLedger,
    strategy_policy: AlpacaPaperStrategyPolicy,
    starting_equity_usd: object,
) -> AlpacaPaperEquityCurve:
    """Build a paper-only realized-equity curve from immutable closed-position evidence.

    Repeated observations of the exact same closed position are deduplicated. If the
    same opening/closing order pair ever appears with different accounting content,
    aggregation fails closed instead of silently double-counting or rewriting P&L.
    """
    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    if not isinstance(strategy_policy, AlpacaPaperStrategyPolicy):
        raise TypeError("strategy_policy must be AlpacaPaperStrategyPolicy")
    starting_equity = _positive_decimal(starting_equity_usd, field="starting_equity_usd")
    strategy_fingerprint = _policy_fingerprint(strategy_policy)
    rows = _read_position_events(audit_ledger, strategy_id=strategy_policy.strategy_id)

    unique_positions: dict[tuple[str, str], tuple[datetime, dict[str, object]]] = {}
    for row in rows:
        occurred = _utc(str(row["occurred_at"]))
        try:
            payload = json.loads(str(row["event_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("closed-position evidence JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("closed-position evidence payload is invalid")
        if payload.get("provider") != "alpaca" or payload.get("mode") != "PAPER_ONLY":
            raise ValueError("closed-position evidence provider or mode mismatch")
        if payload.get("strategy_id") != strategy_policy.strategy_id:
            raise ValueError("closed-position evidence strategy mismatch")
        if payload.get("strategy_policy_fingerprint") != strategy_fingerprint:
            raise ValueError("closed-position evidence strategy policy mismatch")
        if payload.get("position_accounting_policy_version") != ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION:
            raise ValueError("closed-position accounting policy mismatch")
        if payload.get("position_evidence_policy_version") != ALPACA_PAPER_POSITION_EVIDENCE_POLICY_VERSION:
            raise ValueError("closed-position evidence policy mismatch")
        if payload.get("proves_received_cash") is not False:
            raise ValueError("paper position evidence may not prove received cash")
        if payload.get("proves_realized_cash_pnl") is not False:
            raise ValueError("paper position evidence may not prove realized cash pnl")
        if payload.get("may_enter_live_execution") is not False:
            raise ValueError("paper position evidence may not grant live execution")

        position = payload.get("position")
        if not isinstance(position, dict):
            raise ValueError("closed-position evidence position is invalid")
        symbol = position.get("symbol")
        opening_id = position.get("opening_client_order_id")
        closing_id = position.get("closing_client_order_id")
        if not isinstance(symbol, str) or not symbol.strip() or symbol != symbol.strip().upper():
            raise ValueError("closed-position symbol provenance is invalid")
        if not isinstance(opening_id, str) or not opening_id.strip():
            raise ValueError("opening client order id is required")
        if not isinstance(closing_id, str) or not closing_id.strip() or closing_id == opening_id:
            raise ValueError("closing client order id is invalid")

        pnl = _finite_decimal(position.get("paper_realized_pnl_usd"), field="paper_realized_pnl_usd")
        costs = _finite_decimal(
            position.get("modeled_total_execution_cost_usd"),
            field="modeled_total_execution_cost_usd",
            nonnegative=True,
        )
        gross = _finite_decimal(position.get("gross_reference_pnl_usd"), field="gross_reference_pnl_usd")
        if pnl != gross - costs:
            raise ValueError("closed-position evidence pnl is internally inconsistent")

        canonical = {
            "symbol": symbol,
            "opening_client_order_id": opening_id,
            "closing_client_order_id": closing_id,
            "paper_realized_pnl_usd": str(pnl),
            "modeled_total_execution_cost_usd": str(costs),
            "gross_reference_pnl_usd": str(gross),
        }
        key = (opening_id, closing_id)
        existing = unique_positions.get(key)
        if existing is not None:
            if existing[1] != canonical:
                raise ValueError("closed position was observed with conflicting accounting evidence")
            continue
        unique_positions[key] = (occurred, canonical)

    ordered = sorted(unique_positions.values(), key=lambda item: item[0])
    cumulative_pnl = Decimal("0")
    peak_equity = starting_equity
    max_drawdown = Decimal("0")
    total_costs = Decimal("0")
    points: list[AlpacaPaperEquityPoint] = []
    previous_time: datetime | None = None
    for occurred, position in ordered:
        if previous_time is not None and occurred <= previous_time:
            raise ValueError("unique closed positions require strictly increasing evidence timestamps")
        previous_time = occurred
        pnl = Decimal(str(position["paper_realized_pnl_usd"]))
        costs = Decimal(str(position["modeled_total_execution_cost_usd"]))
        cumulative_pnl += pnl
        total_costs += costs
        equity = starting_equity + cumulative_pnl
        if equity > peak_equity:
            peak_equity = equity
        if equity <= 0:
            drawdown = Decimal("100")
        else:
            drawdown = (peak_equity - equity) / peak_equity * Decimal("100")
        if drawdown > max_drawdown:
            max_drawdown = drawdown
        points.append(
            AlpacaPaperEquityPoint(
                occurred_at=occurred.isoformat(),
                symbol=str(position["symbol"]),
                opening_client_order_id=str(position["opening_client_order_id"]),
                closing_client_order_id=str(position["closing_client_order_id"]),
                paper_realized_pnl_usd=pnl,
                cumulative_pnl_usd=cumulative_pnl,
                equity_usd=equity,
                drawdown_pct=drawdown,
            )
        )

    return AlpacaPaperEquityCurve(
        strategy_id=strategy_policy.strategy_id,
        strategy_policy_fingerprint=strategy_fingerprint,
        starting_equity_usd=starting_equity,
        ending_equity_usd=starting_equity + cumulative_pnl,
        net_paper_pnl_usd=cumulative_pnl,
        modeled_execution_costs_usd=total_costs,
        max_drawdown_pct=max_drawdown,
        trade_count=len(points),
        points=tuple(points),
    )
