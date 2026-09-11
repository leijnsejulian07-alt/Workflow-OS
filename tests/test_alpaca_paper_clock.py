import json
from datetime import timezone
from urllib.request import Request

from workflow_os.alpaca_paper_clock import fetch_paper_market_clock
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult


def _credentials() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials("paper-key", "paper-secret")


def _result(payload: object, *, status: int = 200, content_type: str = "application/json") -> _HttpResult:
    return _HttpResult(
        status=status,
        body=json.dumps(payload).encode("utf-8"),
        request_id="req-clock-1",
        content_type=content_type,
    )


def test_fetch_paper_market_clock_uses_exact_paper_endpoint_and_auth_headers() -> None:
    seen: dict[str, object] = {}

    def request_fn(request: Request, timeout: float) -> _HttpResult:
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        seen["key"] = request.headers.get("Apca-api-key-id")
        seen["secret"] = request.headers.get("Apca-api-secret-key")
        return _result({"timestamp": "2026-09-11T13:31:00Z", "is_open": True})

    clock = fetch_paper_market_clock(credentials=_credentials(), request_fn=request_fn)

    assert clock is not None
    assert seen == {
        "url": "https://paper-api.alpaca.markets/v2/clock",
        "method": "GET",
        "timeout": 10.0,
        "key": "paper-key",
        "secret": "paper-secret",
    }
    assert clock.timestamp.tzinfo == timezone.utc
    assert clock.timestamp.isoformat() == "2026-09-11T13:31:00+00:00"
    assert clock.is_open is True
    assert clock.request_id == "req-clock-1"


def test_fetch_paper_market_clock_accepts_closed_market_as_valid_state() -> None:
    clock = fetch_paper_market_clock(
        credentials=_credentials(),
        request_fn=lambda request, timeout: _result(
            {"timestamp": "2026-09-11T22:31:00-04:00", "is_open": False}
        ),
    )
    assert clock is not None
    assert clock.is_open is False


def test_fetch_paper_market_clock_fails_closed_on_transport_and_response_ambiguity() -> None:
    def raises(request: Request, timeout: float) -> _HttpResult:
        raise TimeoutError("timed out")

    assert fetch_paper_market_clock(credentials=_credentials(), request_fn=raises) is None
    assert fetch_paper_market_clock(
        credentials=_credentials(),
        request_fn=lambda request, timeout: _result({}, status=429),
    ) is None
    assert fetch_paper_market_clock(
        credentials=_credentials(),
        request_fn=lambda request, timeout: _result(
            {"timestamp": "2026-09-11T13:31:00Z", "is_open": True},
            content_type="text/html",
        ),
    ) is None
    assert fetch_paper_market_clock(
        credentials=_credentials(),
        request_fn=lambda request, timeout: _result(
            {"timestamp": "not-a-time", "is_open": True}
        ),
    ) is None
    assert fetch_paper_market_clock(
        credentials=_credentials(),
        request_fn=lambda request, timeout: _result(
            {"timestamp": "2026-09-11T13:31:00", "is_open": True}
        ),
    ) is None
    assert fetch_paper_market_clock(
        credentials=_credentials(),
        request_fn=lambda request, timeout: _result(
            {"timestamp": "2026-09-11T13:31:00Z", "is_open": 1}
        ),
    ) is None


def test_fetch_paper_market_clock_rejects_live_host() -> None:
    try:
        fetch_paper_market_clock(
            credentials=_credentials(),
            base_url="https://api.alpaca.markets",
            request_fn=lambda request, timeout: _result(
                {"timestamp": "2026-09-11T13:31:00Z", "is_open": True}
            ),
        )
    except ValueError as exc:
        assert "paper API" in str(exc)
    else:
        raise AssertionError("live Alpaca host must be rejected")
