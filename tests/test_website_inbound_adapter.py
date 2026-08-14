from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workflow_os.adapters.website_inbound import to_opportunity
from workflow_os.opportunities import evaluate, normalize


def valid_lead() -> dict:
    return {
        "lead_id": "lead-123",
        "business_name": "Example Bakery",
        "acquisition_channel": "inbound_form",
        "explicit_request_for_website": True,
        "commercial_contact_consent": True,
        "recurring_maintenance_requested": False,
        "page_count": 4,
        "price_eur": 350,
        "expected_production_cost_eur": 15,
        "expected_laptop_minutes": 45,
        "estimated_success_probability": 0.8,
        "probability_collection": 0.95,
        "expected_time_to_cash_hours": 72,
        "automation_completeness": 1,
        "capital_required_eur": 0,
        "content_rights_grant": "Customer grants rights to use submitted text and images for preview and delivered website.",
        "customer_controls_domain": True,
        "source_checked_at": "2026-08-15T00:00:00+02:00",
        "quote_expires_at": "2026-08-20T23:59:59+02:00",
        "customer_budget_eur": 500,
        "country_code": "NL",
        "payment_method": "hosted checkout",
    }


class WebsiteInboundAdapterTests(unittest.TestCase):
    def test_valid_opt_in_lead_reaches_accept(self):
        raw = to_opportunity(valid_lead())
        normalized = normalize(raw, now=datetime(2026, 8, 14, 22, 5, tzinfo=timezone.utc))
        decision = evaluate(normalized, now=datetime(2026, 8, 14, 22, 5, tzinfo=timezone.utc))
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)
        self.assertEqual(normalized["expected_owner_minutes"], 0)

    def test_unsolicited_channel_is_rejected(self):
        lead = valid_lead()
        lead["acquisition_channel"] = "cold_email"
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_missing_commercial_contact_consent_is_rejected(self):
        lead = valid_lead()
        lead["commercial_contact_consent"] = False
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_recurring_maintenance_is_rejected(self):
        lead = valid_lead()
        lead["recurring_maintenance_requested"] = True
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_customer_must_control_domain(self):
        lead = valid_lead()
        lead["customer_controls_domain"] = False
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_scope_is_bounded_to_five_pages(self):
        lead = valid_lead()
        lead["page_count"] = 6
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_rights_grant_is_required(self):
        lead = valid_lead()
        lead["content_rights_grant"] = ""
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_fractional_page_count_is_rejected(self):
        lead = valid_lead()
        lead["page_count"] = 2.5
        with self.assertRaises(ValueError):
            to_opportunity(lead)

    def test_non_finite_economics_are_rejected(self):
        for field, value in (
            ("price_eur", "NaN"),
            ("expected_production_cost_eur", "Infinity"),
            ("expected_laptop_minutes", "-Infinity"),
            ("probability_collection", float("nan")),
            ("customer_budget_eur", float("inf")),
        ):
            with self.subTest(field=field, value=value):
                lead = valid_lead()
                lead[field] = value
                with self.assertRaises(ValueError):
                    to_opportunity(lead)

    def test_same_lead_identity_is_deterministic(self):
        first = to_opportunity(valid_lead())
        second = to_opportunity(valid_lead())
        self.assertEqual(first["opportunity_id"], second["opportunity_id"])


if __name__ == "__main__":
    unittest.main()
