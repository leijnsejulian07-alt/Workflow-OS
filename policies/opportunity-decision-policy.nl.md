# Beleid voor beslissingen over inkomstenkansen

> **Taal:** Nederlands · [English: Opportunity Decision Policy](opportunity-decision-policy.md)
>
> **Vertaling ter uitleg.** De Engelse beleidsbron en uitvoerbare validatie blijven leidend totdat vertaalde teksten expliciet als equivalente norm zijn gecontroleerd. **Codes en logische regels worden niet vertaald.**

Dit beleid bepaalt de deterministische, **fail-closed** controle tussen een gestandaardiseerd \`OpportunityContract\` en planning/productie. AI mag gegevens helpen uitlezen of schatten, maar mag een afgekeurde harde controle **nooit** overrulen.

## Volgorde van beslissingen

Beoordeel in deze volgorde en stop bij de eerste definitieve afwijzing. Bewaar alle beoordeelde redenen in het auditregister.

### 1. Rechtmatigheid en rechten — REJECT wanneer

- gebruiksrechten onduidelijk, onbevestigd, verlopen of onverenigbaar zijn met de voorgenomen productie/publicatie;
- de betalingsvoorwaarden of betalende partij niet redelijk kunnen worden geverifieerd;
- de kans nepbetrokkenheid, misleiding, verboden inhoud, schending van rechten, omzeiling van toegangs- of botbeveiliging, spam of ander onrechtmatig gedrag vereist;
- vereiste vermeldingen, originaliteitseisen of platformvoorwaarden niet kunnen worden nageleefd;
- de eigenaar structureel handmatig werk moet blijven leveren.

Onbekende rechten worden nooit stilzwijgend verondersteld.

### 2. Accounts en rechtsgebied

**REJECT** als land, platform of account uitdrukkelijk niet in aanmerking komt. **PAUSE** met aandacht van de eigenaar uitsluitend als legitieme KYC-/accountacceptatie of goedkeuring van een risicovol contract/uitgave de enige resterende voorwaarde is. Normale uitvoering mag nooit naar de eigenaar worden doorgeschoven.

### 3. Actualiteit en beschikbaarheid

Kies **REVALIDATE** in plaats van inplannen wanneer deadlines, restbudget, campagnebeschikbaarheid, betaalformule, belangrijke platformvoorwaarden of andere veranderlijke gegevens verouderd of onbekend zijn. Controleer opnieuw via toegestane officiële/API-/gewone HTTP-bronnen en respecteer limieten en voorwaarden.

### 4. Financiële haalbaarheid — REJECT wanneer

- verwachte inbare omzet onvoldoende kan worden onderbouwd;
- verwachte nettowinst na productie-, provider-, platform- en betaalkosten **<= 0** is;
- verwachte winst per laptopuur **<= 0** is;
- een noodzakelijke uitgave boven het autonome uitgavenplafond ligt.

Geschatte omzet wordt **nooit** geregistreerd als daadwerkelijk ontvangen geld.

### 5. Middelen en conflicten

**PAUSE** als de uitvoering ingestelde CPU-, RAM-, opslag-, gelijktijdigheids- of quotagrenzen overschrijdt, strijdig is met een belangrijkere geaccepteerde opdracht of dubbele/conflicterende inzendingen zou opleveren. Op het lokale Windows-profiel heeft maximaal één zware render tegelijk de voorkeur.

### 6. Prioriteitsberekening

Alleen kansen die alle harde controles doorstaan, krijgen een wachtrijscore. Deze score moet met de opgeslagen invoer en beleidsversie reproduceerbaar zijn. Rangschik vooral op verwachte inbare nettowinst en tijd tot betaling, gevolgd door winst per laptopuur en automatiseringsgraad; trek punten af voor beleids-/platformrisico, kapitaalbehoefte, middelenkosten, onzekerheid over uitbetaling en aandacht van de eigenaar.

Voorgestelde genormaliseerde formule (**technische variabelen exact behouden**):

\`priority = 100 * clamp(0,1, 0.30*profit + 0.20*collectibility + 0.15*time_to_cash + 0.15*profit_per_laptop_hour + 0.10*automation - 0.05*risk - 0.03*capital - 0.02*owner_attention)\`

Ieder onderdeel moet eerst via een gedocumenteerde, versiebeheerbare functie worden genormaliseerd. Zolang die functies ontbreken, moeten de componentwaarden worden opgeslagen en moet **REVALIDATE** worden teruggegeven. Verzin geen score.

## Grens voor externe acties

**ACCEPT** betekent geschikt voor de wachtrij, **niet** toestemming voor alle externe acties. Publiceren, uitrollen, betalen, aankopen, berichten verzenden en accounts maken vereisen elk zelfstandig correcte rechten, beleidscontroles en goedkeuring en moeten idempotent of vóór herhaling aantoonbaar verzoend zijn.

## Automatisch behouden / opschalen / pauzeren / stoppen

Gebruik gecontroleerde betaalresultaten in plaats van ijdelheidsstatistieken. **PAUSE** of **KILL** als herhaalde afgeronde metingen een negatieve inbare marge, aanhoudende rechten-/beleidsproblemen, onaanvaardbare accountverslechtering of middelenverbruik zonder geloofwaardig inkomstenbewijs tonen. **SCALE** uitsluitend na controle van inbare omzet en kosten, binnen capaciteit- en risicogrenzen.

## Wanneer is aandacht van de eigenaar toegestaan?

Uitsluitend wettelijk of door platforms vereiste KYC/accountinstellingen, risicovolle uitgaven/contracten, werkelijke uitzonderingen en noodstop. Al het overige wordt automatisch afgehandeld, blijft gepauzeerd of wordt afgewezen.

## Vereisten voor auditregistratie

Ieder besluit registreert beleidsversie, beoordelingsmoment, bron- en actualiteitsbewijs, resultaten van harde controles, financiële gegevens, scorecomponenten, eindbesluit en redenen, eventuele aanleiding voor eigenaarstussenkomst en versie/hash van het \`OpportunityContract\`.

Een beleidswijziging past historische besluiten **niet met terugwerkende kracht** aan; herbeoordeling maakt een nieuw besluit.
