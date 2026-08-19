from datetime import datetime, timezone

import pytest

from workflow_os.adapters.cliparmy_public import normalize_public_campaigns
from workflow_os.opportunities import decide


NOW = datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc)


def payload():
    return {
        "source_url": "https://cliparmy.nl/",
        "source_checked_at": "2026-08-19T17:59:00+00:00",
        "campaigns": [
            {"title": "Supergaande", "budget_eur": 400},
            {"title": "Goudkoorts", "budget_eur": 400},
            {"title": "Food For Skin | Podcast", "budget_eur": 650},
        ],
    }


def test_public_campaigns_are_discovered_but_fail_closed_on_unknown_evidence():
    opportunities = normalize_public_campaigns(payload())
    assert len(opportunities) == 3
    first = opportunities[0]
    assert first["source_platform"] == "cliparmy-public"
    assert first["remaining_budget"] == 400
    assert first["rights_verification_state"] == "UNKNOWN"
    assert first["payment_method"] is None
    assert first["payout_cap"] is None

    decision = decide(first, now=NOW)
    assert decision.decision == "REVALIDATE"
    assert decision.queue_eligible is False


def test_duplicate_public_cards_are_idempotently_collapsed():
    data = payload()
    data["campaigns"].append({"title": "Supergaande", "budget_eur": 400})
    opportunities = normalize_public_campaigns(data)
    assert len(opportunities) == 3
    assert len({item["opportunity_id"] for item in opportunities}) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(source_url="https://example.invalid/"),
        lambda p: p.update(source_checked_at="not-a-date"),
        lambda p: p.update(campaigns="not-a-list"),
        lambda p: p["campaigns"].append({"title": "", "budget_eur": 1}),
        lambda p: p["campaigns"].append({"title": "x", "budget_eur": -1}),
        lambda p: p["campaigns"].append({"title": "x" * 513, "budget_eur": 1}),
    ],
)
def test_malformed_public_snapshots_are_rejected(mutation):
    data = payload()
    mutation(data)
    with pytest.raises(ValueError):
        normalize_public_campaigns(data)


def test_campaign_count_is_bounded():
    data = payload()
    data["campaigns"] = [{"title": f"campaign-{i}", "budget_eur": 1} for i in range(101)]
    with pytest.raises(ValueError):
        normalize_public_campaigns(data)
