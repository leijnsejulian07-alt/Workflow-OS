from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from .polymarket_gamma import GammaMarket
from .polymarket_scanner import FairProbabilityEvidence

XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = "grok-4.20"
MAX_RESPONSE_BYTES = 256_000


def _extract_output_text(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise ValueError("xAI response missing output")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                return part["text"]
    raise ValueError("xAI response missing output_text")


def _normalize_probability_payload(raw: str) -> float:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or set(parsed) != {"probability"}:
        raise ValueError("unexpected estimator schema")
    probability = parsed["probability"]
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        raise ValueError("probability must be numeric")
    probability = float(probability)
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise ValueError("probability must be finite and strictly between zero and one")
    return probability


def estimate_with_xai(
    market: GammaMarket,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = 20.0,
) -> FairProbabilityEvidence | None:
    """Estimate YES probability with xAI web research; any ambiguity/error fails closed.

    This function is opt-in: no API request occurs unless an explicit key or XAI_API_KEY
    exists. The returned timestamp is local receipt time, so scanner freshness still gates it.
    """
    key = (api_key if api_key is not None else os.getenv("XAI_API_KEY", "")).strip()
    if not key:
        return None
    if not isinstance(model, str) or not model.strip():
        return None
    if not 0 < timeout_seconds <= 30:
        return None
    if not isinstance(market, GammaMarket) or not market.question.strip() or not market.resolution_source_present:
        return None

    schema = {
        "type": "object",
        "properties": {"probability": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}},
        "required": ["probability"],
        "additionalProperties": False,
    }
    prompt = (
        "Independently estimate the probability that the YES outcome resolves true for this prediction market. "
        "Use current web evidence and the stated resolution source/rules. Do not use the market price as your estimate. "
        "If evidence is insufficient or the resolution rule is ambiguous, do not guess.\n\n"
        f"Question: {market.question}\n"
        f"Resolution source/rules: {market.resolution_source}\n"
        f"Resolution time: {market.resolves_at.isoformat()}"
    )
    body = json.dumps({
        "model": model.strip(),
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "store": False,
        "text": {"format": {"type": "json_schema", "name": "fair_probability", "schema": schema, "strict": True}},
    }).encode("utf-8")
    request = Request(
        XAI_RESPONSES_URL,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Workflow-OS/PolymarketPaper"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                return None
            raw_body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw_body) > MAX_RESPONSE_BYTES:
            return None
        payload = json.loads(raw_body.decode("utf-8"))
        probability = _normalize_probability_payload(_extract_output_text(payload))
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return FairProbabilityEvidence(probability, f"xai:{model.strip()}:web_search", datetime.now(timezone.utc))
