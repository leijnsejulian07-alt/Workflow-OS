from __future__ import annotations

import json

from workflow_os import polymarket_paper_cli


def test_cli_without_xai_key_fails_before_network_or_store(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    db = tmp_path / "paper.sqlite3"

    assert polymarket_paper_cli.main(["--db", str(db)]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "reason": "XAI_API_KEY_REQUIRED", "network_started": False}
    assert not db.exists()


def test_cli_rejects_invalid_market_limit_before_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XAI_API_KEY", "should-not-be-used")
    db = tmp_path / "paper.sqlite3"

    assert polymarket_paper_cli.main(["--db", str(db), "--market-limit", "0"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "reason": "INVALID_MARKET_LIMIT"}
    assert not db.exists()


def test_cli_rejects_invalid_estimate_budget_before_store(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XAI_API_KEY", "should-not-be-used")
    db = tmp_path / "paper.sqlite3"

    assert polymarket_paper_cli.main(["--db", str(db), "--max-estimates", "11"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "reason": "INVALID_MAX_ESTIMATES"}
    assert not db.exists()


def test_cli_caps_paid_estimator_calls(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    calls = 0

    def fake_estimator(_market):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(polymarket_paper_cli, "estimate_with_xai", fake_estimator)
    monkeypatch.setattr(
        polymarket_paper_cli,
        "run_paper_cycle",
        lambda *, store, estimator, market_limit: _exercise_estimator(estimator, market_limit),
    )

    db = tmp_path / "paper.sqlite3"
    assert polymarket_paper_cli.main(["--db", str(db), "--market-limit", "8", "--max-estimates", "2"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert calls == 2
    assert payload["estimates_used"] == 2
    assert payload["max_estimates"] == 2


def _exercise_estimator(estimator, market_limit):
    from workflow_os.polymarket_paper_runner import PaperRunSummary

    for _ in range(market_limit):
        estimator(object())
    return PaperRunSummary(scanned=market_limit, opened=0, held=market_limit, stopped=False, stop_reason=None)
