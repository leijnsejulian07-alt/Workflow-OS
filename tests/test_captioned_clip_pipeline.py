from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_os.adapters.ffmpeg_clip import ClipRenderSpec
from workflow_os.caption_segments import TranscriptWord
from workflow_os.caption_sidecar import CaptionSidecar
from workflow_os.captioned_clip_pipeline import produce_captioned_clip
from workflow_os.clip_selection import SelectedClip
from workflow_os.production_handoff import ProducerOutput
from workflow_os.word_index_highlights import WordTiming


class CaptionedClipPipelineTests(unittest.TestCase):
    def _workspace(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "out").mkdir()
        source = ProducerOutput(
            relative_path="source.mp4",
            media_type="video/mp4",
            size_bytes=10,
            sha256="1" * 64,
            producer="test-source",
        )
        selected = SelectedClip(
            candidate_id="candidate-1",
            render_spec=ClipRenderSpec(
                source=source,
                output_relative_path="out/clip.mp4",
                start_ms=1_000,
                duration_ms=2_000,
            ),
            ranking_score=0.9,
            analysis_evidence_sha256="a" * 64,
        )
        words = [
            TranscriptWord(WordTiming(0, 1_000, 1_400), "hello"),
            TranscriptWord(WordTiming(1, 1_500, 1_900), "world"),
        ]
        return temp, root, selected, words

    @staticmethod
    def _producer(path: str, payload: bytes, producer: str) -> ProducerOutput:
        return ProducerOutput(
            relative_path=path,
            media_type="video/mp4",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            producer=producer,
        )

    def test_success_cleans_intermediates_and_returns_final_output(self):
        temp, root, selected, words = self._workspace()
        self.addCleanup(temp.cleanup)

        def fake_render(workspace, spec, **kwargs):
            payload = b"clip"
            (root / "out" / "clip.mp4").write_bytes(payload)
            return self._producer("out/clip.mp4", payload, "clip")

        def fake_sidecar(workspace, path, segments):
            payload = b"srt"
            (root / path).write_bytes(payload)
            return CaptionSidecar(path, len(payload), hashlib.sha256(payload).hexdigest(), len(segments))

        def fake_burn(workspace, spec, **kwargs):
            payload = b"final"
            (root / "out" / "final.mp4").write_bytes(payload)
            return self._producer("out/final.mp4", payload, "caption-burn")

        with patch("workflow_os.captioned_clip_pipeline.render_clip", side_effect=fake_render), patch(
            "workflow_os.captioned_clip_pipeline.write_caption_sidecar", side_effect=fake_sidecar
        ), patch("workflow_os.captioned_clip_pipeline.burn_captions", side_effect=fake_burn):
            result = produce_captioned_clip(
                root,
                selected,
                words,
                caption_relative_path="out/clip.srt",
                output_relative_path="out/final.mp4",
            )

        self.assertEqual(result.candidate_id, "candidate-1")
        self.assertEqual(result.output.relative_path, "out/final.mp4")
        self.assertEqual(result.caption_segment_count, 1)
        self.assertFalse((root / "out" / "clip.mp4").exists())
        self.assertFalse((root / "out" / "clip.srt").exists())
        self.assertTrue((root / "out" / "final.mp4").exists())

    def test_invalid_output_path_fails_before_render(self):
        temp, root, selected, words = self._workspace()
        self.addCleanup(temp.cleanup)
        with patch("workflow_os.captioned_clip_pipeline.render_clip") as render:
            with self.assertRaises(ValueError):
                produce_captioned_clip(
                    root,
                    selected,
                    words,
                    caption_relative_path="out/clip.srt",
                    output_relative_path="../final.mp4",
                )
        render.assert_not_called()

    def test_invalid_transcript_fails_before_render(self):
        temp, root, selected, _ = self._workspace()
        self.addCleanup(temp.cleanup)
        with patch("workflow_os.captioned_clip_pipeline.render_clip") as render:
            with self.assertRaises(ValueError):
                produce_captioned_clip(
                    root,
                    selected,
                    [],
                    caption_relative_path="out/clip.srt",
                    output_relative_path="out/final.mp4",
                )
        render.assert_not_called()

    def test_burn_failure_cleans_created_intermediates(self):
        temp, root, selected, words = self._workspace()
        self.addCleanup(temp.cleanup)

        def fake_render(workspace, spec, **kwargs):
            payload = b"clip"
            (root / "out" / "clip.mp4").write_bytes(payload)
            return self._producer("out/clip.mp4", payload, "clip")

        def fake_sidecar(workspace, path, segments):
            payload = b"srt"
            (root / path).write_bytes(payload)
            return CaptionSidecar(path, len(payload), hashlib.sha256(payload).hexdigest(), len(segments))

        with patch("workflow_os.captioned_clip_pipeline.render_clip", side_effect=fake_render), patch(
            "workflow_os.captioned_clip_pipeline.write_caption_sidecar", side_effect=fake_sidecar
        ), patch("workflow_os.captioned_clip_pipeline.burn_captions", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                produce_captioned_clip(
                    root,
                    selected,
                    words,
                    caption_relative_path="out/clip.srt",
                    output_relative_path="out/final.mp4",
                )

        self.assertFalse((root / "out" / "clip.mp4").exists())
        self.assertFalse((root / "out" / "clip.srt").exists())

    def test_cleanup_can_be_disabled_for_debug_evidence(self):
        temp, root, selected, words = self._workspace()
        self.addCleanup(temp.cleanup)

        def fake_render(workspace, spec, **kwargs):
            payload = b"clip"
            (root / "out" / "clip.mp4").write_bytes(payload)
            return self._producer("out/clip.mp4", payload, "clip")

        def fake_sidecar(workspace, path, segments):
            payload = b"srt"
            (root / path).write_bytes(payload)
            return CaptionSidecar(path, len(payload), hashlib.sha256(payload).hexdigest(), len(segments))

        def fake_burn(workspace, spec, **kwargs):
            payload = b"final"
            (root / "out" / "final.mp4").write_bytes(payload)
            return self._producer("out/final.mp4", payload, "caption-burn")

        with patch("workflow_os.captioned_clip_pipeline.render_clip", side_effect=fake_render), patch(
            "workflow_os.captioned_clip_pipeline.write_caption_sidecar", side_effect=fake_sidecar
        ), patch("workflow_os.captioned_clip_pipeline.burn_captions", side_effect=fake_burn):
            produce_captioned_clip(
                root,
                selected,
                words,
                caption_relative_path="out/clip.srt",
                output_relative_path="out/final.mp4",
                cleanup_intermediates=False,
            )

        self.assertTrue((root / "out" / "clip.mp4").exists())
        self.assertTrue((root / "out" / "clip.srt").exists())


if __name__ == "__main__":
    unittest.main()
