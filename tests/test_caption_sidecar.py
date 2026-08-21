from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from workflow_os.caption_segments import CaptionSegment
from workflow_os.caption_sidecar import render_srt_text, write_caption_sidecar


class CaptionSidecarTests(unittest.TestCase):
    def _segments(self) -> list[CaptionSegment]:
        return [
            CaptionSegment(0, 900, "Hello world", 0, 1),
            CaptionSegment(1_000, 2_250, "Second caption", 2, 3),
        ]

    def test_render_srt_text_is_deterministic(self) -> None:
        expected = (
            "1\n00:00:00,000 --> 00:00:00,900\nHello world\n\n"
            "2\n00:00:01,000 --> 00:00:02,250\nSecond caption\n"
        )
        self.assertEqual(render_srt_text(self._segments()), expected)

    def test_write_caption_sidecar_writes_and_hashes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir()
            sidecar = write_caption_sidecar(root, "out/captions.srt", self._segments())
            payload = (root / "out" / "captions.srt").read_bytes()

            self.assertEqual(sidecar.relative_path, "out/captions.srt")
            self.assertEqual(sidecar.size_bytes, len(payload))
            self.assertEqual(sidecar.sha256, hashlib.sha256(payload).hexdigest())
            self.assertEqual(sidecar.segment_count, 2)

    def test_rejects_traversal_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir()
            with self.assertRaises(ValueError):
                write_caption_sidecar(root, "../escape.srt", self._segments())

            target = root / "out" / "captions.srt"
            target.write_text("existing", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_caption_sidecar(root, "out/captions.srt", self._segments())
            self.assertEqual(target.read_text(encoding="utf-8"), "existing")

    def test_rejects_non_monotonic_segments(self) -> None:
        segments = [
            CaptionSegment(1_000, 2_000, "one", 0, 0),
            CaptionSegment(1_500, 2_500, "two", 1, 1),
        ]
        with self.assertRaises(ValueError):
            render_srt_text(segments)

    def test_rejects_control_characters(self) -> None:
        with self.assertRaises(ValueError):
            render_srt_text([CaptionSegment(0, 500, "bad\ntext", 0, 0)])

    def test_rejects_empty_segments(self) -> None:
        with self.assertRaises(ValueError):
            render_srt_text([])

    def test_respects_output_size_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir()
            with self.assertRaises(ValueError):
                write_caption_sidecar(
                    root,
                    "out/captions.srt",
                    self._segments(),
                    max_output_bytes=10,
                )

    def test_rejects_boolean_output_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir()
            with self.assertRaises(ValueError):
                write_caption_sidecar(
                    root,
                    "out/captions.srt",
                    self._segments(),
                    max_output_bytes=True,
                )


if __name__ == "__main__":
    unittest.main()
