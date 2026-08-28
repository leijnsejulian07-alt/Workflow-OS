from __future__ import annotations

import hashlib
import json
import math
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener


_AWIN_API_HOST = "api.awin.com"
_AWIN_BASE_URL = "https://api.awin.com"
_MAX_RESPONSE_BODY_BYTES = 2 * 1024 * 1024
_ALLOWED_DATE_TYPES = {"transaction", "validation", "amendment"}
_ALLOWED_STATUSES = {"pending", "approved", "declined", "deleted"}


class AwinTransactionTransportError(RuntimeError):
    """Network/protocol failure without exposing credentials or response bodies."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class AwinTransactionFetchResult:
    publisher_id: int
    start_at: str
    end_at: str
    date_type: str
    status: str | None
    advertiser_id: int | None
    transactions: tuple[Mapping[str, Any], ...]
    evidence_sha256: str


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso_seconds(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_token(access_token: object) -> str:
    if not isinstance(access_token, str):
        raise ValueError("Awin access token must be a non-empty string")
    token = access_token.strip()
    if not token or len(token) > 8192 or any(ch in token for ch in "\r\n"):
        raise ValueError("Awin access token must be a non-empty string")
    return token


def _read_bounded(response: Any, *, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise AwinTransactionTransportError("Awin response exceeded the configured size limit")
    return body


def _decode_transactions(body: bytes) -> tuple[Mapping[str, Any], ...]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AwinTransactionTransportError("Awin returned malformed JSON") from exc
    if not isinstance(payload, list):
        raise AwinTransactionTransportError("Awin returned a non-list transaction response")
    transactions: list[Mapping[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise AwinTransactionTransportError("Awin returned a non-object transaction item")
        transactions.append(dict(item))
    return tuple(transactions)


def build_awin_transaction_url(
    *,
    publisher_id: int,
    start_at: datetime,
    end_at: datetime,
    date_type: str = "transaction",
    status: str | None = None,
    advertiser_id: int | None = None,
) -> tuple[str, str, str, str, str | None, int | None]:
    publisher = _positive_int(publisher_id, "publisher_id")
    start = _aware_utc(start_at, "start_at")
    end = _aware_utc(end_at, "end_at")
    if end < start:
        raise ValueError("end_at cannot be before start_at")
    if end - start > timedelta(days=31):
        raise ValueError("Awin transaction queries may span at most 31 days")

    if date_type not in _ALLOWED_DATE_TYPES:
        raise ValueError("unsupported Awin transaction date_type")
    if status is not None and status not in _ALLOWED_STATUSES:
        raise ValueError("unsupported Awin transaction status")
    advertiser = None if advertiser_id is None else _positive_int(advertiser_id, "advertiser_id")

    start_text = _iso_seconds(start)
    end_text = _iso_seconds(end)
    query: dict[str, str] = {
        "startDate": start_text,
        "endDate": end_text,
        "dateType": date_type,
        "timezone": "UTC",
        "showBasketProducts": "false",
    }
    if status is not None:
        query["status"] = status
    if advertiser is not None:
        query["advertiserId"] = str(advertiser)

    url = f"{_AWIN_BASE_URL}/publishers/{publisher}/transactions/?{urlencode(query)}"
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _AWIN_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path != f"/publishers/{publisher}/transactions/"
        or parsed.fragment
    ):
        raise ValueError("Awin transaction request has an unexpected origin or path")
    return url, start_text, end_text, date_type, status, advertiser


class AwinTransactionHttpTransport:
    """Bounded dependency-free GET transport for Awin publisher transactions.

    The official Awin API is pinned to the exact api.awin.com publisher transaction
    endpoint. OAuth bearer credentials are carried only in the Authorization header,
    redirects are disabled, response bodies are bounded, and callers choose a query
    window no larger than Awin's documented 31-day maximum.
    """

    def __init__(
        self,
        *,
        opener: OpenerDirector | Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
        ):
            raise TypeError("timeout_seconds must be a finite number")
        if not 1.0 <= float(timeout_seconds) <= 120.0:
            raise ValueError("timeout_seconds must be between 1 and 120 seconds")
        self._opener = opener if opener is not None else build_opener(_NoRedirectHandler())
        self._timeout = float(timeout_seconds)

    def _open(self, request: Request) -> bytes:
        try:
            response = self._opener.open(request, timeout=self._timeout)
            try:
                status = int(response.getcode())
                body = _read_bounded(response, limit=_MAX_RESPONSE_BODY_BYTES)
            finally:
                response.close()
        except HTTPError as exc:
            try:
                _read_bounded(exc, limit=_MAX_RESPONSE_BODY_BYTES)
            finally:
                exc.close()
            raise AwinTransactionTransportError(
                f"Awin transaction API returned HTTP {int(exc.code)}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise AwinTransactionTransportError(
                "Awin transaction transport failed before a confirmed response"
            ) from exc

        if status != 200:
            raise AwinTransactionTransportError(
                f"Awin transaction API returned HTTP {status}"
            )
        return body

    def fetch(
        self,
        *,
        access_token: str,
        publisher_id: int,
        start_at: datetime,
        end_at: datetime,
        date_type: str = "transaction",
        status: str | None = None,
        advertiser_id: int | None = None,
    ) -> AwinTransactionFetchResult:
        token = _validate_token(access_token)
        url, start_text, end_text, normalized_date_type, normalized_status, advertiser = (
            build_awin_transaction_url(
                publisher_id=publisher_id,
                start_at=start_at,
                end_at=end_at,
                date_type=date_type,
                status=status,
                advertiser_id=advertiser_id,
            )
        )
        publisher = _positive_int(publisher_id, "publisher_id")
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        body = self._open(request)
        transactions = _decode_transactions(body)
        return AwinTransactionFetchResult(
            publisher_id=publisher,
            start_at=start_text,
            end_at=end_text,
            date_type=normalized_date_type,
            status=normalized_status,
            advertiser_id=advertiser,
            transactions=transactions,
            evidence_sha256=hashlib.sha256(body).hexdigest(),
        )
