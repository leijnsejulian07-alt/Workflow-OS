import json
from datetime import timezone

import pytest

from workflow_os import polymarket_gamma
from workflow_os.polymarket_gamma import fetch_gamma_market, normalize_gamma_market


def _raw(**overrides):
    raw = {
        "id": "m-1",
        "question": "Will the test resolve yes?",
        "resolutionSource": "https://example.test/official",
        "endDate": "2026-10-01T12:00:00Z",
        "liquidityNum": 7500,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.62", "0.38"]',
        "clobTokenIds": '["yes-token", "no-token"]',
        "active": True,
        "closed": False,
        "acceptingOrders": True,
    }
    raw.update(overrides)
    return raw


def test_normalizes_documented_gamma_shape():
    market = normalize_gamma_market(_raw())
    assert market.market_id == "m-1"
    assert market.yes_price == pytest.approx(0.62)
    assert market.yes_token_id == "yes-token"
    assert market.liquidity_usd == pytest.approx(7500)
    assert market.resolves_at.tzinfo == timezone.utc
    assert market.resolution_source_present


def test_maps_token_id_using_same_yes_outcome_index():
    market = normalize_gamma_market(_raw(
        outcomes=["No", "Yes"], outcomePrices=["0.38", "0.62"], clobTokenIds=["no-token", "yes-token"]
    ))
    assert market.yes_price == pytest.approx(0.62)
    assert market.yes_token_id == "yes-token"


class _Response:
    status = 200

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self._body


def test_fetch_exact_market_uses_id_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response(_raw())

    monkeypatch.setattr(polymarket_gamma, "urlopen", fake_urlopen)
    market = fetch_gamma_market(market_id="m-1", timeout_seconds=4)
    assert seen == {"url": "https://gamma-api.polymarket.com/markets/m-1", "timeout": 4}
    assert market.market_id == "m-1"
    assert market.yes_token_id == "yes-token"


def test_fetch_exact_market_rejects_identity_mismatch(monkeypatch):
    monkeypatch.setattr(polymarket_gamma, "urlopen", lambda request, timeout: _Response(_raw(id="other")))
    with pytest.raises(ValueError, match="identity mismatch"):
        fetch_gamma_market(market_id="m-1")


def test_fetch_exact_market_rejects_unsafe_path_id_before_network(monkeypatch):
    called = False

    def fake_urlopen(request, timeout):
        nonlocal called
        called = True
        return _Response(_raw())

    monkeypatch.setattr(polymarket_gamma, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="unsupported characters"):
        fetch_gamma_market(market_id="../m-1")
    assert called is False


@pytest.mark.parametrize(
    "change",
    [
        {"id": ""},
        {"outcomes": '["No"]', "outcomePrices": '["1"]', "clobTokenIds": '["no-token"]'},
        {"outcomePrices": '["nan", "0.38"]'},
        {"clobTokenIds": '["", "no-token"]'},
        {"clobTokenIds": '["yes-token"]'},
        {"liquidityNum": -1},
        {"endDate": ""},
    ],
)
def test_malformed_market_fails_closed(change):
    with pytest.raises((ValueError, TypeError)):
        normalize_gamma_market(_raw(**change))
