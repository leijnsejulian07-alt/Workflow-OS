import unittest
from dataclasses import replace

from workflow_os.website_fulfillment_gate import FulfillmentGateDecision, WebsiteScopeSnapshot
from workflow_os.website_static_build import (
    BuiltStaticFile,
    StaticPageInput,
    WebsiteBuildArtifact,
    WebsiteContentSpec,
    build_static_site,
    qa_static_site,
)


class WebsiteStaticBuildTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = WebsiteScopeSnapshot(
            opportunity_id="website:test:1",
            lead_id="lead-1",
            pages=2,
            fixed_price_eur=350.0,
            quote_expires_at="2026-09-01T12:00:00+00:00",
            usage_rights="customer_attested_owned_or_licensed_content",
            customer_controls_domain=True,
            recurring_maintenance=False,
            mobile_responsive=True,
            basic_seo_metadata=True,
            contact_or_cta=True,
            payment_method="invoice_or_supported_payment_link",
            approval_rules="fixed_scope_no_recurring_maintenance",
            source_checked_at="2026-08-27T10:00:00+00:00",
            snapshot_sha256="a" * 64,
        )
        self.gate = FulfillmentGateDecision(
            state="READY_FOR_BOUNDED_BUILD",
            reason="PAYMENT_EVIDENCE_ACCEPTED_NOT_YET_RECONCILED_AS_REVENUE",
            opportunity_id=self.snapshot.opportunity_id,
            scope_sha256=self.snapshot.snapshot_sha256,
            payment_reference="pay-1",
        )
        self.content = WebsiteContentSpec(
            site_title="Voorbeeldbedrijf",
            description="Een eenvoudige website voor een lokaal bedrijf.",
            pages=(
                StaticPageInput("index", "Home", "Welkom bij ons bedrijf.\n\nWij helpen klanten graag."),
                StaticPageInput("over-ons", "Over ons", "Wij leveren een duidelijke vaste dienst."),
            ),
            contact_label="Neem contact op",
            contact_href="mailto:info@example.com",
        )

    def test_build_and_qa_pass_without_external_side_effects(self):
        artifact = build_static_site(self.snapshot, self.gate, self.content)
        self.assertEqual(artifact.opportunity_id, self.snapshot.opportunity_id)
        self.assertEqual(len(artifact.files), 2)
        self.assertEqual({f.path for f in artifact.files}, {"index.html", "over-ons/index.html"})
        self.assertNotIn("<script", artifact.files[0].content.lower())
        decision = qa_static_site(self.snapshot, artifact)
        self.assertEqual(decision.state, "PASS_FOR_HANDOFF_RESERVATION")
        self.assertEqual(decision.reason, "STATIC_BUILD_QA_PASSED_NO_DEPLOYMENT_PERFORMED")

    def test_customer_html_is_escaped_not_executed(self):
        hostile = replace(
            self.content,
            pages=(
                StaticPageInput("index", "<script>alert(1)</script>", "<img src=https://evil.example/a>"),
                self.content.pages[1],
            ),
        )
        artifact = build_static_site(self.snapshot, self.gate, hostile)
        combined = "\n".join(f.content for f in artifact.files)
        self.assertNotIn("<script>alert(1)</script>", combined)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", combined)
        self.assertNotIn("<img src=https://evil.example/a>", combined)
        self.assertEqual(qa_static_site(self.snapshot, artifact).state, "PASS_FOR_HANDOFF_RESERVATION")

    def test_build_requires_ready_identity_bound_payment_gate(self):
        with self.assertRaisesRegex(ValueError, "not ready"):
            build_static_site(self.snapshot, replace(self.gate, state="HOLD"), self.content)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            build_static_site(self.snapshot, replace(self.gate, opportunity_id="other"), self.content)

    def test_scope_page_count_and_safe_slugs_are_enforced(self):
        one_page = replace(self.content, pages=(self.content.pages[0],))
        with self.assertRaisesRegex(ValueError, "page count"):
            build_static_site(self.snapshot, self.gate, one_page)
        unsafe = replace(
            self.content,
            pages=(StaticPageInput("../escape", "Bad", "Bad"), self.content.pages[1]),
        )
        with self.assertRaisesRegex(ValueError, "slug"):
            build_static_site(self.snapshot, self.gate, unsafe)

    def test_remote_contact_and_active_urls_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "mailto"):
            build_static_site(self.snapshot, self.gate, replace(self.content, contact_href="https://tracker.example/contact"))
        with self.assertRaisesRegex(ValueError, "mailto"):
            build_static_site(self.snapshot, self.gate, replace(self.content, contact_href="javascript:alert(1)"))

    def test_qa_detects_digest_tampering(self):
        artifact = build_static_site(self.snapshot, self.gate, self.content)
        first = artifact.files[0]
        tampered = replace(first, content=first.content + "tamper")
        bad = replace(artifact, files=(tampered,) + artifact.files[1:])
        decision = qa_static_site(self.snapshot, bad)
        self.assertEqual(decision.state, "HOLD")
        self.assertEqual(decision.reason, "ARTIFACT_SIZE_MISMATCH")

    def test_qa_detects_broken_internal_link(self):
        artifact = build_static_site(self.snapshot, self.gate, self.content)
        first = artifact.files[0]
        mutated_content = first.content.replace('href="/over-ons/"', 'href="/missing/"')
        mutated = BuiltStaticFile(
            path=first.path,
            content=mutated_content,
            sha256=__import__("hashlib").sha256(mutated_content.encode("utf-8")).hexdigest(),
            size_bytes=len(mutated_content.encode("utf-8")),
        )
        total = mutated.size_bytes + sum(f.size_bytes for f in artifact.files[1:])
        bad = WebsiteBuildArtifact(
            opportunity_id=artifact.opportunity_id,
            scope_sha256=artifact.scope_sha256,
            files=(mutated,) + artifact.files[1:],
            manifest_sha256=artifact.manifest_sha256,
            total_bytes=total,
        )
        decision = qa_static_site(self.snapshot, bad)
        self.assertEqual(decision.state, "HOLD")
        self.assertEqual(decision.reason, "BROKEN_INTERNAL_LINK")

    def test_qa_rejects_remote_dependency_even_if_artifact_is_mutated_consistently(self):
        artifact = build_static_site(self.snapshot, self.gate, self.content)
        first = artifact.files[0]
        mutated_content = first.content.replace("</head>", '<link rel="stylesheet" href="https://evil.example/x.css"></head>')
        import hashlib
        mutated = BuiltStaticFile(
            path=first.path,
            content=mutated_content,
            sha256=hashlib.sha256(mutated_content.encode("utf-8")).hexdigest(),
            size_bytes=len(mutated_content.encode("utf-8")),
        )
        bad = replace(
            artifact,
            files=(mutated,) + artifact.files[1:],
            total_bytes=mutated.size_bytes + sum(f.size_bytes for f in artifact.files[1:]),
        )
        decision = qa_static_site(self.snapshot, bad)
        self.assertEqual(decision.state, "HOLD")
        self.assertEqual(decision.reason, "REMOTE_DEPENDENCY_PROHIBITED")


if __name__ == "__main__":
    unittest.main()
