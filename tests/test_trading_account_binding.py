import unittest
from datetime import datetime, timedelta, timezone

from workflow_os.trading_account_binding import (
    assess_account_binding,
    normalize_account_binding_evidence,
)


NOW = datetime(2026, 8, 27, 19, 15, tzinfo=timezone.utc)
BASE = {
    "provider": "Tradeify",
    "program": "Growth 25K Evaluation -> Growth Sim Funded",
    "account_id": "acct-owner-bound-1",
    "account_owned_by_owner": True,
    "funded_activation_verified": True,
    "kyc_aml_verified": True,
    "payout_verification_complete": True,
    "credential_binding_verified": True,
    "credential_scope": "TRADE_ONLY",
    "production_enable_approved": True,
    "checked_at": "2026-08-27T19:10:00+00:00",
    "evidence_sha256": "a" * 64,
}


class TradingAccountBindingTests(unittest.TestCase):
    def decision(self, **overrides):
        raw = dict(BASE)
        raw.update(overrides)
        evidence = normalize_account_binding_evidence(raw)
        return assess_account_binding(
            evidence,
            expected_provider="Tradeify",
            expected_program="Growth 25K Evaluation -> Growth Sim Funded",
            now=NOW,
        )

    def test_complete_binding_is_prepare_only_not_execution(self):
        decision = self.decision()
        self.assertEqual(decision.decision, "PREPARE_ONLY")
        self.assertTrue(decision.may_prepare_live_execution)
        self.assertEqual(decision.reasons, ())

    def test_missing_kyc_fails_closed(self):
        decision = self.decision(kyc_aml_verified=False)
        self.assertEqual(decision.decision, "HOLD")
        self.assertIn("KYC_AML_NOT_VERIFIED", decision.reasons)

    def test_missing_payout_verification_fails_closed(self):
        decision = self.decision(payout_verification_complete=False)
        self.assertIn("PAYOUT_VERIFICATION_NOT_COMPLETE", decision.reasons)

    def test_account_ownership_is_required(self):
        decision = self.decision(account_owned_by_owner=False)
        self.assertIn("ACCOUNT_OWNERSHIP_NOT_VERIFIED", decision.reasons)

    def test_funded_activation_is_required(self):
        decision = self.decision(funded_activation_verified=False)
        self.assertIn("FUNDED_ACCOUNT_NOT_ACTIVATED", decision.reasons)

    def test_credentials_must_be_bound_and_least_privilege(self):
        decision = self.decision(
            credential_binding_verified=False,
            credential_scope="ADMIN",
        )
        self.assertIn("LEAST_PRIVILEGE_CREDENTIAL_BINDING_NOT_VERIFIED", decision.reasons)
        self.assertIn("CREDENTIAL_SCOPE_NOT_LEAST_PRIVILEGE", decision.reasons)

    def test_owner_production_enable_is_required(self):
        decision = self.decision(production_enable_approved=False)
        self.assertIn("PRODUCTION_ENABLE_NOT_OWNER_APPROVED", decision.reasons)

    def test_provider_identity_drift_fails_closed(self):
        decision = self.decision(provider="OtherFirm")
        self.assertIn("PROVIDER_OR_PROGRAM_IDENTITY_MISMATCH", decision.reasons)

    def test_stale_evidence_fails_closed(self):
        decision = self.decision(checked_at="2026-08-25T19:10:00+00:00")
        self.assertIn("ACCOUNT_EVIDENCE_STALE", decision.reasons)

    def test_future_evidence_fails_closed(self):
        decision = self.decision(checked_at="2026-08-27T20:00:00+00:00")
        self.assertIn("ACCOUNT_EVIDENCE_FROM_FUTURE", decision.reasons)

    def test_boolean_fields_are_strict(self):
        raw = dict(BASE)
        raw["kyc_aml_verified"] = "yes"
        with self.assertRaisesRegex(ValueError, "kyc_aml_verified must be boolean"):
            normalize_account_binding_evidence(raw)

    def test_invalid_max_evidence_age_is_rejected(self):
        evidence = normalize_account_binding_evidence(dict(BASE))
        with self.assertRaisesRegex(ValueError, "max_evidence_age"):
            assess_account_binding(
                evidence,
                expected_provider="Tradeify",
                expected_program="Growth 25K Evaluation -> Growth Sim Funded",
                now=NOW,
                max_evidence_age=timedelta(0),
            )


if __name__ == "__main__":
    unittest.main()
