# Owner workload fail-closed audit — 2026-08-14

Status: **P0 finding; code fix required before trusting adapter payloads that omit owner workload.**

## Finding

The current Opportunity Manager normalizer converts a missing `expected_owner_minutes` field to `0`. The decision policy then rejects only values greater than zero. As a result, an adapter can omit owner workload entirely and the normalized opportunity may be treated as requiring no recurring owner work.

This conflicts with the Workflow OS operating constraint that Julian is not an operator. Unknown owner workload must remain unknown, not become zero.

The JSON schema also currently advertises `expected_owner_minutes` with a default of `0`, reinforcing the same optimistic assumption. A similar stale schema default remains on `probability_collection`, even though runtime normalization was previously corrected to keep missing collection probability unknown.

## Required correction

1. Preserve absent/invalid `expected_owner_minutes` as `None` during normalization.
2. Before any ACCEPT decision, return `REVALIDATE` with `expected_owner_minutes` when owner workload is unknown.
3. Continue to `REJECT` when known recurring owner workload is greater than zero.
4. Remove optimistic schema defaults for `expected_owner_minutes` and `probability_collection`; require explicit evidence instead of defaults at adapter boundaries.
5. Add regression tests proving missing owner workload cannot reach ACCEPT and explicit zero still can.
6. Keep KYC, owner approval, exception handling and emergency shutdown represented only through `user_attention_requirement`; they must not be encoded as recurring owner minutes.

## Adapter implication

No new platform adapter should be considered production-ready until it supplies an evidence-backed owner-workload estimate or causes REVALIDATE. This is especially important for clipping/content-reward campaigns where manual review, posting or account actions can otherwise be hidden as assumed-zero labor.

## External platform research note

Whop's current public Content Rewards surfaces confirm creator campaigns, submissions, approvals and payouts, and Whop's terms describe Bounties/Content Rewards as commercial arrangements. Public discovery pages do not establish a supported creator-side campaign-discovery API that Workflow OS can safely rely on. Therefore a Whop adapter must remain HOLD for autonomous discovery until an official/permitted interface is verified; do not replace that gap with browser scraping or access-control bypasses.
