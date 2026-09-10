from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from workflow_os.alpaca_market_data import (
    ALPACA_MARKET_DATA_BASE_URL,
    AlpacaLatestBarObservation,
    fetch_latest_iex_bar,
)
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult


def _creds() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials("paper-key", "paper-secret")


def _valid_bar() -> dict[str, object]:
    return {
        "bar": {
            "t": "2026-09-10T14:31:00Z",
            "o": 226.1,
            "h": 226.5,
            "l": 225.9,
            "c": 226.4,
            "v": 12345,
            "n": 321,
            "vw": 226.2,
        }
    }


def _json_result(status: int, payload: dict[str, object]) -> _HttpResult:
    return _HttpResult(
        status=status,
        body=json.dumps(payload).encode("utf-8"),
        request_id="market-request-1",
        content_type="application/json; charset=utf-8",
    )


def test_latest_bar_uses_exact_market_data_host_and_fixed_iex_feed() -> None:
    captured: dict[str, object] = {}

    def request_fn(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["key"] = request.get_header("Apca-api-key-id")
        captured["secret"] = request.get_header("Apca-api-secret-key")
        return _json_result(200, _valid_bar())

    observation = fetch_latest_iex_bar(
        credentials=_creds(),
        symbol="AAPL",
        request_fn=request_fn,
    )

    assert isinstance(observation, AlpacaLatestBarObservation)
    assert observation.symbol == "AAPL"
    assert observation.feed == "iex"
    assert observation.close == 226.4
    assert observation.request_id == "market-request-1"
    assert captured["method"] == "GET"
    assert captured["url"] == (
        f"{ALPACA_MARKET_DATA_BASE_URL}/v2/stocks/AAPL/bars/latest?feed=iex&currency=USD"
    )
    assert captured["key"] == "paper-key"
    assert captured["secret"] == "paper-secret"


def test_non_exact_market_data_host_fails_before_transport() -> None:
    called = False

    def request_fn(request, timeout):
        nonlocal called
        called = True
        return _json_result(200, _valid_bar())

    with pytest.raises(ValueError, match="exact Alpaca market-data"):
        fetch_latest_iex_bar(
            credentials=_creds(),
            symbol="AAPL",
            base_url="https://api.alpaca.markets",
            request_fn=request_fn,
        )
    assert called is False


@pytest.mark.parametrize("symbol", [" aapl", "AAPL ", "aapl", "AAPL/../../X", "", "A" * 33])
def test_unsafe_or_ambiguous_symbols_fail_before_transport(symbol: str) -> None:
    called = False

    def request_fn(request, timeout):
        nonlocal called
        called = True
        return _json_result(200, _valid_bar())

    with pytest.raises(ValueError):
        fetch_latest_iex_bar(
            credentials=_creds(),
            symbol=symbol,
            request_fn=request_fn,
        )
    assert called is False


def test_network_or_http_ambiguity_returns_no_observation() -> None:
    def raises(request, timeout):
        raise URLError("connection reset")

    assert fetch_latest_iex_bar(credentials=_creds(), symbol="AAPL", request_fn=raises) is None
    for status in (301, 400, 401, 403, 429, 500, 503):
        assert (
            fetch_latest_iex_bar(
                credentials=_creds(),
                symbol="AAPL",
                request_fn=lambda request, timeout, status=status: _json_result(status, _valid_bar()),
            )
            is None
        )


def test_missing_or_wrong_mime_returns_no_observation() -> None:
    body = json.dumps(_valid_bar()).encode("utf-8")
    for mime in (None, "text/html", "text/plain"):
        result = fetch_latest_iex_bar(
            credentials=_creds(),
            symbol="AAPL",
            request_fn=lambda request, timeout, mime=mime: _HttpResult(
                200, body, "market-request-1", mime
            ),
        )
        assert result is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda bar: bar.pop("bar"),
        lambda bar: bar["bar"].__setitem__("c", float("nan")),
        lambda bar: bar["bar"].__setitem__("h", 225.0),
        lambda bar: bar["bar"].__setitem__("l", 227.0),
        lambda bar: bar["bar"].__setitem__("v", -1),
        lambda bar: bar["bar"].__setitem__("n", True),
        lambda bar: bar["bar"].__setitem__("t", "not-rfc3339"),
    ],
)
def test_malformed_latest_bar_fails_closed(mutation) -> None:
    payload = _valid_bar()
    mutation(payload)
    assert (
        fetch_latest_iex_bar(
            credentials=_creds(),
            symbol="AAPL",
            request_fn=lambda request, timeout: _json_result(200, payload),
        )
        is None
    )


def test_invalid_timeout_and_credentials_fail_before_transport() -> None:
    called = False

    def request_fn(request, timeout):
        nonlocal called
        called = True
        return _json_result(200, _valid_bar())

    with pytest.raises(ValueError, match="timeout_seconds"):
        fetch_latest_iex_bar(
            credentials=_creds(),
            symbol="AAPL",
            timeout_seconds=31,
            request_fn=request_fn,
        )
    with pytest.raises(ValueError, match="credentials"):
        fetch_latest_iex_bar(
            credentials=object(),
            symbol="AAPL",
            request_fn=request_fn,
        )
    assert called is False
