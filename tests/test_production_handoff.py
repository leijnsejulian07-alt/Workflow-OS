import unittest

from workflow_os.production_handoff import (
    ProducerOutput,
    TrustedProductionEvidence,
    build_production_manifest,
)


DIGEST = "a" * 64


def valid_output(**overrides):
    values = {
        "relative_path": "outputs/opp-1/final.mp4",
        "media_type": "video/mp4",
        "size_bytes": 1024,
        "sha256": DIGEST,
        "producer": "autoclip-adapter-v1",
    }
    values.update(overrides)
    return ProducerOutput(**values)


def valid_evidence(**overrides):
    values = {
        "opportunity_id": "opp-1",
        "campaign_id": "campaign-1",
        "source_material_rights_verified": True,
        "campaign_requirements_verified": True,
        "disclosure_satisfied": True,
        "qc_passed": True,
    }
    values.update(overrides)
    return TrustedProductionEvidence(**values)


class ProductionHandoffTests(unittest.TestCase):
    def test_builds_manifest_from_independent_evidence(self):
        manifest = build_production_manifest(valid_output(), valid_evidence())
        self.assertEqual(manifest.opportunity_id, "opp-1")
        self.assertEqual(manifest.producer, "autoclip-adapter-v1")
        self.assertTrue(manifest.source_material_rights_verified)

    def test_producer_cannot_supply_publication_evidence(self):
        with self.assertRaises(TypeError):
            ProducerOutput(
                relative_path="outputs/final.mp4",
                media_type="video/mp4",
                size_bytes=10,
                sha256=DIGEST,
                producer="external",
                source_material_rights_verified=True,
            )

    def test_unknown_rights_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "rights"):
            build_production_manifest(
                valid_output(),
                valid_evidence(source_material_rights_verified=False),
            )

    def test_failed_qc_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "QC"):
            build_production_manifest(valid_output(), valid_evidence(qc_passed=False))

    def test_path_traversal_is_rejected_before_handoff(self):
        with self.assertRaisesRegex(ValueError, "traversal"):
            build_production_manifest(valid_output(relative_path="../secret.mp4"), valid_evidence())

    def test_bad_digest_is_rejected_before_handoff(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_production_manifest(valid_output(sha256="bad"), valid_evidence())

    def test_boolean_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "integer"):
            build_production_manifest(valid_output(size_bytes=True), valid_evidence())

    def test_invalid_types_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "ProducerOutput"):
            build_production_manifest({}, valid_evidence())
        with self.assertRaisesRegex(ValueError, "TrustedProductionEvidence"):
            build_production_manifest(valid_output(), {})


if __name__ == "__main__":
    unittest.main()
