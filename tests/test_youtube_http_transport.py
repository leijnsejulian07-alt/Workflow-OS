from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from workflow_os.adapters.youtube_upload import (
    YouTubeInitRequest,
    YouTubeStatusRequest,
    YouTubeUploadRequest,
    YouTubeUploadStatusProbe,
)
from workflow_os.adapters.youtube_http_transport import (
    YouTubeHttpTransport,
    YouTubeHttpTransportError,
)


class _Response:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self._status = status
        self._body = io.BytesIO(body)
        self.headers = headers or {}

    def getcode(self):
        return self._status

    def read(self, size: int = -1):
        return self._body.read(size)

    def close(self):
        pass


class _Opener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests: list[tuple[Request, float]] = []

    def open(self, request: Request, timeout: float):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class YouTubeHttpTransportTests(unittest.TestCase):
    def test_initialize_returns_strict_google_session_url(self):
        opener = _Opener(_Response(200, headers={
            "Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"
        }))
        result = YouTubeHttpTransport(opener=opener).initialize(YouTubeInitRequest(
            url="https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet%2Cstatus",
            headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
            json_body={"snippet": {"title": "safe"}},
        ))
        self.assertEqual(result.status_code, 200)
        self.assertIn("upload_id=abc", result.session_url)
        request, _ = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode()), {"snippet": {"title": "safe"}})

    def test_initialize_rejects_off_origin_location(self):
        opener = _Opener(_Response(200, headers={
            "Location": "https://evil.example/upload/youtube/v3/videos"
        }))
        with self.assertRaises(ValueError):
            YouTubeHttpTransport(opener=opener).initialize(YouTubeInitRequest(
                url="https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable",
                headers={"Authorization": "Bearer secret"},
                json_body={},
            ))

    def test_upload_chunk_accepts_308_recovery_evidence(self):
        error = HTTPError(
            "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
            308,
            "Resume Incomplete",
            {"Range": "bytes=0-3"},
            io.BytesIO(b""),
        )
        result = YouTubeHttpTransport(opener=_Opener(error=error)).upload_chunk(
            YouTubeUploadRequest(
                url="https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
                headers={"Authorization": "Bearer secret", "Content-Length": "4"},
                start_byte=0,
                end_byte=3,
            ),
            b"abcd",
        )
        self.assertEqual(result.status_code, 308)
        self.assertEqual(result.headers["Range"], "bytes=0-3")

    def test_upload_chunk_rejects_length_mismatch_before_network(self):
        opener = _Opener(_Response(200, b'{"id":"video"}'))
        with self.assertRaises(ValueError):
            YouTubeHttpTransport(opener=opener).upload_chunk(
                YouTubeUploadRequest(
                    url="https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
                    headers={"Authorization": "Bearer secret"},
                    start_byte=0,
                    end_byte=3,
                ),
                b"abc",
            )
        self.assertEqual(opener.requests, [])

    def test_probe_preserves_404_session_expiry(self):
        error = HTTPError(
            "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
            404,
            "Not Found",
            {},
            io.BytesIO(b""),
        )
        result = YouTubeHttpTransport(opener=_Opener(error=error)).probe(
            YouTubeUploadStatusProbe(
                url="https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
                headers={"Authorization": "Bearer secret", "Content-Length": "0"},
            )
        )
        self.assertEqual(result.status_code, 404)

    def test_fetch_processing_returns_only_object_json(self):
        opener = _Opener(_Response(200, b'{"items":[{"id":"abc"}]}'))
        result = YouTubeHttpTransport(opener=opener).fetch_processing(
            YouTubeStatusRequest(
                url="https://www.googleapis.com/youtube/v3/videos?part=status%2CprocessingDetails&id=abc",
                headers={"Authorization": "Bearer secret"},
            )
        )
        self.assertEqual(result["items"][0]["id"], "abc")
        self.assertEqual(opener.requests[0][0].get_method(), "GET")

    def test_fetch_processing_rejects_non_object_json(self):
        opener = _Opener(_Response(200, b"[]"))
        with self.assertRaises(YouTubeHttpTransportError):
            YouTubeHttpTransport(opener=opener).fetch_processing(
                YouTubeStatusRequest(
                    url="https://www.googleapis.com/youtube/v3/videos?id=abc",
                    headers={"Authorization": "Bearer secret"},
                )
            )

    def test_oversized_response_fails_closed(self):
        opener = _Opener(_Response(200, b"x" * (2 * 1024 * 1024 + 1)))
        with self.assertRaises(YouTubeHttpTransportError):
            YouTubeHttpTransport(opener=opener).fetch_processing(
                YouTubeStatusRequest(
                    url="https://www.googleapis.com/youtube/v3/videos?id=abc",
                    headers={"Authorization": "Bearer secret"},
                )
            )

    def test_unexpected_http_error_does_not_expose_body(self):
        error = HTTPError(
            "https://www.googleapis.com/youtube/v3/videos?id=abc",
            403,
            "Forbidden",
            {},
            io.BytesIO(b"credential-like-secret"),
        )
        with self.assertRaisesRegex(YouTubeHttpTransportError, "HTTP 403") as ctx:
            YouTubeHttpTransport(opener=_Opener(error=error)).fetch_processing(
                YouTubeStatusRequest(
                    url="https://www.googleapis.com/youtube/v3/videos?id=abc",
                    headers={"Authorization": "Bearer secret"},
                )
            )
        self.assertNotIn("credential-like-secret", str(ctx.exception))

    def test_timeout_bounds(self):
        with self.assertRaises(ValueError):
            YouTubeHttpTransport(timeout_seconds=0)
        with self.assertRaises(ValueError):
            YouTubeHttpTransport(timeout_seconds=121)


if __name__ == "__main__":
    unittest.main()
