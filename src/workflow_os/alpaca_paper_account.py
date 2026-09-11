from __future__ import annotations

import math
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request

from .alpaca_paper_transport import (
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperCredentials,
    _HttpResult,
    _default_request,
    _headers,
    _is_json_content_type,
    _json_object,
    _validate_base_url,
    _validate_credentials,
    _validate_http_result,
    _validate_request_fn,
    _validate_timeout_seconds,
)

_MAX_ACCOUNT_ID_CHARS = 200


@dataclass(frozen=True)
class AlpacaPaperAccountSnapshot:
    account_id: str
    status: str
    currency: str
    buying_power_usd: float
    trading_blocked: bool
    account_blocked: bool
    trade_suspended_by_user: bool
    request_id: str | None

    @property
    def trading_enabled(self) -> bool:
        return (
            self.status == "ACTIVE"
            and self.currency == "USD"
            and not self.trading_blocked
            and not self.account_blocked
            and not self.trade_suspended_by_user
        )


def _validated_account_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > _MAX_ACCOUNT_ID_CHARS
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise ValueError("expected_account_id is required, canonical and bounded")
    return value


def _strict_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Alpaca account boolean field is invalid")
    return value


def _finite_nonnegative_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Alpaca account numeric field is invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Alpaca account numeric field is invalid") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("Alpaca account numeric field is invalid")
    return number


def fetch_paper_account_snapshot(
    *,
    credentials: AlpacaPaperCredentials,
    expected_account_id: str,
    base_url: str = ALPACA_PAPER_BASE_URL,
    timeout_seconds: float = 10.0,
    request_fn: Callable[[Request, float], _HttpResult] = _default_request,
) -> AlpacaPaperAccountSnapshot | None:
    """Read and strictly validate the current Alpaca PAPER account safety state.

    Any transport, HTTP, MIME, JSON, schema, identity, or numeric ambiguity returns
    None so callers can fail closed. The exact paper API host is enforced by the
    shared paper transport validator; live trading is unreachable from this module.
    """

    credentials = _validate_credentials(credentials)
    request_fn = _validate_request_fn(request_fn)
    root = _validate_base_url(base_url)
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    account_id = _validated_account_id(expected_account_id)
    request = Request(
        f"{root}/v2/account",
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
        parsed = _json_object(result.body)
        returned_id = parsed.get("id")
        if returned_id != account_id:
            return None
        status = parsed.get("status")
        currency = parsed.get("currency")
        if not isinstance(status, str) or not status or len(status) > 64:
            return None
        if not isinstance(currency, str) or not currency or len(currency) > 16:
            return None
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in status + currency):
            return None
        snapshot = AlpacaPaperAccountSnapshot(
            account_id=account_id,
            status=status,
            currency=currency,
            buying_power_usd=_finite_nonnegative_number(parsed.get("buying_power")),
            trading_blocked=_strict_bool(parsed.get("trading_blocked")),
            account_blocked=_strict_bool(parsed.get("account_blocked")),
            trade_suspended_by_user=_strict_bool(parsed.get("trade_suspended_by_user")),
            request_id=result.request_id,
        )
    except ValueError:
        return None

    return snapshot
