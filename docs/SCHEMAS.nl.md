# Schemareferentie — Workflow OS

> **Taal:** Nederlands · [English: Schema Reference](SCHEMAS.md)
>
> **Uitleg, geen schemawijziging.** De canonieke JSON Schema-bestanden en alle machineleesbare veldnamen, statussen en validatieregels blijven ongewijzigd. Vertaal **geen** sleutels, API-veldnamen, enumwaarden of andere technische identifiers.

## Canonieke schema's

| Contract | Bronbestand | Betekenis |
| --- | --- | --- |
| OpportunityContract | [schemas/opportunity.schema.json](../schemas/opportunity.schema.json) | Gestandaardiseerde, met bewijs onderbouwde momentopname van een mogelijke inkomstenkans. |
| OpportunityDecision | [schemas/opportunity-decision.schema.json](../schemas/opportunity-decision.schema.json) | Controleerbaar, standaard afwijzend besluit of de kans in de takenwachtrij mag worden opgenomen. |

Beide gebruiken JSON Schema draft 2020-12, het objecttype en `additionalProperties=false`. Software moet vereiste velden en concrete typen, formaten, enumwaarden en getalgrenzen aan de hand van de **JSON-bestanden** valideren, niet alleen met deze leesbare uitleg.

## Veldgroepen van OpportunityContract

| Groep | Ongewijzigde veldnamen | Betekenis |
| --- | --- | --- |
| Identiteit en ontdekking | `opportunity_id`, `source_platform`, `campaign_id`, `title`, `category`, `discovered_at`, `source_checked_at` | Herkomst, leesbare beschrijving en brontijdstippen. |
| Geschiktheid en gebruik | `allowed_countries`, `platforms`, `source_assets`, `usage_rights`, `disclosure_requirements`, `approval_rules`, `originality_requirements`, `account_requirements`, `rights_verification_state` | Wie mee mag doen, met welke rechten en verplichte vermeldingen. |
| Campagnefinanciën | `deadline`, `remaining_budget`, `payout_formula`, `minimum_thresholds`, `payout_cap`, `payment_method` | Campagnegrenzen en betaalregels; **geen** bewijs van ontvangen geld. |
| Verwachtingen en middelen | `expected_production_cost`, `expected_laptop_minutes`, `expected_owner_minutes`, `estimated_success_probability`, `probability_collection`, `expected_revenue`, `expected_collectible_revenue`, `expected_net_profit`, `expected_profit_per_laptop_hour`, `time_to_cash_days`, `capital_at_risk`, `evidence_confidence` | Schattingen, onzekerheid, schaarse computer-/eigenaarstijd en risicokapitaal. **Een schatting is geen bankontvangst.** |
| Veiligheid en actualiteit | `compliance_risk`, `platform_risk`, `duplicate_conflict_status`, `user_attention_requirement`, `terms_hash`, `budget_checked_at`, `freshness_ttl_seconds`, `status` | Geschiktheid, conflicten en geldigheidsduur. |

Belangrijke technische enumwaarden:
- `compliance_risk`, `platform_risk`: `LOW`, `MEDIUM`, `HIGH`, `BLOCKED`.
- `rights_verification_state`: `VERIFIED`, `CLAIMED_UNVERIFIED`, `UNKNOWN`, `REJECTED`, `EXPIRED`.
- `duplicate_conflict_status`: `CLEAR`, `DUPLICATE`, `CONFLICT`, `UNKNOWN`.
- `status`: `DISCOVERED`, `REVALIDATE`, `ACCEPTED`, `QUEUED`, `RUNNING`, `PAUSED`, `REJECTED`, `EXPIRED`, `COMPLETED`.

## Velden van OpportunityDecision

| Groep | Ongewijzigde veldnamen | Betekenis |
| --- | --- | --- |
| Identiteit / reproduceerbaarheid | `opportunity_id`, `evaluated_at`, `policy_version` | Waarover het besluit gaat, wanneer, en met welke beleidsversie. |
| Uitkomst | `decision`, `decision_reasons`, `eligible_for_queue`, `requires_revalidation`, `revalidation_fields`, `owner_attention_requirement` | Resultaat en redenen; wachtrijgeschiktheid is **geen** toestemming voor externe acties. |
| Beoordeling | `economic_score`, `priority_score`, `expected_collectible_revenue`, `expected_net_profit`, `expected_profit_per_laptop_hour`, `estimated_total_cost`, `risk_penalty`, `freshness_expires_at` | Herleidbare scores, schattingen en vervaldatum. |

Toegestane besluiten: `ACCEPT`, `REVALIDATE`, `PAUSE`, `REJECT`. Vertaal deze tekstwaarden **niet** in opgeslagen data, logs of API-verbindingen.

## Veiligheid en vertaalregels

1. De originele JSON Schema-bestanden blijven het **enige machineleesbare contract**. Wel de uitleg vertalen, niet stilzwijgend veldnamen, verplichte velden of waarden aanpassen.
2. Houd het [Engelse beslisbeleid](../policies/opportunity-decision-policy.md) en de [Nederlandse vertaling](../policies/opportunity-decision-policy.nl.md) bij elkaar.
3. Documentatie vertalen is geen softwaremigratie. Bestaande integraties, tests en SQLite-records mogen daardoor niet onverwacht veranderen.
4. Een geslaagd schema bewijst op zichzelf geen rechten, betaling of bevoegdheid tot publicatie, betaalopdracht of handel. De normale controles blijven verplicht.
