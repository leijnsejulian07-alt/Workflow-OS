from __future__ import annotations

import pytest

from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials


@pytest.mark.parametrize(
    ("key_id", "secret_key"),
    [
        (" paper-key", "paper-secret"),
        ("paper-key ", "paper-secret"),
        ("paper-key", " paper-secret"),
        ("paper-key", "paper-secret "),
    ],
)
def test_credentials_reject_surrounding_whitespace(key_id: str, secret_key: str) -> None:
    with pytest.raises(ValueError, match="surrounding whitespace"):
        AlpacaPaperCredentials(key_id, secret_key)
