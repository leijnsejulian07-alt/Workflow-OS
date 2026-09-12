from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

_API_HOST = "api.openshorts.app"
_API_BASE = f"https://{_API_HOST}"
_PROCESS_PATH = "/api/process"
_STATUS_PREFIX = "/api/status/"
_MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
_MAX_ERROR_BODY_BYTES = 64 * 1024
_MAX_URL_CHARS = 4096
_MAX_JOB_ID_CHARS = 256
_MAX_WEBHOOK_SECRET_CHARS = 512
_SOURCE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "youtu.be", "vimeo.com", "www.vimeo.com"})


class OpenShortsHostedTransportError(RuntimeError):
    """Network/protocol failure without exposing credentials or remote bodies."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class OpenShortsProcessResult:
    job_id: str
    response_sha256: str


@dataclass(frozen=True)
class OpenShortsWebhookEvent:
    event: str
    job_id: str
    payload: Mapping[str, object]
    body_sha256: str


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


def _validate_api_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("OpenShorts API key must be a string")
    key = value.strip()
    if (
        not key.startswith("osk_")
        or len(key) < 12
        or len(key) > 512
        or any(ch.isspace() for ch in key)
        or any(ch in key for ch in "\r\n")
    ):
        raise ValueError("OpenShorts API key is malformed")
    return key


def _validate_job_id(value: object) -> str:
    if not isinstance(value, str):
        raise OpenShortsHostedTransportError("OpenShorts response omitted a valid job id")
    job_id = value.strip()
    if (
        not job_id
        or len(job_id) > _MAX_JOB_ID_CHARS
        or any(ch.isspace() for ch in job_id)
        or any(ord(ch) < 33 or ord(ch) == 127 for ch in job_id)
    ):
        raise OpenShortsHostedTransportError("OpenShorts response omitted a valid job id")
    return job_id


def _validate_public_https_url(value: object, *, name: str, allowed_hosts: frozenset[str] | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an https URL")
    url = value.strip()
    if not url or len(url) > _MAX_URL_CHARS:
        raise ValueError(f"{name} must be an https URL")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be a bounded public https URL")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError(f"{name} cannot target a local/private host")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError(f"{name} host is not allowlisted for hosted processing")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(f"{name} cannot target a local/private host")
    return url


def _validate_webhook_secret(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("webhook_secret must be a string")
    secret = value.strip()
    if (
        len(secret) < 32
        or len(secret) > _MAX_WEBHOOK_SECRET_CHARS
        or any(ord(ch) < 33 or ord(ch) == 127 for ch in secret)
    ):
        raise ValueError("webhook_secret must be at least 32 printable characters")
    return secret


def _bounded_read(response: Any, *, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise OpenShortsHostedTransportError("OpenShorts response exceeded the configured size limit")
    return body


def _json_object(body: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenShortsHostedTransportError("OpenShorts returned malformed JSON") from exc
    if not isinstance(payload, Mapping):
        raise OpenShortsHostedTransportError("OpenShorts returned a non-object JSON response")
    return dict(payload)


class OpenShortsHostedTransport:
    """Narrow hosted OpenShorts transport.

    This transport only submits processing jobs and reads their status. It never
    publishes clips and is not authority for rights, economics, settlement, or
    account health. Callers must satisfy Workflow OS gates before invoking it.
    """

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
        accepted_statuses: frozenset[int],
        body_limit: int = _MAX_JSON_BODY_BYTES,
    ) -> bytes:
        try:
            response = self._opener.open(request, timeout=self._timeout)
            try:
                status = int(response.getcode())
                body = _bounded_read(response, limit=body_limit)
            finally:
                response.close()
        except HTTPError as exc:
            try:
                _bounded_read(exc, limit=_MAX_ERROR_BODY_BYTES)
            finally:
                exc.close()
            raise OpenShortsHostedTransportError(
                f"OpenShorts API returned HTTP {int(exc.code)}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise OpenShortsHostedTransportError(
                "OpenShorts transport failed before a confirmed response"
            ) from exc

        if status not in accepted_statuses:
            raise OpenShortsHostedTransportError(f"OpenShorts API returned HTTP {status}")
        return body

    def process_video(
        self,
        *,
        api_key: str,
        source_url: str,
        webhook_url: str,
        webhook_secret: str,
        captions: bool = True,
        auto_hook: bool = True,
    ) -> OpenShortsProcessResult:
        key = _validate_api_key(api_key)
        source = _validate_public_https_url(source_url, name="source_url", allowed_hosts=_SOURCE_HOSTS)
        hook = _validate_public_https_url(webhook_url, name="webhook_url")
        secret = _validate_webhook_secret(webhook_secret)
        if not isinstance(captions, bool) or not isinstance(auto_hook, bool):
            raise TypeError("captions and auto_hook must be booleans")

        payload = {
            "url": source,
            "acknowledged": True,
            "webhook_url": hook,
            "webhook_secret": secret,
            "captions": captions,
            "auto_hook": auto_hook,
        }
        request = Request(
            f"{_API_BASE}{_PROCESS_PATH}",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            method="POST",
        )
        body = self._open(request, accepted_statuses=frozenset({200, 201, 202}))
        response = _json_object(body)
        job_id = _validate_job_id(response.get("job_id"))
        return OpenShortsProcessResult(
            job_id=job_id,
            response_sha256=hashlib.sha256(body).hexdigest(),
        )

    def get_status(self, *, api_key: str, job_id: str) -> Mapping[str, object]:
        key = _validate_api_key(api_key)
        normalized_job_id = _validate_job_id(job_id)
        path = f"{_STATUS_PREFIX}{quote(normalized_job_id, safe='')}"
        parsed = urlparse(f"{_API_BASE}{path}")
        if parsed.scheme != "https" or parsed.hostname != _API_HOST or not parsed.path.startswith(_STATUS_PREFIX):
            raise ValueError("OpenShorts status request has an unexpected origin or path")
        request = Request(
            f"{_API_BASE}{path}",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        return _json_object(self._open(request, accepted_statuses=frozenset({200})))


def verify_openshorts_webhook(
    *,
    body: bytes,
    signature_header: str,
    webhook_secret: str,
) -> OpenShortsWebhookEvent:
    if not isinstance(body, bytes) or not body or len(body) > _MAX_JSON_BODY_BYTES:
        raise ValueError("webhook body must be non-empty bounded bytes")
    secret = _validate_webhook_secret(webhook_secret)
    if not isinstance(signature_header, str):
        raise ValueError("OpenShorts webhook signature is missing")
    signature = signature_header.strip().lower()
    prefix = "sha256="
    digest = signature[len(prefix):] if signature.startswith(prefix) else ""
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("OpenShorts webhook signature is malformed")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise ValueError("OpenShorts webhook signature verification failed")

    payload = _json_object(body)
    event = payload.get("event")
    if event not in {"job.completed", "job.failed"}:
        raise OpenShortsHostedTransportError("OpenShorts webhook event is not terminal")
    job_id = _validate_job_id(payload.get("job_id"))
    if event == "job.completed":
        clips = payload.get("clips")
        if not isinstance(clips, list):
            raise OpenShortsHostedTransportError("completed OpenShorts webhook omitted clips")
        for clip in clips:
            if not isinstance(clip, Mapping):
                raise OpenShortsHostedTransportError("OpenShorts webhook contained malformed clip data")

    return OpenShortsWebhookEvent(
        event=str(event),
        job_id=job_id,
        payload=dict(payload),
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
