from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any

SOURCE_PLATFORM = "cliparmy-public"
SOURCE_URL = "https://cliparmy.nl/"
MAX_CAMPAIGNS = 100
MAX_TEXT = 512


def _text(value: Any, field: str, *, max_length: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return text


def _money(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return number


def _checked_at(value: Any) -> str:
    text = _text(value, "source_checked_at", max_length=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source_checked_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("source_checked_at must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_public_campaigns(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a bounded Clip Army public-page snapshot without inventing evidence.

    The public homepage currently exposes live campaign names and campaign budgets, but
    does not expose enough rights/payment/account evidence for autonomous acceptance.
    Those fields deliberately remain unknown so Opportunity Manager revalidates them.
    This adapter performs discovery only; it has no apply/post/payment side effects.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("source_url") != SOURCE_URL:
        raise ValueError("source_url must be the canonical Clip Army public homepage")
    checked_at = _checked_at(payload.get("source_checked_at"))
    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list):
        raise ValueError("campaigns must be a list")
    if len(campaigns) > MAX_CAMPAIGNS:
        raise ValueError(f"campaigns exceeds {MAX_CAMPAIGNS} items")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, campaign in enumerate(campaigns):
        if not isinstance(campaign, dict):
            raise ValueError(f"campaigns[{index}] must be an object")
        title = _text(campaign.get("title"), f"campaigns[{index}].title")
        budget = _money(campaign.get("budget_eur"), f"campaigns[{index}].budget_eur")
        campaign_id = hashlib.sha256(f"{SOURCE_PLATFORM}|{title}".encode()).hexdigest()[:24]
        if campaign_id in seen:
            continue
        seen.add(campaign_id)
        normalized.append(
            {
                "opportunity_id": campaign_id,
                "source_platform": SOURCE_PLATFORM,
                "campaign_id": campaign_id,
                "title": title,
                "category": "clipping_content_reward",
                "allowed_countries": [],
                "platforms": [],
                "source_assets": [],
                "usage_rights": "",
                "rights_verification_state": "UNKNOWN",
                "disclosure_requirements": [],
                "deadline": None,
                "remaining_budget": budget,
                "payout_formula": "",
                "minimum_thresholds": {},
                "payout_cap": None,
                "payment_method": None,
                "approval_rules": "",
                "originality_requirements": "",
                "account_requirements": None,
                "expected_production_cost": 0.0,
                "expected_laptop_minutes": 0.0,
                "expected_owner_minutes": 0.0,
                "estimated_success_probability": None,
                "probability_collection": None,
                "expected_revenue": None,
                "compliance_risk": "MEDIUM",
                "platform_risk": "MEDIUM",
                "duplicate_conflict_status": "CLEAR",
                "user_attention_requirement": "NONE",
                "source_checked_at": checked_at,
                "freshness_ttl_seconds": 3600,
                "status": "DISCOVERED",
            }
        )
    return normalized
