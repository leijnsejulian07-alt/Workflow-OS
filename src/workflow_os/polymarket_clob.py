from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CLOB_BOOK_URL = "https://clob.polymarket.com/book"


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class ClobBook:
    asset_id: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]


def _levels(raw: Any, *, reverse: bool) -> tuple[BookLevel, ...]:
    if not isinstance(raw, list):
        raise ValueError("orderbook levels must be a list")
    levels: list[BookLevel] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid orderbook level")
        price, size = float(item["price"]), float(item["size"])
        if (not math.isfinite(price) or not math.isfinite(size)
                or not 0.0 < price < 1.0 or size <= 0.0):
            raise ValueError("invalid orderbook price/size")
        levels.append(BookLevel(price, size))
    return tuple(sorted(levels, key=lambda x: x.price, reverse=reverse))


def normalize_book(raw: dict[str, Any], *, expected_token_id: str) -> ClobBook:
    asset_id = str(raw.get("asset_id", "")).strip()
    if not asset_id or asset_id != expected_token_id:
        raise ValueError("CLOB asset id mismatch")
    return ClobBook(asset_id, _levels(raw.get("bids"), reverse=True), _levels(raw.get("asks"), reverse=False))


def fetch_book(token_id: str, *, timeout_seconds: float = 10.0) -> ClobBook:
    """Read-only official CLOB /book request for one documented token/asset id."""
    token_id = token_id.strip()
    if not token_id:
        raise ValueError("token_id required")
    if not 0 < timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be in (0, 30]")
    request = Request(
        f"{CLOB_BOOK_URL}?{urlencode({'token_id': token_id})}",
        headers={"Accept": "application/json", "User-Agent": "Workflow-OS/PolymarketPaper"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"CLOB HTTP {response.status}")
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise RuntimeError("CLOB response exceeds 1 MB")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("invalid CLOB orderbook response")
    return normalize_book(payload, expected_token_id=token_id)


def estimate_buy_slippage(book: ClobBook, *, stake_usd: float) -> float:
    """Estimate market-buy price impact vs best ask. Insufficient depth fails closed."""
    if stake_usd <= 0 or not book.asks:
        raise ValueError("positive stake and asks required")
    remaining = stake_usd
    shares = 0.0
    spent = 0.0
    for level in book.asks:
        level_value = level.price * level.size
        take_value = min(remaining, level_value)
        shares += take_value / level.price
        spent += take_value
        remaining -= take_value
        if remaining <= 1e-9:
            break
    if remaining > 1e-9 or shares <= 0:
        raise ValueError("insufficient ask depth")
    average_price = spent / shares
    return max(0.0, average_price / book.asks[0].price - 1.0)


def estimate_sell_vwap(book: ClobBook, *, shares: float) -> float:
    """Conservative executable paper-exit VWAP over current bids.

    This is read-only and never submits an order. Full requested depth is required;
    partial liquidity fails closed instead of overstating paper proceeds.
    """
    if (not isinstance(shares, (int, float)) or isinstance(shares, bool)
            or not math.isfinite(float(shares)) or shares <= 0 or not book.bids):
        raise ValueError("positive finite shares and bids required")
    remaining = float(shares)
    proceeds = 0.0
    filled = 0.0
    for level in book.bids:
        take = min(remaining, level.size)
        proceeds += take * level.price
        filled += take
        remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-9 or filled <= 0:
        raise ValueError("insufficient bid depth")
    vwap = proceeds / filled
    if not math.isfinite(vwap) or not 0.0 < vwap < 1.0:
        raise ValueError("invalid sell VWAP")
    return vwap
