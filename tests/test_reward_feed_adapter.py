import pytest

from workflow_os.adapters.contracts import AccessMode, SourcePolicy
from workflow_os.adapters.reward_feed import normalize_reward_record


POLICY = SourcePolicy(
    source_platform="example-rewards",
    allowed_hosts=frozenset({"rewards.example.com"}),
    access_mode=AccessMode.AUTHORIZED_ACCOUNT,
)


def valid_payload():
    return {
        "source_platform": "example-rewards",
        "campaign_id": "campaign-123",
        "title": "Creator reward",
        "canonical_url": "https://rewards.example.com/campaigns/123",
        "observed_at": "2026-08-19T20:00:00Z",
        "raw_evidence_sha256": "a" * 64,
        "payout_formula": None,
        "usage_rights": None,
    }


def test_normalizes_without_inventing_unknown_commercial_or_rights_facts():
    record = normalize_reward_record(POLICY, valid_payload())
    assert record.source_platform == "example-rewards"
    assert record.fields["payout_formula"] is None
    assert record.fields["usage_rights"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("campaign_id", ""),
        ("title", None),
        ("raw_evidence_sha256", "A" * 64),
        ("raw_evidence_sha256", "a" * 63),
        ("canonical_url", "http://rewards.example.com/campaigns/123"),
        ("canonical_url", "https://evil.example/campaigns/123"),
    ],
)
def test_rejects_missing_or_untrusted_identity_evidence(key, value):
    payload = valid_payload()
    payload[key] = value
    with pytest.raises(ValueError):
        normalize_reward_record(POLICY, payload)


def test_rejects_remote_source_impersonation():
    payload = valid_payload()
    payload["source_platform"] = "other-platform"
    with pytest.raises(ValueError):
        normalize_reward_record(POLICY, payload)
