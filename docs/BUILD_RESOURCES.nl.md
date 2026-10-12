# Nuttige GitHub-projecten en tutorials — onderzochte selectie

> **Taal:** Nederlands · [English](BUILD_RESOURCES.md)
>
> Bijgewerkt 12 oktober 2026. **Dit is een bronnenlijst en onderzoek, geen toestemming voor installatie.** Voor het toevoegen van deze pagina zijn geen externe softwarepakketten geïnstalleerd, uitgevoerd of gekopieerd. Controleer voor integratie de precieze licentie, versie, beveiliging, platformvoorwaarden, Windows-compatibiliteit, geheugen en kosten.

## GitHub-repositories en mogelijke verbeteringen

| Repository | Waarvoor bruikbaar? | Besluit | Voorwaarden / volgende stap |
| --- | --- | --- | --- |
| [GoogleChrome/lighthouse](https://github.com/GoogleChrome/lighthouse) | Uitgebreidere prestatie-, SEO- en kwaliteitsrapporten voor **Website Audit Factory** | **ADAPT (later)** | Node 22+ en Chrome vragen middelen; eerst apart benchmarken, niet zomaar websites scannen |
| [dequelabs/axe-core](https://github.com/dequelabs/axe-core) | Extra toegankelijkheidscontrole op weergegeven websites | **ADAPT (later)** | MPL-2.0; detecteert niet alle toegankelijkheidsproblemen en geeft **geen WCAG-certificaat** |
| [withastro/astro](https://github.com/withastro/astro) | Herbruikbare statische templates en websitekits | **ADAPT** | MIT; vergelijk met de bestaande Python-websitebouwer voordat je een extra Node-stack toevoegt |
| [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) | De bestaande clipping- en videobewerkingsmotor | **ADAPT** | Begrensde subprocessen, isolatie van bronvideo's; **LGPL/GPL afhankelijk van build** |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | Woord-timing en sprekerherkenning voor creatorclips | **HOLD** | BSD-2-Clause voor de broncode, maar controleer modellen/dependencies; kan veel RAM en rekenkracht vragen |
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | Workflowsjablonen en automatiseringen die klanten zelf draaien | **HOLD voor inbouw/doorverkoop** | **Sustainable Use License, geen OSI-open source**; n8n commercieel hosten/inbouwen kan een aparte overeenkomst vereisen |
| [alpacahq/alpaca-py](https://github.com/alpacahq/alpaca-py) | Officiële Python-SDK voor de aparte Alpaca-onderzoekslijn | **ADAPT-onderzoek, UITSLUITEND PAPER** | Bestaande tradingblokkades blijven; gebruik niet de [gearchiveerde oude SDK](https://github.com/alpacahq/alpaca-trade-api-python); geen live credentials of echt kapitaal |
| [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | Media-invoer, **alleen eigen of expliciet toegestane content** | **HOLD** | Eerst rechten en platformvoorwaarden; uitvoerbare downloads kennen verschillende licenties en YouTube kan JavaScript vereisen |
| [microsoft/playwright-python](https://github.com/microsoft/playwright-python) | UI-/browseracceptatietests op eigen of toegestane websites | **HOLD** | Apache-2.0; browsers verbruiken RAM; niet inzetten om anti-botblokkades of platformregels te omzeilen |
| [temporalio/sdk-python](https://github.com/temporalio/sdk-python) | Patronen voor duurzame uitvoering en herstel | **IDEA_ONLY / HOLD** | Vereist extra server/besturingslaag; bestaande SQLite-worker eerst benutten |
| [PrefectHQ/prefect](https://github.com/PrefectHQ/prefect) | Planning, retries en inzicht in workflows | **IDEA_ONLY / HOLD** | Grote overlap met bestaande scheduler/HQ; alleen vervangen bij bewezen tekort |

**Belangrijk:** ADAPT betekent *eerst gericht evalueren*, niet blind installeren. Op een lichte Windows-laptop is bestaande, geteste Python-code vaak efficiënter dan een hele nieuwe stack. Het bestaande [Engelse OSS-register](OSS_COMPONENT_REGISTRY.md) en de [Nederlandse vertaling](OSS_COMPONENT_REGISTRY.nl.md) blijven leidend voor daadwerkelijke integratiebesluiten.

## YouTube: nuttige video's in logische volgorde

| Video | Maker / datum | Wat Workflow OS ervan kan leren |
| --- | --- | --- |
| [n8n Quick Start Tutorial: Build Your First Workflow](https://www.youtube.com/watch?v=4cQWJViybAQ) | **n8n**, 20 juni 2025 | Triggers, conditionele vertakkingen, data en uitvoeringslogs; principes hergebruiken zonder een tweede besturingssysteem te bouwen |
| [n8n Tutorial #5: Error Handling & Retry Logic](https://www.youtube.com/watch?v=PCs-i_JMCNM) | Kris Torrington, 17 september 2025 | Foutstromen en begrensde retries; **nooit zomaar opnieuw versturen bij onzekere externe uitkomsten** |
| [Start Automating: Build Your First GitHub Action](https://www.youtube.com/watch?v=N7zd6tkqq04) | Real Python, 6 juli 2025 | GitHub CI en tests onderhouden; geen onnodig betaalde Actions-runs aanzetten |
| [Make a Simple Trading Bot in MINUTES With Python & Alpaca](https://www.youtube.com/watch?v=b3VFMdjBfKA) | Nicholas Facciola, 17 juni 2025 | Alleen begrijpen hoe een **paper-account** werkt; voorbeeldstrategie is niet bewezen winstgevend en vereist afgesloten testdata/risicobeheer |

**Een video is educatie, geen bewezen winstmodel, veilige werkende integratie of automatische toestemming van een platform.** Softwareversies in video's kunnen verouderd zijn.

## Praktische volgorde voor het vervolg

1. Bestaande OpenShorts→Whop-worker in veilige simulatie blijven verifiëren; echte Windows-installatie, automatische planning, herstel en reconciliatie bewijzen zodra de bevoegde computer bereikbaar is.
2. Nieuwe offline Website Audit Factory op betrouwbaarheid en beveiliging testen, **zonder extra afhankelijkheden**. Lighthouse/axe-core alleen bij aangetoond nut onderzoeken.
3. Betalingsbereidheid toetsen met vrijwillig aangeleverde voorbeeldwebsites en duidelijk beperkte rapporten; geen spam, nepkeurmerken of verboden webscraping.
4. Daarna maximaal één klant-hosted workflowpakket of monitoringabonnement testen.
5. Trading strikt gescheiden en paper-only houden.

**Afspraak:** werk bij toekomstige wijzigingen [de Engelse versie](BUILD_RESOURCES.md) in dezelfde PR bij.
