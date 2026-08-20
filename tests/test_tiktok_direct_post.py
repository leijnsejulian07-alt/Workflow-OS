import unittest

from workflow_os.adapters.tiktok_direct_post import (
    TIKTOK_VIDEO_INIT_URL,
    TikTokCreatorSnapshot,
    TikTokDirectPostOptions,
    build_video_init_request,
    parse_video_init_response,
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

    def test_builds_official_video_init_request(self):
        built = build_video_init_request(
            self.valid_request(),
            options=self.options(),
            access_token="token-123",
        )
        self.assertEqual(built.url, TIKTOK_VIDEO_INIT_URL)
        self.assertEqual(built.headers["Authorization"], "Bearer token-123")
        self.assertEqual(built.json_body["source_info"]["source"], "FILE_UPLOAD")
        self.assertEqual(built.json_body["source_info"]["video_size"], 6_000_000)
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

    def test_init_response_fails_closed_on_error_or_unexpected_upload_host(self):
        with self.assertRaises(ValueError):
            parse_video_init_response({"data": {}, "error": {"code": "access_token_invalid"}})
        with self.assertRaises(ValueError):
            parse_video_init_response(
                {
                    "data": {
                        "publish_id": "v_pub_123",
                        "upload_url": "https://evil.example/upload/123",
                    },
                    "error": {"code": "ok"},
                }
            )


if __name__ == "__main__":
    unittest.main()
