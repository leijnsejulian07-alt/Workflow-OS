import unittest

from workflow_os.project_scope import ProjectScope, ScopeMismatchError, ScopedAccessContext
from workflow_os.research_provenance import ResearchEvidenceLedger


class TestResearchProvenance(unittest.TestCase):
    def ctx(self, project="a", repo="org/repo", epoch=1):
        return ScopedAccessContext(ProjectScope("chat", project, repo), epoch)

    def test_scope_epoch_and_secret_minimization(self):
        ledger = ResearchEvidenceLedger()
        a1 = self.ctx()
        item = ledger.record(
            context=a1,
            evidence_id="e1",
            claim_id="c1",
            source_url="https://Example.com/doc?q=secret-token#frag",
            source_title=" Example   source ",
            excerpt="private excerpt body",
        )
        self.assertEqual(item.source_url, "https://example.com/doc")
        self.assertNotIn("private excerpt", repr(item))
        self.assertIsNotNone(ledger.get(context=a1, evidence_id="e1"))
        self.assertIsNone(ledger.get(context=self.ctx(project="b"), evidence_id="e1"))
        self.assertIsNone(ledger.get(context=self.ctx(epoch=2), evidence_id="e1"))
        with self.assertRaises(ScopeMismatchError):
            item.require_context(self.ctx(project="b"))
        with self.assertRaises(ScopeMismatchError):
            item.require_context(self.ctx(epoch=2))

    def test_same_id_isolated_per_scope(self):
        ledger = ResearchEvidenceLedger()
        a = self.ctx(project="a")
        b = self.ctx(project="b")
        ledger.record(
            context=a,
            evidence_id="same",
            claim_id="a",
            source_url="https://a.example/x",
            source_title="A",
            excerpt="A body",
        )
        ledger.record(
            context=b,
            evidence_id="same",
            claim_id="b",
            source_url="https://b.example/x",
            source_title="B",
            excerpt="B body",
        )
        self.assertEqual(ledger.get(context=a, evidence_id="same").claim_id, "a")
        self.assertEqual(ledger.get(context=b, evidence_id="same").claim_id, "b")
        self.assertEqual(len(ledger.list_for_context(context=a)), 1)
        self.assertEqual(len(ledger.list_for_context(context=b)), 1)

    def test_claim_coverage_tracks_challenges_without_scope_leaks(self):
        ledger = ResearchEvidenceLedger()
        a = self.ctx(project="a", epoch=7)
        b = self.ctx(project="b", epoch=7)
        stale = self.ctx(project="a", epoch=6)

        ledger.record(
            context=a,
            evidence_id="support-1",
            claim_id="claim-x",
            source_url="https://one.example/report?token=hidden",
            source_title="Support one",
            excerpt="supporting material",
            relationship="supports",
        )
        ledger.record(
            context=a,
            evidence_id="challenge-1",
            claim_id="claim-x",
            source_url="https://two.example/rebuttal",
            source_title="Challenge one",
            excerpt="contradicting material",
            relationship="challenges",
        )
        ledger.record(
            context=a,
            evidence_id="context-1",
            claim_id="claim-x",
            source_url="https://one.example/background",
            source_title="Context",
            excerpt="background material",
            relationship="context",
        )
        ledger.record(
            context=b,
            evidence_id="other-project",
            claim_id="claim-x",
            source_url="https://leak.example/other",
            source_title="Other project",
            excerpt="must not count",
            relationship="challenges",
        )
        ledger.record(
            context=stale,
            evidence_id="stale",
            claim_id="claim-x",
            source_url="https://stale.example/old",
            source_title="Old epoch",
            excerpt="must not count",
            relationship="supports",
        )

        coverage = ledger.coverage_for_claim(context=a, claim_id="claim-x")
        self.assertEqual(coverage.evidence_count, 3)
        self.assertEqual(coverage.supporting_count, 1)
        self.assertEqual(coverage.challenging_count, 1)
        self.assertEqual(coverage.context_count, 1)
        self.assertEqual(coverage.distinct_source_hosts, 2)
        self.assertTrue(coverage.has_challenge)
        self.assertEqual(len(ledger.list_for_claim(context=a, claim_id="claim-x")), 3)
        self.assertEqual(ledger.coverage_for_claim(context=b, claim_id="claim-x").evidence_count, 1)
        self.assertEqual(ledger.coverage_for_claim(context=stale, claim_id="claim-x").evidence_count, 1)

    def test_invalid_relationship_is_rejected(self):
        with self.assertRaises(ValueError):
            ResearchEvidenceLedger().record(
                context=self.ctx(),
                evidence_id="e1",
                claim_id="c1",
                source_url="https://example.com/x",
                source_title="source",
                excerpt="body",
                relationship="maybe",
            )


if __name__ == "__main__":
    unittest.main()