from datetime import timezone

import pytest

from workflow_os.polymarket_gamma import normalize_gamma_market


def _raw(**overrides):
    raw = {
        "id": "m-1",
        "question": "Will the test resolve yes?",
        "resolutionSource": "https://example.test/official",
        "endDate": "2026-10-01T12:00:00Z",
        "liquidityNum": 7500,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.62", "0.38"]',
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
    assert market.liquidity_usd == pytest.approx(7500)
    assert market.resolves_at.tzinfo == timezone.utc
    assert market.resolution_source_present


def test_accepts_array_fields_when_api_returns_decoded_json():
    market = normalize_gamma_market(_raw(outcomes=["No", "Yes"], outcomePrices=["0.38", "0.62"]))
    assert market.yes_price == pytest.approx(0.62)


@pytest.mark.parametrize(
    "change",
    [
        {"id": ""},
        {"outcomes": '["No"]', "outcomePrices": '["1"]'},
        {"outcomePrices": '["nan", "0.38"]'},
        {"liquidityNum": -1},
        {"endDate": ""},
    ],
)
def test_malformed_market_fails_closed(change):
    with pytest.raises((ValueError, TypeError)):
        normalize_gamma_market(_raw(**change))
