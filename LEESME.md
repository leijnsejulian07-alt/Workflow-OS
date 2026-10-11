# Workflow OS

> **Taal:** Nederlands (dit bestand) · [English / README.md](README.md)
>
> **Let op:** Dit document bevat bestaande projectafspraken én **voorstellen voor toekomstige inkomstenbronnen**. Een idee op deze pagina is **niet automatisch gebouwd, getest, toegestaan, operationeel of winstgevend**.

Workflow OS is een centraal, grotendeels autonoom AI-platform om **legitieme online inkomstenmogelijkheden** te ontdekken, beoordelen, uitvoeren, meten en optimaliseren. Het is bedoeld als één besturingssysteem voor meerdere verdienmodellen, niet als verzameling los werkende bots.

## Documentatie in het Nederlands en Engels

**Ieder document voor menselijke lezers heeft een Nederlandse en een Engelse versie.** Technische broncode, testnamen, JSON Schema-veldnamen, omgevingsvariabelen, API-contracten en CI-configuratie behouden hun vaste machineleesbare vorm; het vertalen van die identifiers kan koppelingen kapotmaken en hoort **niet** bij het vertalen van documentatie.

| Nederlands | English |
| --- | --- |
| [LEESME.md](LEESME.md) | [README.md](README.md) |
| [Architectuur](docs/ARCHITECTURE.nl.md) | [Architecture](docs/ARCHITECTURE.md) |
| [Open-sourcecomponentenregister](docs/OSS_COMPONENT_REGISTRY.nl.md) | [Open-source component registry](docs/OSS_COMPONENT_REGISTRY.md) |
| [Beleid voor kansbesluiten](policies/opportunity-decision-policy.nl.md) | [Opportunity decision policy](policies/opportunity-decision-policy.md) |
| [Productiebeleid](policies/production-policy.nl.md) | [Production policy](policies/production-policy.md) |
| [Schemareferentie](docs/SCHEMAS.nl.md) | [Schema reference](docs/SCHEMAS.md) |

**Afspraak voor toekomstige wijzigingen:** pas beide taalversies aan binnen dezelfde pull request. Behoud technische namen, beleidsconstanten, formules, veiligheidsregels, licentievermeldingen en bronverwijzingen exact. Leg nieuwe machineleesbare bestanden tweetalig uit in de documentatie in plaats van sleutels of uitwisselformaten te vertalen.

**Commercieel doel:** richting **€ 10.000 bruto omzet per maand in december 2026**. Dit is een ambitieuze doelstelling, geen prognose of garantie. Werkelijke, aantoonbaar ontvangen inkomsten zijn belangrijker dan views, theoretische opbrengsten of schattingen.

## Starten en controleren (werkende offline opdrachten)

**Vereisten:** Python 3.12 of nieuwer; voor deze veilige opdrachten zijn geen externe accounts of API-sleutels nodig.

Voer uit vanuit de hoofdmap van de repository:

```powershell
python scripts/run_workflow_os_paper_acceptance.py --output-dir .\paper-evidence
python scripts/workflow_os_doctor.py --paper-run-dir "MAP-DIE-DE-TEST-TOONT"
```

Het eerste commando test de **bestaande** OpenShorts→Whop-worker in **zeven afzonderlijke Python-processen**. Het gebruikt gesimuleerde mediacontroles, nepcredentials en een in-memory HTTP-vervanger die **geen echte Whop-inzendingen kan doen**. Het bewaart SQLite-gegevens, `events.jsonl`-logregels en een `summary.json` in een nieuwe unieke map. Herstel na een lokale fout, voorkoming van duplicaten, blokkeren van onzekere uitkomsten en persistentie na een procesherstart worden gecontroleerd. Een door het besturingssysteem beheerde lock voorkomt gelijktijdige runs en wordt bij een crash automatisch vrijgegeven; het lockbestand blijft bestaan.

De doctor past een bestaande SQLite-database **niet** aan, verstuurt niets naar platforms en print geen credentialwaarden. Met `--state-db` kun je een **bevoegde** Workflow OS-database uitsluitend lezen om aantallen taken, onzekere acties en verlopen leases te controleren. Met `--paper-run-dir` verifieer je het bewijs van één volledige synthetische test. `--output` maakt optioneel een **nieuw** opgeschoond JSON-rapport zonder eerder bewijs te overschrijven.

**Belangrijk:** dit zijn uitgevoerde offline softwaretests, **geen echte inkomsten of bewezen autonome achtergrondwerking**. De meldingen blijven `TEST_MODE_READY: NO` en `LIVE_MODE_READY: NO` totdat de toegestane Windows-machine, de planning, accounts, toestemming voor externe acties en betaalreconciliatie afzonderlijk zijn bewezen. Gebruik nooit echte secrets in een synthetische test. Installatie op de runtimecomputer moet apart plaatsvinden.

## Uitgangspunt: zo min mogelijk handwerk

De eigenaar houdt toezicht op strategie, eenmalige accountinstellingen/KYC, noodzakelijke goedkeuringen en echte uitzonderingen. Workflow OS moet dagelijkse werkzaamheden, leveringen en herstelacties zelf kunnen uitvoeren waar dit wettelijk, technisch en contractueel is toegestaan.

Geen structurele afhankelijkheid van handmatig editen, verkopen via telefoongesprekken, dagelijks posten, klantservers beheren of telkens individuele klanten ondersteunen.

## Bestaande systeemrichting

De beoogde keten is:

**Bronnen/adapters → Opportunity Manager → rechten/beleid/actualiteit → planning en middelenbeheer → gedeelde productiemotoren → toestemming voor externe acties → platform/leveringsadapter → inkomsten- en betaalregister → meet- en verbeterlus.**

Gedeelde onderdelen:

- Opportunity Manager, één centrale AI-providerrouter, takenwachtrij en planning.
- Auditlog, geheimenbeheer, accountisolatie en herstelmechanismen.
- Rechtenregister, veiligheids- en goedkeuringsbeleid en externe-actieregister.
- Inkomstenregister met **daadwerkelijke uitbetalingscontrole**, attributie en kostenregistratie.
- Experimentenregister, prestatiemeting en centraal controlepaneel (Workflow HQ).
- Beheersbaar gebruik van computerkracht, opslag, API's en AI-generatiebudget.

**Technische richting:** voortbouwen op de bestaande Python-/SQLite-onderdelen; n8n waar nuttig. Geen nieuw zwaar framework of tweede AI-router toevoegen zonder aantoonbare noodzaak.

## Al geplande inkomstenkanalen

Deze routes zijn onderdeel van de projectvisie. **De aanwezigheid van een module in de repository betekent niet dat de complete inkomstenroute al werkt.**

1. Clipping/content rewards/UGC, alleen met geldige rechten en toegestane platformautomatisering.
2. Affiliate marketing en meetbare doorverwijzingen.
3. Digitale sjablonen en downloadbare automatiseringspakketten.
4. Website-in-a-Box.
5. Zelfservice- en white-labelsoftwarelicenties.
6. Geautomatiseerde nieuwsbrieven.
7. Leadgeneratie met toestemming.
8. Data- en waarschuwingsabonnementen.
9. Marktplaatsen en print-on-demand, alleen bij automatische afhandeling en ondersteuning.
10. Micro-SaaS nadat betalende vraag bewezen is.

De huidige codebasis bevat onder meer onderdelen voor OpenShorts/Whop, AWIN, websitebouw/-overdracht, wachtrijen, herstel en registers, en Alpaca-papertrading. Dat is **geen** bevestiging van productiegeschiktheid of ontvangen opbrengsten.

---

## Voorstel: Workflow OS uitbreiden met nieuwe verdienmodellen

**Status van alle onderstaande ideeën: ONDERZOEK / VALIDATIE — niet gebouwd.** Voorbeelden van abonnementen en verkoopvormen moeten eerst met echte klanten worden getoetst. De eerste prioriteit blijft het werkend krijgen van één reeds bestaande inkomstenroute in een veilige testomgeving.

### Drie inkomstenlagen

1. **Directe inkomsten:** goedgekeurde campagnes, clippingbeloningen, affiliateconversies en downloads.
2. **Terugkerende inkomsten:** monitoring, aanbestedingenalerts, data-abonnementen en zelfservicesoftware.
3. **Herbruikbare digitale producten:** workflowsjablonen, websitekits, vergelijkingstools, databronnen en white-labelpakketten.

Eén bestaande productiemotor kan meer dan één product aanbieden. Bijvoorbeeld: een websitecontrole kan leiden tot een betaald auditrapport, een geautomatiseerd verbeterpakket, een monitoringabonnement of een websiteproduct. Videotechniek kan worden benut voor zowel goedgekeurde contentcampagnes als door klanten aangeleverde video's.

### Twaalf kandidaatproducten

| Prioriteit | Nieuwe inkomstenkans | Werking en noodzakelijke validatie |
| --- | --- | --- |
| P1 | **Website Audit Factory** | Kleine bedrijven laten hun website controleren op meetbare technische, toegankelijkheids-, SEO- en conversieproblemen. Test of zij voor een betrouwbaar rapport betalen; bied optioneel een websiteverbetering aan. |
| P1 | **AI Automation Store** | Verkoop beveiligde, uitvoerig geteste n8n-/workflowpakketten die klanten zelf installeren of hosten. Hergebruik uitsluitend geschikt materiaal met juiste licenties, instructies en onderhoudsgrenzen. |
| P1 | **Website Monitoring** | Terugkerend abonnement voor bereikbaarheid, certificaten, domeinverloop en relevante wijzigingen. Vereist bewezen alarmbetrouwbaarheid en een geautoriseerd controleproces. |
| P1 | **Creator Video Repurposing** | Klanten uploaden eigen video's/podcasts; Workflow OS maakt fragmenten, ondertitels, hoofdstukken en samenvattingen. Gebruik bestaande clippingtechniek en controleer bronrechten. |
| P2 | **Aanbestedingenradar** | Match bedrijven met relevante officiële aanbestedingen, deadlines en bewijsbare samenvattingen. Onderzoek toegestane openbare bronnen (bijvoorbeeld TED) en werkelijke abonnementsvraag. |
| P2 | **Offerte-automatiseringspakketten** | Zelfservice klantintake, conceptoffertes en herinneringsflows voor bijvoorbeeld vakbedrijven. Extern verzenden en bindende offertes vragen afzonderlijke toestemming. |
| P2 | **Product Feed Optimizer** | Controleer en verbeter door webwinkels aangeleverde catalogi, beschrijvingen, vertalingen en productfeeds. Test meetbare waarde en bronrechten. |
| P2 | **Concurrentie- en marktmonitoring** | Meld relevante veranderingen in legaal toegankelijke openbare aanbiedingen/prijzen. Geen verboden scraping, omzeiling van beveiliging of gebruik van onbetrouwbare gegevens. |
| P2 | **Niche Data API's en alerts** | Lever betrouwbare, bijgewerkte en correct gelicentieerde datasets en waarschuwingen aan professionals. Vereist bronherkomst, privacy en datakwaliteit. |
| P3 | **Review & Reputation Assistant** | Suggesties voor reacties en analyses van beoordelingen voor eigen bedrijfsaccounts. Geen nepbeoordelingen of ongeautoriseerd automatisch plaatsen. |
| P3 | **Affiliate Comparison Tools** | Nuttige vergelijkingstools en rekenhulpen met transparante affiliatevermelding; geen massale inhoud zonder echte toegevoegde waarde. |
| P3 | **AI Localization Factory** | Maak ondertitels, scripts en lokalisatiepakketten voor klanten met toestemming, inclusief kwaliteitscontrole en stem-/portretrechten. |

**Prijzen zijn nog geen feiten.** Test eenmalige verkoop, abonnementen of betaling per gebruik op basis van echte klantvraag. Bereken de marge na betaal- en platformkosten, AI-verbruik, opslag, belastingen, retourbetalingen en ondersteuning.

## Nieuwe kans: Higgsfield Earn — geld verdienen met AI-video's

**Status: ONDERZOEK, NIET GEÏNTEGREERD.**

**Aanleiding:** [gedeelde Instagram-reel](https://www.instagram.com/reel/DeUNJxWOJWe/). De inhoud van de reel kon tijdens de controle niet zelfstandig worden bekeken. Het programma is wel bevestigd via [Higgsfield Earn (officieel)](https://higgsfield.ai/earn) en de [officiële uitleg over het creatorprogramma](https://higgsfield.ai/creator-hub/help-center/business/how-do-i-join-a-partnership-or-creator-program).

### Hoe het programma volgens Higgsfield werkt (informatie uit augustus 2026)

- Je maakt een account aan op [creators.higgsfield.ai](https://creators.higgsfield.ai) en koppelt een geschikt Instagram-, YouTube- of X-account.
- Beschikbare campagnes zijn afhankelijk van land, doelgroep, account en campagnevoorwaarden; er is niet voor iedereen altijd een campagne.
- Per campagne gelden specifieke eisen voor inhoud, formaat, lengte, hashtags en vermeldingen.
- Je maakt toegestane AI-video's en publiceert of dient die volgens de regels in.
- Volgens Higgsfield kan een **goedgekeurde** inzending recht geven op een vaste vergoeding, met mogelijke prestatiebonus op basis van resultaten rond een week later. Uitbetaling verloopt via Garna.
- **Higgsfield Earn** is iets anders dan het **Creator Partnership Program**: dat tweede programma biedt onder meer credits en toegang tot tools; credits zijn geen uitbetaald inkomen.

### Wat eerst geverifieerd moet worden

1. Beschikbaarheid van Higgsfield Earn en campagnes **in Nederland**.
2. Toelatingseisen, echte gekoppelde accounts, KYC, actuele voorwaarden en vereiste eenmalige verificatie.
3. Of AI-generatie, het inplannen, het publiceren en het indienen **via toegestane automatische middelen** mogen gebeuren. Geen API of toestemming verzinnen.
4. Werkelijke generatiekosten, videorechten, licenties, kwaliteitseisen en eventuele afwijzingen.
5. Of er na goedkeuring werkelijk betalingen worden ontvangen en hoe die worden geregistreerd. Campagnevergoedingen zijn per account en kunnen vertrouwelijk zijn.
6. Mogelijke uitbetaling, wachttijd, bonusvenster, limieten, retourboekingen en economische haalbaarheid.

### Veilige proef en mogelijke vervolgstappen

**Eerst:** eigenaar controleert accounttoegang/voorwaarden; vervolgens één goedgekeurde, rechtenveilige campagne als beperkte handmatig geautoriseerde proef. Maak een financieel overzicht met generatiekosten, tijd, kwaliteit, inzending, afwijzingen en echte uitbetaling. Pas **na toestemming voor toegestane integratie** eventueel nadenken over een Workflow OS-adapter, met logboek en herstelmechanisme.

**Nooit:** nepviews, bots, gekochte betrokkenheid, accountfarms, imitatie van personen, ongeautoriseerde publicatie, beschermingsomzeiling, inbreuk op auteursrecht of onjuiste claims over inkomsten.

**Besluit:** serieuze kandidaat voor onderzoek; geen nieuwe abonnementen afsluiten, geen posts publiceren, geen campagnes accepteren en geen echte uitbetalingen claimen zonder afzonderlijke controle en toestemming.

---

## Hoe Workflow OS slimmer moet worden

### 1. Profit Manager (toekomstig, nog niet gebouwd)

Workflow OS moet leren welke bestaande inkomstenroutes daadwerkelijk bijdragen aan het resultaat. Beslissingen om een route op te schalen, te beperken of te stoppen zijn afhankelijk van:

- **Ontvangen en gecontroleerde betalingen**, niet alleen clicks, views of beloofde omzet.
- Betaalkosten, AI/API-kosten, energie-/computerbelasting, opslag en platformkosten.
- Afwijzingen, fraude- en terugboekingsrisico, storingen en benodigde menselijke tijd.
- Beschikbare rechten, accountgezondheid, contractuele regels en afgebakende budgetten.

Gebruik bestaande kosten-, experimenten- en inkomstenregisters; bouw geen tweede administratiesysteem.

### 2. Hergebruik van productiemotoren

- **Website Engine →** websiteaudit, websitebouw, monitoring en white-labelkits.
- **Media Engine →** clippingbeloningen, podcasts naar shorts, ondertiteling en toegestane AI-videocampagnes.
- **Data Engine →** aanbestedingen, marktsignalen, dataservices en nuttige vergelijkingsproducten.
- **Automation Engine →** zelfservicepakketten, offerteworkflows en klant-hosted bedrijfsprocessen.

Iedere extra toepassing moet aantoonbaar weinig nieuwe infrastructuur en weinig eigenaarshandwerk vergen.

### 3. Automatische commerciële afhandeling

Voor een goedgekeurd digitaal product moet de gewenste route zijn:

**Product ontdekken → vrijwillige aankoop → geverifieerde betaling → automatische levering → administratie → zelfservicehulp/terugbetaling → meting en verbetering.**

Live betalingen, klantberichten en andere externe acties blijven geblokkeerd zonder de juiste accountinstellingen en expliciete autorisatie. Bij klantautomatiseringen gaat de voorkeur uit naar hosting door de klant.

### 4. Experimenten die eerlijk vergelijken

Werk met kleine tests van bijvoorbeeld productprijzen, aanbiedingen en landingspagina's. Vergelijk **netto ontvangen bedragen** na kosten; stop automatisch bij budgetoverschrijding, technische problemen, te weinig bewijs of beleidsrisico's. Geen kunstmatige engagementcijfers of misleidende optimalisatie.

## Uitvoeringsvolgorde — geen bouwopdracht voor alles tegelijk

### Fase 0 — Bestaande Workflow OS-route echt draaien (hoogste prioriteit)

1. Controleer de exacte repository, branch, rechten, lokale wijzigingen, afhankelijkheden en toegestane Windows-runtime.
2. Herstel en voer de bestaande OpenShorts → Whop-workflow uit met een veilige **offline/paper** startopdracht.
3. Bewijs een echte workerketen met persistente SQLite-gegevens, audit/JSONL-logs, retry, idempotentie, reconciliatie en herstel na herstart.
4. Test veilige automatische herstart en planning; alle externe acties blijven in testmodus uitgeschakeld.
5. Werk alleen via geïsoleerde branches en gecontroleerde pull requests. Bescherm main, voer lokale tests uit, voorkom onnodige betaalde CI.
6. Meld altijd bewijs, blokkades en **TEST MODE READY: JA/NEE**. Gesimuleerde inzendingen zijn geen daadwerkelijke inkomsten.

### Fase 1 — Eerste nieuwe product verkopen (eerst simulatie)

1. Werk een **Website Audit Factory** en **AI Automation Store** elk uit als korte aanbodhypothese, zonder beide tegelijk volledig te bouwen.
2. Toets de belangstelling via toegestane, vrijwillige kanalen en kleine betaalde pilots.
3. Kies het beste product en bewijs de volledige leveringsketen, in simulatie voordat echte betaalmethoden worden geactiveerd.
4. Beoordeel opbrengst, kosten, foutafhandeling, herhaalbaarheid, ondersteuning en automatiseringsgraad.
5. Gebruik waar mogelijk klant-hosting en downloadbare producten.

### Fase 2 — Een abonnement testen

Vergelijk website-monitoring en aanbestedingenalerts. Kies **één** kleinschalige pilot met aantoonbare betalende vraag, betrouwbare toegestane bronnen, heldere annulering, geautomatiseerde onboarding en beheersbare kosten.

### Fase 3 — Zelfoptimalisatie

Laat de beoogde Profit Manager uitsluitend goedgekeurde en bewezen routes vergelijken. Verdeel beperkte testbudgetten, stop verliesgevende activiteiten en schaal alleen op na aangetoonde netto ontvangen inkomsten, goedgekeurde risico's en betrouwbare uitvoering.

### Afzonderlijk: tradingonderzoek blijft paper-only

Gebruik de bestaande Alpaca-/papertradingcode waar passend. Bewaak code-level blokkades op echt geld, geldige papercredentials, realistische kosten, voorkomen van datalekken in backtests, walk-forwardtests, afgesloten holdoutdata en een register van strategievarianten en mislukkingen.

**Geen echte handelsorders of financiële risico's zonder afzonderlijke expliciete toestemming.** Gidsen en open-sourcerepositories zijn geen kant-en-klare veilige integraties.

## Wanneer mag een inkomstenidee 'klaar' heten?

Een idee doorloopt: **ONDERZOEK → PILOT → TESTKLAAR → TOEGESTAAN LIVE → BEWEZEN INKOMSTEN**.

Daarvoor moet bewezen zijn:

- **Rechten en toestemming:** juiste klant-/accounttoegang, bronrechten, platformvoorwaarden, regels, disclosures en eventuele KYC.
- **Kosten:** begrensd testbudget, werkelijke leveranciersprijzen en marge inclusief mislukkingen.
- **Betrouwbaarheid:** herstartbestendige opslag, logboeken, idempotente externe acties en begrensde automatische retries.
- **Levering:** onboarding, toegestane betalingen, automatische levering, annulering en ondersteuning zonder dagelijks eigenaarshandwerk.
- **Bewijs:** herhaalbare tests, gelogde afwijzingen, betaalbewijzen, bank-/settlementreconciliatie en geen verzonnen resultaten.
- **Opschalen:** meetbare vraag, ontvangen nettomarge en veilige capaciteitslimieten.

**Vaste veiligheidsregels:** geen spam, geen nepbetrokkenheid, geen verboden scraping, geen ongeautoriseerd posten of berichten verzenden, geen onbeheerd echt geld, geen omzeiling van platformregels, geen ongedekte auteursrechten. Bij twijfel stopt de route veilig.

## Eerstvolgende acties (voorstellen; nog niet uitgevoerd)

- [ ] Bevoegde Windows-machine bereikbaar krijgen, lokale Workflow OS-status veiligstellen en bestaande worker opnieuw betrouwbaar testen.
- [ ] Automatische offline uitvoering, herstel na procesonderbreking en duurzame logboeken aantonen.
- [ ] Runtimewijzigingen via een gerichte PR controleren voordat ze in main terechtkomen.
- [ ] Voor Website Audit Factory en AI Automation Store elk een eenvoudige klant-, prijs-, marge- en haalbaarheidstest op papier zetten.
- [ ] De eigenaar controleert Nederlandse toelating en actuele regels van Higgsfield Earn en eventuele beschikbare echte campagne, zonder vertrouwelijke uitbetalingsgegevens openbaar te maken.
- [ ] Pas **na** het slagen van de bestaande testomgeving één nieuwe inkomstenroute tegelijk onderzoeken en bouwen.

---

## Talen en bronverwijzingen

- [English README](README.md) — Engelstalige projectdocumentatie en dezelfde toekomstige kansen.
- [Higgsfield Earn (officieel)](https://higgsfield.ai/earn)
- [Higgsfield: hoe creator- en partnerprogramma's werken](https://higgsfield.ai/creator-hub/help-center/business/how-do-i-join-a-partnership-or-creator-program)
- [Higgsfield Earn-regels (officieel)](https://creators.higgsfield.ai/terms)
- [Instagram-reel als oorspronkelijke tip](https://www.instagram.com/reel/DeUNJxWOJWe/)

**Laatste inhoudelijke controle: 11 oktober 2026.** Dit document is een plan; het autoriseert geen software-installaties, betaalde accounts, platformpublicaties, financiële transacties of live uitrol.
