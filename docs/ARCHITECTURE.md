# Workflow OS Architecture

## Control plane

Workflow HQ is the canonical state authority. n8n performs integration/orchestration work but does not own commercial truth, rights truth, settlement truth, or privileged side-effect authority.

## Unified flow

1. Platform/source adapters discover legitimate opportunities.
2. Opportunity Manager normalizes them into the canonical OpportunityContract.
3. Duplicate/conflict, rights, compliance, account, freshness, economics, and owner-attention gates run.
4. Scheduler ranks eligible work by expected collectible profit, time-to-cash, automation completeness, operational/platform risk, capital intensity, laptop cost, deadline, and owner attention.
5. Resource Governor issues a lease; only one heavy local render runs at a time by default.
6. Shared production engines create artifacts.
7. Artifact QA + Rights Ledger + disclosure checks run.
8. Side-Effect Gate grants least-privilege authority for an idempotent external action.
9. Account adapters publish/submit/deploy only where platform rules and account capabilities permit automation.
10. Revenue/Settlement Ledger reconciles platform results with actual collectible/received cash.
11. Evidence/Experiment Ledger learns only from sufficiently supported outcomes; workflows cannot rewrite their own production policy directly.
12. Keep/scale/pause/kill decisions are applied centrally.

## Shared engines

### Provider Router
Use exactly one primary multi-provider AI router after benchmark. Do not stack routers without a measured reason. Provider adapters must expose quota, cost, health, latency, supported capabilities, and retry/failover semantics.

### Media Engine
Adapt proven clipping/transcription/reframing components where licensing and security checks pass. Avoid duplicate full video stacks. Heavy local work is centrally scheduled.

### Website-in-a-Box
Productized static-first brochure/service websites, normally 1-5 pages, responsive, CTA/contact, basic SEO metadata, lawful privacy/cookie components, analytics only when configured lawfully. Customer owns/controls long-term domain and hosting. Lifecycle:

`OPT_IN_LEAD -> QUALIFIED -> SCOPE_LOCKED -> PREVIEW_GENERATED -> QA_PASSED -> PAYMENT_PENDING -> PAID -> DEPLOYMENT_AUTHORIZED -> DEPLOYING -> VERIFIED_LIVE -> HANDOVER_DELIVERED -> CLOSED`

Out-of-scope support becomes a new paid opportunity instead of recurring maintenance.

## Core ledgers/services

- Opportunity Ledger: normalized opportunity snapshots + freshness state.
- Rights Ledger: verifiable license/provenance evidence bound to assets and intended use.
- Side-Effect Ledger: idempotency and outcome truth for external actions.
- Revenue/Settlement Ledger: estimates, earned state, payout status, received/reconciled cash, refunds/clawbacks.
- Attribution Ledger: causal contribution without double-counting cash.
- Account Registry: non-secret credential references, capabilities, health, quota, KYC state, spend limits.
- Resource/Cost Ledger: compute/provider/storage/ad costs and scarce-resource use.
- Asset Lifecycle Ledger: hashes, provenance, references, retention eligibility, verified deletion.
- Recovery Manager: classified bounded recovery and failover.
- Evidence/Experiment Ledger: observations, hypotheses, bounded tests, promotion/rejection.
- Audit Log: append-oriented records of policy decisions and state transitions.

## Platform adapter rule

Prefer official API/feed/webhook/plain HTTP where available and permitted. Browser automation is fallback-only and must not bypass anti-bot/access controls, CAPTCHAs, rate limits, account verification, or platform terms. When no compliant automated path exists, the adapter remains read-only/manual-account-setup limited rather than inventing a bypass.

Target adapter families include Clip Army, Whop Content Rewards/bounties, CLIPPING/clipping.net, Clip/Clip Tech where accessible, affiliate networks, digital-product marketplaces, lawful consent-based lead sources, newsletter/YouTube channels, licensing/data-alert products, and Website-in-a-Box acquisition/deployment channels.

## Dependency policy

Open source accelerates development only after verification. Every adopted dependency should have an identified upstream, license, pinned version/commit, integrity/provenance record, vulnerability scan, capability scope, and update policy. Third-party code receives no payment, publishing, DNS, account, or credential authority merely because it is open source.

## Laptop-first constraints

- SQLite/local lightweight HQ first.
- Avoid Redis/Temporal/Windmill/Payload/PocketBase duplication until measured scale justifies migration.
- Automatic temp cleanup is reference-aware, never timer-only deletion authority.
- Reproducible intermediates can have short TTL; necessary source/evidence/handover/settlement records remain until lifecycle rules allow deletion.
- Cloud migration must preserve canonical IDs, ledgers, idempotency keys, and state-machine semantics.
