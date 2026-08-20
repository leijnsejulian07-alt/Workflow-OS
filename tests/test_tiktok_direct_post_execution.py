import hashlib
import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.tiktok_direct_post import TikTokCreatorSnapshot, TikTokDirectPostOptions
from workflow_os.adapters.tiktok_direct_post_execution import TikTokPollingPolicy, execute_tiktok_direct_post_attempt
from workflow_os.adapters.tiktok_http_transport import TikTokHttpTransport
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


class FakeTikTokTransport(TikTokHttpTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.uploads = []

    def post_json(self, request):
        return self.responses.pop(0)

    def put_chunk(self, request, *, data, is_final_chunk):
        self.uploads.append((request, data, is_final_chunk))


class TikTokDirectPostExecutionTests(unittest.TestCase):
    def make_fixture(self, root: Path):
        data = b"video-bytes"
        path = root / "clip.mp4"
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        request = SubmissionRequest(
            opportunity_id="opp-123",
            source_platform="whop",
            campaign_url="https://whop.com/content-rewards/campaign-123",
            destination_url="https://www.tiktok.com/upload",
            caption="Campaign clip",
            asset=SubmissionAsset("clip.mp4", "video/mp4", len(data), digest),
            rights_verified=True,
            account_authorized=True,
            disclosure_satisfied=True,
            campaign_requirements_verified=True,
        )
        options = TikTokDirectPostOptions(
            privacy_level="SELF_ONLY",
            creator_snapshot=TikTokCreatorSnapshot(("SELF_ONLY",), True),
            explicit_user_consent=True,
            client_audited=False,
        )
        return request, options, data

    def init_ok(self):
        return {
            "data": {"publish_id": "v_pub_123", "upload_url": "https://open-upload.tiktokapis.com/upload/abc"},
            "error": {"code": "ok"},
        }

    def status(self, value, **extra):
        data = {"status": value, **extra}
        return {"data": data, "error": {"code": "ok"}}

    def test_complete_post_returns_applied_external_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            request, options, data = self.make_fixture(Path(tmp))
            transport = FakeTikTokTransport([self.init_ok(), self.status("PUBLISH_COMPLETE", publicaly_available_post_id=[12345])])
            result = execute_tiktok_direct_post_attempt(
                request,
                options=options,
                access_token="token",
                asset_root=tmp,
                transport=transport,
                sleep=lambda _: None,
            )
        self.assertEqual(result.outcome, "APPLIED")
        self.assertEqual(result.external_reference, "tiktok:12345")
        self.assertEqual(transport.uploads[0][1], data)
        self.assertTrue(transport.uploads[0][2])

    def test_processing_exhaustion_is_unknown_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            request, options, _ = self.make_fixture(Path(tmp))
            transport = FakeTikTokTransport([self.init_ok()] + [self.status("PROCESSING_UPLOAD")] * 3)
            sleeps = []
            result = execute_tiktok_direct_post_attempt(
                request,
                options=options,
                access_token="token",
                asset_root=tmp,
                transport=transport,
                polling=TikTokPollingPolicy(max_polls=3, interval_seconds=1),
                sleep=sleeps.append,
            )
        self.assertEqual(result.outcome, "UNKNOWN")
        self.assertEqual(sleeps, [1.0, 1.0])
        self.assertEqual(transport.responses, [])

    def test_terminal_failure_is_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            request, options, _ = self.make_fixture(Path(tmp))
            transport = FakeTikTokTransport([self.init_ok(), self.status("FAILED", fail_reason="invalid video")])
            result = execute_tiktok_direct_post_attempt(
                request,
                options=options,
                access_token="token",
                asset_root=tmp,
                transport=transport,
                sleep=lambda _: None,
            )
        self.assertEqual(result.outcome, "NOT_APPLIED")
        self.assertIsNone(result.external_reference)

    def test_complete_without_post_id_fails_closed_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            request, options, _ = self.make_fixture(Path(tmp))
            transport = FakeTikTokTransport([self.init_ok(), self.status("PUBLISH_COMPLETE")])
            result = execute_tiktok_direct_post_attempt(
                request,
                options=options,
                access_token="token",
                asset_root=tmp,
                transport=transport,
                sleep=lambda _: None,
            )
        self.assertEqual(result.outcome, "UNKNOWN")

    def test_polling_policy_is_bounded(self):
        with self.assertRaises(ValueError):
            TikTokPollingPolicy(max_polls=31)
        with self.assertRaises(ValueError):
            TikTokPollingPolicy(interval_seconds=0)


if __name__ == "__main__":
    unittest.main()
