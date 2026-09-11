from __future__ import annotations

import math
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request

from .alpaca_paper_transport import (
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperCredentials,
    _HttpResult,
    _bounded_external_reference,
    _default_request,
    _headers,
    _is_json_content_type,
    _json_object,
    _validate_base_url,
    _validate_credentials,
    _validate_http_result,
    _validate_request_fn,
    _validate_timeout_seconds,
    _validated_client_order_id,
)

KNOWN_ORDER_STATUSES = frozenset(
    {
        "accepted",
        "pending_new",
        "new",
        "partially_filled",
        "filled",
        "done_for_day",
        "canceled",
        "expired",
        "replaced",
        "pending_cancel",
        "pending_replace",
        "accepted_for_bidding",
        "stopped",
        "rejected",
        "suspended",
        "calculated",
        "held",
    }
)
TERMINAL_ORDER_STATUSES = frozenset({"filled", "canceled", "expired", "rejected"})
_MAX_SYMBOL_CHARS = 32


@dataclass(frozen=True)
class AlpacaPaperOrderOutcome:
    external_order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    ordered_qty: Decimal
    filled_qty: Decimal
    filled_avg_price: Decimal | None
    submitted_at: datetime
    filled_at: datetime | None
    terminal: bool

    @property
    def has_fill(self) -> bool:
        return self.filled_qty > 0

    @property
    def filled_notional_usd(self) -> Decimal | None:
        if self.filled_qty <= 0 or self.filled_avg_price is None:
            return None
        return self.filled_qty * self.filled_avg_price


def _canonical_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("symbol must be text")
    normalized = value.strip().upper()
    if value != normalized or not normalized or len(normalized) > _MAX_SYMBOL_CHARS:
        raise ValueError("symbol must be canonical and bounded")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-/" for ch in normalized):
        raise ValueError("symbol is invalid")
    return normalized


def _positive_decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a positive decimal")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a positive decimal") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a positive finite decimal")
    return number


def _nonnegative_decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a nonnegative decimal")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a nonnegative decimal") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a nonnegative finite decimal")
    return number


def _optional_positive_decimal(value: Any, *, field: str) -> Decimal | None:
    if value is None:
        return None
    return _positive_decimal(value, field=field)


def _utc_timestamp(value: Any, *, field: str, required: bool) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a canonical ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00") if value.endswith("Z") else datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _parse_outcome(
    payload: dict[str, Any],
    *,
    expected_client_order_id: str,
    expected_symbol: str,
    expected_side: str,
    expected_qty: Decimal,
) -> AlpacaPaperOrderOutcome:
    external_order_id = _bounded_external_reference(payload.get("id"))
    if external_order_id is None:
        raise ValueError("order id is missing or invalid")
    if payload.get("client_order_id") != expected_client_order_id:
        raise ValueError("client_order_id identity mismatch")
    if _canonical_symbol(payload.get("symbol")) != expected_symbol:
        raise ValueError("symbol identity mismatch")
    if payload.get("side") != expected_side:
        raise ValueError("side identity mismatch")
    if payload.get("type") != "market" or payload.get("time_in_force") != "day":
        raise ValueError("unexpected order execution contract")

    ordered_qty = _positive_decimal(payload.get("qty"), field="qty")
    if ordered_qty != expected_qty:
        raise ValueError("ordered quantity identity mismatch")
    filled_qty = _nonnegative_decimal(payload.get("filled_qty"), field="filled_qty")
    if filled_qty > ordered_qty:
        raise ValueError("filled quantity exceeds ordered quantity")

    status = payload.get("status")
    if not isinstance(status, str) or status not in KNOWN_ORDER_STATUSES:
        raise ValueError("unknown or invalid Alpaca order status")

    filled_avg_price = _optional_positive_decimal(payload.get("filled_avg_price"), field="filled_avg_price")
    if filled_qty == 0 and filled_avg_price is not None:
        raise ValueError("fill price without filled quantity")
    if filled_qty > 0 and filled_avg_price is None:
        raise ValueError("filled quantity requires fill price")
    if status == "filled" and filled_qty != ordered_qty:
        raise ValueError("filled order must report complete quantity")

    submitted_at = _utc_timestamp(payload.get("submitted_at"), field="submitted_at", required=True)
    assert submitted_at is not None
    filled_at = _utc_timestamp(payload.get("filled_at"), field="filled_at", required=False)
    if filled_qty > 0 and filled_at is None:
        raise ValueError("filled quantity requires filled_at")
    if filled_at is not None and filled_at < submitted_at:
        raise ValueError("filled_at precedes submitted_at")

    return AlpacaPaperOrderOutcome(
        external_order_id=external_order_id,
        client_order_id=expected_client_order_id,
        symbol=expected_symbol,
        side=expected_side,
        status=status,
        ordered_qty=ordered_qty,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
        submitted_at=submitted_at,
        filled_at=filled_at,
        terminal=status in TERMINAL_ORDER_STATUSES,
    )


def fetch_paper_order_outcome(
    *,
    credentials: AlpacaPaperCredentials,
    client_order_id: str,
    expected_symbol: str,
    expected_qty: str,
    expected_side: str = "buy",
    base_url: str = ALPACA_PAPER_BASE_URL,
    timeout_seconds: float = 10.0,
    request_fn: Callable[[Request, float], _HttpResult] = _default_request,
) -> AlpacaPaperOrderOutcome | None:
    """Fetch a paper order snapshot with strict identity and fill validation.

    This is read-only outcome evidence. Unknown schemas/statuses, identity mismatches,
    malformed fills, transport ambiguity, redirects, non-JSON responses, and all
    non-200 statuses fail closed to None. A returned snapshot may be non-terminal;
    callers must not infer realized paper P&L until terminal/fill evidence is present.
    """

    credentials = _validate_credentials(credentials)
    request_fn = _validate_request_fn(request_fn)
    root = _validate_base_url(base_url)
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    key = _validated_client_order_id(client_order_id)
    symbol = _canonical_symbol(expected_symbol)
    side = expected_side.strip().lower() if isinstance(expected_side, str) else ""
    if expected_side != side or side not in {"buy", "sell"}:
        raise ValueError("expected_side must be canonical buy or sell")
    qty = _positive_decimal(expected_qty, field="expected_qty")

    query = urlencode({"client_order_id": key})
    request = Request(
        f"{root}/v2/orders:by_client_order_id?{query}",
        headers=_headers(credentials),
        method="GET",
    )
    try:
        result = _validate_http_result(request_fn(request, timeout_seconds))
    except (TimeoutError, socket.timeout, URLError, OSError, ValueError):
        return None
    if result.status != 200 or not _is_json_content_type(result.content_type):
        return None
    try:
        payload = _json_object(result.body)
        return _parse_outcome(
            payload,
            expected_client_order_id=key,
            expected_symbol=symbol,
            expected_side=side,
            expected_qty=qty,
        )
    except ValueError:
        return None
