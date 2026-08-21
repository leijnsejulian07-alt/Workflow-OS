import unittest

from workflow_os.clip_selection import (
    ClipCandidate,
    evidence_digest_for_analysis,
    select_clip_candidate,
)
from workflow_os.production_handoff import ProducerOutput


class ClipSelectionTests(unittest.TestCase):
    def setUp(self):
        self.source = ProducerOutput(
            relative_path="input/source.mp4",
            media_type="video/mp4",
            size_bytes=1234,
            sha256="a" * 64,
            producer="local-media-ingest-v1",
        )
        self.digest = "b" * 64

    def candidate(self, **overrides):
        values = dict(
            candidate_id="clip-a",
            start_ms=1000,
            duration_ms=15000,
            hook_score=0.8,
            relevance_score=0.7,
            quality_score=0.9,
            analysis_evidence_sha256=self.digest,
        )
        values.update(overrides)
        return ClipCandidate(**values)

    def test_selects_highest_weighted_candidate(self):
        lower = self.candidate(candidate_id="lower", hook_score=0.6)
        higher = self.candidate(candidate_id="higher", hook_score=0.95)
        selected = select_clip_candidate(
            self.source,
            [lower, higher],
            output_relative_path="render/selected.mp4",
        )
        self.assertEqual(selected.candidate_id, "higher")
        self.assertEqual(selected.render_spec.start_ms, 1000)
        self.assertEqual(selected.render_spec.duration_ms, 15000)
        self.assertEqual(selected.render_spec.source, self.source)
        self.assertEqual(selected.analysis_evidence_sha256, self.digest)

    def test_tie_break_is_deterministic(self):
        later = self.candidate(candidate_id="z", start_ms=2000)
        earlier = self.candidate(candidate_id="a", start_ms=1000)
        selected = select_clip_candidate(
            self.source,
            [later, earlier],
            output_relative_path="render/tie.mp4",
        )
        self.assertEqual(selected.candidate_id, "a")

    def test_rejects_duplicate_candidate_ids(self):
        with self.assertRaises(ValueError):
            select_clip_candidate(
                self.source,
                [self.candidate(), self.candidate()],
                output_relative_path="render/x.mp4",
            )

    def test_rejects_empty_or_excessive_candidate_sets(self):
        with self.assertRaises(ValueError):
            select_clip_candidate(self.source, [], output_relative_path="render/x.mp4")
        with self.assertRaises(ValueError):
            select_clip_candidate(
                self.source,
                [self.candidate(candidate_id=f"c{i}") for i in range(101)],
                output_relative_path="render/x.mp4",
            )

    def test_rejects_non_finite_and_out_of_range_scores(self):
        for bad in (-0.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(score=bad):
                with self.assertRaises(ValueError):
                    select_clip_candidate(
                        self.source,
                        [self.candidate(hook_score=bad)],
                        output_relative_path="render/x.mp4",
                    )

    def test_rejects_bad_timing_and_digest(self):
        with self.assertRaises(ValueError):
            select_clip_candidate(
                self.source,
                [self.candidate(duration_ms=0)],
                output_relative_path="render/x.mp4",
            )
        with self.assertRaises(ValueError):
            select_clip_candidate(
                self.source,
                [self.candidate(analysis_evidence_sha256="bad")],
                output_relative_path="render/x.mp4",
            )

    def test_analysis_digest_is_stable_and_bounded(self):
        self.assertEqual(
            evidence_digest_for_analysis(b"analysis"),
            "f44e85c4b8ea2addc796f8beab6600e801d767ccd26c800dce6d88fdaa5eb4e6",
        )
        with self.assertRaises(ValueError):
            evidence_digest_for_analysis(b"")
        with self.assertRaises(ValueError):
            evidence_digest_for_analysis("analysis")


if __name__ == "__main__":
    unittest.main()
