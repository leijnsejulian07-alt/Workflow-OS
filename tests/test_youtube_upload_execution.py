import hashlib
import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.youtube_http_transport import (
    YouTubeHttpResponse,
    YouTubeHttpTransport,
    YouTubeInitResponse,
)
from workflow_os.adapters.youtube_upload import YouTubeProjectEvidence, YouTubeUploadOptions
from workflow_os.adapters.youtube_upload_execution import (
    YouTubePollingPolicy,
    execute_youtube_upload_attempt,
)
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


class FakeTransport(YouTubeHttpTransport):
    def __init__(self, upload_responses, processing_responses):
        self.upload_responses = list(upload_responses)
        self.processing_responses = list(processing_responses)
        self.uploaded_ranges = []
        self.processing_calls = 0

    def initialize(self, init):
        return YouTubeInitResponse(
            session_url="https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
            status_code=200,
        )

    def upload_chunk(self, upload, chunk):
        self.uploaded_ranges.append((upload.start_byte, upload.end_byte, len(chunk)))
        return self.upload_responses.pop(0)

    def fetch_processing(self, status_request):
        self.processing_calls += 1
        return self.processing_responses.pop(0)


class YouTubeUploadExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.asset_path = self.root / "video.mp4"
        self.asset_path.write_bytes(b"x" * 300_000)
        digest = hashlib.sha256(self.asset_path.read_bytes()).hexdigest()
        self.request = SubmissionRequest(
            opportunity_id="yt:owned:1",
            source_platform="youtube",
            campaign_url="https://www.youtube.com/",
            destination_url="https://www.youtube.com/",
            caption="caption",
            asset=SubmissionAsset(
                path="video.mp4",
                media_type="video/mp4",
                size_bytes=300_000,
                sha256=digest,
            ),
            rights_verified=True,
            account_authorized=True,
            disclosure_satisfied=True,
            campaign_requirements_verified=True,
        )
        self.options = YouTubeUploadOptions(
            title="Owned video",
            description="description",
            category_id="22",
            category_id_verified=True,
            privacy_status="private",
            self_declared_made_for_kids=False,
            project_evidence=YouTubeProjectEvidence(
                api_project_verified=False,
                owned_channel_verified=True,
                upload_scope_verified=True,
            ),
        )

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def processing(status="processing", upload="uploaded", failure=None):
        details = {"processingStatus": status}
        if failure is not None:
            details["processingFailureReason"] = failure
        return {
            "items": [
                {
                    "id": "video123",
                    "status": {"uploadStatus": upload},
                    "processingDetails": details,
                }
            ]
        }

    def test_success_requires_terminal_processing_evidence(self):
        transport = FakeTransport(
            [
                YouTubeHttpResponse(308, {"Range": "bytes=0-262143"}, b""),
                YouTubeHttpResponse(200, {}, b'{"id":"video123"}'),
            ],
            [self.processing(), self.processing(status="succeeded", upload="processed")],
        )
        sleeps = []
        result = execute_youtube_upload_attempt(
            self.request,
            options=self.options,
            access_token="token123",
            asset_root=self.root,
            transport=transport,
            polling=YouTubePollingPolicy(max_polls=2, interval_seconds=1),
            sleep=sleeps.append,
            chunk_size=256 * 1024,
        )
        self.assertEqual(result.outcome, "APPLIED")
        self.assertEqual(result.external_reference, "youtube:video123")
        self.assertEqual(sleeps, [1.0])
        self.assertEqual(
            transport.uploaded_ranges,
            [(0, 262143, 262144), (262144, 299999, 37856)],
        )

    def test_mismatched_308_range_fails_closed_unknown(self):
        transport = FakeTransport(
            [YouTubeHttpResponse(308, {"Range": "bytes=0-100"}, b"")],
            [],
        )
        result = execute_youtube_upload_attempt(
            self.request,
            options=self.options,
            access_token="token123",
            asset_root=self.root,
            transport=transport,
            sleep=lambda _: None,
            chunk_size=256 * 1024,
        )
        self.assertEqual(result.outcome, "UNKNOWN")

    def test_processing_failure_is_definitely_not_applied(self):
        transport = FakeTransport(
            [
                YouTubeHttpResponse(308, {"Range": "bytes=0-262143"}, b""),
                YouTubeHttpResponse(200, {}, b'{"id":"video123"}'),
            ],
            [self.processing(status="failed", upload="failed", failure="transcode")],
        )
        result = execute_youtube_upload_attempt(
            self.request,
            options=self.options,
            access_token="token123",
            asset_root=self.root,
            transport=transport,
            sleep=lambda _: None,
            chunk_size=256 * 1024,
        )
        self.assertEqual(result.outcome, "NOT_APPLIED")

    def test_asset_drift_blocks_before_network_side_effect(self):
        self.asset_path.write_bytes(b"y" * 300_000)
        transport = FakeTransport([], [])
        with self.assertRaisesRegex(ValueError, "digest no longer matches"):
            execute_youtube_upload_attempt(
                self.request,
                options=self.options,
                access_token="token123",
                asset_root=self.root,
                transport=transport,
                sleep=lambda _: None,
                chunk_size=256 * 1024,
            )
        self.assertEqual(transport.uploaded_ranges, [])

    def test_polling_policy_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 60"):
            YouTubePollingPolicy(max_polls=61)
        with self.assertRaisesRegex(ValueError, "between 1 and 300"):
            YouTubePollingPolicy(interval_seconds=0.5)


if __name__ == "__main__":
    unittest.main()
