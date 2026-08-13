# Opportunity Decision Policy

This policy defines the deterministic, fail-closed gate between a normalized OpportunityContract and scheduling/production. AI may help extract or estimate inputs, but it may not override a failed hard gate.

## Decision order

Evaluate in this order and stop on the first terminal rejection. Store all evaluated reasons in the audit record.

### 1. Legitimacy and rights gate — REJECT when

- usage rights are unclear, unverified, expired, or incompatible with the intended production/publication;
- payout terms or the paying counterparty cannot be reasonably verified;
- the opportunity requires fake engagement, deceptive claims, prohibited content, rights infringement, access-control bypass, bot-protection bypass, spam, or other unlawful/non-compliant conduct;
- required disclosure/originality/platform rules cannot be satisfied;
- the opportunity requires recurring manual fulfillment by the owner.

Unknown rights never become assumed rights.

### 2. Account and jurisdiction gate

REJECT when the country/platform/account is explicitly ineligible. PAUSE with owner attention only when legitimate KYC/account acceptance or a high-risk contract/spend approval is the sole unresolved requirement. Routine operational work must never be routed to the owner.

### 3. Freshness and availability gate

REVALIDATE instead of scheduling when deadline, remaining budget, campaign availability, payout formula, material platform terms, or other volatile fields are stale or unknown. Revalidation must use an allowed official/API/plain-HTTP source where practical and must respect rate limits and terms.

### 4. Economics gate — REJECT when

- expected collectible revenue is not supportable from the available evidence;
- expected net profit is <= 0 after expected production/provider/platform/payment costs;
- expected profit per laptop-hour is <= 0;
- a required spend exceeds the configured autonomous spend cap.

Forecast revenue is never recorded as cash received.

### 5. Resource and conflict gate

PAUSE when execution would exceed configured CPU/RAM/storage/concurrency/quota limits, conflict with a higher-value accepted job, or create duplicate/conflicting submissions. Prefer one heavy render at a time on the local Windows profile.

### 6. Priority scoring

Only opportunities that pass the hard gates receive a queue score. The score must be reproducible from stored inputs and policy version. Rank primarily by expected collectible net profit and time-to-cash, then profit per laptop-hour and automation completeness; penalize compliance/platform risk, capital intensity, resource cost, payout uncertainty, and owner attention.

A suggested normalized score is:

`priority = 100 * clamp(0,1, 0.30*profit + 0.20*collectibility + 0.15*time_to_cash + 0.15*profit_per_laptop_hour + 0.10*automation - 0.05*risk - 0.03*capital - 0.02*owner_attention)`

Each component must be normalized by a documented versioned function before this formula is used. Until those normalization functions exist, store component values and return REVALIDATE rather than inventing a score.

## Side-effect boundary

ACCEPT means eligible for the queue, not permission for every external side effect. Publish, deploy, pay, purchase, message, or account-creation actions must independently satisfy rights/compliance/approval policy and be idempotent or reconciled before retry.

## Automated keep / scale / pause / kill

Use reconciled outcomes rather than vanity metrics. PAUSE or KILL a workflow when repeated completed samples show negative collectible margin, persistent rights/compliance failures, unacceptable account-health degradation, or resource consumption without credible revenue evidence. SCALE only after collectible revenue and costs are reconciled and capacity/risk limits remain satisfied.

## Owner-attention taxonomy

Allowed owner attention: legally/platform-required KYC/account setup; high-risk spending; high-risk contracts; true exceptions; emergency shutdown. Everything else must resolve automatically, remain paused, or be rejected.

## Audit requirements

Every decision records policy version, evaluated timestamp, source/freshness evidence, hard-gate results, economic inputs, score components, final decision/reasons, owner-attention reason if any, and the OpportunityContract version/hash. Changes to this policy must not retroactively mutate historical decisions; re-evaluation creates a new decision record.