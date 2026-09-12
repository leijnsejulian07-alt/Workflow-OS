import unittest

from workflow_os.plaid_bank_receipt import normalize_plaid_bank_receipt


class PlaidBankReceiptEvidenceTests(unittest.TestCase):
    def _raw(self):
        return {
            "transaction_id": "plaid-tx-1",
            "account_id": "settlement-account-1",
            "amount": -25.50,
            "iso_currency_code": "EUR",
            "unofficial_currency_code": None,
            "date": "2026-09-12",
            "name": "AWIN PAYMENT 12345",
            "pending": False,
        }

    def test_normalizes_posted_eur_credit(self):
        evidence = normalize_plaid_bank_receipt(self._raw())
        self.assertEqual(evidence.amount_cents, 2550)
        self.assertEqual(evidence.currency, "EUR")
        self.assertEqual(len(evidence.evidence_sha256), 64)

    def test_pending_fails_closed(self):
        raw = self._raw()
        raw["pending"] = True
        with self.assertRaisesRegex(ValueError, "pending"):
            normalize_plaid_bank_receipt(raw)

    def test_unknown_pending_state_fails_closed(self):
        raw = self._raw()
        raw.pop("pending")
        with self.assertRaisesRegex(ValueError, "pending"):
            normalize_plaid_bank_receipt(raw)

    def test_outgoing_transaction_fails_closed(self):
        raw = self._raw()
        raw["amount"] = 25.50
        with self.assertRaisesRegex(ValueError, "incoming credit"):
            normalize_plaid_bank_receipt(raw)

    def test_non_eur_fails_closed(self):
        raw = self._raw()
        raw["iso_currency_code"] = "USD"
        with self.assertRaisesRegex(ValueError, "EUR"):
            normalize_plaid_bank_receipt(raw)

    def test_unofficial_currency_fails_closed(self):
        raw = self._raw()
        raw["unofficial_currency_code"] = "EUR"
        with self.assertRaisesRegex(ValueError, "official EUR"):
            normalize_plaid_bank_receipt(raw)

    def test_subcent_amount_fails_closed(self):
        raw = self._raw()
        raw["amount"] = "-25.501"
        with self.assertRaisesRegex(ValueError, "two decimal"):
            normalize_plaid_bank_receipt(raw)

    def test_evidence_digest_is_deterministic(self):
        first = normalize_plaid_bank_receipt(self._raw())
        second = normalize_plaid_bank_receipt(self._raw())
        self.assertEqual(first.evidence_sha256, second.evidence_sha256)


if __name__ == "__main__":
    unittest.main()
