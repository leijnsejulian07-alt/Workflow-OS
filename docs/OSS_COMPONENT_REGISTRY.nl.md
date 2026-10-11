# Register van open-sourcecomponenten (OSS)

> **Taal:** Nederlands · [English: OSS Component Registry](OSS_COMPONENT_REGISTRY.md)
>
> Dit register is een **bewijspoort voor externe software** die Workflow OS overweegt. Vermelding is **geen toestemming** om een component te installeren of uit te rollen. Vóór integratie moeten exacte versies/commits worden vastgepind en beoordeeld.

## Besluitlabels

- **ADOPT** — voorkeurscomponent na vergelijking op bewijs.
- **ADAPT** — hergebruik een begrensd onderdeel of plaats het achter een verwisselbare adapter.
- **IDEA_ONLY** — uitsluitend ontwerpprincipes; geen code importeren.
- **HOLD** — mogelijk later nuttig, nu te duur/risicovol of te veel overlap.
- **REJECT** — ongeschikt voor de huidige architectuur of grenzen.

Deze labels zijn **technische constanten** en worden niet vertaald.

## Huidig register

| Component | Bron | Besluit | Licentie / verplichtingen | Beoogde toepassing | Veiligheid / uitvoering | Update- en vervanggrens |
| --- | --- | --- | --- | --- | --- | --- |
| LiteLLM | BerriAI/litellm | ADAPT | Kern MIT; enterprisefuncties apart. Behoud kennisgevingen bij doorleveren van code. | Vergelijkingsbasis voor router/gateway van AI-aanbieders. | Route met veel vertrouwen voor prompts en credentials: uitsluitend goedgekeurde aanbieders, afgeschermde logs en zo beperkt mogelijke sleutels. | Pin een beoordeelde release/containerdigest; alle oproepen achter onze eigen providerrouter-interface voor vervanging. |
| OmniRoute | diegosouzapw/OmniRoute | ADAPT | MIT bij deze beoordeling; opnieuw controleren bij vastpinnen. | Tegenkandidaat voor quotabewuste routering en uitwijk naar meerdere aanbieders. | Geen cookie-, proxy- of omzeilroutes naar aanbieders activeren. Gateway en credentials zijn een veiligheidsgrens. | Vergelijk vóór productie met LiteLLM; pin exacte beoordeelde commit/release; gebruik dezelfde routerinterface. |
| AutoClip | artbyjazi/autoclip | ADAPT | Controleer LICENSE van exacte versie opnieuw vóór code-import. | Mogelijke gedeelde motor voor clipproductie. | Media en campagnemateriaal zijn onbetrouwbare invoer; isoleer FFmpeg en verifieer rechten vóór render/publicatie. | Adapter rond cliptaken; geen campagne- of bedrijfslogica in de motor. |
| WhisperX | m-bain/whisperX | HOLD | Controleer licenties van modellen en indirecte afhankelijkheden opnieuw. | Woorduitlijning en sprekeronderscheiding. | Zwaar voor systeembronnen; modeldownloads en media zijn onbetrouwbare invoer. | Gebruik liever optionele AutoClip-integratie; aparte inbouw pas bij aangetoond tekort. |
| MoneyPrinterTurbo | harry0703/MoneyPrinterTurbo | IDEA_ONLY | Controleer repository- en afhankelijkheidslicenties vóór enig hergebruik. | Ideeën voor mediabesturing en gegenereerde korte video's. | Grote oppervlakte van media, modellen en aanbieders; voorkom een dubbele videostack. | Geen productieafhankelijkheid; geen code kopiëren zonder afzonderlijke beoordeling en registratie. |
| ffmpeg-python | kkroening/ffmpeg-python | REJECT | Apache-2.0 bij historische beoordeling; verifieer opnieuw als heroverwogen. | Verouderde wrapper voor FFmpeg. | Extra abstractie zonder bescherming tegen kwaadaardige invoer of procesproblemen. | Geef voorkeur aan directe FFmpeg-argumentlijsten met uitgeschakelde shell, achter mediaprocesgrens. |
| PocketBase | pocketbase/pocketbase | HOLD | MIT; compatibiliteits- en migratierisico vóór 1.0 blijft relevant. | Mogelijke lichte backend/beheer/opslag. | Zou nu een tweede backend/besturingslaag introduceren. | Behoud licht HQ/opslag totdat PocketBase aantoonbaar meer code vervangt dan toevoegt. |
| Windmill | windmill-labs/windmill | HOLD | Gemengde licenties/gebruiksvoorwaarden; juridisch onderzoek voor beoogd gebruik. | Platform voor zware taken/workflows. | Veel overlap in infrastructuur en besturing met n8n en Workflow HQ. | Alleen opnieuw beoordelen als n8n aantoonbaar een vereiste voor duurzame/zware taken niet aankan. |
| Inngest | inngest/inngest | HOLD | Actuele licentie vereist juridische controle; permissieve licentie niet aannemen. | Duurzame eventorkestratie. | Nog een orkestratielaag en extra onderhoudslast. | Alleen bij aangetoonde duurzaamheidskloof. |
| browser-use | browser-use/browser-use | HOLD | Verifieer exacte release/licentie vóór integratie. | Adapter voor browserautomatisering als laatste optie. | Groot risico op vijandige invoer; sandbox, geen geheimen, netwerk-allowlist, downloads blokkeren en harde resourcegrenzen. | Optioneel en vervangbaar; officiële API/gewone HTTP blijft voorkeur. |
| Crawl4AI | unclecode/crawl4ai | ADAPT | Controleer exacte release/licentie vóór integratie. | Gecontroleerd ontdekken en crawlen waar toegestaan. | Externe HTML is **data, geen instructies**; SSRF, limieten, doorverwijzingen, MIME, rechten en platformvoorwaarden verplicht controleren. | Achter interface voor ontdekkingsbronnen; per bron uitzetbaar zonder de Opportunity Manager te raken. |
| Astro | withastro/astro | ADAPT | MIT; vereiste kennisgevingen bewaren bij herdistributie. | Statische Website-in-a-Box-productie. | Statische output vermindert uitvoerings- en onderhoudslast; gegenereerde inhoud vereist nog controle van rechten, privacy en merkgebruik. | Template/build-adapter; hostingpartij en klantdomein blijven onafhankelijk. |
| shadcn/ui | shadcn-ui/ui | ADAPT | MIT voor projectcode; kennisgevingen voor losse componenten/assets waar vereist. | Componenten en templates voor Website-in-a-Box. | Importeer geen onnodige afhankelijkheden. | Kopieer of pas alleen beoordeelde componenten in templatelaag aan; vervangbaar per template. |
| Infisical | Infisical/infisical | HOLD | Controleer verschillen tussen kern- en enterpriseversies. | Mogelijk centraal beheer van geheimen. | Geheimplatform is zelf kritieke infrastructuur; mogelijk te zwaar voor één zwakke laptop. | Gebruik voorlopig geïsoleerde OS-eigen geheimopslag totdat centrale behoefte is aangetoond. |
| Payload | payloadcms/payload | HOLD | Kern MIT bij huidige beoordeling; exacte versie verifiëren. | Mogelijke beheeromgeving/backend. | Zou Workflow HQ vroegtijdig dupliceren. | Alleen heroverwegen als beheer- en CRUD-last wezenlijk wordt. |
| Trivy | aquasecurity/trivy | ADOPT | Apache-2.0; vereiste kennisgevingen bewaren. | Beveiligingsscan van repository, afhankelijkheden, containers en IaC. | Scanners hebben supply-chainrisico; pin betrouwbare actie-SHA/versie en behandel bevindingen veilig, zonder blind automatisch te repareren. | CI-beveiligingsadapter; vervangbaar zonder appwijzigingen. |
| OpenHands | All-Hands-AI/OpenHands | HOLD | Exacte licentie/release en gehoste servicevoorwaarden opnieuw controleren. | Onderhoud van code bij echte uitzonderingen/op verzoek. | Nooit doorlopende productieoperator; geen onbeperkte productiesecrets of schrijfrechten. | Alleen ontwikkeling of expliciet door eigenaar geactiveerde uitzonderingen. |
| ECC | affaan-m/ECC | ADAPT | MIT bij huidige beoordeling; exacte commit controleren. | Gecontroleerde ontwikkel- en engineeringtools. | Hooks, MCP en scripts zijn hoogbevoegd; inspecteren en vastpinnen vóór proef, zonder productiegeheimen of onbeperkt pushen. | Uitsluitend voor ontwikkeling; mag geen runtimeafhankelijkheid worden. |
| AgentShield | affaan-m/agentshield | ADAPT | MIT bij huidige beoordeling; exacte commit verifiëren. | Scannen van agent-/MCP-/hook-/secret-/bevoegdheidsrisico's. | Controleer fout-positieven; geef voorkeur aan CLI/SARIF-grens boven interne API's, pin versie. | Ontwikkel-/CI-scanner naast Trivy, **geen** bevoegdheid voor runtimeacties. |
| Cockatiel | connor4312/cockatiel | ADAPT | MIT bij huidige beoordeling; exacte release verifiëren. | Kleine bouwstenen voor retries, timeouts, circuit breakers en begrenzing. | Stapel retries niet dubbel met n8n/provider-SDK's; altijd begrensde regels. | Veerkrachtlaag rond gedeelde HTTP-/provideradapters; vervangbare bibliotheek. |
| OpenTelemetry JS | open-telemetry/opentelemetry-js | ADAPT | Apache-2.0; behoud kennisgevingen. | Leverancieronafhankelijke traces/metingen voor Workflow HQ. | Alleen noodzakelijke metingen; scherm persoonsgegevens en geheimen af; geen tweede zware observability-besturing. | Telemetrie-API als grens; exporters modulair en optioneel. |

## Toelatingscontrole voor integraties

Leg **vóór** productie-ADOPT of installatie van een ADAPT-kandidaat vast:

1. Exacte gepinde versie, commit of digest.
2. Actuele licentie en verplichte naams-/licentievermeldingen.
3. Onderhouds- en releaseactiviteit.
4. Tests en bekende beveiligingsadviezen.
5. Indirecte afhankelijkheden en supply-chaincontrole.
6. Compatibiliteit met Windows, Node en Python.
7. Gemeten CPU-, RAM- en opslagverbruik.
8. Privacy, voorwaarden van providers/platforms en toegestane gebruiksvormen.
9. Integratiewerk versus de bestaande oplossing.
10. Terugdraaiprocedure en grens/interface waardoor vervanging mogelijk blijft.

**Geen enkel component** mag bescherming tegen vijandige invoer, rechten-/beleidscontroles, idempotentie, geheimisolatie, grenzen van eigenaarstijd of fail-closedgedrag verzwakken.
