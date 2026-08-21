from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workflow_os.adapters.ffmpeg_clip import (
    ClipRenderSpec,
    build_ffmpeg_clip_command,
    render_clip,
)
from workflow_os.adapters.local_media_ingest import ingest_local_media


class FfmpegClipTests(unittest.TestCase):
    def _workspace(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "inputs").mkdir()
        (root / "outputs").mkdir()
        source_path = root / "inputs" / "source.mp4"
        source_path.write_bytes(b"source-video-bytes")
        source = ingest_local_media(root, "inputs/source.mp4", producer="fixture")
        return temp, root, source

    def test_command_is_argument_array_without_shell_syntax(self):
        command = build_ffmpeg_clip_command(
            "/usr/bin/ffmpeg",
            Path("/safe/input.mp4"),
            Path("/safe/output.mp4"),
            start_ms=1250,
            duration_ms=2500,
        )
        self.assertIsInstance(command, tuple)
        self.assertEqual(command[0], "/usr/bin/ffmpeg")
        self.assertIn("1.250", command)
        self.assertIn("2.500", command)
        self.assertNotIn(";", command)
        self.assertNotIn("&&", command)

    @mock.patch("workflow_os.adapters.ffmpeg_clip.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("workflow_os.adapters.ffmpeg_clip.subprocess.run")
    def test_render_reverifies_source_and_returns_new_producer_output(self, run, _which):
        temp, root, source = self._workspace()
        self.addCleanup(temp.cleanup)

        def fake_run(command, **kwargs):
            Path(command[-1]).write_bytes(b"rendered-clip")
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_run
        result = render_clip(
            root,
            ClipRenderSpec(source, "outputs/clip.mp4", 0, 1500),
            producer="test-renderer",
        )
        self.assertEqual(result.relative_path, "outputs/clip.mp4")
        self.assertEqual(result.media_type, "video/mp4")
        self.assertEqual(result.producer, "test-renderer")
        self.assertEqual(result.sha256, hashlib.sha256(b"rendered-clip").hexdigest())
        self.assertEqual((root / "outputs" / "clip.mp4").read_bytes(), b"rendered-clip")

    @mock.patch("workflow_os.adapters.ffmpeg_clip.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("workflow_os.adapters.ffmpeg_clip.subprocess.run")
    def test_changed_source_is_rejected_before_process_execution(self, run, _which):
        temp, root, source = self._workspace()
        self.addCleanup(temp.cleanup)
        (root / "inputs" / "source.mp4").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            render_clip(root, ClipRenderSpec(source, "outputs/clip.mp4", 0, 1000))
        run.assert_not_called()

    @mock.patch("workflow_os.adapters.ffmpeg_clip.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("workflow_os.adapters.ffmpeg_clip.subprocess.run")
    def test_failed_render_leaves_no_final_or_temp_output(self, run, _which):
        temp, root, source = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value = subprocess.CompletedProcess(("ffmpeg",), 1)
        with self.assertRaisesRegex(RuntimeError, "render failed"):
            render_clip(root, ClipRenderSpec(source, "outputs/clip.mp4", 0, 1000))
        self.assertFalse((root / "outputs" / "clip.mp4").exists())
        self.assertEqual(list((root / "outputs").iterdir()), [])

    def test_rejects_unsafe_output_and_invalid_bounds(self):
        temp, root, source = self._workspace()
        self.addCleanup(temp.cleanup)
        bad_specs = [
            ClipRenderSpec(source, "../clip.mp4", 0, 1000),
            ClipRenderSpec(source, "/clip.mp4", 0, 1000),
            ClipRenderSpec(source, "outputs/clip.mov", 0, 1000),
            ClipRenderSpec(source, "outputs/clip.mp4", -1, 1000),
            ClipRenderSpec(source, "outputs/clip.mp4", 0, 0),
            ClipRenderSpec(source, "outputs/clip.mp4", 0, 180001),
        ]
        for spec in bad_specs:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    render_clip(root, spec)

    @mock.patch("workflow_os.adapters.ffmpeg_clip.shutil.which", return_value=None)
    def test_missing_ffmpeg_fails_before_render(self, _which):
        temp, root, source = self._workspace()
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(RuntimeError, "not available"):
            render_clip(root, ClipRenderSpec(source, "outputs/clip.mp4", 0, 1000))

    @mock.patch("workflow_os.adapters.ffmpeg_clip.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("workflow_os.adapters.ffmpeg_clip.subprocess.run")
    def test_existing_output_is_never_overwritten(self, run, _which):
        temp, root, source = self._workspace()
        self.addCleanup(temp.cleanup)
        target = root / "outputs" / "clip.mp4"
        target.write_bytes(b"keep-me")
        with self.assertRaisesRegex(ValueError, "already exists"):
            render_clip(root, ClipRenderSpec(source, "outputs/clip.mp4", 0, 1000))
        self.assertEqual(target.read_bytes(), b"keep-me")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
