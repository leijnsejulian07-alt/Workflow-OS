import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.adapters.openshorts_hosted import verify_openshorts_webhook
from workflow_os.openshorts_execution import OpenShortsTerminalEvidence
from workflow_os.openshorts_output_provenance import (
    OpenShortsOutputProvenanceStore,
    record_completed_clip_outputs,
)
from workflow_os.side_effects import SideEffectLedger


class OpenShortsOutputProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow.sqlite3"
        self.ledger = SideEffectLedger(self.path)
        self.store = OpenShortsOutputProvenanceStore(self.path)
        self.key = "openshorts:1:" + "a" * 64
        self.job_id = "job_123"
        self.secret = "s" * 40
        self.ledger.reserve(
            idempotency_key=self.key,
            action="openshorts.process",
            target="https://api.openshorts.app/api/process",
            payload={"x": 1},
            max_attempts=2,
        )
        self.ledger.begin_attempt(self.key)
        self.ledger.mark_succeeded(self.key, external_reference=self.job_id)

    def tearDown(self):
        self.tmp.cleanup()

    def _event(self, clips=None):
        payload = {
            "event": "job.completed",
            "job_id": self.job_id,
            "clips": clips if clips is not None else [
                {
                    "index": 0,
                    "title": "Best moment",
                    "video_url": "https://cdn.example.com/watch/clip-0.mp4",
                    "download_url": "https://cdn.example.com/download/clip-0.mp4",
                }
            ],
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        sig = "sha256=" + hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        event = verify_openshorts_webhook(body=body, signature_header=sig, webhook_secret=self.secret)
        evidence = OpenShortsTerminalEvidence(
            idempotency_key=self.key,
            provider_job_id=self.job_id,
            terminal_state="COMPLETED",
            evidence_sha256=event.body_sha256,
            source="webhook",
        )
        return event, evidence

    def test_records_signed_completed_clip_outputs(self):
        event, evidence = self._event()
        outputs = record_completed_clip_outputs(
            ledger=self.ledger, store=self.store,
            terminal_evidence=evidence, webhook_event=event,
        )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].clip_index, 0)
        self.assertEqual(self.store.list_for(self.key), outputs)

    def test_replay_is_idempotent(self):
        event, evidence = self._event()
        first = record_completed_clip_outputs(
            ledger=self.ledger, store=self.store,
            terminal_evidence=evidence, webhook_event=event,
        )
        second = record_completed_clip_outputs(
            ledger=self.ledger, store=self.store,
            terminal_evidence=evidence, webhook_event=event,
        )
        self.assertEqual(first, second)

    def test_rejects_non_webhook_or_failed_terminal_evidence(self):
        event, evidence = self._event()
        for bad in (
            OpenShortsTerminalEvidence(self.key, self.job_id, "COMPLETED", evidence.evidence_sha256, "status_api"),
            OpenShortsTerminalEvidence(self.key, self.job_id, "FAILED", evidence.evidence_sha256, "webhook"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(RuntimeError):
                    record_completed_clip_outputs(
                        ledger=self.ledger, store=self.store,
                        terminal_evidence=bad, webhook_event=event,
                    )

    def test_rejects_terminal_evidence_mismatch(self):
        event, evidence = self._event()
        bad = OpenShortsTerminalEvidence(self.key, self.job_id, "COMPLETED", "f" * 64, "webhook")
        with self.assertRaises(RuntimeError):
            record_completed_clip_outputs(
                ledger=self.ledger, store=self.store,
                terminal_evidence=bad, webhook_event=event,
            )

    def test_rejects_dispatch_binding_mismatch(self):
        event, evidence = self._event()
        other = OpenShortsTerminalEvidence("missing", self.job_id, "COMPLETED", evidence.evidence_sha256, "webhook")
        with self.assertRaises(RuntimeError):
            record_completed_clip_outputs(
                ledger=self.ledger, store=self.store,
                terminal_evidence=other, webhook_event=event,
            )

    def test_rejects_private_or_malformed_output_urls(self):
        bad_urls = (
            "http://cdn.example.com/x.mp4",
            "https://127.0.0.1/x.mp4",
            "https://localhost/x.mp4",
            "https://user:pass@cdn.example.com/x.mp4",
            "https://cdn.example.com/x.mp4#frag",
        )
        for index, bad_url in enumerate(bad_urls):
            with self.subTest(bad_url=bad_url):
                event, evidence = self._event([{
                    "index": index,
                    "title": "x",
                    "video_url": bad_url,
                    "download_url": f"https://cdn.example.com/good-{index}.mp4",
                }])
                with self.assertRaises(ValueError):
                    record_completed_clip_outputs(
                        ledger=self.ledger, store=self.store,
                        terminal_evidence=evidence, webhook_event=event,
                    )

    def test_rejects_duplicate_indexes_and_urls(self):
        cases = (
            [
                {"index": 0, "video_url": "https://cdn.example.com/a.mp4", "download_url": "https://cdn.example.com/b.mp4"},
                {"index": 0, "video_url": "https://cdn.example.com/c.mp4", "download_url": "https://cdn.example.com/d.mp4"},
            ],
            [
                {"index": 0, "video_url": "https://cdn.example.com/a.mp4", "download_url": "https://cdn.example.com/b.mp4"},
                {"index": 1, "video_url": "https://cdn.example.com/a.mp4", "download_url": "https://cdn.example.com/d.mp4"},
            ],
        )
        for clips in cases:
            with self.subTest(clips=clips):
                event, evidence = self._event(clips)
                with self.assertRaises(ValueError):
                    record_completed_clip_outputs(
                        ledger=self.ledger, store=self.store,
                        terminal_evidence=evidence, webhook_event=event,
                    )

    def test_conflicting_replay_is_immutable(self):
        event, evidence = self._event()
        record_completed_clip_outputs(
            ledger=self.ledger, store=self.store,
            terminal_evidence=evidence, webhook_event=event,
        )
        event2, evidence2 = self._event([{
            "index": 0,
            "title": "changed",
            "video_url": "https://cdn.example.com/changed.mp4",
            "download_url": "https://cdn.example.com/changed-download.mp4",
        }])
        with self.assertRaises(ValueError):
            record_completed_clip_outputs(
                ledger=self.ledger, store=self.store,
                terminal_evidence=evidence2, webhook_event=event2,
            )


if __name__ == "__main__":
    unittest.main()
