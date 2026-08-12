# Workflow OS

Workflow OS is a zero-touch autonomous revenue control plane for legitimate n8n/AI income workflows.

## Mission

Build a unified system that discovers, evaluates, produces, publishes/deploys where explicitly authorized, reconciles revenue, and automatically keeps/scales/pauses/kills work based on collectible profit.

Commercial target: **EUR 10,000 gross monthly revenue by December 2026**. This is an aggressive target, not a guarantee.

## Owner model

Julian is not an operator. Recurring manual fulfillment is prohibited by architecture.

Allowed owner involvement is limited to:
- owner-level control and strategy;
- legally/platform-required KYC or account setup;
- approval of high-risk spending or contracts;
- true exception handling after bounded automated recovery is exhausted;
- emergency shutdown.

## Core architecture

`Sources/Adapters -> Opportunity Manager -> Policy/Rights/Freshness Gate -> Scheduler/Resource Governor -> Shared Production Engines -> Side-Effect Gate -> Platform/Deployment Adapters -> Revenue & Settlement Ledger -> Evidence/Experiment Loop`

### Shared services

- Opportunity Manager
- Provider Router (exactly one primary router)
- Job Queue / Orchestration
- Audit Log
- Secrets references / account isolation
- Revenue & Settlement Ledger
- Attribution Ledger
- Approval Policy
- Rights Ledger
- Account Health Monitor
- Storage / Asset Lifecycle Manager
- Side-Effect Ledger
- Recovery Manager
- Resource / Cost Ledger
- Evidence / Experiment Ledger
- Workflow HQ

## Revenue channels

Priority channels are near-zero-touch only:

1. clipping / content rewards / UGC where rights and platform automation are explicitly allowed;
2. affiliate funnels;
3. digital templates and workflow bundles;
4. Website-in-a-Box;
5. white-label / self-service licenses;
6. automated newsletters;
7. consent-based lead generation;
8. data / alert subscriptions;
9. marketplace / POD only with automated fulfillment and support;
10. micro-SaaS only after repeated demand is proven.

Excluded: sales calls, custom recurring fulfillment, manual editing, daily customer support, inventory handling, recurring owner posting, ongoing website maintenance, fake engagement, spam, access-control bypasses, unsafe claims, and unverifiable payouts.

## Safety invariants

- Never bypass platform access controls, bot protections, rate limits, terms, disclosures, KYC, or anti-spam rules.
- `CLAIMED rights != VERIFIED rights`.
- Opportunity snapshots are not permanent execution authority; freshness must be revalidated.
- Estimated revenue is forecasting; **reconciled received cash is scaling truth**.
- A legacy workflow flag such as `auto_publish=true` is never publication authority.
- Every irreversible external action requires a policy pass and idempotent side-effect key.
- Heavy local render concurrency defaults to 1.
- Unknown or high-risk states fail closed.
- No workflow may assign recurring operational work to the owner.

## Initial technology direction

Core: n8n + lightweight Workflow HQ / SQLite.

Candidates to benchmark/adapt rather than blindly stack:
- one provider router: LiteLLM **or** a policy-safe OmniRoute subset;
- AutoClip / WhisperX for shared media production;
- Crawl4AI only for sources where automated retrieval is permitted;
- Astro + shadcn/ui for Website-in-a-Box;
- Trivy + agent-security checks for dependency and agent safety.

Heavy orchestration/datastore additions remain on hold until measured demand justifies them.

## Repository status

This repository is the canonical Workflow OS source of truth. Legacy n8n workflows are migration inputs, not authority sources.
