# Workflow OS — architectuur

> **Taal:** Nederlands · [English: Architecture](ARCHITECTURE.md)
>
> Dit is de Nederlandse vertaling van de architectuurafspraken. **Technische identifiers, statussen, interfaces en autorisatieregels blijven onveranderd**.

## Centrale besturing

Workflow HQ is de gezaghebbende bron voor de systeemstatus. n8n voert integratie- en orkestratiewerk uit, maar bepaalt **niet** wat commercieel waar is, welke rechten bestaan, welke betalingen zijn afgerond of welke externe acties bevoegd zijn.

## Geïntegreerde procesketen

1. Platform- en bronadapters vinden legitieme inkomstenmogelijkheden.
2. De Opportunity Manager zet deze om naar het canonieke \`OpportunityContract\`.
3. Controles op duplicaten/conflicten, rechten, naleving van regels, accounts, actualiteit, financiële haalbaarheid en benodigde aandacht van de eigenaar worden uitgevoerd.
4. De planner rangschikt geschikte opdrachten op verwachte **daadwerkelijk inbare** winst, tijd tot betaling, automatiseringsgraad, operationeel/platformrisico, kapitaalbehoefte, computerkosten, deadline en benodigde eigenaarstijd.
5. De Resource Governor verstrekt een uitvoeringsrecht (lease). Standaard draait maximaal één zware lokale rendertaak tegelijk.
6. Gedeelde productiemotoren maken bestanden of andere resultaten.
7. Kwaliteitscontrole, Rights Ledger en controles op verplichte vermeldingen volgen.
8. De Side-Effect Gate verleent de minimaal noodzakelijke toestemming voor een idempotente externe actie.
9. Accountadapters publiceren, dienen in of implementeren **alleen** wanneer platformregels en accountrechten automatisering toestaan.
10. Het Revenue/Settlement Ledger vergelijkt platformresultaten met werkelijk inbare en ontvangen bedragen.
11. Het Evidence/Experiment Ledger leert uitsluitend van voldoende onderbouwde uitkomsten. Workflows mogen hun eigen productiebeleid niet zelfstandig herschrijven.
12. Beslissingen om te behouden, op te schalen, te pauzeren of te stoppen worden centraal uitgevoerd.

## Gedeelde productiemotoren

### Provider Router

Gebruik na vergelijking **exact één** primaire router voor verschillende AI-aanbieders. Stapel geen routers zonder meetbare reden. Adapters moeten informatie kunnen geven over quota, kosten, beschikbaarheid, vertraging, mogelijkheden en de regels voor opnieuw proberen of uitwijken.

### Media Engine

Pas bewezen onderdelen voor clipping, transcriptie en beeldkadering toe als licenties en veiligheidscontroles akkoord zijn. Bouw geen dubbele complete videostacks. Zwaar lokaal werk wordt centraal gepland.

### Website-in-a-Box

Gestandaardiseerde, bij voorkeur statische bedrijfs- of dienstverleningswebsites van doorgaans 1–5 pagina's: responsief, met duidelijke contact/actieknoppen, basis-SEO, rechtmatige privacy- en cookievoorzieningen en alleen wettig ingestelde analytics. Het domein en de hosting blijven langdurig in beheer van de klant.

**Technische levenscyclus (statusnamen niet vertalen):**

\`OPT_IN_LEAD -> QUALIFIED -> SCOPE_LOCKED -> PREVIEW_GENERATED -> QA_PASSED -> PAYMENT_PENDING -> PAID -> DEPLOYMENT_AUTHORIZED -> DEPLOYING -> VERIFIED_LIVE -> HANDOVER_DELIVERED -> CLOSED\`

Ondersteuning buiten de afgesproken opdracht wordt een **nieuwe betaalde mogelijkheid**, geen doorlopende onderhoudsverplichting.

## Kernregisters en diensten

- **Opportunity Ledger:** gestandaardiseerde momentopnamen van kansen en hun actualiteitsstatus.
- **Rights Ledger:** verifieerbare licentie- en herkomstbewijzen, gekoppeld aan bestanden en toegestaan gebruik.
- **Side-Effect Ledger:** idempotentie en daadwerkelijke uitkomsten van externe acties.
- **Revenue/Settlement Ledger:** schattingen, verdiende bedragen, betaalstatussen, ontvangen/gecontroleerd geld en terugboekingen.
- **Attribution Ledger:** bijdragen aan resultaten toewijzen zonder één betaling dubbel te tellen.
- **Account Registry:** verwijzingen naar geheime gegevens (niet de geheimen zelf), accountmogelijkheden, gezondheid, quota, KYC en uitgavenlimieten.
- **Resource/Cost Ledger:** kosten van rekentijd, aanbieders, opslag en advertenties en gebruik van schaarse middelen.
- **Asset Lifecycle Ledger:** hashes, herkomst, verwijzingen, bewaartermijnen en geverifieerde verwijderingen.
- **Recovery Manager:** geclassificeerd en begrensd foutherstel en uitwijkmogelijkheden.
- **Evidence/Experiment Ledger:** waarnemingen, hypothesen, beperkte tests en goedkeuring of afwijzing.
- **Audit Log:** zoveel mogelijk append-only gegevens van beleidsbesluiten en statusveranderingen.

## Regel voor platformadapters

Gebruik bij voorkeur officiële API's, feeds, webhooks of gewone HTTP, **alleen waar toegestaan**. Browserautomatisering is een laatste optie en mag nooit anti-botmaatregelen, toegangsbescherming, CAPTCHA's, snelheidslimieten, accountverificatie of platformvoorwaarden omzeilen. Ontbreekt een toegestane automatische manier, dan blijft de adapter beperkt tot lezen of handmatige accountinstellingen; verzin geen omweg.

Beoogde adaptergroepen omvatten Clip Army, Whop Content Rewards/bounties, CLIPPING/clipping.net, Clip/Clip Tech waar toegankelijk, affiliatenetwerken, marktplaatsen voor digitale producten, rechtmatige leadbronnen met toestemming, nieuwsbrieven/YouTube-kanalen, licentie- en data-alertproducten en kanalen voor verkoop/overdracht van Website-in-a-Box.

## Beleid voor afhankelijkheden

Open source versnelt uitsluitend **na verificatie**. Iedere overgenomen dependency moet een vastgelegde bron, licentie, gepinde versie of commit, integriteits-/herkomstbewijzen, beveiligingsscan, afgebakende rechten en updatebeleid hebben. Externe code krijgt **geen** bevoegdheid voor betalingen, publicaties, DNS, accounts of credentials alleen omdat deze open source is.

## Grenzen van de laptopgerichte aanpak

- Begin met SQLite en een licht lokaal Workflow HQ.
- Voorkom dubbele infrastructuur met Redis, Temporal, Windmill, Payload of PocketBase totdat aantoonbare schaal het rechtvaardigt.
- Tijdelijke bestanden worden pas opgeruimd met controle op bestaande verwijzingen; een timer alleen is geen verwijderbevoegdheid.
- Reproduceerbare tussenresultaten mogen een korte bewaartermijn hebben; noodzakelijke bron-, bewijs-, overdrachts- en betaalgegevens blijven zolang het bewaarbeleid dat voorschrijft.
- Een eventuele migratie naar de cloud behoudt canonieke ID's, registers, idempotentiesleutels en regels voor statusovergangen.
