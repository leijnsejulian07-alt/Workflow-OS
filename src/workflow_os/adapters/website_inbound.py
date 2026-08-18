from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any

ALLOWED_ACQUISITION_CHANNELS = {
    "inbound_form",
    "marketplace_opt_in",
    "referral",
    "partner_referral",
    "paid_ad_inbound",
}
MAX_PAGES = 5
MIN_PRICE_EUR = 1.0
MAX_TEXT = 2000


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


def _number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
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


def to_opportunity(lead: dict[str, Any]) -> dict[str, Any]:
    """Normalize an explicitly opt-in Website-in-a-Box lead into Opportunity Manager input."""
    if not isinstance(lead, dict):
        raise ValueError("lead must be an object")

    channel = _text(lead.get("acquisition_channel"), "acquisition_channel", max_length=64)
    if channel not in ALLOWED_ACQUISITION_CHANNELS:
        raise ValueError("acquisition_channel is not an approved opt-in/inbound channel")
    if lead.get("explicit_request_for_website") is not True:
        raise ValueError("explicit_request_for_website must be true")
    if lead.get("commercial_contact_consent") is not True:
        raise ValueError("commercial_contact_consent must be true")
    if lead.get("recurring_maintenance_requested") is not False:
        raise ValueError("recurring_maintenance_requested must be explicitly false")

    pages_number = _number(lead.get("page_count"), "page_count", minimum=1, maximum=MAX_PAGES)
    pages = int(pages_number)
    if float(pages) != pages_number:
        raise ValueError("page_count must be a whole number")

    price = _number(lead.get("price_eur"), "price_eur", minimum=MIN_PRICE_EUR)
    production_cost = _number(lead.get("expected_production_cost_eur"), "expected_production_cost_eur", minimum=0)
    laptop_minutes = _number(lead.get("expected_laptop_minutes"), "expected_laptop_minutes", minimum=0)
    success_probability = _number(lead.get("estimated_success_probability"), "estimated_success_probability", minimum=0, maximum=1)
    collection_probability = _number(lead.get("probability_collection"), "probability_collection", minimum=0, maximum=1)
    time_to_cash = _number(lead.get("expected_time_to_cash_hours"), "expected_time_to_cash_hours", minimum=0)
    automation = _number(lead.get("automation_completeness"), "automation_completeness", minimum=0, maximum=1)
    capital_required = _number(lead.get("capital_required_eur"), "capital_required_eur", minimum=0)

    rights_grant = _text(lead.get("content_rights_grant"), "content_rights_grant")
    if lead.get("content_rights_attested") is not True:
        raise ValueError("content_rights_attested must be true")
    if lead.get("customer_controls_domain") is not True:
        raise ValueError("customer_controls_domain must be true")

    lead_id = _text(lead.get("lead_id"), "lead_id", max_length=128)
    business_name = _text(lead.get("business_name"), "business_name", max_length=200)
    source_checked_at = _iso(lead.get("source_checked_at"), "source_checked_at")
    deadline = _iso(lead.get("quote_expires_at"), "quote_expires_at")
    remaining_budget = _number(lead.get("customer_budget_eur"), "customer_budget_eur", minimum=0)
    payment_method = _text(lead.get("payment_method"), "payment_method", max_length=80)

    fingerprint = hashlib.sha256(f"website-in-a-box|{channel}|{lead_id}".encode()).hexdigest()[:24]
    return {
        "opportunity_id": fingerprint,
        "source_platform": f"website-in-a-box:{channel}",
        "campaign_id": lead_id,
        "title": f"Website-in-a-Box — {business_name}",
        "category": "website_in_a_box",
        "allowed_countries": [_text(lead.get("country_code"), "country_code", max_length=2).upper()],
        "platforms": ["static_web"],
        "source_assets": [],
        "usage_rights": rights_grant,
        "rights_verification_state": "VERIFIED",
        "disclosure_requirements": [],
        "account_requirements": ["customer-controlled-domain"],
        "expected_production_cost": production_cost,
        "estimated_success_probability": success_probability,
        "probability_collection": collection_probability,
        "expected_revenue": price,
        "expected_laptop_minutes": laptop_minutes,
        "expected_owner_minutes": 0,
        "expected_time_to_cash_hours": time_to_cash,
        "automation_completeness": automation,
        "capital_required": capital_required,
        "compliance_risk": "LOW",
        "platform_risk": "LOW",
        "duplicate_conflict_status": "CLEAR",
        "user_attention_requirement": "NONE",
        "source_checked_at": source_checked_at,
        "freshness_ttl_seconds": 86400,
        "deadline": deadline,
        "remaining_budget": remaining_budget,
        "payout_formula": f"EUR {price:.2f} fixed-price website job",
        "originality_requirements": "Customer-provided or licensed content only",
        "approval_rules": "Fixed-scope automated QA before deployment",
        "payment_method": payment_method,
        "minimum_thresholds": {"page_count": 1},
        "payout_cap": price,
        "website_scope": {
            "pages": pages,
            "mobile_responsive": True,
            "basic_seo_metadata": True,
            "contact_or_cta": True,
            "recurring_maintenance": False,
            "customer_controls_domain": True,
        },
        "lead_evidence": {
            "acquisition_channel": channel,
            "explicit_request_for_website": True,
            "commercial_contact_consent": True,
            "recurring_maintenance_requested": False,
            "content_rights_attested": True,
            "content_rights_grant": rights_grant,
        },
    }