from __future__ import annotations

import json
import math
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from .youtube_upload import (
    YouTubeChannelIdentityRequest,
    YouTubeInitRequest,
    YouTubeStatusRequest,
    YouTubeUploadRequest,
    YouTubeUploadStatusProbe,
)

_MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
_MAX_ERROR_BODY_BYTES = 64 * 1024
_MAX_SESSION_URL_CHARS = 4096
_ALLOWED_HOST = "www.googleapis.com"
_ALLOWED_UPLOAD_PATH = "/upload/youtube/v3/videos"
_ALLOWED_STATUS_PATH = "/youtube/v3/videos"
_ALLOWED_CHANNELS_PATH = "/youtube/v3/channels"
_MAX_CHANNEL_ID_CHARS = 256


class YouTubeHttpTransportError(RuntimeError):
    """Network/protocol failure without exposing credentials or response bodies."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class YouTubeHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class YouTubeInitResponse:
    session_url: str
    status_code: int


def _validate_timeout(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise TypeError("timeout_seconds must be a finite number")
    timeout = float(value)
    if not 1.0 <= timeout <= 120.0:
        raise ValueError("timeout_seconds must be between 1 and 120 seconds")
    return timeout


def _validated_google_url(url: str, *, expected_path: str) -> str:
    if not isinstance(url, str) or not url or len(url) > _MAX_SESSION_URL_CHARS:
        raise ValueError("YouTube request URL is missing or too long")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ALLOWED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path != expected_path
        or parsed.fragment
    ):
        raise ValueError("YouTube request URL has an unexpected origin or path")
    return url


def _bounded_read(response: Any, *, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise YouTubeHttpTransportError("YouTube response exceeded the configured size limit")
    return body


def _string_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise YouTubeHttpTransportError("YouTube returned malformed response headers")
        result[name] = value
    return result


def _json_object(body: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YouTubeHttpTransportError("YouTube returned malformed JSON") from exc
    if not isinstance(payload, Mapping):
        raise YouTubeHttpTransportError("YouTube returned a non-object JSON response")
    return dict(payload)


class YouTubeHttpTransport:
    """Bounded dependency-free transport for official YouTube Data API upload calls."""

    def __init__(
        self,
        *,
        opener: OpenerDirector | Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._opener = opener if opener is not None else build_opener(_NoRedirectHandler())
        self._timeout = _validate_timeout(timeout_seconds)

    def _open(
        self,
        request: Request,
        *,
        body_limit: int,
        accepted_statuses: frozenset[int],
        allow_http_error_statuses: frozenset[int] = frozenset(),
    ) -> YouTubeHttpResponse:
        try:
            response = self._opener.open(request, timeout=self._timeout)
            try:
                status = int(response.getcode())
                headers = _string_headers(response.headers)
                body = _bounded_read(response, limit=body_limit)
            finally:
                response.close()
        except HTTPError as exc:
            try:
                status = int(exc.code)
                headers = _string_headers(exc.headers)
                body = _bounded_read(exc, limit=min(body_limit, _MAX_ERROR_BODY_BYTES))
            finally:
                exc.close()
            if status not in allow_http_error_statuses:
                raise YouTubeHttpTransportError(
                    f"YouTube Data API returned HTTP {status}"
                ) from exc
            return YouTubeHttpResponse(status_code=status, headers=headers, body=body)
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise YouTubeHttpTransportError(
                "YouTube transport failed before a confirmed response"
            ) from exc

        if status not in accepted_statuses:
            raise YouTubeHttpTransportError(f"YouTube Data API returned HTTP {status}")
        return YouTubeHttpResponse(status_code=status, headers=headers, body=body)

    def initialize(self, init: YouTubeInitRequest) -> YouTubeInitResponse:
        if not isinstance(init, YouTubeInitRequest):
            raise TypeError("init must be YouTubeInitRequest")
        url = _validated_google_url(init.url, expected_path=_ALLOWED_UPLOAD_PATH)
        request = Request(
            url,
            headers=dict(init.headers),
            data=json.dumps(init.json_body, separators=(",", ":")).encode("utf-8"),
            method="POST",
        )
        response = self._open(
            request,
            body_limit=_MAX_ERROR_BODY_BYTES,
            accepted_statuses=frozenset({200}),
        )
        location = None
        for name, value in response.headers.items():
            if name.lower() == "location":
                if location is not None:
                    raise YouTubeHttpTransportError("YouTube returned duplicate Location headers")
                location = value.strip()
        if not location:
            raise YouTubeHttpTransportError("YouTube resumable initialization omitted Location")
        session_url = _validated_google_url(location, expected_path=_ALLOWED_UPLOAD_PATH)
        return YouTubeInitResponse(session_url=session_url, status_code=response.status_code)

    def upload_chunk(self, upload: YouTubeUploadRequest, chunk: bytes) -> YouTubeHttpResponse:
        if not isinstance(upload, YouTubeUploadRequest):
            raise TypeError("upload must be YouTubeUploadRequest")
        if not isinstance(chunk, bytes):
            raise TypeError("chunk must be bytes")
        expected_length = upload.end_byte - upload.start_byte + 1
        if len(chunk) != expected_length:
            raise ValueError("YouTube upload chunk length does not match request byte range")
        url = _validated_google_url(upload.url, expected_path=_ALLOWED_UPLOAD_PATH)
        request = Request(url, headers=dict(upload.headers), data=chunk, method="PUT")
        return self._open(
            request,
            body_limit=_MAX_JSON_BODY_BYTES,
            accepted_statuses=frozenset({200, 201, 308}),
            allow_http_error_statuses=frozenset({308, 404}),
        )

    def probe(self, probe: YouTubeUploadStatusProbe) -> YouTubeHttpResponse:
        if not isinstance(probe, YouTubeUploadStatusProbe):
            raise TypeError("probe must be YouTubeUploadStatusProbe")
        url = _validated_google_url(probe.url, expected_path=_ALLOWED_UPLOAD_PATH)
        request = Request(url, headers=dict(probe.headers), data=b"", method="PUT")
        return self._open(
            request,
            body_limit=_MAX_JSON_BODY_BYTES,
            accepted_statuses=frozenset({200, 201, 308}),
            allow_http_error_statuses=frozenset({308, 404}),
        )


    def fetch_authenticated_channel_identity(self, identity_request: YouTubeChannelIdentityRequest) -> str:
        if not isinstance(identity_request, YouTubeChannelIdentityRequest):
            raise TypeError("identity_request must be YouTubeChannelIdentityRequest")
        url = _validated_google_url(identity_request.url, expected_path=_ALLOWED_CHANNELS_PATH)
        request = Request(
            url,
            headers={**dict(identity_request.headers), "Accept": "application/json"},
            method="GET",
        )
        response = self._open(
            request,
            body_limit=_MAX_JSON_BODY_BYTES,
            accepted_statuses=frozenset({200}),
        )
        payload = _json_object(response.body)
        items = payload.get("items")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
            raise YouTubeHttpTransportError("YouTube authenticated channel identity is ambiguous")
        channel_id = items[0].get("id")
        if not isinstance(channel_id, str):
            raise YouTubeHttpTransportError("YouTube authenticated channel identity is malformed")
        value = channel_id.strip()
        if (
            not value
            or len(value) > _MAX_CHANNEL_ID_CHARS
            or any(ch.isspace() for ch in value)
            or any(ord(ch) < 33 or ord(ch) == 127 for ch in value)
        ):
            raise YouTubeHttpTransportError("YouTube authenticated channel identity is malformed")
        return value

    def fetch_processing(self, status_request: YouTubeStatusRequest) -> Mapping[str, object]:
        if not isinstance(status_request, YouTubeStatusRequest):
            raise TypeError("status_request must be YouTubeStatusRequest")
        url = _validated_google_url(status_request.url, expected_path=_ALLOWED_STATUS_PATH)
        request = Request(
            url,
            headers={**dict(status_request.headers), "Accept": "application/json"},
            method="GET",
        )
        response = self._open(
            request,
            body_limit=_MAX_JSON_BODY_BYTES,
            accepted_statuses=frozenset({200}),
        )
        return _json_object(response.body)
