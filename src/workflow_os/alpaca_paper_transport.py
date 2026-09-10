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
_MAX_EXTERNAL_REFERENCE_CHARS = 256
_MAX_RESPONSE_METADATA_CHARS = 256


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
            if value != value.strip():
                raise ValueError(f"paper {name} must not contain surrounding whitespace")
            if len(value) > _MAX_CREDENTIAL_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
                raise ValueError(f"paper {name} is invalid")


def _validated_client_order_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("client_order_id is required and must be <= 128 characters")
    normalized = value.strip()
    if value != normalized:
        raise ValueError("client_order_id must not contain surrounding whitespace")
    if len(normalized) > 128:
        raise ValueError("client_order_id is required and must be <= 128 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized):
        raise ValueError("client_order_id contains control characters")
    return normalized


@dataclass(frozen=True)
class AlpacaPaperOrder:
    client_order_id: str
    symbol: str
    qty: str
    side: str
    order_type: str = "market"
    time_in_force: str = "day"

    def __post_init__(self) -> None:
        _validated_client_order_id(self.client_order_id)
        symbol = self.symbol.strip().upper() if isinstance(self.symbol, str) else ""
        qty = self.qty.strip() if isinstance(self.qty, str) else ""
        side = self.side.strip().lower() if isinstance(self.side, str) else ""
        order_type = self.order_type.strip().lower() if isinstance(self.order_type, str) else ""
        tif = self.time_in_force.strip().lower() if isinstance(self.time_in_force, str) else ""
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
    content_type: str | None = None


def _validate_credentials(value: Any) -> AlpacaPaperCredentials:
    if not isinstance(value, AlpacaPaperCredentials):
        raise ValueError("credentials must be validated AlpacaPaperCredentials")
    return value


def _validate_order(value: Any) -> AlpacaPaperOrder:
    if not isinstance(value, AlpacaPaperOrder):
        raise ValueError("order must be a validated AlpacaPaperOrder")
    return value


def _validate_request_fn(value: Any) -> Callable[[Request, float], _HttpResult]:
    if not callable(value):
        raise ValueError("request_fn must be callable")
    return value


def _validate_base_url(base_url: str) -> str:
    if base_url != ALPACA_PAPER_BASE_URL:
        raise ValueError("only the exact Alpaca paper API base URL is allowed")
    return base_url


def _validate_timeout_seconds(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be numeric")
    value = float(timeout_seconds)
    if value <= 0 or value > 30 or value != value or value in {float("inf"), float("-inf")}:
        raise ValueError("timeout_seconds must be finite, > 0 and <= 30")
    return value


def _read_bounded(response: Any) -> bytes:
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Alpaca response exceeded size limit")
    return body


def _default_request(request: Request, timeout_seconds: float) -> _HttpResult:
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return _HttpResult(
                status=int(response.status),
                body=_read_bounded(response),
                request_id=response.headers.get("X-Request-ID"),
                content_type=response.headers.get("Content-Type"),
            )
    except HTTPError as exc:
        return _HttpResult(
            status=int(exc.code),
            body=_read_bounded(exc),
            request_id=exc.headers.get("X-Request-ID") if exc.headers else None,
            content_type=exc.headers.get("Content-Type") if exc.headers else None,
        )


def _bounded_response_metadata(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _MAX_RESPONSE_METADATA_CHARS:
        raise ValueError("Alpaca response metadata is invalid")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Alpaca response metadata is invalid")
    return value


def _validate_http_result(result: Any) -> _HttpResult:
    if not isinstance(result, _HttpResult):
        raise ValueError("Alpaca transport returned an invalid result")
    if isinstance(result.status, bool) or not isinstance(result.status, int) or not 100 <= result.status <= 599:
        raise ValueError("Alpaca response status is invalid")
    if not isinstance(result.body, bytes) or len(result.body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Alpaca response body is invalid or exceeded size limit")
    _bounded_response_metadata(result.request_id)
    _bounded_response_metadata(result.content_type)
    return result


def _is_json_content_type(content_type: str | None) -> bool:
    if not isinstance(content_type, str):
        return False
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in {"application/json", "application/problem+json"}


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Alpaca response was not valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Alpaca response must be a JSON object")
    return parsed


def _bounded_external_reference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_EXTERNAL_REFERENCE_CHARS:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized):
        return None
    return normalized


def _headers(credentials: AlpacaPaperCredentials) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": credentials.key_id,
        "APCA-API-SECRET-KEY": credentials.secret_key,
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

    2xx is accepted only when Alpaca returns JSON with both a stable order id and
    the exact client_order_id. Explicit 4xx rejection is NOT_APPLIED only when
    the status itself proves the request was rejected. Timeouts, redirects,
    408/409/429, 5xx, malformed or unexpected-MIME responses, or identity
    mismatches are UNKNOWN so callers must reconcile instead of blindly retrying.
    """

    credentials = _validate_credentials(credentials)
    order = _validate_order(order)
    request_fn = _validate_request_fn(request_fn)
    root = _validate_base_url(base_url)
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    client_order_id = _validated_client_order_id(order.client_order_id)
    payload = {
        "symbol": order.symbol.strip().upper(),
        "qty": order.qty.strip(),
        "side": order.side.strip().lower(),
        "type": "market",
        "time_in_force": "day",
        "client_order_id": client_order_id,
    }
    request = Request(
        f"{root}/v2/orders",
        data=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        headers=_headers(credentials),
        method="POST",
    )
    try:
        result = _validate_http_result(request_fn(request, timeout_seconds))
    except (TimeoutError, socket.timeout, URLError, OSError, ValueError):
        return TradingOrderAttemptResult("UNKNOWN")

    if 200 <= result.status < 300:
        if not _is_json_content_type(result.content_type):
            return TradingOrderAttemptResult("UNKNOWN")
        try:
            parsed = _json_object(result.body)
        except ValueError:
            return TradingOrderAttemptResult("UNKNOWN")
        external_id = _bounded_external_reference(parsed.get("id"))
        returned_client_id = parsed.get("client_order_id")
        if external_id is not None and returned_client_id == client_order_id:
            return TradingOrderAttemptResult("APPLIED", external_id)
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

    credentials = _validate_credentials(credentials)
    request_fn = _validate_request_fn(request_fn)
    root = _validate_base_url(base_url)
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    key = _validated_client_order_id(client_order_id)
    query = urlencode({"client_order_id": key})
    request = Request(
        f"{root}/v2/orders:by_client_order_id?{query}",
        headers=_headers(credentials),
        method="GET",
    )
    try:
        result = _validate_http_result(request_fn(request, timeout_seconds))
    except (TimeoutError, socket.timeout, URLError, OSError, ValueError):
        return TradingOrderReconciliationResult("STILL_UNKNOWN")

    if result.status == 200:
        if not _is_json_content_type(result.content_type):
            return TradingOrderReconciliationResult("STILL_UNKNOWN")
        try:
            parsed = _json_object(result.body)
        except ValueError:
            return TradingOrderReconciliationResult("STILL_UNKNOWN")
        external_id = _bounded_external_reference(parsed.get("id"))
        returned_client_id = parsed.get("client_order_id")
        if external_id is not None and returned_client_id == key:
            return TradingOrderReconciliationResult("FOUND_APPLIED", external_id)
        return TradingOrderReconciliationResult("STILL_UNKNOWN")

    # A lookup miss is not strong enough evidence that a prior POST was never accepted;
    # propagation/race ambiguity must remain fail-closed.
    return TradingOrderReconciliationResult("STILL_UNKNOWN")
