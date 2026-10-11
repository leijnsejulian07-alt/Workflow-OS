# Workflow OS — productiebeleid

> **Taal:** Nederlands · [English: Production Policy](production-policy.md)
>
> Nederlandse vertaling van de bestaande regels. **Technische statuscodes, veiligheidsgrenzen en vereiste toestemming blijven exact gelden.**

## Grens van de eigenaar

De eigenaar krijgt **nooit** terugkerende operationele taken toegewezen. Tussenkomst is alleen toegestaan voor strategie/toezicht, wettelijk of door platforms vereiste KYC/accountinstellingen, risicovolle uitgaven/contracten, echte uitzonderingen nadat automatisch herstel is uitgeput, en de noodstop.

## Toelating van kansen

Wijs een kans af of blokkeer die wanneer:

- gebruiksrechten onduidelijk, onbevestigd, verlopen, tegenstrijdig of voor het beoogde gebruik verboden zijn;
- het gaat om verboden, misleidende, onveilige financiële/medische of oncontroleerbare claims of kunstmatig opgewekte betrokkenheid;
- de herkomst van uitbetalingen of betalingen niet geverifieerd kan worden;
- de verwachte nettomarge negatief is;
- structureel handmatig werk of structurele ondersteuning nodig is;
- de acquisitie- of benaderingsmethode toestemming-, platform-, anti-spam-, telemarketing-, limiet-, toegangs- of botbeschermingsregels schendt;
- noodzakelijke account-/KYC-status ontbreekt;
- gegevens verouderd zijn en een nieuwe broncontrole niet beschikbaar is;
- de bevoegdheid voor externe acties ontbreekt.

## Externe acties

Iedere onomkeerbare of extern zichtbare actie doorloopt **vlak voor uitvoering** alle controles:

1. De inkomstenkans is momenteel geldig en actueel.
2. Het rechtenregister geeft **VERIFIED** terug voor exact bestand, gebruik, platform en gebied.
3. Verplichte vermeldingen en nalevingscontroles zijn in orde.
4. Het account is gezond en heeft de minimaal noodzakelijke bevoegdheid.
5. De verwachte financiële uitkomst blijft positief.
6. De lease voor benodigde middelen is geldig.
7. De vereiste goedkeuring door de eigenaar is aanwezig.
8. De idempotente sleutel voor de externe actie is ongebruikt of veilig hervatbaar.

Verouderde vlaggen zoals \`auto_publish\`, \`READY\`, \`PENDING\` of \`rights=yes\` geven **nooit** bevoegdheid.

## Beleid voor computerbronnen

- Gelijktijdigheid van lokaal \`HEAVY_RENDER\` staat standaard op **1**.
- Nieuwe zware taken worden geblokkeerd bij schaarste aan schijfruimte, RAM of CPU.
- De planning draait primair om verwachte inbare nettowinst per schaars middel, gecorrigeerd voor tijd tot betaling, zekerheid, risico, deadline en eigenaarstijd.
- Werk zonder geloofwaardig inkomstenbewijs wordt automatisch gepauzeerd of gestopt na begrensde experiment- en herstelbudgetten.

## Herstelbeleid

Classificeer storingen **vóór** een nieuwe poging. Pogingen zijn begrensd en idempotent. Fouten door rechten, beleid, onveilige invoer, definitieve afwijzing of ontbrekende accounttoegang worden **niet** omzeild. Alleen na uitgeput automatisch herstel én voldoende verwacht financieel nut wordt de eigenaar ingeschakeld, of wanneer menselijk handelen voor KYC, herauthenticatie of contractgoedkeuring echt vereist is.

## Welke omzet telt?

Inkomsten doorlopen schatting, verificatie en uiteindelijk ontvangen/gecontroleerd geld. Geschatte uitbetaling, views, klikken, publicaties, geaccepteerde inhoud en bedragen in platformdashboards tellen **niet** als gecontroleerd ontvangen geld.

Opschalen gebeurt op basis van gecontroleerde **inbare winst**. Attributie mag bijdragen van meerdere workflows herkennen, maar één geldontvangst mag nooit dubbel worden geteld.

## Noodstop

**PAUSE** blokkeert nieuwe toelating en laat veilig af te ronden werk doorgaan. Een noodstop (**emergency kill**) trekt nieuwe bevoegdheden voor externe acties in, beëindigt waar veilig eigen leases/processen, registreert onderbroken toestand en bewaart bewijs. Een onomkeerbare externe actie wordt **nooit** geacht zomaar te kunnen worden teruggedraaid.
