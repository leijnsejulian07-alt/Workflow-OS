from __future__ import annotations

import json
import socket
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from workflow_os.adapters.whop_bounty_submission import (
    WHOP_BOUNTY_SUBMISSION_URL,
    WhopBountySubmissionRequest,
    WhopBountySubmissionResult,
    parse_workforce_submission_response,
)


_MAX_REQUEST_BODY_BYTES = 256 * 1024
_MAX_RESPONSE_BODY_BYTES = 256 * 1024
_WHOP_API_HOST = "api.whop.com"
_WHOP_SUBMISSION_PATH = "/api/v1/bounty_submissions"


class WhopBountyTransportError(RuntimeError):
    """Network/protocol failure without exposing credentials or request bodies."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validate_url(url: str) -> str:
    if url != WHOP_BOUNTY_SUBMISSION_URL:
        raise ValueError("Whop bounty request URL does not match the documented endpoint")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _WHOP_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path != _WHOP_SUBMISSION_PATH
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Whop bounty request has an unexpected origin or path")
    return url


def _validate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise TypeError("Whop bounty request headers must be a mapping")

    authorization = headers.get("Authorization")
    content_type = headers.get("Content-Type")
    version_date = headers.get("Api-Version-Date")
    idempotency_key = headers.get("Idempotency-Key")

    if (
        not isinstance(authorization, str)
        or not authorization.startswith("Bearer ")
        or len(authorization) > 8199
        or any(ch in authorization for ch in "\r\n")
    ):
        raise ValueError("Whop bounty request lacks a valid bearer credential")
    if content_type != "application/json":
        raise ValueError("Whop bounty request has an unexpected content type")
    if not isinstance(version_date, str) or len(version_date) != 10:
        raise ValueError("Whop bounty request lacks an API version date")
    if (
        not isinstance(idempotency_key, str)
        or not 8 <= len(idempotency_key) <= 255
        or any(ch in idempotency_key for ch in "\r\n")
    ):
        raise ValueError("Whop bounty request lacks a valid idempotency key")

    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Api-Version-Date": version_date,
        "Idempotency-Key": idempotency_key,
    }


def _read_bounded(response: Any, *, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise WhopBountyTransportError("Whop response exceeded the configured size limit")
    return body


def _decode_json(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WhopBountyTransportError("Whop returned malformed JSON") from exc
    if not isinstance(payload, Mapping):
        raise WhopBountyTransportError("Whop returned a non-object JSON response")
    return payload


class WhopBountyHttpTransport:
    """Bounded dependency-free transport for the official Whop bounty submit endpoint.

    Redirects are disabled, only the exact documented endpoint is accepted, response
    bodies are bounded, and retry/reconciliation policy remains outside this transport.
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

    def _open(self, request: Request) -> tuple[int, bytes]:
        try:
            response = self._opener.open(request, timeout=self._timeout)
            try:
                status = int(response.getcode())
                body = _read_bounded(response, limit=_MAX_RESPONSE_BODY_BYTES)
            finally:
                response.close()
            return status, body
        except HTTPError as exc:
            try:
                body = _read_bounded(exc, limit=_MAX_RESPONSE_BODY_BYTES)
            finally:
                exc.close()
            return int(exc.code), body
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise WhopBountyTransportError("Whop transport failed before a confirmed response") from exc

    def submit(
        self,
        request: WhopBountySubmissionRequest,
        *,
        expected_bounty_id: str,
    ) -> WhopBountySubmissionResult:
        if not isinstance(request, WhopBountySubmissionRequest):
            raise TypeError("request must be a WhopBountySubmissionRequest")

        url = _validate_url(request.url)
        headers = _validate_headers(request.headers)
        try:
            body = json.dumps(request.json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Whop bounty request body is not JSON serializable") from exc
        if len(body) > _MAX_REQUEST_BODY_BYTES:
            raise ValueError("Whop bounty request exceeded the configured size limit")

        http_request = Request(url, data=body, headers=headers, method="POST")
        status, response_body = self._open(http_request)
        payload = _decode_json(response_body)
        try:
            return parse_workforce_submission_response(
                status_code=status,
                payload=payload,
                expected_bounty_id=expected_bounty_id,
            )
        except (TypeError, ValueError) as exc:
            raise WhopBountyTransportError("Whop did not confirm the expected bounty submission state") from exc
