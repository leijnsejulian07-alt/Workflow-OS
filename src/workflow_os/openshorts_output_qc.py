from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from .adapters.local_media_ingest import ingest_local_media
from .openshorts_output_provenance import OpenShortsClipOutput, OpenShortsOutputProvenanceStore
from .production_handoff import ProducerOutput
from .qc_evidence import BoundMediaQC, run_bound_media_qc

_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_DEFAULT_DOWNLOAD_BYTES = 128 * 1024 * 1024
_MAX_HOSTS = 16
_MAX_RESOLVED_ADDRESSES = 32
_CHUNK_BYTES = 1024 * 1024
_ALLOWED_MEDIA = {"video/mp4": ".mp4", "video/webm": ".webm"}
_OPENSHORTS_API_HOST = "api.openshorts.app"


class OpenShortsOutputQCError(RuntimeError):
    """Fail-closed remote-output verification error."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class OpenShortsOutputQCEvidence:
    idempotency_key: str
    provider_job_id: str
    clip_index: int
    provider_evidence_sha256: str
    media_sha256: str
    media_type: str
    size_bytes: int
    duration_ms: int
    width: int
    height: int
    video_codec: str
    has_audio: bool


def _hosts(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("allowed_download_hosts must be an iterable of explicit hosts")
    hosts: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("allowed download hosts must be strings")
        host = raw.strip().lower().rstrip(".")
        if (
            not host
            or len(host) > 253
            or ":" in host
            or "/" in host
            or "@" in host
            or "*" in host
            or host.startswith(".")
            or host.endswith(".")
        ):
            raise ValueError("allowed download host is malformed")
        hosts.add(host)
        if len(hosts) > _MAX_HOSTS:
            raise ValueError("allowed download host list exceeds configured bound")
    if not hosts:
        raise ValueError("at least one allowed download host is required")
    return frozenset(hosts)


def _public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_resolution(host: str, resolver: Callable[..., Any]) -> None:
    try:
        results = resolver(host, 443, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise OpenShortsOutputQCError("OpenShorts output host resolution failed") from exc
    if not isinstance(results, (list, tuple)) or not results or len(results) > _MAX_RESOLVED_ADDRESSES:
        raise OpenShortsOutputQCError("OpenShorts output host resolution is outside allowed bounds")
    addresses: set[str] = set()
    for item in results:
        try:
            address = str(item[4][0]).strip()
            if not address:
                raise ValueError
            addresses.add(address)
        except (IndexError, TypeError, ValueError) as exc:
            raise OpenShortsOutputQCError("OpenShorts output host resolved malformed address data") from exc
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise OpenShortsOutputQCError("OpenShorts output host resolved to a local/private address")


def _validated_url(value: str, allowed_hosts: frozenset[str]) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("OpenShorts download URL must be a string")
    url = value.strip()
    if not url or len(url) > 4096:
        raise ValueError("OpenShorts download URL is missing or too long")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path
        or parsed.fragment
        or host not in allowed_hosts
    ):
        raise ValueError("OpenShorts download URL is outside the explicit https allowlist")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _public_ip(host):
        raise ValueError("OpenShorts download URL targets a local/private address")
    return url, host


def _validate_api_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("OpenShorts API key must be a string")
    key = value.strip()
    if (
        not key.startswith("osk_")
        or not 12 <= len(key) <= 512
        or any(ch.isspace() for ch in key)
        or any(ch in key for ch in "\r\n")
    ):
        raise ValueError("OpenShorts API key is malformed")
    return key


def _validate_output_provenance(
    output: OpenShortsClipOutput,
    store: OpenShortsOutputProvenanceStore,
) -> None:
    if not isinstance(output, OpenShortsClipOutput):
        raise TypeError("output must be OpenShortsClipOutput")
    if not isinstance(store, OpenShortsOutputProvenanceStore):
        raise TypeError("store must be OpenShortsOutputProvenanceStore")
    persisted = store.list_for(output.idempotency_key)
    matches = [item for item in persisted if item.clip_index == output.clip_index]
    if len(matches) != 1 or matches[0] != output:
        raise RuntimeError("OpenShorts output is not bound to immutable durable provenance")


def _bounded_positive_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_content_type(response: Any) -> tuple[str, str]:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        raise OpenShortsOutputQCError("OpenShorts output response omitted headers")
    encoding = str(headers.get("Content-Encoding") or "").strip().lower()
    if encoding not in {"", "identity"}:
        raise OpenShortsOutputQCError("compressed OpenShorts output responses are not accepted")
    raw_type = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    suffix = _ALLOWED_MEDIA.get(raw_type)
    if suffix is None:
        raise OpenShortsOutputQCError("OpenShorts output response has an unsupported media type")
    return raw_type, suffix


def _declared_length(response: Any, max_bytes: int) -> int | None:
    headers = response.headers
    raw = headers.get("Content-Length")
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise OpenShortsOutputQCError("OpenShorts output response has malformed Content-Length") from exc
    if not 1 <= value <= max_bytes:
        raise OpenShortsOutputQCError("OpenShorts output response exceeds the configured size bound")
    return value


def _download_to_workspace(
    *,
    url: str,
    host: str,
    workspace_root: Path,
    opener: OpenerDirector | Any,
    timeout_seconds: int,
    max_bytes: int,
    api_key: str | None,
) -> tuple[Path, str]:
    headers = {
        "Accept": "video/mp4, video/webm",
        "Accept-Encoding": "identity",
        "User-Agent": "Workflow-OS/OpenShorts-QC",
    }
    if host == _OPENSHORTS_API_HOST:
        if api_key is None:
            raise OpenShortsOutputQCError("authenticated OpenShorts-hosted output download requires an API key")
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers, method="GET")
    try:
        response = opener.open(request, timeout=timeout_seconds)
    except HTTPError as exc:
        try:
            code = int(exc.code)
        finally:
            exc.close()
        raise OpenShortsOutputQCError(f"OpenShorts output download returned HTTP {code}") from exc
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise OpenShortsOutputQCError("OpenShorts output download failed before a confirmed response") from exc

    path: Path | None = None
    try:
        status = int(response.getcode())
        if status != 200:
            raise OpenShortsOutputQCError(f"OpenShorts output download returned HTTP {status}")
        media_type, suffix = _read_content_type(response)
        declared = _declared_length(response, max_bytes)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".workflow-os-openshorts-qc-",
            suffix=suffix,
            dir=workspace_root,
            delete=False,
        )
        path = Path(handle.name)
        total = 0
        try:
            while True:
                chunk = response.read(_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray)):
                    raise OpenShortsOutputQCError("OpenShorts output response yielded non-byte content")
                total += len(chunk)
                if total > max_bytes:
                    raise OpenShortsOutputQCError("OpenShorts output response exceeded the configured size bound")
                handle.write(chunk)
        finally:
            handle.close()
        if total < 1 or (declared is not None and total != declared):
            raise OpenShortsOutputQCError("OpenShorts output response length did not match bounded evidence")
        return path, media_type
    except Exception:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        response.close()


def verify_openshorts_output_technical_qc(
    output: OpenShortsClipOutput,
    *,
    store: OpenShortsOutputProvenanceStore,
    workspace_root: str | os.PathLike[str],
    allowed_download_hosts: Iterable[str],
    api_key: str | None = None,
    max_download_bytes: int = _DEFAULT_DOWNLOAD_BYTES,
    timeout_seconds: int = 30,
    expected_duration_ms: int | None = None,
    require_audio: bool = False,
    opener: OpenerDirector | Any | None = None,
    resolver: Callable[..., Any] = socket.getaddrinfo,
    probe: Callable[..., BoundMediaQC] = run_bound_media_qc,
) -> OpenShortsOutputQCEvidence:
    """Download and technically QC one immutable OpenShorts clip output.

    This boundary proves only the exact remote media bytes and technical media QC.
    It grants no campaign, rights, disclosure, publication or payout authority.
    The caller must keep those as independent fail-closed gates before Whop I/O.
    """
    _validate_output_provenance(output, store)
    hosts = _hosts(allowed_download_hosts)
    url, host = _validated_url(output.download_url, hosts)
    _validate_resolution(host, resolver)
    key = _validate_api_key(api_key)
    max_bytes = _bounded_positive_int(
        max_download_bytes,
        "max_download_bytes",
        minimum=1,
        maximum=_MAX_DOWNLOAD_BYTES,
    )
    timeout = _bounded_positive_int(timeout_seconds, "timeout_seconds", minimum=1, maximum=120)
    if not isinstance(require_audio, bool):
        raise ValueError("require_audio must be a boolean")
    if expected_duration_ms is not None:
        expected_duration_ms = _bounded_positive_int(
            expected_duration_ms,
            "expected_duration_ms",
            minimum=250,
            maximum=3 * 60 * 1000,
        )
    if not callable(probe):
        raise TypeError("probe must be callable")

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")
    runtime_opener = opener if opener is not None else build_opener(_NoRedirectHandler())

    path, media_type = _download_to_workspace(
        url=url,
        host=host,
        workspace_root=root,
        opener=runtime_opener,
        timeout_seconds=timeout,
        max_bytes=max_bytes,
        api_key=key,
    )
    cleanup_error: OSError | None = None
    try:
        relative = path.relative_to(root).as_posix()
        producer = ingest_local_media(
            root,
            relative,
            producer="openshorts-authenticated-output-v1",
            max_bytes=max_bytes,
        )
        if producer.media_type != media_type:
            raise OpenShortsOutputQCError("downloaded media type disagrees with local media evidence")
        qc = probe(
            str(root),
            producer,
            expected_duration_ms=expected_duration_ms,
            require_audio=require_audio,
        )
        if not isinstance(qc, BoundMediaQC):
            raise TypeError("probe must return BoundMediaQC")
        if qc.source_sha256 != producer.sha256 or qc.source_size_bytes != producer.size_bytes:
            raise OpenShortsOutputQCError("technical QC is not bound to the exact downloaded media")
        result = qc.result
        if result.passed is not True:
            raise OpenShortsOutputQCError(f"technical media QC failed: {result.reason}")
        if (
            result.duration_ms is None
            or result.width is None
            or result.height is None
            or result.video_codec is None
        ):
            raise OpenShortsOutputQCError("technical media QC omitted required evidence")
        return OpenShortsOutputQCEvidence(
            idempotency_key=output.idempotency_key,
            provider_job_id=output.provider_job_id,
            clip_index=output.clip_index,
            provider_evidence_sha256=output.evidence_sha256,
            media_sha256=producer.sha256,
            media_type=producer.media_type,
            size_bytes=producer.size_bytes,
            duration_ms=result.duration_ms,
            width=result.width,
            height=result.height,
            video_codec=result.video_codec,
            has_audio=result.has_audio,
        )
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_error = exc
        if cleanup_error is not None:
            raise OpenShortsOutputQCError("temporary OpenShorts QC media could not be safely removed") from cleanup_error
