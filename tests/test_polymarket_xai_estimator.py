import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from workflow_os.polymarket_gamma import GammaMarket
from workflow_os.polymarket_xai_estimator import _extract_output_text, _normalize_probability_payload, estimate_with_xai

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
MARKET = GammaMarket("m1", "Will the event happen?", 0.62, "token", 10_000.0, NOW + timedelta(hours=12), "https://example.com/rules", True, False, True)


def test_no_key_never_calls_network():
    with patch.dict("os.environ", {}, clear=True), patch("workflow_os.polymarket_xai_estimator.urlopen") as urlopen:
        assert estimate_with_xai(MARKET) is None
    urlopen.assert_not_called()


def test_probability_payload_is_strict():
    assert _normalize_probability_payload('{"probability":0.74}') == 0.74
    for raw in ('{"probability":true}', '{"probability":0}', '{"probability":1}', '{"probability":0.74,"extra":1}', '[]'):
        try:
            _normalize_probability_payload(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(raw)


def test_extracts_only_message_output_text():
    payload = {"output": [{"type": "reasoning", "content": []}, {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"probability": 0.74})}]}]}
    assert _extract_output_text(payload) == '{"probability": 0.74}'


def test_missing_resolution_source_fails_closed_before_network():
    market = GammaMarket("m1", "Will the event happen?", 0.62, "token", 10_000.0, NOW + timedelta(hours=12), "", True, False, True)
    with patch("workflow_os.polymarket_xai_estimator.urlopen") as urlopen:
        assert estimate_with_xai(market, api_key="test-key") is None
    urlopen.assert_not_called()
