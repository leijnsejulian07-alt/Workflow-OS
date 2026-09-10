from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from workflow_os.alpaca_paper_transport import (
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperCredentials,
    AlpacaPaperOrder,
    _HttpResult,
    reconcile_paper_order,
    submit_paper_order,
)


def _creds() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials("paper-key", "paper-secret")


def _order() -> AlpacaPaperOrder:
    return AlpacaPaperOrder(
        client_order_id="workflow-os:test:001",
        symbol="AAPL",
        qty="1",
        side="buy",
    )


def _json_result(status: int, body: bytes, request_id: str | None = None) -> _HttpResult:
    return _HttpResult(status, body, request_id, "application/json; charset=utf-8")


def test_live_endpoint_is_impossible_to_select() -> None:
    with pytest.raises(ValueError, match="exact Alpaca paper"):
        submit_paper_order(
            credentials=_creds(),
            order=_order(),
            base_url="https://api.alpaca.markets",
            request_fn=lambda request, timeout: _json_result(200, b"{}"),
        )


def test_credentials_are_not_exposed_by_repr_and_reject_header_injection() -> None:
    credentials = _creds()
    assert "paper-key" not in repr(credentials)
    assert "paper-secret" not in repr(credentials)
    with pytest.raises(ValueError):
        AlpacaPaperCredentials("paper-key\r\nInjected: yes", "secret")
    with pytest.raises(ValueError):
        AlpacaPaperCredentials("paper-key", "secret\nInjected: yes")


def test_submit_uses_official_paper_endpoint_and_client_order_id() -> None:
    captured = {}

    def request_fn(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _json_result(
            200,
            json.dumps(
                {"id": "alpaca-order-123", "client_order_id": "workflow-os:test:001"}
            ).encode(),
            "request-1",
        )

    result = submit_paper_order(
        credentials=_creds(),
        order=_order(),
        request_fn=request_fn,
    )

    assert result.outcome == "APPLIED"
    assert result.external_reference == "alpaca-order-123"
    assert captured["url"] == f"{ALPACA_PAPER_BASE_URL}/v2/orders"
    assert captured["body"]["client_order_id"] == "workflow-os:test:001"
    assert captured["body"]["type"] == "market"
    assert captured["body"]["time_in_force"] == "day"
    assert "paper-secret" not in json.dumps(captured["body"])


def test_success_with_mismatched_client_order_identity_is_unknown() -> None:
    result = submit_paper_order(
        credentials=_creds(),
        order=_order(),
        request_fn=lambda request, timeout: _json_result(
            200,
            b'{"id":"alpaca-order-123","client_order_id":"different"}',
        ),
    )
    assert result.outcome == "UNKNOWN"
    assert result.external_reference is None


def test_success_with_unbounded_or_control_character_external_reference_is_unknown() -> None:
    for external_reference in ("x" * 257, "alpaca\norder"):
        result = submit_paper_order(
            credentials=_creds(),
            order=_order(),
            request_fn=lambda request, timeout, external_reference=external_reference: _json_result(
                200,
                json.dumps(
                    {
                        "id": external_reference,
                        "client_order_id": "workflow-os:test:001",
                    }
                ).encode(),
            ),
        )
        assert result.outcome == "UNKNOWN"
        assert result.external_reference is None


def test_success_with_unexpected_or_missing_mime_is_unknown() -> None:
    body = b'{"id":"alpaca-order-123","client_order_id":"workflow-os:test:001"}'
    for content_type in (None, "text/html", "text/plain", "application/octet-stream"):
        result = submit_paper_order(
            credentials=_creds(),
            order=_order(),
            request_fn=lambda request, timeout, mime=content_type: _HttpResult(
                200, body, None, mime
            ),
        )
        assert result.outcome == "UNKNOWN"


def test_explicit_client_rejection_is_not_applied() -> None:
    result = submit_paper_order(
        credentials=_creds(),
        order=_order(),
        request_fn=lambda request, timeout: _json_result(422, b'{"message":"rejected"}'),
    )
    assert result.outcome == "NOT_APPLIED"


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 301, 302])
def test_ambiguous_server_conflict_timeout_or_redirect_status_is_unknown(status: int) -> None:
    result = submit_paper_order(
        credentials=_creds(),
        order=_order(),
        request_fn=lambda request, timeout: _json_result(status, b"{}"),
    )
    assert result.outcome == "UNKNOWN"


def test_transport_exception_after_dispatch_is_unknown() -> None:
    def request_fn(request, timeout):
        raise URLError("connection reset")

    result = submit_paper_order(
        credentials=_creds(),
        order=_order(),
        request_fn=request_fn,
    )
    assert result.outcome == "UNKNOWN"


def test_reconcile_finds_applied_order_by_exact_client_order_id() -> None:
    captured = {}

    def request_fn(request, timeout):
        captured["url"] = request.full_url
        return _json_result(
            200,
            b'{"id":"alpaca-order-123","client_order_id":"workflow-os:test:001"}',
        )

    result = reconcile_paper_order(
        credentials=_creds(),
        client_order_id="workflow-os:test:001",
        request_fn=request_fn,
    )
    assert result.outcome == "FOUND_APPLIED"
    assert result.external_reference == "alpaca-order-123"
    assert captured["url"].startswith(
        f"{ALPACA_PAPER_BASE_URL}/v2/orders:by_client_order_id?"
    )


def test_reconcile_unbounded_or_control_character_external_reference_remains_unknown() -> None:
    for external_reference in ("x" * 257, "alpaca\torder"):
        result = reconcile_paper_order(
            credentials=_creds(),
            client_order_id="workflow-os:test:001",
            request_fn=lambda request, timeout, external_reference=external_reference: _json_result(
                200,
                json.dumps(
                    {
                        "id": external_reference,
                        "client_order_id": "workflow-os:test:001",
                    }
                ).encode(),
            ),
        )
        assert result.outcome == "STILL_UNKNOWN"
        assert result.external_reference is None


def test_reconcile_unexpected_or_missing_mime_remains_unknown() -> None:
    body = b'{"id":"alpaca-order-123","client_order_id":"workflow-os:test:001"}'
    for content_type in (None, "text/html", "text/plain", "application/octet-stream"):
        result = reconcile_paper_order(
            credentials=_creds(),
            client_order_id="workflow-os:test:001",
            request_fn=lambda request, timeout, mime=content_type: _HttpResult(
                200, body, None, mime
            ),
        )
        assert result.outcome == "STILL_UNKNOWN"


def test_reconcile_lookup_miss_remains_unknown_fail_closed() -> None:
    result = reconcile_paper_order(
        credentials=_creds(),
        client_order_id="workflow-os:test:001",
        request_fn=lambda request, timeout: _json_result(404, b'{"message":"not found"}'),
    )
    assert result.outcome == "STILL_UNKNOWN"


def test_order_contract_rejects_unbounded_or_non_v1_order_shapes() -> None:
    with pytest.raises(ValueError):
        AlpacaPaperOrder("x", "AAPL", "0", "buy")
    with pytest.raises(ValueError):
        AlpacaPaperOrder("x", "AAPL", "1" * 65, "buy")
    with pytest.raises(ValueError):
        AlpacaPaperOrder("x", "AAPL", "1", "buy", order_type="limit")
    with pytest.raises(ValueError):
        AlpacaPaperOrder("x", "AAPL", "1", "buy", time_in_force="gtc")
