import unittest

from workflow_os.word_index_highlights import (
    WordSpanProposal,
    WordTiming,
    candidates_from_word_spans,
)


class WordIndexHighlightTests(unittest.TestCase):
    def setUp(self):
        self.words = [
            WordTiming(0, 100, 300),
            WordTiming(1, 320, 600),
            WordTiming(2, 610, 900),
            WordTiming(3, 920, 1300),
        ]
        self.proposal = WordSpanProposal(
            candidate_id="hook-1",
            start_word_index=1,
            end_word_index=3,
            hook_score=0.9,
            relevance_score=0.8,
            quality_score=0.7,
        )

    def test_resolves_word_indices_to_measured_timing(self):
        candidates = candidates_from_word_spans(
            self.words,
            [self.proposal],
            analysis_evidence=b"transcript-and-analysis",
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.candidate_id, "hook-1")
        self.assertEqual(candidate.start_ms, 320)
        self.assertEqual(candidate.duration_ms, 980)
        self.assertEqual(len(candidate.analysis_evidence_sha256), 64)

    def test_rejects_non_contiguous_or_overlapping_word_timings(self):
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                [WordTiming(0, 0, 200), WordTiming(2, 210, 400)],
                [self.proposal],
                analysis_evidence=b"evidence",
            )
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                [WordTiming(0, 0, 300), WordTiming(1, 250, 500)],
                [WordSpanProposal("x", 0, 1, 0.5, 0.5, 0.5)],
                analysis_evidence=b"evidence",
            )

    def test_rejects_out_of_range_or_reversed_spans(self):
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                self.words,
                [WordSpanProposal("x", 0, 9, 0.5, 0.5, 0.5)],
                analysis_evidence=b"evidence",
            )
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                self.words,
                [WordSpanProposal("x", 3, 1, 0.5, 0.5, 0.5)],
                analysis_evidence=b"evidence",
            )

    def test_rejects_bad_scores_duplicate_ids_and_empty_evidence(self):
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                self.words,
                [WordSpanProposal("x", 0, 1, float("nan"), 0.5, 0.5)],
                analysis_evidence=b"evidence",
            )
        duplicate = WordSpanProposal("hook-1", 0, 1, 0.5, 0.5, 0.5)
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                self.words,
                [self.proposal, duplicate],
                analysis_evidence=b"evidence",
            )
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                self.words,
                [self.proposal],
                analysis_evidence=b"",
            )

    def test_rejects_boolean_indices(self):
        with self.assertRaises(ValueError):
            candidates_from_word_spans(
                [WordTiming(True, 0, 100)],
                [WordSpanProposal("x", 0, 0, 0.5, 0.5, 0.5)],
                analysis_evidence=b"evidence",
            )


if __name__ == "__main__":
    unittest.main()
