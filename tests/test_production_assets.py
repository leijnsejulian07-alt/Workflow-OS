import unittest

from workflow_os.production_assets import ProductionAssetManifest, evaluate_production_asset


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


class ProductionAssetGateTests(unittest.TestCase):
    def test_accepts_fully_verified_asset(self):
        decision = evaluate_production_asset(valid_manifest())
        self.assertTrue(decision.ready)
        self.assertTrue(decision.asset_key.startswith("asset:"))

    def test_is_deterministic_for_same_manifest(self):
        first = evaluate_production_asset(valid_manifest())
        second = evaluate_production_asset(valid_manifest())
        self.assertEqual(first.asset_key, second.asset_key)

    def test_changed_digest_changes_asset_key(self):
        first = evaluate_production_asset(valid_manifest())
        second = evaluate_production_asset(valid_manifest(sha256="b" * 64))
        self.assertNotEqual(first.asset_key, second.asset_key)

    def test_unknown_rights_fail_closed(self):
        decision = evaluate_production_asset(valid_manifest(source_material_rights_verified=False))
        self.assertFalse(decision.ready)
        self.assertIsNone(decision.asset_key)

    def test_missing_campaign_evidence_fails_closed(self):
        decision = evaluate_production_asset(valid_manifest(campaign_requirements_verified=False))
        self.assertFalse(decision.ready)

    def test_failed_qc_cannot_reach_submission(self):
        decision = evaluate_production_asset(valid_manifest(qc_passed=False))
        self.assertFalse(decision.ready)

    def test_path_traversal_is_rejected(self):
        decision = evaluate_production_asset(valid_manifest(relative_path="../secret.mp4"))
        self.assertFalse(decision.ready)

    def test_absolute_path_is_rejected(self):
        decision = evaluate_production_asset(valid_manifest(relative_path="/tmp/final.mp4"))
        self.assertFalse(decision.ready)

    def test_malformed_digest_is_rejected(self):
        decision = evaluate_production_asset(valid_manifest(sha256="not-a-digest"))
        self.assertFalse(decision.ready)

    def test_unsupported_media_type_is_rejected(self):
        decision = evaluate_production_asset(valid_manifest(media_type="application/octet-stream"))
        self.assertFalse(decision.ready)

    def test_boolean_size_is_rejected(self):
        decision = evaluate_production_asset(valid_manifest(size_bytes=True))
        self.assertFalse(decision.ready)

    def test_invalid_manifest_type_fails_closed(self):
        decision = evaluate_production_asset({})
        self.assertFalse(decision.ready)
        self.assertIsNone(decision.asset_key)


if __name__ == "__main__":
    unittest.main()
