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
