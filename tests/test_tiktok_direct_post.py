import unittest

from workflow_os.adapters.tiktok_direct_post import (
    TIKTOK_STATUS_FETCH_URL,
    TIKTOK_VIDEO_INIT_URL,
    TikTokCreatorSnapshot,
    TikTokDirectPostOptions,
    build_status_request,
    build_upload_request,
    build_video_init_request,
    parse_status_response,
    parse_upload_response,
    parse_video_init_response,
    plan_file_upload,
)
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


DIGEST = "a" * 64


class TikTokDirectPostTests(unittest.TestCase):
    def valid_request(self, **changes):
        values = {
            "opportunity_id": "opp-123",
            "source_platform": "whop",
            "campaign_url": "https://whop.com/content-rewards/campaign-123",
            "destination_url": "https://www.tiktok.com/upload",
            "caption": "Campaign clip",
            "asset": SubmissionAsset("renders/clip.mp4", "video/mp4", 6_000_000, DIGEST),
            "rights_verified": True,
            "account_authorized": True,
            "disclosure_satisfied": True,
            "campaign_requirements_verified": True,
        }
        values.update(changes)
        return SubmissionRequest(**values)

    def options(self, **changes):
        values = {
            "privacy_level": "SELF_ONLY",
            "creator_snapshot": TikTokCreatorSnapshot(("SELF_ONLY", "PUBLIC_TO_EVERYONE"), True),
            "explicit_user_consent": True,
            "client_audited": False,
            "is_aigc": False,
        }
        values.update(changes)
        return TikTokDirectPostOptions(**values)

    def test_builds_official_video_init_request_with_chunk_contract(self):
        built = build_video_init_request(
            self.valid_request(),
            options=self.options(),
            access_token="token-123",
        )
        self.assertEqual(built.url, TIKTOK_VIDEO_INIT_URL)
        self.assertEqual(built.headers["Authorization"], "Bearer token-123")
        source = built.json_body["source_info"]
        self.assertEqual(source["source"], "FILE_UPLOAD")
        self.assertEqual(source["video_size"], 6_000_000)
        self.assertEqual(source["chunk_size"], 6_000_000)
        self.assertEqual(source["total_chunk_count"], 1)
        self.assertEqual(built.json_body["post_info"]["privacy_level"], "SELF_ONLY")

    def test_unaudited_client_fails_closed_to_private(self):
        with self.assertRaises(ValueError):
            build_video_init_request(
                self.valid_request(),
                options=self.options(privacy_level="PUBLIC_TO_EVERYONE"),
                access_token="token-123",
            )

    def test_audited_client_may_use_creator_supported_public_option(self):
        built = build_video_init_request(
            self.valid_request(),
            options=self.options(privacy_level="PUBLIC_TO_EVERYONE", client_audited=True),
            access_token="token-123",
        )
        self.assertEqual(built.json_body["post_info"]["privacy_level"], "PUBLIC_TO_EVERYONE")

    def test_privacy_must_exist_in_latest_creator_snapshot(self):
        with self.assertRaises(ValueError):
            build_video_init_request(
                self.valid_request(),
                options=self.options(
                    privacy_level="PUBLIC_TO_EVERYONE",
                    client_audited=True,
                    creator_snapshot=TikTokCreatorSnapshot(("SELF_ONLY",), True),
                ),
                access_token="token-123",
            )

    def test_creator_info_and_explicit_consent_are_required(self):
        with self.assertRaises(ValueError):
            build_video_init_request(
                self.valid_request(),
                options=self.options(creator_snapshot=TikTokCreatorSnapshot(("SELF_ONLY",), False)),
                access_token="token-123",
            )
        with self.assertRaises(ValueError):
            build_video_init_request(
                self.valid_request(),
                options=self.options(explicit_user_consent=False),
                access_token="token-123",
            )

    def test_central_submission_evidence_remains_mandatory(self):
        for field in (
            "rights_verified",
            "account_authorized",
            "disclosure_satisfied",
            "campaign_requirements_verified",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    build_video_init_request(
                        self.valid_request(**{field: False}),
                        options=self.options(),
                        access_token="token-123",
                    )

    def test_rejects_unsupported_media_and_oversized_caption(self):
        with self.assertRaises(ValueError):
            build_video_init_request(
                self.valid_request(asset=SubmissionAsset("renders/a.gif", "image/gif", 1000, DIGEST)),
                options=self.options(),
                access_token="token-123",
            )
        with self.assertRaises(ValueError):
            build_video_init_request(
                self.valid_request(caption="x" * 2201),
                options=self.options(),
                access_token="token-123",
            )

    def test_access_token_is_bounded_and_non_whitespace(self):
        for token in ("", " ", "bad token", "x" * 4097):
            with self.subTest(token_len=len(token)):
                with self.assertRaises(ValueError):
                    build_video_init_request(self.valid_request(), options=self.options(), access_token=token)

    def test_parses_confirmed_init_response(self):
        result = parse_video_init_response(
            {
                "data": {
                    "publish_id": "v_pub_123",
                    "upload_url": "https://open-upload.tiktokapis.com/upload/?upload_id=123&upload_token=abc",
                },
                "error": {"code": "ok", "message": "", "log_id": "log-1"},
            }
        )
        self.assertEqual(result.publish_id, "v_pub_123")
        self.assertTrue(result.upload_url.startswith("https://open-upload.tiktokapis.com/"))

    def test_init_response_fails_closed_on_error_or_unexpected_upload_origin(self):
        with self.assertRaises(ValueError):
            parse_video_init_response({"data": {}, "error": {"code": "access_token_invalid"}})
        for url in (
            "https://evil.example/upload/123",
            "https://open-upload.tiktokapis.com.evil.example/upload/123",
            "https://user@open-upload.tiktokapis.com/upload/123",
            "http://open-upload.tiktokapis.com/upload/123",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    parse_video_init_response(
                        {
                            "data": {"publish_id": "v_pub_123", "upload_url": url},
                            "error": {"code": "ok"},
                        }
                    )

    def test_plans_whole_file_and_large_sequential_chunks(self):
        whole = plan_file_upload(4 * 1024 * 1024)
        self.assertEqual(whole.total_chunk_count, 1)
        self.assertEqual(whole.chunk_size, 4 * 1024 * 1024)
        self.assertEqual(whole.chunks[0].content_range, f"bytes 0-{4 * 1024 * 1024 - 1}/{4 * 1024 * 1024}")

        large_size = 130 * 1024 * 1024
        chunked = plan_file_upload(large_size)
        self.assertEqual(chunked.total_chunk_count, 2)
        self.assertEqual(chunked.chunk_size, 64 * 1024 * 1024)
        self.assertEqual(chunked.chunks[0].start_byte, 0)
        self.assertEqual(chunked.chunks[1].start_byte, 64 * 1024 * 1024)
        self.assertEqual(chunked.chunks[1].end_byte, large_size - 1)

    def test_upload_request_uses_exact_range_and_expected_status(self):
        plan = plan_file_upload(130 * 1024 * 1024)
        built = build_upload_request(
            "https://open-upload.tiktokapis.com/video/?upload_id=123&upload_token=abc",
            media_type="video/mp4",
            chunk=plan.chunks[0],
        )
        self.assertEqual(built.headers["Content-Length"], str(64 * 1024 * 1024))
        self.assertEqual(built.headers["Content-Range"], plan.chunks[0].content_range)
        self.assertTrue(parse_upload_response(206, is_final_chunk=False))
        self.assertTrue(parse_upload_response(201, is_final_chunk=True))
        with self.assertRaises(ValueError):
            parse_upload_response(201, is_final_chunk=False)
        with self.assertRaises(ValueError):
            parse_upload_response(500, is_final_chunk=True)

    def test_builds_bounded_status_request(self):
        built = build_status_request(publish_id="v_pub_123", access_token="token-123")
        self.assertEqual(built.url, TIKTOK_STATUS_FETCH_URL)
        self.assertEqual(built.json_body, {"publish_id": "v_pub_123"})
        self.assertEqual(built.headers["Authorization"], "Bearer token-123")
        for publish_id in ("", "bad id", "x" * 65):
            with self.subTest(publish_id=publish_id):
                with self.assertRaises(ValueError):
                    build_status_request(publish_id=publish_id, access_token="token-123")

    def test_status_processing_is_not_mistaken_for_success(self):
        parsed = parse_status_response(
            {
                "data": {"status": "PROCESSING_UPLOAD", "uploaded_bytes": 1234},
                "error": {"code": "ok"},
            }
        )
        self.assertFalse(parsed.terminal)
        self.assertFalse(parsed.succeeded)
        self.assertEqual(parsed.uploaded_bytes, 1234)

    def test_status_publish_complete_and_failed_are_terminal(self):
        complete = parse_status_response(
            {
                "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [123456789]},
                "error": {"code": "ok"},
            }
        )
        self.assertTrue(complete.terminal)
        self.assertTrue(complete.succeeded)
        self.assertEqual(complete.post_ids, ("123456789",))

        failed = parse_status_response(
            {
                "data": {"status": "FAILED", "fail_reason": "file_format_check_failed"},
                "error": {"code": "ok"},
            }
        )
        self.assertTrue(failed.terminal)
        self.assertFalse(failed.succeeded)
        self.assertEqual(failed.fail_reason, "file_format_check_failed")

    def test_status_fails_closed_on_unknown_or_malformed_state(self):
        bad_payloads = (
            {"data": {"status": "SOMETHING_NEW"}, "error": {"code": "ok"}},
            {"data": {"status": "FAILED"}, "error": {"code": "ok"}},
            {"data": {"status": "PUBLISH_COMPLETE", "fail_reason": "unexpected"}, "error": {"code": "ok"}},
            {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [True]}, "error": {"code": "ok"}},
            {"data": {"status": "PROCESSING_UPLOAD", "uploaded_bytes": -1}, "error": {"code": "ok"}},
            {"data": {}, "error": {"code": "access_token_invalid"}},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_status_response(payload)


if __name__ == "__main__":
    unittest.main()
