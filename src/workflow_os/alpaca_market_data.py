from __future__ import annotations

import math
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request

from .alpaca_paper_transport import (
    AlpacaPaperCredentials,
    _HttpResult,
    _default_request,
    _is_json_content_type,
    _json_object,
    _validate_credentials,
    _validate_http_result,
    _validate_request_fn,
    _validate_timeout_seconds,
)

ALPACA_MARKET_DATA_BASE_URL = "https://data.alpaca.markets"
ALPACA_MARKET_DATA_FEED = "iex"
_MAX_SYMBOL_CHARS = 32
_MAX_TIMESTAMP_CHARS = 64


@dataclass(frozen=True)
class AlpacaLatestBarObservation:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int
    vwap: float
    feed: str = ALPACA_MARKET_DATA_FEED
    request_id: str | None = None


def _validate_market_data_base_url(base_url: Any) -> str:
    if base_url != ALPACA_MARKET_DATA_BASE_URL:
        raise ValueError("only the exact Alpaca market-data API base URL is allowed")
    return base_url


def _validated_stock_symbol(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("stock symbol is required")
    if value != value.strip() or value != value.upper():
        raise ValueError("stock symbol must already be canonical uppercase without surrounding whitespace")
    if len(value) > _MAX_SYMBOL_CHARS:
        raise ValueError("stock symbol is too long")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for ch in value):
        raise ValueError("stock symbol contains unsupported characters")
    return value


def _validated_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not 20 <= len(value) <= _MAX_TIMESTAMP_CHARS:
        raise ValueError("market-data timestamp is invalid")
    if value != value.strip() or "T" not in value or not value.endswith("Z"):
        raise ValueError("market-data timestamp is invalid")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("market-data timestamp is invalid")
    return value


def _finite_float(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("market-data numeric field is invalid")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("market-data numeric field is invalid")
    return number


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("market-data integer field is invalid")
    return value


def _parse_latest_bar(
    *, symbol: str, parsed: dict[str, Any], request_id: str | None
) -> AlpacaLatestBarObservation:
    bar = parsed.get("bar")
    if not isinstance(bar, dict):
        raise ValueError("Alpaca latest-bar response is missing bar data")

    open_price = _finite_float(bar.get("o"), positive=True)
    high_price = _finite_float(bar.get("h"), positive=True)
    low_price = _finite_float(bar.get("l"), positive=True)
    close_price = _finite_float(bar.get("c"), positive=True)
    vwap = _finite_float(bar.get("vw"), positive=True)
    if high_price < max(open_price, low_price, close_price, vwap):
        raise ValueError("market-data bar high is inconsistent")
    if low_price > min(open_price, high_price, close_price, vwap):
        raise ValueError("market-data bar low is inconsistent")

    return AlpacaLatestBarObservation(
        symbol=symbol,
        timestamp=_validated_timestamp(bar.get("t")),
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=_nonnegative_int(bar.get("v")),
        trade_count=_nonnegative_int(bar.get("n")),
        vwap=vwap,
        request_id=request_id,
    )


def fetch_latest_iex_bar(
    *,
    credentials: AlpacaPaperCredentials,
    symbol: str,
    base_url: str = ALPACA_MARKET_DATA_BASE_URL,
    timeout_seconds: float = 10.0,
    request_fn: Callable[[Request, float], _HttpResult] = _default_request,
) -> AlpacaLatestBarObservation | None:
    """Fetch one bounded real-market minute-bar observation for a paper-learning decision.

    This read-only transport is deliberately fixed to Alpaca's IEX stock feed and exact
    market-data host. Invalid caller configuration raises before transport. Network,
    status, MIME, JSON, or schema ambiguity returns ``None`` so downstream strategy and
    risk gates cannot act on an unverified observation.
    """

    credentials = _validate_credentials(credentials)
    request_fn = _validate_request_fn(request_fn)
    root = _validate_market_data_base_url(base_url)
    timeout_seconds = _validate_timeout_seconds(timeout_seconds)
    key = _validated_stock_symbol(symbol)
    query = urlencode({"feed": ALPACA_MARKET_DATA_FEED, "currency": "USD"})
    request = Request(
        f"{root}/v2/stocks/{key}/bars/latest?{query}",
        headers={
            "APCA-API-KEY-ID": credentials.key_id,
            "APCA-API-SECRET-KEY": credentials.secret_key,
            "Accept": "application/json",
            "User-Agent": "Workflow-OS/AlpacaMarketData",
        },
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
        return _parse_latest_bar(symbol=key, parsed=parsed, request_id=result.request_id)
    except ValueError:
        return None
