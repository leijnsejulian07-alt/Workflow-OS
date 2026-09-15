from __future__ import annotations

import io
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from workflow_os.adapters.ffprobe_media_qc import MediaQCResult
from workflow_os.openshorts_output_provenance import OpenShortsClipOutput, OpenShortsOutputProvenanceStore
from workflow_os.openshorts_output_qc import OpenShortsOutputQCError, verify_openshorts_output_technical_qc
from workflow_os.qc_evidence import BoundMediaQC


class _Response:
    def __init__(self, body: bytes, *, headers: dict[str, str], status: int = 200):
        self._body = io.BytesIO(body)
        self.headers = headers
        self._status = status
        self.closed = False

    def getcode(self):
        return self._status

    def read(self, size=-1):
        return self._body.read(size)

    def close(self):
        self.closed = True


class _Opener:
    def __init__(self, response: _Response):
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


def _public_resolver(host, port, type=0):  # noqa: A002
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]


def _private_resolver(host, port, type=0):  # noqa: A002
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port))]


def _passing_probe(_root, source, **_kwargs):
    return BoundMediaQC(
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
        result=MediaQCResult(
            passed=True,
            reason="technical media QC passed",
            duration_ms=12_000,
            width=1080,
            height=1920,
            video_codec="h264",
            has_audio=True,
        ),
    )


class OpenShortsOutputQCTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = OpenShortsOutputProvenanceStore(self.root / "state.sqlite")
        self.output = OpenShortsClipOutput(
            idempotency_key="openshorts:41:" + "b" * 64,
            provider_job_id="job_123",
            clip_index=0,
            video_url="https://api.openshorts.app/files/clip.mp4",
            download_url="https://api.openshorts.app/files/clip.mp4",
            title="clip",
            evidence_sha256="c" * 64,
        )
        self.store.record_many((self.output,))

    def tearDown(self):
        self.tmp.cleanup()

    def _response(self, body=b"bounded-media-bytes", **headers):
        values = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(body)),
            "Content-Encoding": "identity",
        }
        values.update(headers)
        return _Response(body, headers=values)

    def test_authenticated_hosted_output_is_qc_bound_and_temp_file_is_removed(self):
        opener = _Opener(self._response())
        evidence = verify_openshorts_output_technical_qc(
            self.output,
            store=self.store,
            workspace_root=self.root,
            allowed_download_hosts=("api.openshorts.app",),
            api_key="osk_1234567890",
            opener=opener,
            resolver=_public_resolver,
            probe=_passing_probe,
        )

        self.assertEqual(self.output.idempotency_key, evidence.idempotency_key)
        self.assertEqual(self.output.evidence_sha256, evidence.provider_evidence_sha256)
        self.assertEqual("video/mp4", evidence.media_type)
        self.assertEqual("h264", evidence.video_codec)
        self.assertEqual(1, len(opener.requests))
        request, timeout = opener.requests[0]
        self.assertEqual("Bearer osk_1234567890", request.get_header("Authorization"))
        self.assertEqual(30, timeout)
        self.assertEqual([], list(self.root.glob(".workflow-os-openshorts-qc-*")))

    def test_external_allowlisted_cdn_never_receives_openshorts_api_key(self):
        output = replace(
            self.output,
            video_url="https://cdn.example.com/clip.mp4",
            download_url="https://cdn.example.com/clip.mp4",
        )
        store = OpenShortsOutputProvenanceStore(self.root / "cdn.sqlite")
        store.record_many((output,))
        opener = _Opener(self._response())

        verify_openshorts_output_technical_qc(
            output,
            store=store,
            workspace_root=self.root,
            allowed_download_hosts=("cdn.example.com",),
            api_key=None,
            opener=opener,
            resolver=_public_resolver,
            probe=_passing_probe,
        )

        request, _ = opener.requests[0]
        self.assertIsNone(request.get_header("Authorization"))

    def test_provenance_drift_is_rejected_before_network_io(self):
        opener = _Opener(self._response())
        drifted = replace(self.output, download_url="https://api.openshorts.app/files/other.mp4")
        with self.assertRaises(RuntimeError):
            verify_openshorts_output_technical_qc(
                drifted,
                store=self.store,
                workspace_root=self.root,
                allowed_download_hosts=("api.openshorts.app",),
                api_key="osk_1234567890",
                opener=opener,
                resolver=_public_resolver,
                probe=_passing_probe,
            )
        self.assertEqual([], opener.requests)

    def test_private_dns_resolution_is_rejected_before_network_io(self):
        opener = _Opener(self._response())
        with self.assertRaises(OpenShortsOutputQCError):
            verify_openshorts_output_technical_qc(
                self.output,
                store=self.store,
                workspace_root=self.root,
                allowed_download_hosts=("api.openshorts.app",),
                api_key="osk_1234567890",
                opener=opener,
                resolver=_private_resolver,
                probe=_passing_probe,
            )
        self.assertEqual([], opener.requests)

    def test_compressed_response_is_rejected_and_temp_file_is_not_left_behind(self):
        opener = _Opener(self._response(**{"Content-Encoding": "gzip"}))
        with self.assertRaises(OpenShortsOutputQCError):
            verify_openshorts_output_technical_qc(
                self.output,
                store=self.store,
                workspace_root=self.root,
                allowed_download_hosts=("api.openshorts.app",),
                api_key="osk_1234567890",
                opener=opener,
                resolver=_public_resolver,
                probe=_passing_probe,
            )
        self.assertEqual([], list(self.root.glob(".workflow-os-openshorts-qc-*")))

    def test_streaming_size_bound_rejects_oversize_and_cleans_temp_file(self):
        body = b"x" * 32
        response = self._response(body)
        response.headers.pop("Content-Length")
        opener = _Opener(response)
        with self.assertRaises(OpenShortsOutputQCError):
            verify_openshorts_output_technical_qc(
                self.output,
                store=self.store,
                workspace_root=self.root,
                allowed_download_hosts=("api.openshorts.app",),
                api_key="osk_1234567890",
                max_download_bytes=16,
                opener=opener,
                resolver=_public_resolver,
                probe=_passing_probe,
            )
        self.assertEqual([], list(self.root.glob(".workflow-os-openshorts-qc-*")))


if __name__ == "__main__":
    unittest.main()
