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


if __name__ == "__main__":
    unittest.main()
