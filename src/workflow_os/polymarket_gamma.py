from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
_MARKET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class GammaMarket:
    market_id: str
    question: str
    yes_price: float
    yes_token_id: str
    liquidity_usd: float
    resolves_at: datetime
    resolution_source: str
    active: bool
    closed: bool
    accepting_orders: bool

    @property
    def resolution_source_present(self) -> bool:
        return bool(self.resolution_source.strip())


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    raise ValueError("expected JSON list")


def normalize_gamma_market(raw: dict[str, Any]) -> GammaMarket:
    """Normalize documented Gamma fields; malformed or ambiguous input fails closed."""
    market_id = str(raw.get("id", "")).strip()
    question = str(raw.get("question", "")).strip()
    source = str(raw.get("resolutionSource", "")).strip()
    if not market_id or not question:
        raise ValueError("missing market identity")

    outcomes = _json_list(raw.get("outcomes"))
    prices = _json_list(raw.get("outcomePrices"))
    token_ids = _json_list(raw.get("clobTokenIds"))
    if len(outcomes) != len(prices) or len(outcomes) != len(token_ids) or "Yes" not in outcomes:
        raise ValueError("aligned binary YES contract unavailable")
    yes_index = outcomes.index("Yes")
    yes_price = float(prices[yes_index])
    yes_token_id = str(token_ids[yes_index]).strip()
    # Exact-market monitoring must remain able to read resolved contracts whose
    # terminal YES value is legitimately 0 or 1. Discovery still filters to active,
    # open, order-accepting markets before any entry can be considered.
    if not math.isfinite(yes_price) or not 0.0 <= yes_price <= 1.0:
        raise ValueError("invalid YES price")
    if not yes_token_id:
        raise ValueError("missing YES CLOB token id")

    liquidity_raw = raw.get("liquidityNum", raw.get("liquidity"))
    liquidity = float(liquidity_raw)
    if liquidity < 0:
        raise ValueError("invalid liquidity")

    end_raw = raw.get("endDateIso") or raw.get("endDate")
    if not isinstance(end_raw, str) or not end_raw.strip():
        raise ValueError("missing resolution date")
    resolves_at = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
    if resolves_at.tzinfo is None or resolves_at.utcoffset() is None:
        raise ValueError("resolution date must be timezone-aware")

    return GammaMarket(
        market_id=market_id,
        question=question,
        yes_price=yes_price,
        yes_token_id=yes_token_id,
        liquidity_usd=liquidity,
        resolves_at=resolves_at,
        resolution_source=source,
        active=raw.get("active") is True,
        closed=raw.get("closed") is True,
        accepting_orders=raw.get("acceptingOrders") is True,
    )


def _read_gamma_json(url: str, *, timeout_seconds: float) -> Any:
    if not 0 < timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be in (0, 30]")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Workflow-OS/PolymarketPaper"})
    with urlopen(request, timeout=timeout_seconds) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"Gamma HTTP {response.status}")
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise RuntimeError("Gamma response exceeds 2 MB")
    return json.loads(body.decode("utf-8"))


def fetch_gamma_market(*, market_id: str, timeout_seconds: float = 10.0) -> GammaMarket:
    """Fetch one market by exact Gamma id for restart-safe position monitoring."""
    clean_id = str(market_id).strip()
    if _MARKET_ID_RE.fullmatch(clean_id) is None:
        raise ValueError("market_id contains unsupported characters")
    payload = _read_gamma_json(f"{GAMMA_MARKETS_URL}/{clean_id}", timeout_seconds=timeout_seconds)
    if not isinstance(payload, dict):
        raise ValueError("Gamma market response must be an object")
    market = normalize_gamma_market(payload)
    if market.market_id != clean_id:
        raise ValueError("Gamma market identity mismatch")
    return market


def fetch_gamma_markets(*, limit: int = 100, timeout_seconds: float = 10.0) -> list[GammaMarket]:
    """Read-only official Gamma ingest. No credentials, wallet, or trading side effects."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    query = urlencode({"active": "true", "closed": "false", "limit": limit})
    payload = _read_gamma_json(f"{GAMMA_MARKETS_URL}?{query}", timeout_seconds=timeout_seconds)
    if not isinstance(payload, list):
        raise ValueError("Gamma response must be a list")

    markets: list[GammaMarket] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        try:
            market = normalize_gamma_market(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if market.active and not market.closed and market.accepting_orders:
            markets.append(market)
    return markets
