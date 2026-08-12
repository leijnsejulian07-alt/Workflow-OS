# Workflow OS Production Policy

## Owner boundary

The owner is never assigned recurring operational work. Owner attention is permitted only for strategy/control, legally or platform-required KYC/account setup, high-risk spending/contracts, true exceptions after automated recovery is exhausted, and emergency shutdown.

## Opportunity admission

Reject or block an opportunity when any of the following is true:

- usage rights are unclear, unverified, expired, conflicting, or prohibit the intended use;
- the opportunity involves prohibited, deceptive, misleading, fake-engagement, unsafe financial/medical, or unverifiable claims;
- payout or payment provenance is unverifiable;
- expected net margin is negative;
- recurring manual fulfillment or support is required;
- the acquisition or outreach method violates applicable consent, platform, anti-spam, telemarketing, rate-limit, access-control, or bot-protection requirements;
- required account/KYC state is missing;
- freshness has expired and source revalidation is unavailable;
- side-effect authority is missing.

## Side effects

Every irreversible or externally visible action must pass all of these gates immediately before execution:

1. opportunity is currently eligible and fresh;
2. rights ledger returns VERIFIED for the exact asset/use/platform/territory;
3. disclosure/compliance checks pass;
4. account is healthy and has least-privilege capability;
5. expected economics remain positive;
6. resource lease is valid;
7. owner approval exists when the approval policy requires it;
8. idempotent side-effect key is unused or safely resumable.

Legacy flags such as `auto_publish`, `READY`, `PENDING`, or `rights=yes` are never authority.

## Resource policy

- Local HEAVY_RENDER concurrency defaults to 1.
- New heavy jobs are blocked under disk/RAM/CPU pressure.
- Scheduling priority is based primarily on expected collectible net profit per scarce resource unit, adjusted for time-to-cash, confidence, risk, deadline, and owner attention.
- Work without evidence of revenue must be automatically paused or killed after bounded experiments/recovery budgets.

## Recovery policy

Failures are classified before retry. Retries are bounded and idempotent. Rights, policy, unsafe input, permanent rejection, and unauthorized account failures do not trigger bypasses. Owner escalation occurs only when automated recovery is exhausted and expected economic value justifies attention, or when human KYC/re-auth/contract approval is genuinely required.

## Revenue truth

Revenue states progress through forecasting and verification to received/reconciled cash. Estimated payout, views, clicks, publications, accepted content, and platform dashboard estimates never count as reconciled portfolio cash.

Portfolio scaling uses reconciled collectible profit. Attribution may assign assisted value to multiple workflows, but one cash event is never counted more than once.

## Emergency stop

Pause blocks new admission while allowing safe work to finish. Emergency kill revokes new side-effect authority, cancels owned execution leases/processes where safe, records interrupted state, preserves evidence, and never assumes an irreversible external action can be blindly rolled back.
