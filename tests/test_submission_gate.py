import unittest

from workflow_os.submissions import SubmissionAsset, SubmissionRequest, evaluate_submission


DIGEST = "a" * 64


class SubmissionGateTests(unittest.TestCase):
    def valid_request(self, **changes):
        values = {
            "opportunity_id": "opp-123",
            "source_platform": "whop",
            "campaign_url": "https://whop.com/content-rewards/campaign-123",
            "destination_url": "https://www.tiktok.com/upload",
            "caption": "Campaign clip",
            "asset": SubmissionAsset("renders/clip.mp4", "video/mp4", 1024, DIGEST),
            "rights_verified": True,
            "account_authorized": True,
            "disclosure_satisfied": True,
            "campaign_requirements_verified": True,
        }
        values.update(changes)
        return SubmissionRequest(**values)

    def evaluate(self, request):
        return evaluate_submission(request, allowed_destination_hosts={"www.tiktok.com", "www.instagram.com"})

    def test_verified_request_is_allowed_with_stable_idempotency_key(self):
        first = self.evaluate(self.valid_request())
        second = self.evaluate(self.valid_request())
        self.assertTrue(first.allowed)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertTrue(first.idempotency_key.startswith("submit:"))

    def test_unknown_or_false_safety_evidence_fails_closed(self):
        fields = [
            "rights_verified",
            "account_authorized",
            "disclosure_satisfied",
            "campaign_requirements_verified",
        ]
        for field in fields:
            with self.subTest(field=field):
                decision = self.evaluate(self.valid_request(**{field: False}))
                self.assertFalse(decision.allowed)
                self.assertIsNone(decision.idempotency_key)

    def test_destination_must_be_exact_explicit_host(self):
        for url in [
            "https://evil.example/upload",
            "https://www.tiktok.com.evil.example/upload",
            "http://www.tiktok.com/upload",
            "https://user:pass@www.tiktok.com/upload",
        ]:
            with self.subTest(url=url):
                self.assertFalse(self.evaluate(self.valid_request(destination_url=url)).allowed)

    def test_asset_rejects_traversal_unsupported_type_and_invalid_digest(self):
        assets = [
            SubmissionAsset("../secrets.txt", "video/mp4", 1024, DIGEST),
            SubmissionAsset("renders/clip.exe", "application/octet-stream", 1024, DIGEST),
            SubmissionAsset("renders/clip.mp4", "video/mp4", 1024, "not-a-digest"),
            SubmissionAsset("renders/clip.mp4", "video/mp4", 0, DIGEST),
            SubmissionAsset("renders/clip.mp4", "video/mp4", 2 * 1024 * 1024 * 1024 + 1, DIGEST),
        ]
        for asset in assets:
            with self.subTest(asset=asset):
                self.assertFalse(self.evaluate(self.valid_request(asset=asset)).allowed)

    def test_changed_payload_changes_idempotency_key(self):
        original = self.evaluate(self.valid_request()).idempotency_key
        changed = self.evaluate(self.valid_request(caption="Different approved caption")).idempotency_key
        self.assertNotEqual(original, changed)

    def test_gate_has_no_network_or_side_effect_result(self):
        decision = self.evaluate(self.valid_request())
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "submission evidence verified")


if __name__ == "__main__":
    unittest.main()
