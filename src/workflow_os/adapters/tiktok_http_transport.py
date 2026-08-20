from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from workflow_os.adapters.tiktok_direct_post import (
    TIKTOK_API_HOST,
    TikTokInitRequest,
    TikTokStatusRequest,
    TikTokUploadRequest,
    parse_upload_response,
)
from workflow_os.submissions import SubmissionAsset


_MAX_JSON_RESPONSE_BYTES = 256 * 1024
_MAX_UPLOAD_RESPONSE_BYTES = 64 * 1024
_MAX_REQUEST_BODY_BYTES = 256 * 1024
_HASH_BLOCK_BYTES = 1024 * 1024
_UPLOAD_HOST = "open-upload.tiktokapis.com"


class TikTokTransportError(RuntimeError):
    """Network/protocol failure that must not expose credentials or signed URLs."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class VerifiedLocalAsset:
    path: Path
    size_bytes: int
    sha256: str
    mtime_ns: int


def _validate_api_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != TIKTOK_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/v2/")
    ):
        raise ValueError("TikTok API request has an unexpected origin")
    return url


def _validate_upload_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _UPLOAD_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/")
    ):
        raise ValueError("TikTok upload request has an unexpected origin")
    return url


def _validated_json_headers(headers: Mapping[str, str]) -> dict[str, str]:
    authorization = headers.get("Authorization")
    content_type = headers.get("Content-Type")
    if (
        not isinstance(authorization, str)
        or not authorization.startswith("Bearer ")
        or len(authorization) > 4103
        or any(ch in authorization for ch in "\r\n")
    ):
        raise ValueError("TikTok API request is missing a valid bearer credential")
    if content_type not in {"application/json", "application/json; charset=UTF-8"}:
        raise ValueError("TikTok API request has an unexpected content type")
    return {"Authorization": authorization, "Content-Type": content_type}


def _validated_upload_headers(headers: Mapping[str, str]) -> dict[str, str]:
    content_type = headers.get("Content-Type")
    content_length = headers.get("Content-Length")
    content_range = headers.get("Content-Range")
    if not isinstance(content_type, str) or not content_type.startswith("video/"):
        raise ValueError("TikTok upload request has an unexpected content type")
    if not isinstance(content_length, str) or not content_length.isdigit():
        raise ValueError("TikTok upload request has an invalid Content-Length")
    if not isinstance(content_range, str) or not content_range.startswith("bytes "):
        raise ValueError("TikTok upload request has an invalid Content-Range")
    return {
        "Content-Type": content_type,
        "Content-Length": content_length,
        "Content-Range": content_range,
    }


def _read_bounded(response: Any, *, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise TikTokTransportError("TikTok response exceeded the configured size limit")
    return body


def _decode_json(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TikTokTransportError("TikTok returned a malformed JSON response") from exc
    if not isinstance(payload, Mapping):
        raise TikTokTransportError("TikTok returned a non-object JSON response")
    return payload


def verify_local_asset(asset_root: str | Path, asset: SubmissionAsset) -> VerifiedLocalAsset:
    """Bind submission evidence to the exact local file before any network side effect."""

    if not isinstance(asset, SubmissionAsset):
        raise TypeError("asset must be a SubmissionAsset")

    root = Path(asset_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("asset root must be a directory")

    unresolved = (root / asset.path).resolve(strict=False)
    try:
        unresolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("submission asset resolves outside the configured asset root") from exc

    candidate = unresolved.resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("submission asset resolves outside the configured asset root") from exc
    if not candidate.is_file():
        raise ValueError("submission asset must resolve to a regular file")

    stat = candidate.stat()
    if stat.st_size != asset.size_bytes:
        raise ValueError("submission asset size no longer matches verified evidence")

    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        while True:
            block = handle.read(_HASH_BLOCK_BYTES)
            if not block:
                break
            digest.update(block)
    actual = digest.hexdigest()
    if actual != asset.sha256.strip().lower():
        raise ValueError("submission asset digest no longer matches verified evidence")

    return VerifiedLocalAsset(
        path=candidate,
        size_bytes=stat.st_size,
        sha256=actual,
        mtime_ns=stat.st_mtime_ns,
    )


def read_verified_chunk(asset: VerifiedLocalAsset, request: TikTokUploadRequest) -> bytes:
    """Read exactly one already-planned range and fail if the file changed after verification."""

    if not isinstance(asset, VerifiedLocalAsset):
        raise TypeError("asset must be a VerifiedLocalAsset")
    if not isinstance(request, TikTokUploadRequest):
        raise TypeError("request must be a TikTokUploadRequest")

    expected = request.end_byte - request.start_byte + 1
    if expected <= 0:
        raise ValueError("upload request has an invalid byte range")

    with asset.path.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        if stat.st_size != asset.size_bytes or stat.st_mtime_ns != asset.mtime_ns:
            raise ValueError("submission asset changed after verification")
        handle.seek(request.start_byte)
        data = handle.read(expected)
    if len(data) != expected:
        raise ValueError("submission asset did not contain the requested byte range")
    return data


class TikTokHttpTransport:
    """Small dependency-free transport for official TikTok Content Posting endpoints.

    It follows no redirects, bounds all response bodies, never persists credentials,
    and deliberately leaves retry/reconciliation policy to SideEffectLedger.
    """

    def __init__(
        self,
        *,
        opener: OpenerDirector | Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
            raise TypeError("timeout_seconds must be numeric")
        if not 1.0 <= float(timeout_seconds) <= 120.0:
            raise ValueError("timeout_seconds must be between 1 and 120 seconds")
        self._opener = opener if opener is not None else build_opener(_NoRedirectHandler())
        self._timeout = float(timeout_seconds)

    def _open(self, request: Request, *, response_limit: int) -> tuple[int, bytes]:
        try:
            response = self._opener.open(request, timeout=self._timeout)
            try:
                status = int(response.getcode())
                body = _read_bounded(response, limit=response_limit)
            finally:
                response.close()
            return status, body
        except HTTPError as exc:
            try:
                body = _read_bounded(exc, limit=response_limit)
            finally:
                exc.close()
            return int(exc.code), body
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise TikTokTransportError("TikTok transport failed before a confirmed response") from exc

    def post_json(self, request: TikTokInitRequest | TikTokStatusRequest) -> Mapping[str, Any]:
        if not isinstance(request, (TikTokInitRequest, TikTokStatusRequest)):
            raise TypeError("request must be a TikTok init or status request")
        url = _validate_api_url(request.url)
        headers = _validated_json_headers(request.headers)
        body = json.dumps(request.json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(body) > _MAX_REQUEST_BODY_BYTES:
            raise ValueError("TikTok JSON request exceeded the configured size limit")
        http_request = Request(url, data=body, headers=headers, method="POST")
        status, response_body = self._open(http_request, response_limit=_MAX_JSON_RESPONSE_BYTES)
        if status != 200:
            raise TikTokTransportError(f"TikTok API returned HTTP {status}")
        return _decode_json(response_body)

    def put_chunk(
        self,
        request: TikTokUploadRequest,
        *,
        data: bytes,
        is_final_chunk: bool,
    ) -> None:
        if not isinstance(request, TikTokUploadRequest):
            raise TypeError("request must be a TikTokUploadRequest")
        if not isinstance(data, bytes):
            raise TypeError("upload chunk data must be bytes")

        url = _validate_upload_url(request.url)
        headers = _validated_upload_headers(request.headers)
        expected = request.end_byte - request.start_byte + 1
        if len(data) != expected or headers["Content-Length"] != str(expected):
            raise ValueError("upload chunk bytes do not match the declared Content-Length")

        http_request = Request(url, data=data, headers=headers, method="PUT")
        status, _ = self._open(http_request, response_limit=_MAX_UPLOAD_RESPONSE_BYTES)
        try:
            parse_upload_response(status, is_final_chunk=is_final_chunk)
        except ValueError as exc:
            raise TikTokTransportError("TikTok upload did not confirm the expected chunk state") from exc
