from __future__ import annotations

import pytest

from workflow_os.alpaca_paper_transport import (
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
        client_order_id="workflow-os:test:entry-contract",
        symbol="AAPL",
        qty="1",
        side="buy",
    )


def test_submit_rejects_invalid_caller_objects_before_transport() -> None:
    calls = 0

    def request_fn(request, timeout):
        nonlocal calls
        calls += 1
        return _HttpResult(200, b"{}", None, "application/json")

    with pytest.raises(ValueError, match="credentials"):
        submit_paper_order(credentials=object(), order=_order(), request_fn=request_fn)
    with pytest.raises(ValueError, match="order"):
        submit_paper_order(credentials=_creds(), order=object(), request_fn=request_fn)
    with pytest.raises(ValueError, match="request_fn"):
        submit_paper_order(credentials=_creds(), order=_order(), request_fn=None)

    assert calls == 0


def test_reconcile_rejects_invalid_caller_objects_before_transport() -> None:
    calls = 0

    def request_fn(request, timeout):
        nonlocal calls
        calls += 1
        return _HttpResult(200, b"{}", None, "application/json")

    with pytest.raises(ValueError, match="credentials"):
        reconcile_paper_order(
            credentials=object(),
            client_order_id="workflow-os:test:entry-contract",
            request_fn=request_fn,
        )
    with pytest.raises(ValueError, match="request_fn"):
        reconcile_paper_order(
            credentials=_creds(),
            client_order_id="workflow-os:test:entry-contract",
            request_fn=None,
        )

    assert calls == 0
