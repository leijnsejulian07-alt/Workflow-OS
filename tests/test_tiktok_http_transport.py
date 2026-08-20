import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from workflow_os.adapters.tiktok_direct_post import (
    TikTokInitRequest,
    build_upload_request,
    plan_file_upload,
)
from workflow_os.adapters.tiktok_http_transport import (
    TikTokHttpTransport,
    TikTokTransportError,
    read_verified_chunk,
    verify_local_asset,
)
from workflow_os.submissions import SubmissionAsset


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status = status
        self.body = body
        self.offset = 0
        self.closed = False

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TikTokHttpTransportTests(unittest.TestCase):
    def test_posts_bounded_json_to_exact_api_origin(self):
        payload = {"data": {"publish_id": "v_pub_123"}, "error": {"code": "ok"}}
        opener = FakeOpener([FakeResponse(200, json.dumps(payload).encode())])
        transport = TikTokHttpTransport(opener=opener, timeout_seconds=5)
        request = TikTokInitRequest(
            url="https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization": "Bearer secret-token", "Content-Type": "application/json"},
            json_body={"source_info": {"source": "FILE_UPLOAD"}},
        )

        parsed = transport.post_json(request)

        self.assertEqual(parsed, payload)
        sent, timeout = opener.requests[0]
        self.assertEqual(sent.get_method(), "POST")
        self.assertEqual(sent.full_url, request.url)
        self.assertEqual(timeout, 5.0)
        self.assertIn(b"FILE_UPLOAD", sent.data)

    def test_rejects_unexpected_api_origin_before_network(self):
        opener = FakeOpener([])
        transport = TikTokHttpTransport(opener=opener)
        request = TikTokInitRequest(
            url="https://open.tiktokapis.com.evil.example/v2/post/publish/video/init/",
            headers={"Authorization": "Bearer secret-token"},
            json_body={},
        )
        with self.assertRaises(ValueError):
            transport.post_json(request)
        self.assertEqual(opener.requests, [])

    def test_http_and_network_errors_do_not_leak_credentials(self):
        token = "super-secret-token"
        request = TikTokInitRequest(
            url="https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {token}"},
            json_body={},
        )
        transport = TikTokHttpTransport(opener=FakeOpener([FakeResponse(500, b"server error")]))
        with self.assertRaises(TikTokTransportError) as raised:
            transport.post_json(request)
        self.assertNotIn(token, str(raised.exception))

        transport = TikTokHttpTransport(opener=FakeOpener([URLError("socket failed")]))
        with self.assertRaises(TikTokTransportError) as raised:
            transport.post_json(request)
        self.assertNotIn(token, str(raised.exception))

    def test_response_body_is_bounded_and_malformed_json_fails_closed(self):
        huge = b"x" * (256 * 1024 + 1)
        request = TikTokInitRequest(
            url="https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={},
            json_body={},
        )
        with self.assertRaises(TikTokTransportError):
            TikTokHttpTransport(opener=FakeOpener([FakeResponse(200, huge)])).post_json(request)
        with self.assertRaises(TikTokTransportError):
            TikTokHttpTransport(opener=FakeOpener([FakeResponse(200, b"not-json")])).post_json(request)

    def test_verifies_local_asset_evidence_and_reads_exact_upload_range(self):
        content = b"abcdef"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "renders").mkdir()
            path = root / "renders" / "clip.mp4"
            path.write_bytes(content)
            asset = SubmissionAsset("renders/clip.mp4", "video/mp4", len(content), digest)

            verified = verify_local_asset(root, asset)
            chunk = plan_file_upload(len(content)).chunks[0]
            request = build_upload_request(
                "https://open-upload.tiktokapis.com/video/?upload_id=123&upload_token=abc",
                media_type="video/mp4",
                chunk=chunk,
            )
            self.assertEqual(read_verified_chunk(verified, request), content)

    def test_local_asset_traversal_size_digest_and_change_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "clip.mp4"
            inside.write_bytes(b"abc")
            good_digest = hashlib.sha256(b"abc").hexdigest()

            with self.assertRaises(ValueError):
                verify_local_asset(root, SubmissionAsset("../outside.mp4", "video/mp4", 3, good_digest))
            with self.assertRaises(ValueError):
                verify_local_asset(root, SubmissionAsset("clip.mp4", "video/mp4", 4, good_digest))
            with self.assertRaises(ValueError):
                verify_local_asset(root, SubmissionAsset("clip.mp4", "video/mp4", 3, "0" * 64))

            verified = verify_local_asset(root, SubmissionAsset("clip.mp4", "video/mp4", 3, good_digest))
            inside.write_bytes(b"abcd")
            chunk = plan_file_upload(3).chunks[0]
            request = build_upload_request(
                "https://open-upload.tiktokapis.com/video/?upload_id=123&upload_token=abc",
                media_type="video/mp4",
                chunk=chunk,
            )
            with self.assertRaises(ValueError):
                read_verified_chunk(verified, request)

    def test_put_chunk_requires_exact_bytes_and_expected_tiktok_ack(self):
        chunk = plan_file_upload(6).chunks[0]
        request = build_upload_request(
            "https://open-upload.tiktokapis.com/video/?upload_id=123&upload_token=abc",
            media_type="video/mp4",
            chunk=chunk,
        )
        opener = FakeOpener([FakeResponse(201)])
        transport = TikTokHttpTransport(opener=opener)
        transport.put_chunk(request, data=b"abcdef", is_final_chunk=True)
        sent, _ = opener.requests[0]
        self.assertEqual(sent.get_method(), "PUT")
        self.assertEqual(sent.data, b"abcdef")

        with self.assertRaises(ValueError):
            TikTokHttpTransport(opener=FakeOpener([])).put_chunk(
                request,
                data=b"short",
                is_final_chunk=True,
            )
        with self.assertRaises(TikTokTransportError):
            TikTokHttpTransport(opener=FakeOpener([FakeResponse(206)])).put_chunk(
                request,
                data=b"abcdef",
                is_final_chunk=True,
            )

    def test_timeout_boundary_is_bounded(self):
        for timeout in (0.5, 121, True, "30"):
            with self.subTest(timeout=timeout):
                with self.assertRaises((TypeError, ValueError)):
                    TikTokHttpTransport(timeout_seconds=timeout)


if __name__ == "__main__":
    unittest.main()
