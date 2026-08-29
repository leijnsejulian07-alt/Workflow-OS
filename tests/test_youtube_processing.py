import unittest

from workflow_os.adapters.youtube_processing import (
    parse_terminal_upload_video_id,
    parse_video_processing_response,
)


class YouTubeProcessingEvidenceTests(unittest.TestCase):
    def test_terminal_upload_extracts_bounded_video_identity_only(self):
        self.assertEqual(parse_terminal_upload_video_id({"id": "abcDEF_123-"}), "abcDEF_123-")
        for payload in ({}, {"id": ""}, {"id": "has space"}, {"id": "x/y"}, {"id": 123}):
            with self.subTest(payload=payload):
                with self.assertRaises((TypeError, ValueError)):
                    parse_terminal_upload_video_id(payload)

    def test_processing_success_requires_exact_identity_and_both_success_signals(self):
        payload = {
            "items": [
                {
                    "id": "abcDEF_123-",
                    "status": {"uploadStatus": "processed"},
                    "processingDetails": {"processingStatus": "succeeded"},
                }
            ]
        }
        result = parse_video_processing_response(payload, expected_video_id="abcDEF_123-")
        self.assertEqual(result.state, "SUCCEEDED")
        self.assertTrue(result.terminal_publication_verified)
        self.assertEqual(result.video_id, "abcDEF_123-")

    def test_missing_duplicate_or_wrong_identity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_video_processing_response({"items": []}, expected_video_id="abcDEF_123-")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_video_processing_response(
                {"items": [{"id": "abcDEF_123-"}, {"id": "abcDEF_123-"}]},
                expected_video_id="abcDEF_123-",
            )
        with self.assertRaisesRegex(ValueError, "unexpected"):
            parse_video_processing_response(
                {
                    "items": [
                        {
                            "id": "other_ID-123",
                            "status": {"uploadStatus": "processed"},
                            "processingDetails": {"processingStatus": "succeeded"},
                        }
                    ]
                },
                expected_video_id="abcDEF_123-",
            )

    def test_processing_and_unknown_states_never_gain_terminal_authority(self):
        processing = parse_video_processing_response(
            {
                "items": [
                    {
                        "id": "abcDEF_123-",
                        "status": {"uploadStatus": "uploaded"},
                        "processingDetails": {"processingStatus": "processing"},
                    }
                ]
            },
            expected_video_id="abcDEF_123-",
        )
        self.assertEqual(processing.state, "PROCESSING")
        self.assertFalse(processing.terminal_publication_verified)

        unknown = parse_video_processing_response(
            {
                "items": [
                    {
                        "id": "abcDEF_123-",
                        "status": {"uploadStatus": "processed"},
                        "processingDetails": {"processingStatus": "terminated"},
                    }
                ]
            },
            expected_video_id="abcDEF_123-",
        )
        self.assertEqual(unknown.state, "UNKNOWN")
        self.assertFalse(unknown.terminal_publication_verified)

    def test_processing_failure_and_rejected_upload_fail_terminally(self):
        failed = parse_video_processing_response(
            {
                "items": [
                    {
                        "id": "abcDEF_123-",
                        "status": {"uploadStatus": "uploaded"},
                        "processingDetails": {
                            "processingStatus": "failed",
                            "processingFailureReason": "transcodeFailed",
                        },
                    }
                ]
            },
            expected_video_id="abcDEF_123-",
        )
        self.assertEqual(failed.state, "FAILED")
        self.assertFalse(failed.terminal_publication_verified)
        self.assertEqual(failed.failure_reason, "transcodeFailed")

        rejected = parse_video_processing_response(
            {
                "items": [
                    {
                        "id": "abcDEF_123-",
                        "status": {"uploadStatus": "rejected"},
                        "processingDetails": {"processingStatus": "succeeded"},
                    }
                ]
            },
            expected_video_id="abcDEF_123-",
        )
        self.assertEqual(rejected.state, "FAILED")
        self.assertFalse(rejected.terminal_publication_verified)

    def test_conflicting_failure_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            parse_video_processing_response(
                {
                    "items": [
                        {
                            "id": "abcDEF_123-",
                            "status": {"uploadStatus": "processed"},
                            "processingDetails": {
                                "processingStatus": "succeeded",
                                "processingFailureReason": "other",
                            },
                        }
                    ]
                },
                expected_video_id="abcDEF_123-",
            )

    def test_malformed_response_shape_fails_closed(self):
        with self.assertRaises(TypeError):
            parse_video_processing_response([], expected_video_id="abcDEF_123-")
        with self.assertRaises(TypeError):
            parse_video_processing_response({"items": {}}, expected_video_id="abcDEF_123-")
        with self.assertRaises(TypeError):
            parse_video_processing_response({"items": ["x"]}, expected_video_id="abcDEF_123-")
        with self.assertRaises(TypeError):
            parse_video_processing_response(
                {"items": [{"id": "abcDEF_123-", "status": {}, "processingDetails": "x"}]},
                expected_video_id="abcDEF_123-",
            )


if __name__ == "__main__":
    unittest.main()
