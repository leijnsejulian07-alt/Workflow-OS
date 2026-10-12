# Website Audit Factory — offline HTML-proef

> **Taal:** Nederlands · [English](WEBSITE_AUDIT.md)
>
> **Status:** er bestaat een lokale module en een startcommando op deze branch. Dit is **geen** verkocht product, live websitecrawler, officiële toegankelijkheidsverklaring, volledige SEO-analyse of bewijs van omzet.

## Doel en hergebruik van bestaande code

De nieuwe `src/workflow_os/website_audit.py`-module controleert op een reproduceerbare manier **HTML-bestanden van klanten of andere bronnen waarvoor gebruikstoestemming bestaat**. Er zijn **geen extra Python-afhankelijkheden** nodig. Er worden **geen** websites opgehaald, externe accounts verbonden, scripts uitgevoerd, sites gepubliceerd, verkoopberichten verzonden, abonnementen geactiveerd of betalingen uitgevoerd.

- `audit_html_pages({"index.html": "<html>...</html>"})` analyseert HTML in het geheugen, bijvoorbeeld ook HTML van de bestaande Website-in-a-Box-motor. Het resultaat is een **aanvullend advies**, nooit een vervanging voor `qa_static_site`, betaaltoestemming, bronrechten, klantgoedkeuring of publicatieregels.
- `audit_local_site(Path("map"))` laadt beperkte lokale HTML-bestanden en wijst symlinks en te grote bestanden af.
- `scripts/run_website_audit.py` is een zelfstandig, alleen-lezend diagnosecommando. Het produceert reproduceerbare JSON en kan een **nieuw** rapport maken zonder eerdere gegevens te overschrijven.
- `tests/test_website_audit.py` controleert goede en gebrekkige HTML, ontbrekende metadata, links, grenzen, symlinks en de veiligheid van het startcommando.

## Eén opdracht

Voer vanuit de Workflow OS-repository met Python 3.12+ het volgende uit, **uitsluitend op bestanden die je mag controleren**:

```powershell
python scripts/run_website_audit.py --site-dir "C:\mijn-toegestane-website" --output "C:\rapporten\audit.json"
```

**Invoer:** een bestaande lokale map met UTF-8-bestanden met `.html` of `.htm`, maximaal 25 pagina's, 256 KiB per bestand en in totaal 2 MiB. Het aantal te bezoeken mappen is begrensd. De uitvoermap moet al bestaan. Het rapport wordt **niet** over een bestaand bestand heen geschreven. Bestandsnamen zijn relatief en een SHA-256-controlesom maakt herhaling controleerbaar.

De JSON bevat een versienummer van de controles, het aantal pagina's, een inhoudscontrolegetal, aantallen bevindingen en uitleg. Een geslaagd commando is **geen bewijs** dat een website geheel toegankelijk, vindbaar, privacyveilig of snel is. De controles zijn **vuistregels** die eerst moeten worden beoordeeld voordat je commerciële claims maakt.

## Controles die nu bestaan

- Aanwezigheid van een titel, HTML-taal, basisbeschrijving en mobiele viewport.
- Precies één niet-lege `<h1>`-kop.
- Afbeeldingen zonder `alt`-attribuut; `alt=""` is toegestaan voor decoratieve afbeeldingen.
- Links zonder herkende tekst, ARIA-label, titel of alt-naam van een afbeelding (beperkte heuristiek).
- Kapotte **interne HTML-links binnen de aangeleverde bestanden** en duidelijk onveilige linkadressen.

**Niet inbegrepen:** live websites bezoeken, HTML/JS uitvoeren, JavaScript-rendering, echte snelheidsmetingen, volledige WCAG-/SEO-certificering, controles van formulieren/betalingen, externe links controleren, screenshots, juridische privacybeoordelingen en winstberekeningen. Sommige dynamische links en toegankelijke namen zijn niet door deze eenvoudige parser herkenbaar.

## Voorwaarden voordat het een verkoopbaar product kan worden

1. Met toestemming representatieve websites testen, fouten in de detectie controleren en versienummers bijhouden.
2. Alleen bij bewezen nut later Lighthouse/axe-core overwegen in een **afgeschermde** omgeving; browserkosten, rechten, kwetsbaarheden en Windows-belasting eerst beoordelen.
3. Vraag toetsen met vrijwillig aangeleverde voorbeelden en eerlijke rapporten; geen massale ongewenste acquisitie of verzonnen kwaliteitskeurmerken.
4. Pas na goedgekeurde klantvoorwaarden, accountinstellingen en een aparte autorisatie voor betalingen: de koop-, rapport-, leverings- en restitutieketen in een simulatie bewijzen.
5. Alleen **echt ontvangen betalingen minus kosten** mogen meetellen voor het rendement.

Dit onderdeel bevat **geen** live accountkoppeling, extern netwerkverkeer, betaalfunctie of automatische publicatie.
