from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any

ALLOWED_CONTENT_REWARD_PLATFORMS = {
    "clip_army",
    "whop_content_rewards",
    "clipping_exchange",
    "bounty_content_network",
}
ALLOWED_TARGET_PLATFORMS = {
    "tiktok",
    "youtube_shorts",
    "instagram_reels",
    "x",
    "youtube",
}
MAX_TEXT = 2000
MAX_ITEMS = 32
MIN_REWARD_USD = 1.0


def _text(value: Any, field: str, *, required: bool = True, max_length: int = MAX_TEXT) -> str:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return ""
    text = str(value).strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return text


def _number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} must be <= {maximum}")
    return number


def _iso(value: Any, field: str) -> str:
    text = _text(value, field, max_length=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def to_opportunity(campaign: dict[str, Any]) -> dict[str, Any]:
    """Normalize a verified read-only clipping/content-reward campaign into Opportunity Manager input."""
    if not isinstance(campaign, dict):
        raise ValueError("campaign must be an object")

    source_platform = _text(campaign.get("source_platform"), "source_platform", max_length=64)
    if source_platform not in ALLOWED_CONTENT_REWARD_PLATFORMS:
        raise ValueError("source_platform is not an approved content reward platform")

    campaign_id = _text(campaign.get("campaign_id"), "campaign_id", max_length=128)
    title = _text(campaign.get("title"), "title", max_length=200)
    category = _text(campaign.get("category", "content_clipping_reward"), "category", max_length=64)

    # Validate target distribution platforms
    raw_platforms = campaign.get("platforms")
    if not isinstance(raw_platforms, list) or not raw_platforms or len(raw_platforms) > MAX_ITEMS:
        raise ValueError("platforms must be a non-empty list of supported social distribution platforms")
    platforms: list[str] = []
    for p in raw_platforms:
        plat_str = _text(p, "platform", max_length=32).lower()
        if plat_str not in ALLOWED_TARGET_PLATFORMS:
            raise ValueError(f"platform '{plat_str}' is not supported")
        platforms.append(plat_str)

    # Allowed countries
    raw_countries = campaign.get("allowed_countries", ["GLOBAL"])
    if not isinstance(raw_countries, list) or len(raw_countries) > MAX_ITEMS:
        raise ValueError("allowed_countries must be a list")
    allowed_countries = [_text(c, "country_code", max_length=10).upper() for c in raw_countries]

    # Source assets and usage rights
    usage_rights = _text(campaign.get("usage_rights"), "usage_rights")
    rights_verified = campaign.get("rights_verification_state")
    if rights_verified not in ("VERIFIED", "UNVERIFIED", "UNKNOWN"):
        rights_verified = "VERIFIED" if campaign.get("rights_attested") is True else "UNKNOWN"

    source_assets = campaign.get("source_assets", [])
    if not isinstance(source_assets, list) or len(source_assets) > MAX_ITEMS:
        raise ValueError("source_assets must be a list")

    # Economics
    expected_revenue = _number(campaign.get("expected_revenue_usd"), "expected_revenue_usd", minimum=MIN_REWARD_USD)
    production_cost = _number(campaign.get("expected_production_cost_usd", 0.0), "expected_production_cost_usd", minimum=0.0)
    laptop_minutes = _number(campaign.get("expected_laptop_minutes", 10.0), "expected_laptop_minutes", minimum=0.0)
    success_probability = _number(campaign.get("estimated_success_probability", 0.7), "estimated_success_probability", minimum=0.0, maximum=1.0)
    collection_probability = _number(campaign.get("probability_collection", 0.9), "probability_collection", minimum=0.0, maximum=1.0)
    time_to_cash = _number(campaign.get("expected_time_to_cash_hours", 48.0), "expected_time_to_cash_hours", minimum=0.0)
    automation = _number(campaign.get("automation_completeness", 0.9), "automation_completeness", minimum=0.0, maximum=1.0)
    capital_required = _number(campaign.get("capital_required_usd", 0.0), "capital_required_usd", minimum=0.0)
    remaining_budget = _number(campaign.get("remaining_budget_usd", expected_revenue), "remaining_budget_usd", minimum=0.0)

    # Dates and compliance
    source_checked_at = _iso(campaign.get("source_checked_at"), "source_checked_at")
    deadline = _iso(campaign.get("deadline"), "deadline")
    payment_method = _text(campaign.get("payment_method", "escrow_payout"), "payment_method", max_length=80)
    payout_formula = _text(campaign.get("payout_formula", f"USD {expected_revenue:.2f} per verified clipped video"), "payout_formula", max_length=200)

    fingerprint = hashlib.sha256(f"content-reward|{source_platform}|{campaign_id}".encode()).hexdigest()[:24]

    return {
        "opportunity_id": fingerprint,
        "source_platform": f"content-reward:{source_platform}",
        "campaign_id": campaign_id,
        "title": title,
        "category": category,
        "allowed_countries": allowed_countries,
        "platforms": platforms,
        "source_assets": source_assets,
        "usage_rights": usage_rights,
        "rights_verification_state": rights_verified,
        "disclosure_requirements": campaign.get("disclosure_requirements", []),
        "account_requirements": campaign.get("account_requirements", ["creator-account"]),
        "expected_production_cost": production_cost,
        "estimated_success_probability": success_probability,
        "probability_collection": collection_probability,
        "expected_revenue": expected_revenue,
        "expected_laptop_minutes": laptop_minutes,
        "expected_owner_minutes": 0,
        "expected_time_to_cash_hours": time_to_cash,
        "automation_completeness": automation,
        "capital_required": capital_required,
        "compliance_risk": campaign.get("compliance_risk", "LOW"),
        "platform_risk": campaign.get("platform_risk", "LOW"),
        "duplicate_conflict_status": campaign.get("duplicate_conflict_status", "CLEAR"),
        "user_attention_requirement": campaign.get("user_attention_requirement", "NONE"),
        "source_checked_at": source_checked_at,
        "freshness_ttl_seconds": 86400,
        "deadline": deadline,
        "remaining_budget": remaining_budget,
        "payout_formula": payout_formula,
        "originality_requirements": campaign.get("originality_requirements", "Licensed clip stream editing"),
        "approval_rules": campaign.get("approval_rules", "Automated view and engagement verification"),
        "payment_method": payment_method,
        "minimum_thresholds": campaign.get("minimum_thresholds", {"min_views": 1000}),
        "payout_cap": _number(campaign.get("payout_cap_usd", expected_revenue), "payout_cap_usd", minimum=0.0),
        "content_reward_evidence": {
            "source_platform": source_platform,
            "campaign_id": campaign_id,
            "rights_attested": campaign.get("rights_attested", True),
            "read_only_discovery": True,
        },
    }
