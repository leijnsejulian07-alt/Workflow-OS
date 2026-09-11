from __future__ import annotations

from tests import unittest_compat as pytest

from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials


@pytest.mark.parametrize("control", ["\x00", "\t", "\x1f", "\x7f"])
def test_credentials_reject_all_ascii_control_characters(control: str) -> None:
    with pytest.raises(ValueError, match="paper key_id is invalid"):
        AlpacaPaperCredentials(f"paper{control}key", "paper-secret")

    with pytest.raises(ValueError, match="paper secret_key is invalid"):
        AlpacaPaperCredentials("paper-key", f"paper{control}secret")

load_tests = pytest.make_load_tests(globals())
