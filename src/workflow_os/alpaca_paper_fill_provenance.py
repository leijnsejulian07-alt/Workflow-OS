from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .alpaca_paper_equity import AlpacaPaperEquityCurve
from .alpaca_paper_evidence import _policy_fingerprint
from .alpaca_paper_runtime import AlpacaPaperStrategyPolicy
from .audit import AuditRevenueLedger

ALPACA_PAPER_FILL_PROVENANCE_POLICY_VERSION = "alpaca-paper-fill-provenance/1"
_OUTCOME_EVENT_TYPE = "trading.alpaca_paper_order_outcome"
_POSITION_EVENT_TYPE = "trading.alpaca_paper_closed_position"


@dataclass(frozen=True)
class AlpacaPaperClosedPositionFillProvenance:
    symbol: str
    opening_client_order_id: str
    closing_client_order_id: str
    opening_filled_at: str
    closing_filled_at: str
    policy_version: str = ALPACA_PAPER_FILL_PROVENANCE_POLICY_VERSION


def _utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a canonical ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00") if value.endswith("Z") else datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a positive decimal") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a positive finite decimal")
    return number


def _read_events(audit_ledger: AuditRevenueLedger, *, strategy_id: str) -> list[sqlite3.Row]:
    if not audit_ledger.verify_audit_chain():
        raise ValueError("audit chain verification failed")
    db = sqlite3.connect(audit_ledger.path, timeout=5.0)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(
            """
            SELECT event_type, occurred_at, event_json
            FROM audit_events
            WHERE event_type IN (?, ?) AND subject_id=?
            ORDER BY occurred_at ASC, id ASC
            """,
            (_OUTCOME_EVENT_TYPE, _POSITION_EVENT_TYPE, strategy_id),
        ).fetchall()
    finally:
        db.close()


def verify_alpaca_paper_curve_fill_provenance(
    *,
    audit_ledger: AuditRevenueLedger,
    strategy_policy: AlpacaPaperStrategyPolicy,
    curve: AlpacaPaperEquityCurve,
) -> tuple[AlpacaPaperClosedPositionFillProvenance, ...]:
    """Bind closed-position equity points to immutable Alpaca fill timestamps.

    Evidence observation timestamps are intentionally ignored for trade chronology.
    Each equity point must bind to one immutable closed-position record and exact
    opening/closing order-outcome fills matching symbol, side, quantity and price.
    Missing or conflicting fill provenance fails closed.
    """
    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    if not isinstance(strategy_policy, AlpacaPaperStrategyPolicy):
        raise TypeError("strategy_policy must be AlpacaPaperStrategyPolicy")
    if not isinstance(curve, AlpacaPaperEquityCurve):
        raise TypeError("curve must be AlpacaPaperEquityCurve")

    expected_fingerprint = _policy_fingerprint(strategy_policy)
    if curve.strategy_id != strategy_policy.strategy_id:
        raise ValueError("paper equity strategy mismatch")
    if curve.strategy_policy_fingerprint != expected_fingerprint:
        raise ValueError("paper equity strategy-policy fingerprint mismatch")

    outcomes: dict[tuple[str, str], list[dict[str, object]]] = {}
    positions: dict[tuple[str, str], dict[str, object]] = {}
    for row in _read_events(audit_ledger, strategy_id=strategy_policy.strategy_id):
        try:
            payload = json.loads(str(row["event_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Alpaca paper evidence JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("Alpaca paper evidence payload is invalid")
        if payload.get("provider") != "alpaca" or payload.get("mode") != "PAPER_ONLY":
            raise ValueError("Alpaca paper evidence provider or mode mismatch")
        if payload.get("strategy_id") != strategy_policy.strategy_id:
            raise ValueError("Alpaca paper evidence strategy mismatch")
        if payload.get("strategy_policy_fingerprint") != expected_fingerprint:
            continue
        if payload.get("proves_received_cash") is not False:
            raise ValueError("Alpaca paper evidence may not prove received cash")
        if payload.get("may_enter_live_execution") is not False:
            raise ValueError("Alpaca paper evidence may not grant live execution")

        if row["event_type"] == _OUTCOME_EVENT_TYPE:
            order = payload.get("order")
            if not isinstance(order, dict):
                raise ValueError("paper outcome evidence order is invalid")
            client_order_id = order.get("client_order_id")
            side = order.get("side")
            if not isinstance(client_order_id, str) or not client_order_id.strip():
                raise ValueError("paper outcome client order id is invalid")
            if side not in {"buy", "sell"}:
                raise ValueError("paper outcome side is invalid")
            if order.get("has_fill") is True:
                outcomes.setdefault((client_order_id, side), []).append(order)
            continue

        position = payload.get("position")
        if not isinstance(position, dict):
            raise ValueError("closed-position evidence position is invalid")
        opening_id = position.get("opening_client_order_id")
        closing_id = position.get("closing_client_order_id")
        if not isinstance(opening_id, str) or not opening_id.strip():
            raise ValueError("closed-position opening order id is invalid")
        if not isinstance(closing_id, str) or not closing_id.strip() or closing_id == opening_id:
            raise ValueError("closed-position closing order id is invalid")
        key = (opening_id, closing_id)
        canonical = {
            "symbol": position.get("symbol"),
            "closed_qty": str(_positive_decimal(position.get("closed_qty"), field="closed_qty")),
            "opening_fill_price": str(
                _positive_decimal(position.get("opening_fill_price"), field="opening_fill_price")
            ),
            "closing_fill_price": str(
                _positive_decimal(position.get("closing_fill_price"), field="closing_fill_price")
            ),
        }
        existing = positions.get(key)
        if existing is not None and existing != canonical:
            raise ValueError("closed position has conflicting immutable execution provenance")
        positions[key] = canonical

    proven: list[AlpacaPaperClosedPositionFillProvenance] = []
    for point in curve.points:
        key = (point.opening_client_order_id, point.closing_client_order_id)
        position = positions.get(key)
        if position is None:
            raise ValueError("paper equity point lacks immutable closed-position evidence")
        if position.get("symbol") != point.symbol:
            raise ValueError("paper equity symbol does not match closed-position evidence")
        expected_qty = _positive_decimal(position["closed_qty"], field="closed_qty")
        expected_open_price = _positive_decimal(position["opening_fill_price"], field="opening_fill_price")
        expected_close_price = _positive_decimal(position["closing_fill_price"], field="closing_fill_price")

        def resolve(
            candidates: list[dict[str, object]],
            *,
            side: str,
            expected_price: Decimal,
        ) -> datetime:
            matching_times: set[datetime] = set()
            for order in candidates:
                if order.get("symbol") != point.symbol:
                    continue
                filled_at = order.get("filled_at")
                if filled_at is None:
                    continue
                qty = _positive_decimal(order.get("filled_qty"), field="filled_qty")
                fill_price = _positive_decimal(order.get("filled_avg_price"), field="filled_avg_price")
                filled_notional = _positive_decimal(order.get("filled_notional_usd"), field="filled_notional_usd")
                if filled_notional != qty * fill_price:
                    raise ValueError("paper outcome filled notional is inconsistent")
                if qty != expected_qty or fill_price != expected_price:
                    continue
                matching_times.add(_utc(filled_at, field=f"{side}.filled_at"))
            if not matching_times:
                raise ValueError(f"closed paper position lacks matching {side} fill provenance")
            if len(matching_times) != 1:
                raise ValueError(f"closed paper position has conflicting {side} fill timestamps")
            return next(iter(matching_times))

        opening_filled_at = resolve(
            outcomes.get((point.opening_client_order_id, "buy"), []),
            side="opening",
            expected_price=expected_open_price,
        )
        closing_filled_at = resolve(
            outcomes.get((point.closing_client_order_id, "sell"), []),
            side="closing",
            expected_price=expected_close_price,
        )
        if not opening_filled_at < closing_filled_at:
            raise ValueError("closed paper position fill chronology is invalid")
        proven.append(
            AlpacaPaperClosedPositionFillProvenance(
                symbol=point.symbol,
                opening_client_order_id=point.opening_client_order_id,
                closing_client_order_id=point.closing_client_order_id,
                opening_filled_at=opening_filled_at.isoformat(),
                closing_filled_at=closing_filled_at.isoformat(),
            )
        )
    return tuple(proven)
