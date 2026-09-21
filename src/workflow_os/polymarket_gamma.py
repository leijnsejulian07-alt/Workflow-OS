from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


@dataclass(frozen=True)
class GammaMarket:
    market_id: str
    question: str
    yes_price: float
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
    """Normalize only fields documented by Polymarket Gamma; malformed input fails closed."""
    market_id = str(raw.get("id", "")).strip()
    question = str(raw.get("question", "")).strip()
    source = str(raw.get("resolutionSource", "")).strip()
    if not market_id or not question:
        raise ValueError("missing market identity")

    outcomes = _json_list(raw.get("outcomes"))
    prices = _json_list(raw.get("outcomePrices"))
    if len(outcomes) != len(prices) or "Yes" not in outcomes:
        raise ValueError("binary YES price unavailable")
    yes_price = float(prices[outcomes.index("Yes")])
    if not 0.0 < yes_price < 1.0:
        raise ValueError("invalid YES price")

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
        liquidity_usd=liquidity,
        resolves_at=resolves_at,
        resolution_source=source,
        active=raw.get("active") is True,
        closed=raw.get("closed") is True,
        accepting_orders=raw.get("acceptingOrders") is True,
    )


def fetch_gamma_markets(*, limit: int = 100, timeout_seconds: float = 10.0) -> list[GammaMarket]:
    """Read-only official Gamma ingest. No credentials, wallet, or trading side effects."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not 0 < timeout_seconds <= 30:
        raise ValueError("timeout_seconds must be in (0, 30]")
    query = urlencode({"active": "true", "closed": "false", "limit": limit})
    request = Request(f"{GAMMA_MARKETS_URL}?{query}", headers={"Accept": "application/json", "User-Agent": "Workflow-OS/PolymarketPaper"})
    with urlopen(request, timeout=timeout_seconds) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"Gamma HTTP {response.status}")
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise RuntimeError("Gamma response exceeds 2 MB")
    payload = json.loads(body.decode("utf-8"))
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
