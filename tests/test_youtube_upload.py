import unittest

from workflow_os.adapters.youtube_upload import (
    YouTubeProjectEvidence,
    YouTubeUploadOptions,
    build_resumable_init_request,
    build_upload_request,
    build_upload_status_probe,
    build_video_status_request,
)
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


class YouTubeUploadContractTests(unittest.TestCase):
    def make_request(self, **overrides):
        values = {
            "opportunity_id": "yt:owned:1",
            "source_platform": "youtube",
            "campaign_url": "https://www.youtube.com/",
            "destination_url": "https://www.youtube.com/",
            "caption": "caption",
            "asset": SubmissionAsset(
                path="assets/video.mp4",
                media_type="video/mp4",
                size_bytes=8_000_000,
                sha256="a" * 64,
            ),
            "rights_verified": True,
            "account_authorized": True,
            "disclosure_satisfied": True,
            "campaign_requirements_verified": True,
        }
        values.update(overrides)
        return SubmissionRequest(**values)

    def make_options(self, **overrides):
        values = {
            "title": "Owned video",
            "description": "description",
            "category_id": "22",
            "category_id_verified": True,
            "privacy_status": "private",
            "self_declared_made_for_kids": False,
            "project_evidence": YouTubeProjectEvidence(
                api_project_verified=False,
                owned_channel_verified=True,
                upload_scope_verified=True,
            ),
        }
        values.update(overrides)
        return YouTubeUploadOptions(**values)

    def test_unverified_project_is_private_only(self):
        with self.assertRaisesRegex(ValueError, "fail closed to private"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(privacy_status="public"),
                access_token="token123",
            )

    def test_verified_private_init_request_is_bounded_and_official(self):
        result = build_resumable_init_request(
            self.make_request(), options=self.make_options(), access_token="token123"
        )
        self.assertTrue(result.url.startswith("https://www.googleapis.com/upload/youtube/v3/videos?"))
        self.assertIn("uploadType=resumable", result.url)
        self.assertEqual(result.headers["Authorization"], "Bearer token123")
        self.assertEqual(result.headers["X-Upload-Content-Length"], "8000000")
        self.assertEqual(result.json_body["snippet"]["categoryId"], "22")
        self.assertEqual(result.json_body["status"]["privacyStatus"], "private")

    def test_category_is_required_and_must_be_verified(self):
        with self.assertRaisesRegex(ValueError, "category id is not verified"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(category_id_verified=False),
                access_token="token123",
            )
        with self.assertRaisesRegex(ValueError, "category id is malformed"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(category_id="People & Blogs"),
                access_token="token123",
            )

    def test_account_rights_scope_and_channel_evidence_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "account is not authorized"):
            build_resumable_init_request(
                self.make_request(account_authorized=False),
                options=self.make_options(),
                access_token="token123",
            )
        with self.assertRaisesRegex(ValueError, "rights are not verified"):
            build_resumable_init_request(
                self.make_request(rights_verified=False),
                options=self.make_options(),
                access_token="token123",
            )
        with self.assertRaisesRegex(ValueError, "channel identity is not verified"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(
                    project_evidence=YouTubeProjectEvidence(False, False, True)
                ),
                access_token="token123",
            )
        with self.assertRaisesRegex(ValueError, "upload scope is not verified"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(
                    project_evidence=YouTubeProjectEvidence(False, True, False)
                ),
                access_token="token123",
            )

    def test_upload_request_rejects_hostile_session_origin_and_bad_ranges(self):
        with self.assertRaisesRegex(ValueError, "unexpected origin"):
            build_upload_request(
                "https://evil.example/upload/youtube/v3/videos?upload_id=x",
                access_token="token123",
                media_type="video/mp4",
                total_size=262_144,
                start_byte=0,
                end_byte=262_143,
                chunk_size=262_144,
            )
        with self.assertRaisesRegex(ValueError, "invalid YouTube resumable byte range"):
            build_upload_request(
                "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
                access_token="token123",
                media_type="video/mp4",
                total_size=262_144,
                start_byte=0,
                end_byte=262_144,
                chunk_size=262_144,
            )

    def test_upload_request_enforces_official_chunk_granularity_and_sequence_size(self):
        url = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"
        with self.assertRaisesRegex(ValueError, "multiple of 256 KB"):
            build_upload_request(
                url,
                access_token="token123",
                media_type="video/mp4",
                total_size=600_000,
                start_byte=0,
                end_byte=199_999,
                chunk_size=200_000,
            )
        with self.assertRaisesRegex(ValueError, "planned chunk size"):
            build_upload_request(
                url,
                access_token="token123",
                media_type="video/mp4",
                total_size=800_000,
                start_byte=262_144,
                end_byte=524_287,
                chunk_size=524_288,
            )
        with self.assertRaisesRegex(ValueError, "non-final"):
            build_upload_request(
                url,
                access_token="token123",
                media_type="video/mp4",
                total_size=800_000,
                start_byte=0,
                end_byte=262_143,
                chunk_size=524_288,
            )

    def test_upload_request_has_exact_range_and_accepts_smaller_final_chunk(self):
        url = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"
        first = build_upload_request(
            url,
            access_token="token123",
            media_type="video/mp4",
            total_size=600_000,
            start_byte=0,
            end_byte=262_143,
            chunk_size=262_144,
        )
        self.assertEqual(first.headers["Content-Range"], "bytes 0-262143/600000")
        self.assertEqual(first.headers["Content-Length"], "262144")

        final = build_upload_request(
            url,
            access_token="token123",
            media_type="video/mp4",
            total_size=600_000,
            start_byte=524_288,
            end_byte=599_999,
            chunk_size=262_144,
        )
        self.assertEqual(final.headers["Content-Range"], "bytes 524288-599999/600000")
        self.assertEqual(final.headers["Content-Length"], "75712")

    def test_upload_status_probe_is_empty_put_contract_for_recovery(self):
        url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=x"
        result = build_upload_status_probe(url, access_token="token123", total_size=600_000)
        self.assertEqual(result.url, url)
        self.assertEqual(result.headers["Authorization"], "Bearer token123")
        self.assertEqual(result.headers["Content-Length"], "0")
        self.assertEqual(result.headers["Content-Range"], "bytes */600000")

        with self.assertRaisesRegex(ValueError, "unexpected origin"):
            build_upload_status_probe(
                "https://evil.example/upload/youtube/v3/videos?upload_id=x",
                access_token="token123",
                total_size=600_000,
            )
        with self.assertRaisesRegex(ValueError, "positive integer"):
            build_upload_status_probe(url, access_token="token123", total_size=0)

    def test_status_request_uses_official_api_and_bearer_auth(self):
        result = build_video_status_request("abc123", access_token="token123")
        self.assertTrue(result.url.startswith("https://www.googleapis.com/youtube/v3/videos?"))
        self.assertIn("processingDetails", result.url)
        self.assertEqual(result.headers, {"Authorization": "Bearer token123"})

    def test_tokens_and_metadata_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "token is missing or malformed"):
            build_resumable_init_request(
                self.make_request(), options=self.make_options(), access_token="bad token"
            )
        with self.assertRaisesRegex(ValueError, "title is missing or too long"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(title="x" * 101),
                access_token="token123",
            )
        with self.assertRaisesRegex(ValueError, "description exceeds allowed size"):
            build_resumable_init_request(
                self.make_request(),
                options=self.make_options(description="é" * 3000),
                access_token="token123",
            )


if __name__ == "__main__":
    unittest.main()
