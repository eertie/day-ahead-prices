# ENSTO-E integratie voor Home Automation

Overzicht

- Deze tool haalt data op uit de ENTSO‑E Transparency Platform REST API voor Nederland en gebruikt die voor slimme automatiseringen in huis (laden EV, boiler, warmtepomp, batterij).
- Gericht op de belangrijkste datasets: prijzen, vraag (load), wind/zon-forecast, netpositie en geplande uitwisselingen.
- Ontworpen met caching, backoff en duidelijke units/tijdafhandeling (CET/CEST).

Belangrijkste features

- .env support (ENTSOE_API_KEY)
- Europe/Brussels tijdzone; correcte verwerking van 23/24/25‑uur dagen
- Retries met exponentiële backoff
- Eenvormige normalisatie van units en tijd
- Day‑ahead caching per dag (in ./cache/)
- Pollingrichtlijnen voor actuals; respect voor rate limits
- Fallbacks bij missende punten
- Percentiel‑heuristieken voor automation (goedkoopste/groene uren)
- Ingebouwde run‑loop met instelbare pollingintervallen en jitter
- psrType‑filters voor A69 (bijv. B16=Solar, B18=Wind Offshore, B19=Wind Onshore)
- Losse CLI‑commands voor elk datasettype

Systeemvereisten

- Python 3.9+
- Internettoegang
- ENTSO‑E API‑sleutel (securityToken)

Installatie

- pip install python-dotenv requests python-dateutil pytz
- Maak een .env in de projectmap:
  ENTSOE_API_KEY=jouw_security_token

EIC-codes (Nederland + directe buren voor exchanges)

- NL (Nederland, bidding zone): 10YNL----------L
- BE (België, voor NL↔BE exchanges): 10YBE----------2
- DE‑LU (Duitsland‑Luxemburg, voor NL↔DE exchanges): 10Y1001A1001A83F

Let op: Deze tool is NL‑georiënteerd; gebruik 10YNL----------L als standaard zone. Voor exchanges kun je NL combineren met BE of DE‑LU.

Gebruik

- Algemene vorm:
  python ha_entsoe.py command [args]

Commands

- prices [YYYY-MM-DD] [ZONeEIC]
  Day‑Ahead prijzen (standaard: morgen, zone NL)
  Voorbeeld:

  - python ha_entsoe.py prices
  - python ha_entsoe.py prices 2025-10-07 10YNL----------L

- load [YYYY-MM-DD] [ZONeEIC]
  Total Load Day‑Ahead (A65) en Actual (A68)
  Voorbeeld:

  - python ha_entsoe.py load 2025-10-07 10YNL----------L

- gen-forecast [YYYY-MM-DD] [ZONeEIC] [psrType...]
  Generation Forecasts (A69) met optionele psrType‑filters
  Voorbeelden:

  - Alle types in één call (NL):
    python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L
  - Alleen Solar (PV):
    python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L B16
  - Wind Onshore + Offshore + Solar:
    python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L B19 B18 B16

  Veelgebruikte psrType-codes:

  - B16: Solar (Photovoltaic)
  - B18: Wind Offshore
  - B19: Wind Onshore

- netpos [YYYY-MM-DD] [ZONeEIC]
  Net Position (A75: import/export)
  Voorbeeld:

  - python ha_entsoe.py netpos 2025-10-07 10YNL----------L

- exchanges [YYYY-MM-DD] FROMEIC TOEIC
  Scheduled Commercial Exchanges (A01) voor NL↔BE of NL↔DE‑LU
  Voorbeelden:

  - NL → BE:
    python ha_entsoe.py exchanges 2025-10-07 10YNL----------L 10YBE----------2
  - NL → DE‑LU:
    python ha_entsoe.py exchanges 2025-10-07 10YNL----------L 10Y1001A1001A83F

- plan [YYYY-MM-DD] [ZONeEIC]
  Voorbeeld beslisregels op basis van prijzen (percentiel), load en wind/zon:
  - python ha_entsoe.py plan
  - python ha_entsoe.py plan 2025-10-07 10YNL----------L

Run-loop (continumodus)

- Start:
  python ha_entsoe.py run-loop

- Handige opties:
  - --zone 10YNL----------L
  - --from 10YNL----------L --to 10YBE----------2
  - --prices-ttl 86400 --load-da-ttl 86400 --load-act-ttl 900 --gen-ttl 10800 --netpos-ttl 3600 --exch-ttl 10800
  - --tick 5 (hoofdloop-slaap in seconden)

Voorbeelden

- Basis NL-run (met BE-exchanges):
  python ha_entsoe.py run-loop --zone 10YNL----------L --from 10YNL----------L --to 10YBE----------2
- Actuele load frequenter (elke 10 min):
  python ha_entsoe.py run-loop --load-act-ttl 600

Datasets en parameters (conform ENTSO‑E API)

- Day-Ahead Prices (A44)
  - Params: documentType=A44, in_Domain=10YNL----------L, out_Domain=10YNL----------L, periodStart/End
  - Unit: EUR/MWh (omgerekend naar ct/kWh)
- Total Load – Day Ahead (A65)
  - Params: documentType=A65, outBiddingZone_Domain=10YNL----------L, processType=A01, periodStart/End
  - Unit: MWh per uur
- Total Load – Actual (A68)
  - Params: documentType=A68, outBiddingZone_Domain=10YNL----------L, periodStart/End
  - Unit: MWh per uur
- Generation Forecasts (A69) met psrType
  - Params: documentType=A69, processType=A01, in_Domain=out_Domain=10YNL----------L, periodStart/End
  - Optioneel: psrType in de query (B16, B18, B19). Met meerdere psrType’s doet de tool meerdere API‑calls en merge’t de resultaten.
  - Unit: MW
- Net Position (A75)
  - Params: documentType=A75, in_Domain=out_Domain=10YNL----------L, periodStart/End
  - Interpretatie: positief ≈ export, negatief ≈ import (verifieer lokaal)
- Scheduled Commercial Exchanges (A01)
  - Params: documentType=A01, in_Domain=FROM, out_Domain=TO, periodStart/End
  - Richting NL→BE of NL→DE‑LU (omkeren geeft de tegengestelde stroom)

Tijd en tijdzones

- ENTSO‑E gebruikt CET/CEST (Europe/Brussels).
- periodStart/periodEnd-formaat: yyyymmddhhmm.
- Een leverdag kan 23/24/25 tijdslots hebben door zomer‑/wintertijd. De tool koppelt posities aan lokale uren en verwerkt dit automatisch.

psrType-filters: waarom en hoe

- Waarom filteren?
  - Minder payload en snellere responses.
  - Focus op relevante “groene uren” (wind/zon).
- Hoe gebruiken?
  - Voeg één of meerdere psrType-codes toe na datum en EIC:
    - python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L B16 B18 B19
- Standaard in ‘plan’:
  - De plan‑logica gebruikt B16, B18, B19 om “groene uren” te bepalen (sommen van MW).

Beste praktijken (rate limits en stabiliteit)

- Caching en TTL’s:
  - A44/A65/A69: 1–4x per dag is genoeg (bijv. vlak na publicatie rond 13:00–15:00 CET/CEST)
  - A68 (Actual): elke 5–30 min (start met 15 min)
  - A75 (Net Position): elke ~60 min
  - A01 (Exchanges): elke 1–6 uur
- Jitter en backoff:
  - De run‑loop voegt jitter toe en heeft exponentiële backoff bij fouten/429’s.
- Fallbacks:
  - Bij missende punten gebruikt de tool veilige defaults (hoge prijs, 0 MW, etc.).

Veelgestelde vragen

- Wanneer zijn day‑ahead prijzen beschikbaar?
  - Meestal tussen 13:00 en 15:00 CET/CEST voor de volgende dag.
- Waarom zie ik 23 of 25 uren?
  - Zomertijdschakeling. De tool mapt posities naar lokale uren.
- Net Position lijkt “omgekeerd”?
  - Controleer een sampledag of import/export‑definities in jouw use‑case en documenteer de conventie.

Probleemoplossing

- “ENTSOE_API_KEY ontbreekt”
  - Controleer .env en environment.
- HTTP 429 Too Many Requests
  - Verhoog TTL’s, verlaag polling, of gebruik run‑loop met jitter; plan calls verspreid.
- “Geen TimeSeries gevonden”
  - Publicatie nog niet beschikbaar, verkeerd tijdvenster of parameters. Probeer later of vergroot je window.

Licentie en bronvermelding

- Data: ENTSO‑E Transparency Platform. Respecteer de Terms & Conditions.
- Vermeld “Source: ENTSO‑E Transparency Platform” in UI’s/exports waar van toepassing.

Changelog (beknopt)

- v1.1: psrType‑filters (A69), uitgebreide README (NL), NL‑focus.
- v1.0: Run‑loop, caching, plan‑heuristiek, CLI‑commands.

Contact en uitbreidingen

- Wil je extra NL‑datapunten (balancingprijzen, outages) of meer automatiseringsregels? Open een issue of deel je wensen.
