from __future__ import annotations

import pytest

from workflow_os.alpaca_paper_transport import (
    AlpacaPaperCredentials,
    AlpacaPaperOrder,
    reconcile_paper_order,
)


def _creds() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials("paper-key", "paper-secret")


@pytest.mark.parametrize("client_order_id", ["bad\nvalue", "bad\rvalue", "bad\tvalue", "bad\x00value", "bad\x7fvalue"])
def test_order_rejects_control_characters_in_client_order_id(client_order_id: str) -> None:
    with pytest.raises(ValueError, match="control characters"):
        AlpacaPaperOrder(
            client_order_id=client_order_id,
            symbol="AAPL",
            qty="1",
            side="buy",
        )


@pytest.mark.parametrize("client_order_id", ["bad\nvalue", "bad\rvalue", "bad\tvalue", "bad\x00value", "bad\x7fvalue"])
def test_reconcile_rejects_control_characters_before_transport(client_order_id: str) -> None:
    called = False

    def request_fn(request, timeout):
        nonlocal called
        called = True
        raise AssertionError("transport must not run")

    with pytest.raises(ValueError, match="control characters"):
        reconcile_paper_order(
            credentials=_creds(),
            client_order_id=client_order_id,
            request_fn=request_fn,
        )

    assert called is False
