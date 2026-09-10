from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .trading_order_execution import (
    TradingOrderAttemptResult,
    TradingOrderReconciliationResult,
)

ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_CREDENTIAL_CHARS = 512
_MAX_QTY_CHARS = 64


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class AlpacaPaperCredentials:
    key_id: str = field(repr=False)
    secret_key: str = field(repr=False)

    def __post_init__(self) -> None:
        for name, value in (("key_id", self.key_id), ("secret_key", self.secret_key)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"paper {name} is required")
            if len(value) > _MAX_CREDENTIAL_CHARS or "\r" in value or "\n" in value:
                raise ValueError(f"paper {name} is invalid")


@dataclass(frozen=True)
class AlpacaPaperOrder:
    client_order_id: str
    symbol: str
    qty: str
    side: str
    order_type: str = "market"
    time_in_force: str = "day"

    def __post_init__(self) -> None:
        client_order_id = self.client_order_id.strip() if isinstance(self.client_order_id, str) else ""
        symbol = self.symbol.strip().upper() if isinstance(self.symbol, str) else ""
        qty = self.qty.strip() if isinstance(self.qty, str) else ""
        side = self.side.strip().lower() if isinstance(self.side, str) else ""
        order_type = self.order_type.strip().lower() if isinstance(self.order_type, str) else ""
        tif = self.time_in_force.strip().lower() if isinstance(self.time_in_force, str) else ""
        if not client_order_id or len(client_order_id) > 128:
            raise ValueError("client_order_id is required and must be <= 128 characters")
        if not symbol or len(symbol) > 32 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-/" for ch in symbol):
            raise ValueError("symbol is invalid")
        if not qty or len(qty) > _MAX_QTY_CHARS:
            raise ValueError("qty is required and bounded")
        try:
            qty_number = float(qty)
        except (TypeError, ValueError) as exc:
            raise ValueError("qty must be a positive number encoded as text") from exc
        if qty_number <= 0 or qty_number != qty_number or qty_number in {float("inf"), float("-inf")}:
            raise ValueError("qty must be finite and positive")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if order_type != "market":
            raise ValueError("paper transport v1 only permits market orders")
        if tif != "day":
            raise ValueError("paper transport v1 only permits day time-in-force")


@dataclass(frozen=True)
class _HttpResult:
    status: int
    body: bytes
    request_id: str | None


def _validate_base_url(base_url: str) -> str:
    if base_url != ALPACA_PAPER_BASE_URL:
        raise ValueError("only the exact Alpaca paper API base URL is allowed")
    return base_url


def _read_bounded(response: Any) -> bytes:
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Alpaca response exceeded size limit")
    return body


def _default_request(request: Request, timeout_seconds: float) -> _HttpResult:
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ValueError("timeout_seconds must be > 0 and <= 30")
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return _HttpResult(
                status=int(response.status),
                body=_read_bounded(response),
                request_id=response.headers.get("X-Request-ID"),
            )
    except HTTPError as exc:
        return _HttpResult(
            status=int(exc.code),
            body=_read_bounded(exc),
            request_id=exc.headers.get("X-Request-ID") if exc.headers else None,
        )


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Alpaca response was not valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Alpaca response must be a JSON object")
    return parsed


def _headers(credentials: AlpacaPaperCredentials) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": credentials.key_id.strip(),
        "APCA-API-SECRET-KEY": credentials.secret_key.strip(),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Workflow-OS/AlpacaPaperTransport",
    }


def submit_paper_order(
    *,
    credentials: AlpacaPaperCredentials,
    order: AlpacaPaperOrder,
    base_url: str = ALPACA_PAPER_BASE_URL,
    timeout_seconds: float = 10.0,
    request_fn: Callable[[Request, float], _HttpResult] = _default_request,
) -> TradingOrderAttemptResult:
    """Submit one strict paper-only market/day order through Alpaca's official endpoint.

    2xx is accepted only when Alpaca returns both a stable order id and the exact
    client_order_id. Explicit 4xx rejection is NOT_APPLIED only when the status
    itself proves the request was rejected. Timeouts, redirects, 408/409/429,
    5xx, malformed responses, or identity mismatches are UNKNOWN so callers
    must reconcile instead of blindly retrying.
    """

    root = _validate_base_url(base_url)
    payload = {
        "symbol": order.symbol.strip().upper(),
        "qty": order.qty.strip(),
        "side": order.side.strip().lower(),
        "type": "market",
        "time_in_force": "day",
        "client_order_id": order.client_order_id.strip(),
    }
    request = Request(
        f"{root}/v2/orders",
        data=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        headers=_headers(credentials),
        method="POST",
    )
    try:
        result = request_fn(request, timeout_seconds)
    except (TimeoutError, socket.timeout, URLError, OSError, ValueError):
        return TradingOrderAttemptResult("UNKNOWN")

    if 200 <= result.status < 300:
        try:
            parsed = _json_object(result.body)
        except ValueError:
            return TradingOrderAttemptResult("UNKNOWN")
        external_id = parsed.get("id")
        returned_client_id = parsed.get("client_order_id")
        if (
            isinstance(external_id, str)
            and external_id.strip()
            and returned_client_id == order.client_order_id.strip()
        ):
            return TradingOrderAttemptResult("APPLIED", external_id.strip())
        return TradingOrderAttemptResult("UNKNOWN")

    if 400 <= result.status < 500 and result.status not in {408, 409, 429}:
        return TradingOrderAttemptResult("NOT_APPLIED")
    return TradingOrderAttemptResult("UNKNOWN")


def reconcile_paper_order(
    *,
    credentials: AlpacaPaperCredentials,
    client_order_id: str,
    base_url: str = ALPACA_PAPER_BASE_URL,
    timeout_seconds: float = 10.0,
    request_fn: Callable[[Request, float], _HttpResult] = _default_request,
) -> TradingOrderReconciliationResult:
    """Reconcile by Alpaca client_order_id without dispatching another order."""

    root = _validate_base_url(base_url)
    key = client_order_id.strip() if isinstance(client_order_id, str) else ""
    if not key or len(key) > 128:
        raise ValueError("client_order_id is required and must be <= 128 characters")
    query = urlencode({"client_order_id": key})
    request = Request(
        f"{root}/v2/orders:by_client_order_id?{query}",
        headers=_headers(credentials),
        method="GET",
    )
    try:
        result = request_fn(request, timeout_seconds)
    except (TimeoutError, socket.timeout, URLError, OSError, ValueError):
        return TradingOrderReconciliationResult("STILL_UNKNOWN")

    if result.status == 200:
        try:
            parsed = _json_object(result.body)
        except ValueError:
            return TradingOrderReconciliationResult("STILL_UNKNOWN")
        external_id = parsed.get("id")
        returned_client_id = parsed.get("client_order_id")
        if (
            isinstance(external_id, str)
            and external_id.strip()
            and returned_client_id == key
        ):
            return TradingOrderReconciliationResult("FOUND_APPLIED", external_id.strip())
        return TradingOrderReconciliationResult("STILL_UNKNOWN")

    # A lookup miss is not strong enough evidence that a prior POST was never accepted;
    # propagation/race ambiguity must remain fail-closed.
    return TradingOrderReconciliationResult("STILL_UNKNOWN")
