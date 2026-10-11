# Schema Reference — Workflow OS

> **Language:** English · [Nederlands: Schemareferentie](SCHEMAS.nl.md)
>
> **Reference guide, not a schema migration.** Both canonical JSON Schema files and their machine-readable property names, enums and validation behavior remain unchanged. Never translate schema keys, wire-format values or API payload identifiers.

## Canonical schemas

| Contract | Source file | Purpose |
| --- | --- | --- |
| OpportunityContract | [schemas/opportunity.schema.json](../schemas/opportunity.schema.json) | A normalized, evidence-backed snapshot of a potential revenue opportunity. |
| OpportunityDecision | [schemas/opportunity-decision.schema.json](../schemas/opportunity-decision.schema.json) | The auditable, fail-closed result of deciding whether that opportunity may enter the job queue. |

Both use JSON Schema draft 2020-12, object types, and additionalProperties=false. Consumers must validate required fields and each property's actual type, format, enum and numeric bounds against the **JSON files**, not against this human-readable guide.

## OpportunityContract field groups

| Group | Stable field names | Meaning |
| --- | --- | --- |
| Identity and discovery | `opportunity_id`, `source_platform`, `campaign_id`, `title`, `category`, `discovered_at`, `source_checked_at` | Origin, human-readable description and source timestamps. |
| Eligibility / usage | `allowed_countries`, `platforms`, `source_assets`, `usage_rights`, `disclosure_requirements`, `approval_rules`, `originality_requirements`, `account_requirements`, `rights_verification_state` | Who may participate, with which rights and disclosures. |
| Campaign economics | `deadline`, `remaining_budget`, `payout_formula`, `minimum_thresholds`, `payout_cap`, `payment_method` | Campaign constraints and payout rules; not proof of payment. |
| Forecasting and resources | `expected_production_cost`, `expected_laptop_minutes`, `expected_owner_minutes`, `estimated_success_probability`, `probability_collection`, `expected_revenue`, `expected_collectible_revenue`, `expected_net_profit`, `expected_profit_per_laptop_hour`, `time_to_cash_days`, `capital_at_risk`, `evidence_confidence` | Forecasts, uncertainty, scarce resources and risk capital. **Forecasts are not bank receipts.** |
| Safety and freshness | `compliance_risk`, `platform_risk`, `duplicate_conflict_status`, `user_attention_requirement`, `terms_hash`, `budget_checked_at`, `freshness_ttl_seconds`, `status` | Eligibility, conflicts and expiry. |

Important stable enum examples:
- `compliance_risk`, `platform_risk`: `LOW`, `MEDIUM`, `HIGH`, `BLOCKED`.
- `rights_verification_state`: `VERIFIED`, `CLAIMED_UNVERIFIED`, `UNKNOWN`, `REJECTED`, `EXPIRED`.
- `duplicate_conflict_status`: `CLEAR`, `DUPLICATE`, `CONFLICT`, `UNKNOWN`.
- `status`: `DISCOVERED`, `REVALIDATE`, `ACCEPTED`, `QUEUED`, `RUNNING`, `PAUSED`, `REJECTED`, `EXPIRED`, `COMPLETED`.

## OpportunityDecision fields

| Group | Stable field names | Meaning |
| --- | --- | --- |
| Identity / reproducibility | `opportunity_id`, `evaluated_at`, `policy_version` | Decision subject, timestamp and applied policy. |
| Outcome | `decision`, `decision_reasons`, `eligible_for_queue`, `requires_revalidation`, `revalidation_fields`, `owner_attention_requirement` | Gate output and explicit reasons; queue eligibility does **not** authorize external actions. |
| Assessment | `economic_score`, `priority_score`, `expected_collectible_revenue`, `expected_net_profit`, `expected_profit_per_laptop_hour`, `estimated_total_cost`, `risk_penalty`, `freshness_expires_at` | Reproducible scores, estimates and expiry. |

Stable decisions: `ACCEPT`, `REVALIDATE`, `PAUSE`, `REJECT`. Do **not** translate these string values in stored data, logs or integrations.

## Safety and localization rules

1. Preserve the original JSON Schema files as the **single machine-readable contract**. Documentation may be translated; keys, enum values and required fields must not silently change.
2. Keep the [English opportunity decision policy](../policies/opportunity-decision-policy.md) and [Dutch translation](../policies/opportunity-decision-policy.nl.md) aligned.
3. Translation is not a migration: consumers, tests and persisted SQLite rows should not need updates simply to provide Dutch documentation.
4. Schema validation alone does not prove rights, cash settlement or authorization for publish/payment/trading actions. The normal gates still apply.
