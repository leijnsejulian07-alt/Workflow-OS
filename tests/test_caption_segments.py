import unittest

from workflow_os.caption_segments import CaptionSegment, TranscriptWord, plan_caption_segments
from workflow_os.word_index_highlights import WordTiming


def w(index: int, start: int, end: int, text: str) -> TranscriptWord:
    return TranscriptWord(WordTiming(index, start, end), text)


class CaptionSegmentTests(unittest.TestCase):
    def test_segments_are_clip_relative_and_bounded(self):
        words = [
            w(0, 900, 1200, "hello"),
            w(1, 1200, 1500, "world"),
            w(2, 1500, 1800, "from"),
            w(3, 1800, 2100, "workflow"),
        ]
        result = plan_caption_segments(
            words,
            clip_start_ms=1000,
            clip_duration_ms=1000,
            max_words_per_segment=2,
        )
        self.assertEqual(
            result,
            [
                CaptionSegment(0, 500, "hello world", 0, 1),
                CaptionSegment(500, 1000, "from workflow", 2, 3),
            ],
        )

    def test_character_limit_splits_segments(self):
        words = [w(0, 0, 300, "abc"), w(1, 300, 600, "def"), w(2, 600, 900, "ghi")]
        result = plan_caption_segments(
            words,
            clip_start_ms=0,
            clip_duration_ms=1000,
            max_words_per_segment=6,
            max_chars_per_segment=7,
        )
        self.assertEqual([item.text for item in result], ["abc def", "ghi"])

    def test_duration_limit_splits_segments(self):
        words = [w(0, 0, 400, "one"), w(1, 1400, 1800, "two")]
        result = plan_caption_segments(
            words,
            clip_start_ms=0,
            clip_duration_ms=2000,
            max_segment_ms=1000,
        )
        self.assertEqual([item.text for item in result], ["one", "two"])

    def test_no_words_in_clip_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "does not contain"):
            plan_caption_segments(
                [w(0, 0, 100, "one")],
                clip_start_ms=1000,
                clip_duration_ms=500,
            )

    def test_bad_timing_and_indices_fail_closed(self):
        cases = [
            [w(1, 0, 100, "one")],
            [w(0, 100, 100, "one")],
            [w(0, 100, 200, "one"), w(1, 150, 250, "two")],
        ]
        for words in cases:
            with self.subTest(words=words):
                with self.assertRaises(ValueError):
                    plan_caption_segments(words, clip_start_ms=0, clip_duration_ms=500)

    def test_bad_text_fails_closed(self):
        for text in ["", "   ", "x" * 201, "bad\x00word"]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    plan_caption_segments(
                        [w(0, 0, 100, text)],
                        clip_start_ms=0,
                        clip_duration_ms=500,
                    )

    def test_boolean_and_invalid_limits_fail_closed(self):
        words = [w(0, 0, 100, "one")]
        cases = [
            {"clip_start_ms": True, "clip_duration_ms": 500},
            {"clip_start_ms": 0, "clip_duration_ms": 249},
            {"clip_start_ms": 0, "clip_duration_ms": 500, "max_words_per_segment": 0},
            {"clip_start_ms": 0, "clip_duration_ms": 500, "max_chars_per_segment": 0},
            {"clip_start_ms": 0, "clip_duration_ms": 500, "max_segment_ms": 249},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    plan_caption_segments(words, **kwargs)

    def test_single_word_over_limits_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "duration"):
            plan_caption_segments(
                [w(0, 0, 1500, "longword")],
                clip_start_ms=0,
                clip_duration_ms=2000,
                max_segment_ms=1000,
            )
        with self.assertRaisesRegex(ValueError, "character"):
            plan_caption_segments(
                [w(0, 0, 100, "longword")],
                clip_start_ms=0,
                clip_duration_ms=500,
                max_chars_per_segment=4,
            )


if __name__ == "__main__":
    unittest.main()
