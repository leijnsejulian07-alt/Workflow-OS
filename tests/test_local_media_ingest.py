from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.local_media_ingest import ingest_local_media


class LocalMediaIngestTests(unittest.TestCase):
    def test_ingests_supported_file_with_streamed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "campaign" / "clip.mp4"
            media.parent.mkdir()
            payload = b"bounded-video-fixture"
            media.write_bytes(payload)

            output = ingest_local_media(root, "campaign/clip.mp4")

            self.assertEqual(output.relative_path, "campaign/clip.mp4")
            self.assertEqual(output.media_type, "video/mp4")
            self.assertEqual(output.size_bytes, len(payload))
            self.assertEqual(output.sha256, hashlib.sha256(payload).hexdigest())
            self.assertEqual(output.producer, "local-media-ingest-v1")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "traversal-free"):
                ingest_local_media(root, "../outside.mp4")

    def test_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            absolute = str((root / "clip.mp4").resolve())
            with self.assertRaisesRegex(ValueError, "relative"):
                ingest_local_media(root, absolute)

    def test_rejects_unsupported_media_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "payload.exe"
            source.write_bytes(b"not-media")
            with self.assertRaisesRegex(ValueError, "media type"):
                ingest_local_media(root, "payload.exe")

    def test_rejects_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "size"):
                ingest_local_media(root, "clip.mp4")

    def test_rejects_file_over_caller_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"12345")
            with self.assertRaisesRegex(ValueError, "size"):
                ingest_local_media(root, "clip.mp4", max_bytes=4)

    def test_rejects_symlink_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "real.mp4"
            target.write_bytes(b"fixture")
            link = root / "alias.mp4"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            with self.assertRaisesRegex(ValueError, "symlink"):
                ingest_local_media(root, "alias.mp4")

    def test_rejects_symlink_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temporary)
            outside = Path(outside_temp)
            (outside / "clip.mp4").write_bytes(b"fixture")
            linked_dir = root / "linked"
            try:
                linked_dir.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            with self.assertRaisesRegex(ValueError, "escapes"):
                ingest_local_media(root, "linked/clip.mp4")

    def test_rejects_invalid_bounds_and_producer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "clip.mp4").write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "positive integer"):
                ingest_local_media(root, "clip.mp4", max_bytes=True)
            with self.assertRaisesRegex(ValueError, "producer"):
                ingest_local_media(root, "clip.mp4", producer="   ")


if __name__ == "__main__":
    unittest.main()
