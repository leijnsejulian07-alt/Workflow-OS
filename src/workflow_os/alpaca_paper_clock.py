from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class AlpacaPaperMarketClock:
    timestamp: datetime
    is_open: bool
    request_id: str | None


def _strict_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Alpaca clock is_open field is invalid")
    return value


def _utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("Alpaca clock timestamp is invalid")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Alpaca clock timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00") if value.endswith("Z") else datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Alpaca clock timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Alpaca clock timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def fetch_paper_market_clock(
    *,
    credentials: AlpacaPaperCredentials,
    base_url: str = ALPACA_PAPER_BASE_URL,
    timeout_seconds: float = 10.0,
    request_fn: Callable[[Request, float], _HttpResult] = _default_request,
) -> AlpacaPaperMarketClock | None:
    """Read Alpaca's official PAPER market clock and fail closed on ambiguity.

    Only the exact paper Trading API host is reachable. Transport, HTTP, MIME,
    JSON, timestamp, and schema failures return None. The caller must separately
    enforce freshness against its own trusted UTC clock before authorizing an
    order side effect.
    """

    credentials = _validate_credentials(credentials)
    request_fn = _validate_request_fn(request_fn)
    root = _validate_base_url(base_url)
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    request = Request(
        f"{root}/v2/clock",
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
        return AlpacaPaperMarketClock(
            timestamp=_utc_timestamp(parsed.get("timestamp")),
            is_open=_strict_bool(parsed.get("is_open")),
            request_id=result.request_id,
        )
    except ValueError:
        return None
