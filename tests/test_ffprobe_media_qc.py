from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workflow_os.adapters.ffprobe_media_qc import probe_media_qc
from workflow_os.adapters.local_media_ingest import ingest_local_media


class FfprobeMediaQCTests(unittest.TestCase):
    def _workspace(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "outputs").mkdir()
        path = root / "outputs" / "final.mp4"
        path.write_bytes(b"rendered-video")
        output = ingest_local_media(root, "outputs/final.mp4", producer="fixture")
        return temp, root, output

    def _completed(self, payload, returncode=0):
        return subprocess.CompletedProcess(("ffprobe",), returncode, stdout=json.dumps(payload).encode("utf-8"))

    def _payload(self, *, duration="30.000", width=1080, height=1920, codec="h264", audio=True):
        streams = [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": codec,
                "width": width,
                "height": height,
                "duration": duration,
            }
        ]
        if audio:
            streams.append({"index": 1, "codec_type": "audio", "codec_name": "aac"})
        return {"streams": streams, "format": {"duration": duration}}

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    @mock.patch("workflow_os.adapters.ffprobe_media_qc.subprocess.run")
    def test_passes_valid_video_and_preserves_no_publication_authority(self, run, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value = self._completed(self._payload())

        result = probe_media_qc(root, output, expected_duration_ms=30_000, require_audio=True)

        self.assertTrue(result.passed)
        self.assertEqual(result.duration_ms, 30_000)
        self.assertEqual((result.width, result.height), (1080, 1920))
        self.assertEqual(result.video_codec, "h264")
        self.assertTrue(result.has_audio)
        _, kwargs = run.call_args
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    @mock.patch("workflow_os.adapters.ffprobe_media_qc.subprocess.run")
    def test_duration_mismatch_fails_closed(self, run, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value = self._completed(self._payload(duration="25.000"))

        result = probe_media_qc(root, output, expected_duration_ms=30_000, duration_tolerance_ms=1000)

        self.assertFalse(result.passed)
        self.assertIn("duration", result.reason)

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    @mock.patch("workflow_os.adapters.ffprobe_media_qc.subprocess.run")
    def test_missing_required_audio_fails_closed(self, run, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value = self._completed(self._payload(audio=False))

        result = probe_media_qc(root, output, require_audio=True)

        self.assertFalse(result.passed)
        self.assertEqual(result.reason, "audio stream is required")

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    @mock.patch("workflow_os.adapters.ffprobe_media_qc.subprocess.run")
    def test_disallowed_codec_and_dimensions_fail_closed(self, run, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value = self._completed(self._payload(codec="mpeg2video"))
        self.assertFalse(probe_media_qc(root, output).passed)

        run.return_value = self._completed(self._payload(width=100, height=100))
        self.assertFalse(probe_media_qc(root, output).passed)

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    @mock.patch("workflow_os.adapters.ffprobe_media_qc.subprocess.run")
    def test_malformed_or_oversized_probe_output_fails_closed(self, run, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        run.return_value = subprocess.CompletedProcess(("ffprobe",), 0, stdout=b"not-json")
        self.assertFalse(probe_media_qc(root, output).passed)

        run.return_value = subprocess.CompletedProcess(("ffprobe",), 0, stdout=b"x" * (64 * 1024 + 1))
        self.assertFalse(probe_media_qc(root, output).passed)

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    @mock.patch("workflow_os.adapters.ffprobe_media_qc.subprocess.run")
    def test_multiple_video_streams_fail_closed(self, run, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        payload = self._payload()
        payload["streams"].append(
            {"index": 2, "codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280, "duration": "30.000"}
        )
        run.return_value = self._completed(payload)

        self.assertFalse(probe_media_qc(root, output).passed)

    @mock.patch("workflow_os.adapters.ffprobe_media_qc.shutil.which", return_value="/usr/bin/ffprobe")
    def test_changed_source_evidence_is_rejected_before_probe(self, _which):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)
        (root / output.relative_path).write_bytes(b"mutated")

        with self.assertRaisesRegex(ValueError, "no longer matches"):
            probe_media_qc(root, output)

    def test_boolean_and_excessive_bounds_are_rejected(self):
        temp, root, output = self._workspace()
        self.addCleanup(temp.cleanup)

        with self.assertRaises(ValueError):
            probe_media_qc(root, output, expected_duration_ms=True)
        with self.assertRaises(ValueError):
            probe_media_qc(root, output, duration_tolerance_ms=10_001)
        with self.assertRaises(ValueError):
            probe_media_qc(root, output, timeout_seconds=61)


if __name__ == "__main__":
    unittest.main()
