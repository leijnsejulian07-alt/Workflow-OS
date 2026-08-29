import unittest

from workflow_os.adapters.youtube_upload_recovery import parse_resumable_recovery_response


class YouTubeResumableRecoveryTests(unittest.TestCase):
    def test_308_without_range_restarts_from_zero_without_guessing(self):
        result = parse_resumable_recovery_response(308, {}, total_size=600_000)
        self.assertEqual(result.state, "INCOMPLETE")
        self.assertEqual(result.next_byte, 0)
        self.assertFalse(result.restart_required)
        self.assertFalse(result.processing_verification_required)

    def test_308_range_advances_to_exact_next_byte(self):
        result = parse_resumable_recovery_response(
            308,
            {"Range": "bytes=0-262143"},
            total_size=600_000,
        )
        self.assertEqual(result.state, "INCOMPLETE")
        self.assertEqual(result.next_byte, 262_144)

    def test_308_rejects_gaps_backwards_and_overflow_claims(self):
        malformed = (
            "bytes=1-262143",
            "bytes=0-x",
            "bytes 0-262143",
            "bytes=0-600000",
            "bytes=0-599999",
        )
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_resumable_recovery_response(
                        308,
                        {"Range": value},
                        total_size=600_000,
                    )

    def test_range_header_is_case_insensitive_but_duplicate_fails_closed(self):
        result = parse_resumable_recovery_response(
            308,
            {"range": "bytes=0-0"},
            total_size=10,
        )
        self.assertEqual(result.next_byte, 1)

        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_resumable_recovery_response(
                308,
                {"Range": "bytes=0-0", "range": "bytes=0-0"},
                total_size=10,
            )

    def test_404_marks_session_expired_and_requires_fresh_session(self):
        result = parse_resumable_recovery_response(404, {}, total_size=600_000)
        self.assertEqual(result.state, "SESSION_EXPIRED")
        self.assertIsNone(result.next_byte)
        self.assertTrue(result.restart_required)
        self.assertFalse(result.processing_verification_required)

    def test_terminal_2xx_requires_processing_verification_not_publication_success(self):
        result = parse_resumable_recovery_response(200, {}, total_size=600_000)
        self.assertEqual(result.state, "COMPLETE_NEEDS_PROCESSING_VERIFY")
        self.assertIsNone(result.next_byte)
        self.assertFalse(result.restart_required)
        self.assertTrue(result.processing_verification_required)

    def test_other_statuses_remain_unknown_without_retry_authority(self):
        for status in (400, 401, 403, 408, 429, 500, 503):
            with self.subTest(status=status):
                result = parse_resumable_recovery_response(status, {}, total_size=600_000)
                self.assertEqual(result.state, "UNKNOWN")
                self.assertIsNone(result.next_byte)
                self.assertFalse(result.restart_required)
                self.assertFalse(result.processing_verification_required)

    def test_non_308_range_header_is_not_trusted(self):
        with self.assertRaisesRegex(ValueError, "only trusted"):
            parse_resumable_recovery_response(
                500,
                {"Range": "bytes=0-262143"},
                total_size=600_000,
            )

    def test_input_bounds_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "HTTP status"):
            parse_resumable_recovery_response(True, {}, total_size=10)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            parse_resumable_recovery_response(308, {}, total_size=0)
        with self.assertRaisesRegex(TypeError, "mapping"):
            parse_resumable_recovery_response(308, [], total_size=10)
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse_resumable_recovery_response(
                308,
                {"Range": "x" * 129},
                total_size=10,
            )


if __name__ == "__main__":
    unittest.main()
