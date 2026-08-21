import unittest

from workflow_os.production_assets import ProductionAssetManifest
from workflow_os.production_submission import ProductionSubmissionContext, build_submission_request
from workflow_os.submissions import evaluate_submission


DIGEST = "a" * 64


def valid_manifest(**overrides):
    values = {
        "opportunity_id": "opp-1",
        "campaign_id": "campaign-1",
        "relative_path": "outputs/opp-1/final.mp4",
        "media_type": "video/mp4",
        "size_bytes": 1024,
        "sha256": DIGEST,
        "producer": "autoclip-adapter-v1",
        "source_material_rights_verified": True,
        "campaign_requirements_verified": True,
        "disclosure_satisfied": True,
        "qc_passed": True,
    }
    values.update(overrides)
    return ProductionAssetManifest(**values)


def valid_context(**overrides):
    values = {
        "source_platform": "cliparmy",
        "campaign_url": "https://cliparmy.com/campaigns/example",
        "destination_url": "https://www.tiktok.com/upload",
        "caption": "Campaign-compliant caption",
        "account_authorized": True,
    }
    values.update(overrides)
    return ProductionSubmissionContext(**values)


class ProductionSubmissionBridgeTests(unittest.TestCase):
    def test_verified_manifest_becomes_submission_request(self):
        request = build_submission_request(valid_manifest(), valid_context())
        decision = evaluate_submission(request, allowed_destination_hosts={"www.tiktok.com"})
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.idempotency_key.startswith("submit:"))

    def test_asset_evidence_is_preserved_exactly(self):
        request = build_submission_request(valid_manifest(), valid_context())
        self.assertEqual(request.asset.path, "outputs/opp-1/final.mp4")
        self.assertEqual(request.asset.media_type, "video/mp4")
        self.assertEqual(request.asset.size_bytes, 1024)
        self.assertEqual(request.asset.sha256, DIGEST)

    def test_failed_qc_never_becomes_submission_request(self):
        with self.assertRaises(ValueError):
            build_submission_request(valid_manifest(qc_passed=False), valid_context())

    def test_unknown_rights_never_becomes_submission_request(self):
        with self.assertRaises(ValueError):
            build_submission_request(
                valid_manifest(source_material_rights_verified=False), valid_context()
            )

    def test_missing_campaign_evidence_never_becomes_submission_request(self):
        with self.assertRaises(ValueError):
            build_submission_request(
                valid_manifest(campaign_requirements_verified=False), valid_context()
            )

    def test_disclosure_failure_never_becomes_submission_request(self):
        with self.assertRaises(ValueError):
            build_submission_request(valid_manifest(disclosure_satisfied=False), valid_context())

    def test_account_authorization_is_not_inferred(self):
        request = build_submission_request(
            valid_manifest(), valid_context(account_authorized=False)
        )
        decision = evaluate_submission(request, allowed_destination_hosts={"www.tiktok.com"})
        self.assertFalse(decision.allowed)
        self.assertIn("not authorized", decision.reason)

    def test_destination_policy_remains_downstream_authority(self):
        request = build_submission_request(
            valid_manifest(), valid_context(destination_url="https://evil.example/upload")
        )
        decision = evaluate_submission(request, allowed_destination_hosts={"www.tiktok.com"})
        self.assertFalse(decision.allowed)
        self.assertIn("not explicitly allowed", decision.reason)

    def test_invalid_context_type_is_rejected(self):
        with self.assertRaises(ValueError):
            build_submission_request(valid_manifest(), {})


if __name__ == "__main__":
    unittest.main()
