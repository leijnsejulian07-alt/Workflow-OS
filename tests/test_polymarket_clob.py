import pytest

from workflow_os.polymarket_clob import estimate_buy_slippage, estimate_sell_vwap, normalize_book


def _book(**overrides):
    raw = {
        "asset_id": "yes-token",
        "bids": [{"price": "0.59", "size": "100"}],
        "asks": [{"price": "0.60", "size": "5"}, {"price": "0.62", "size": "100"}],
    }
    raw.update(overrides)
    return raw


def test_normalizes_and_sorts_official_book_shape():
    book = normalize_book(_book(asks=[{"price": "0.62", "size": "100"}, {"price": "0.60", "size": "5"}]), expected_token_id="yes-token")
    assert book.asks[0].price == pytest.approx(0.60)


@pytest.mark.parametrize(
    "level",
    [
        {"price": "nan", "size": "1"},
        {"price": "inf", "size": "1"},
        {"price": "0.50", "size": "nan"},
        {"price": "0.50", "size": "inf"},
    ],
)
def test_non_finite_orderbook_levels_fail_closed(level):
    with pytest.raises(ValueError, match="invalid orderbook price/size"):
        normalize_book(_book(bids=[level]), expected_token_id="yes-token")


def test_small_order_has_zero_price_impact_at_best_ask():
    book = normalize_book(_book(), expected_token_id="yes-token")
    assert estimate_buy_slippage(book, stake_usd=3.0) == pytest.approx(0.0)


def test_larger_order_reports_vwap_impact():
    book = normalize_book(_book(), expected_token_id="yes-token")
    slip = estimate_buy_slippage(book, stake_usd=6.0)
    assert 0.0 < slip < 0.03


def test_insufficient_depth_fails_closed():
    book = normalize_book(_book(asks=[{"price": "0.60", "size": "1"}]), expected_token_id="yes-token")
    with pytest.raises(ValueError, match="insufficient"):
        estimate_buy_slippage(book, stake_usd=10.0)


def test_asset_mismatch_fails_closed():
    with pytest.raises(ValueError, match="mismatch"):
        normalize_book(_book(asset_id="different"), expected_token_id="yes-token")


def test_sell_vwap_uses_bid_depth_not_mark_price():
    book = normalize_book(_book(bids=[{"price": "0.59", "size": "2"}, {"price": "0.57", "size": "10"}]), expected_token_id="yes-token")
    assert estimate_sell_vwap(book, shares=4.0) == pytest.approx((2 * 0.59 + 2 * 0.57) / 4)


def test_sell_vwap_requires_full_executable_depth():
    book = normalize_book(_book(bids=[{"price": "0.59", "size": "1"}]), expected_token_id="yes-token")
    with pytest.raises(ValueError, match="insufficient bid depth"):
        estimate_sell_vwap(book, shares=2.0)


@pytest.mark.parametrize("shares", [0, -1, float("nan"), float("inf"), True])
def test_sell_vwap_rejects_invalid_share_amount(shares):
    book = normalize_book(_book(), expected_token_id="yes-token")
    with pytest.raises(ValueError):
        estimate_sell_vwap(book, shares=shares)
