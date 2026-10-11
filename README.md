> **Language:** English (this file) · [Nederlands / LEESME.md](LEESME.md)
> **Status:** The opportunity roadmap below is **planning only**. Listed ideas are not implemented, launched, authorized, or generating income unless separately verified.

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


---

## Opportunity roadmap (proposed — NOT implemented)

**Last reviewed:** 2026-10-11. This section records candidates and validation steps, **not a request to build every idea immediately**. The production priority is still to make one existing revenue route reliably runnable end-to-end in authorized simulation/paper mode before adding products.

### Investment thesis

Workflow OS should grow into a small, software-first autonomous business with three complementary income categories:

1. **Transaction/campaign income:** approved creator campaigns, rights-cleared clipping, affiliate conversions, and self-service digital sales.
2. **Recurring subscriptions:** website monitoring, tender intelligence, niche alerts, data/API access, and repeatable SaaS utilities.
3. **Reusable digital assets:** tested workflow templates, website kits, comparison tools, licensed data products, and self-service white-label packages.

The same production engine should support several sellable products. For example, website scanning can become an audit, a website improvement kit, a monitoring subscription, or an optional self-service website build; media production can serve both licensed campaign rewards and creator-owned repurposing. Do not add a second orchestration stack or provider router solely to support a new revenue idea.

### Candidate revenue products

**All rows below are RESEARCH / VALIDATION CANDIDATES, not implemented products.** Pricing must be validated with customers; examples are neither offers nor forecasts.

| Priority | Candidate | Potential buyer / commercial unit | Reuse and next validation |
| --- | --- | --- | --- |
| P1 | **Website Audit Factory** | SMEs; paid one-off accessibility, performance, SEO and conversion diagnostics, optionally followed by a self-service website upgrade | Reuse website build/fulfillment concepts; verify repeatable audit accuracy, proof, disclaimers, and customer demand |
| P1 | **AI Automation Store** | Small businesses; downloadable, documented n8n/workflow packages and self-host/customer-host installations | Adapt **only independently packaged** and licensed internal patterns; version, test, document customer setup, support and security requirements |
| P1 | **Website Uptime & Change Monitoring** | SMEs/agencies; monthly site uptime, certificate, expiry and content-change alerts | Start with legitimate authorized monitoring and low resource use; prove reliable alerting and billing |
| P1 | **Creator Video Repurposing** | Creators/podcasters; self-service video-to-shorts, captions, chapters and summaries | Reuse existing captions/clips/QC, with customer-supplied rights and transparent AI-content disclosures |
| P2 | **Tender / Procurement Radar** | Companies; subscription to legally sourced tender matching, deadlines and evidence-backed summaries | Validate demand and access to official public feeds (e.g., TED; TenderNed access separately verified) |
| P2 | **Quote / Proposal Automation Kits** | Trades and service providers; self-service customer-hosted intake, draft quote and reminder packages | Human/customer approval for contractual offers or outbound messages; no unauthorized messages |
| P2 | **Product Feed Optimization** | Merchants; catalog checks, translations, descriptions and structured feed exports | Test using merchant-authorized uploads and measurable feed quality |
| P2 | **Competitor / Market Intelligence** | Businesses; opt-in alerts on publicly accessible, lawfully obtained price/category changes | Source permission, freshness, provenance, no bot-protection bypass |
| P2 | **Niche Data & Alert APIs** | Professionals; access to maintained, licensed datasets and alerts | Data provenance, correction workflows, refresh SLAs and privacy safeguards |
| P3 | **Review / Reputation Assistant** | SMEs; reply suggestions and trend reporting for their own accounts | No fake reviews or auto-posting without provider and customer authorization |
| P3 | **Affiliate Comparison Utilities** | Shoppers; useful comparison and calculators supported by disclosed affiliate referrals | Independent editorial utility, disclosure, source freshness, no thin SEO spam |
| P3 | **AI Localization Packs** | Creators and SMEs; consented subtitles, voiceover/script localization and QA | Rights, voice/likeness consent, translation accuracy and customer-hosted delivery |

**Commercial hypothesis:** tests may explore one-time purchases, monthly subscriptions, or usage-based pricing. Set prices only after demand interviews and small paid trials; calculate net margin after generation/compute, storage, processing, tax, refunds, platform fees and support.

### New candidate: Higgsfield Earn — paid AI-video campaigns (P1 validation, no implementation)

**Discovery:** [User-shared Instagram reel](https://www.instagram.com/reel/DeUNJxWOJWe/) (reel content not independently accessible during review). The program itself is corroborated by the [official Higgsfield Earn page](https://higgsfield.ai/earn) and [official Higgsfield creator-program explanation](https://higgsfield.ai/creator-hub/help-center/business/how-do-i-join-a-partnership-or-creator-program).

- **How it works, as described by Higgsfield (August 2026):** an eligible creator connects an Instagram, YouTube or X account at [creators.higgsfield.ai](https://creators.higgsfield.ai), sees *available matched campaigns*, follows that campaign's specific format, tags/mentions and minimum-duration rules, publishes/submits compliant promotional media, and may receive an approved-submission payment plus performance-based bonuses. Higgsfield describes bonus calculation around one week after submission and payout handling via Garna.
- **Different programs:** Higgsfield Earn pays for approved campaigns; the Creator Partnership Program primarily grants creators tools, credits and access. Do not conflate partnership credits with cash payouts.
- **Unverified for Workflow OS:** Netherlands availability, actual accessible campaigns, account eligibility, payout thresholds, acceptance rates for this account, individual rates, commercial generation costs, payout settlement and whether any machine-assisted generation/submission or auto-publication is allowed by *current* terms. Higgsfield says rates and correspondence are confidential; do not publish private campaign terms.
- **Safe validation sequence:** (1) owner checks official terms, regional access, KYC and linked account; (2) capture an authorized campaign brief without exposing confidential terms; (3) calculate spend limit and projected unit economics using non-guaranteed forecasts; (4) manually approved, rights-cleared pilot content; (5) publish/submit only via explicitly authorized interfaces; (6) record campaign ID, asset provenance, posts, approvals, bonus windows, rejections, fees and *settled cash*; (7) evaluate zero-touch viability, then only consider an adapter if compliant APIs/automation permissions exist.
- **Hard no:** inflated or purchased views, bot engagement, fake accounts, account farms, scraped private dashboards, unauthorized browser automation, misleading endorsements, impersonation, copyright infringement, payout fabrication or live posting without explicit approval.
- **Decision:** **RESEARCH / OWNER-ACCESS VALIDATION ONLY**. No Higgsfield integration, campaign activation, payment, generation subscription or posting is approved by this README.

### Existing routes versus new proposals

Code exists under src/workflow_os/ for components related to OpenShorts/Whop rewards, AWIN affiliate evidence, website building/handoff, queue/recovery/ledgers, and Alpaca/paper-trading research. This describes repository scope **only**, not audited end-to-end readiness or verified revenue. Locally tested or unmerged work must be verified independently; do not infer operational status from this README.

New ideas in the table above have **no runtime integration implied**. Do not mark any candidate as live until installation, rights, account access, delivery, failure recovery, logs and paid-receipt reconciliation are proven.

## Delivery and improvement roadmap (proposed)

### Phase 0 — Make the first existing route runnable (highest priority)

1. Verify exact repository URL, clean or isolated checkout, branch, runtime device, dependencies, secrets references and current policy/permission state before writing or running.
2. Restore/install the **existing** OpenShorts -> Whop pipeline on the authorized Windows runtime; use a one-command **offline/paper** launcher.
3. Demonstrate a real worker path with durable SQLite queue, provenance, retries, idempotency, restart recovery, bounded errors, reconciliation and JSONL/audit logs. Synthetic provider mocks must be clearly labeled; never describe them as real submissions or earnings.
4. Prove safe unattended scheduling and recovery after a process interruption, while keeping all external side effects disabled.
5. Protect main, make focused branch/PR changes, test locally before CI, avoid paid GitHub Actions overage and document an honest **TEST MODE READY: YES/NO** gate.

### Phase 1 — Validate reusable, sellable products

1. Pilot **Website Audit Factory** and **AI Automation Store** as **two separate minimum sellable experiments**, not an all-at-once rebuild.
2. Validate prospective buyer interest and actual willingness to pay using lawful, opt-in channels; no mass cold outreach or purchased engagement.
3. Complete one end-to-end self-service purchase -> payment confirmation -> versioned delivery -> refund/help flow, **in simulation first**. Live payments require explicit owner approval and proper setup.
4. Benchmark contribution margin (collected sales less tools, compute, delivery fees, refunds and estimated support), reliability, rights and time-to-recovery.
5. If one succeeds, add the narrowest product adapter; prefer customer-owned hosting for automation packages so the owner does not operate customer machines.

### Phase 2 — Add recurring revenue carefully

- Compare **website monitoring** and **tender radar** with no more than one limited pilot at a time.
- Build only around official/permitted data channels and verified recurring demand.
- Define alert accuracy, freshness guarantees, outage handling, cancellation, automated customer onboarding and transparent subscription economics.

### Phase 3 — Profit Manager / experimentation (after receipts exist)

- Use existing cost, evidence, settlement, attribution and experiment ledgers; **do not create a parallel ledger/router**.
- Allocate bounded budgets across experiments using *collected, reconciled* profit rather than views, gross platform estimates or speculative traffic.
- Run small controlled trials on offers, landing pages, pricing and content; avoid evaluation leakage and stale data; stop experiments at preset budget or safety limits.
- Fail closed on unknown policy, third-party rights, account health, region, payout or side-effect permissions.
- Scaling remains subject to resource limits, compliance, explicit spend caps and owner approval for high-risk actions.

### Separate research route — trading / paper only

Keep Alpaca and other existing trading research isolated from content and B2B commerce. Preserve broker paper-account constraints, code-level live-money kill switches, backtest leakage protection, walk-forward testing, sealed holdouts, execution-cost assumptions, strategy version/failure ledgers and loss limits. **No live capital or order routing is permitted without an entirely separate explicit authorization.** Unverified external guides or open-source projects are not executable integrations.

## Acceptance gates for every proposed income stream

A candidate may only graduate from RESEARCH -> PILOT -> PAPER/TEST READY -> AUTHORIZED LIVE -> PROVEN REVENUE once evidence exists for each transition:

1. **Permissions:** geographic/account eligibility; rights to inputs/assets; platform ToS, disclosures, KYC/tax/account responsibilities and allowed automation path.
2. **Economics:** explicit trial budget, real provider pricing, expected margin range, break-even sensitivity and fraud/refund exposure.
3. **Operations:** customer-owned or approved runtime, one-command recovery, restart-safe persistent state, unique side-effect reservations, bounded retry and alerting.
4. **Customer journey:** self-service discovery, onboarding, checkout only if approved, delivery, reconciliation, cancellation and exception-only support.
5. **Evidence:** timestamped receipts/logs, reproducible tests, settled cash distinguished from estimates and reject/failure records. Never invent income.
6. **Scale:** measured demand and risk-adjusted collected profit justify extension; otherwise pause/kill.

**Never relax existing policy, rights, compliance, financial settlement, privacy, resource, provider-rate-limit, account-health or cost gates to accelerate launches.** No platform spam, unauthorized posting, payouts, orders or live transactions. Keep the owner out of recurring manual fulfillment.

## Suggested immediate next steps (documentation, not performed)

- [ ] Reconnect and verify the authorized runtime; preserve all uncommitted local Workflow OS state.
- [ ] Prove one uninterrupted + restart-interrupted offline worker sequence, persistent records and safe unattended launch.
- [ ] Review and merge the isolated runtime branch only after tests/checks pass.
- [ ] Draft a *single-page* commercial validation sheet for Website Audit Factory and AI Automation Store (buyer, offer, price hypothesis, cost ceiling, go/no-go).
- [ ] Owner verifies Higgsfield Earn availability/terms for the Netherlands, accepted accounts, approved integration and legitimate test-campaign availability; record evidence without exposing confidential rates.
- [ ] Pick only **one** new revenue experiment after the existing route reaches test readiness; revisit the rest from measured demand.
