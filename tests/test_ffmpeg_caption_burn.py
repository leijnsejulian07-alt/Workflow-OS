from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_os.adapters.ffmpeg_caption_burn import (
    CaptionBurnSpec,
    build_ffmpeg_caption_command,
    burn_captions,
)
from workflow_os.adapters.local_media_ingest import ingest_local_media
from workflow_os.caption_sidecar import CaptionSidecar


class FfmpegCaptionBurnTests(unittest.TestCase):
    def _workspace(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "media").mkdir()
        (root / "out").mkdir()
        video = root / "media" / "clip.mp4"
        video.write_bytes(b"video-bytes")
        captions = root / "media" / "clip.srt"
        payload = b"1\n00:00:00,000 --> 00:00:01,000\nhello\n"
        captions.write_bytes(payload)
        source = ingest_local_media(root, "media/clip.mp4", producer="test", max_bytes=1024)
        sidecar = CaptionSidecar(
            relative_path="media/clip.srt",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            segment_count=1,
        )
        return temp, root, source, sidecar

    def test_command_uses_direct_filter_and_no_shell(self):
        command = build_ffmpeg_caption_command(
            "/usr/bin/ffmpeg",
            Path("/tmp/input.mp4"),
            Path("/tmp/captions.srt"),
            Path("/tmp/output.mp4"),
        )
        self.assertEqual(command[0], "/usr/bin/ffmpeg")
        self.assertIn("-nostdin", command)
        self.assertIn("-vf", command)
        self.assertTrue(any(value.startswith("subtitles=filename=") for value in command))

    def test_changed_caption_evidence_fails_closed(self):
        temp, root, source, sidecar = self._workspace()
        self.addCleanup(temp.cleanup)
        (root / "media" / "clip.srt").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            burn_captions(root, CaptionBurnSpec(source, sidecar, "out/final.mp4"))

    def test_output_traversal_fails_before_ffmpeg_lookup(self):
        temp, root, source, sidecar = self._workspace()
        self.addCleanup(temp.cleanup)
        with self.assertRaises(ValueError):
            burn_captions(root, CaptionBurnSpec(source, sidecar, "../final.mp4"))

    @patch("workflow_os.adapters.ffmpeg_caption_burn.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("workflow_os.adapters.ffmpeg_caption_burn.subprocess.run")
    def test_failed_ffmpeg_does_not_promote_output(self, run, which):
        temp, root, source, sidecar = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value.returncode = 1
        with self.assertRaises(RuntimeError):
            burn_captions(root, CaptionBurnSpec(source, sidecar, "out/final.mp4"))
        self.assertFalse((root / "out" / "final.mp4").exists())

    def test_existing_output_is_never_overwritten(self):
        temp, root, source, sidecar = self._workspace()
        self.addCleanup(temp.cleanup)
        (root / "out" / "final.mp4").write_bytes(b"existing")
        with self.assertRaises(ValueError):
            burn_captions(root, CaptionBurnSpec(source, sidecar, "out/final.mp4"))


if __name__ == "__main__":
    unittest.main()
