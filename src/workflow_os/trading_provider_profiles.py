from __future__ import annotations

from .trading_provider_rules import ProviderRuleEvidence, normalize_provider_rule_evidence

TRADEIFY_GROWTH_25K_PROFILE_VERSION = "tradeify-growth-25k/2026-08-26"


def tradeify_growth_25k_profile() -> ProviderRuleEvidence:
    """Return the evidence-bound Tradeify Growth 25K provider profile.

    Sources are official Tradeify help-center pages checked on 2026-08-26.
    This profile verifies that Tradeify permits personal bots under conditions and
    that Tradeify-supported Rithmic credentials can be used with Quantower, whose
    official Tradeify setup guide explicitly lists custom automated strategies.

    Live trading remains disabled here. Provider capability evidence is not the
    same as possession of an account, credentials, KYC completion, or authority
    to emit an order.
    """
    return normalize_provider_rule_evidence(
        {
            "provider": "Tradeify",
            "program": "Growth 25K Evaluation -> Growth Sim Funded",
            "account_size": 25_000,
            "account_currency": "USD",
            "purchase_cost": 99,
            "rule_version": TRADEIFY_GROWTH_25K_PROFILE_VERSION,
            "checked_at": "2026-08-26T01:15:00+02:00",
            "official_source_urls": [
                "https://help.tradeify.co/en/articles/10495915-growth-evaluation-accounts",
                "https://help.tradeify.co/en/articles/11083796-growth-funded-account-payout-policy",
                "https://help.tradeify.co/en/articles/10468318-guidelines-for-traders",
                "https://help.tradeify.co/en/articles/10468221-supported-platforms",
                "https://help.tradeify.co/en/articles/12294317-quantower-setup-guide",
                "https://help.tradeify.co/en/articles/14369021-tradeify-pricing-reference",
            ],
            "evidence_sha256": "8aa465f9f13bfb27360906785dcd84838bd1fbd20a22108ccc4f03062c874bff",
            "automation_state": "CONDITIONAL",
            "automation_requires_written_approval": False,
            "execution_access_state": "VERIFIED",
            "daily_loss_limit": 600,
            "max_drawdown": 1_000,
            "max_position_contracts": 1,
            "payout_share_pct": 90,
            "prohibited_strategies": [
                "HFT",
                "HEDGING",
                "CORRELATED_HEDGING",
                "SHARED_BOT_ACROSS_FIRMS",
            ],
            "restricted_times": [],
            "production_enabled": False,
        }
    )
