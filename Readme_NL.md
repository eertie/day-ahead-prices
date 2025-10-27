# ENTSO-E Day-Ahead Energy Prices API

## Overzicht

Deze applicatie biedt een REST API en CLI-tool voor het ophalen van Europese energieprijzen via de ENTSO‑E Transparency Platform. Het project is ontworpen voor integratie met home automation systemen en slimme energiemanagement.

## Project Structuur

```
├── api_server.py           # FastAPI REST server
├── ha_entsoe.py           # CLI tool en core functionaliteit
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container configuratie
├── docker-compose.yml    # Docker Compose setup
├── .env                  # Environment variabelen (API keys)
├── .gitignore           # Git ignore regels
├── pytest.ini          # Test configuratie
├── logging.json         # Logging configuratie
├── tests/               # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api_server.py
│   └── test_ha_entsoe.py
├── .github/workflows/   # CI/CD pipeline
│   └── ci.yml
├── cache/              # API response cache
├── data/               # Processed data storage
└── ENTSO‑E codes.md    # Referentie voor land/zone codes
```

## Belangrijkste Features

- **REST API**: FastAPI-gebaseerde web service voor energieprijzen
- **CLI Tool**: Command-line interface voor directe data toegang
- **Caching**: Intelligente caching van API responses
- **Docker Support**: Containerized deployment
- **Automated Testing**: Comprehensive test suite met pytest
- **CI/CD Pipeline**: GitHub Actions voor automated testing en deployment
- **Environment Configuration**: .env support voor API keys
- **Timezone Handling**: Correcte verwerking van CET/CEST en 23/24/25-uur dagen
- **Rate Limiting**: Respect voor ENTSO-E API limits met exponential backoff
- **Data Normalization**: Eenvormige units en tijdafhandeling
- **Fallback Mechanisms**: Robuuste error handling bij missende data

## REST API

De FastAPI server biedt een web interface voor het ophalen van energieprijzen:

### API Endpoints

- `GET /` - API documentatie en status
- `GET /prices/{country_code}` - Day-ahead prijzen voor specifiek land
- `GET /health` - Health check endpoint

### API Server Starten

```bash
# Lokaal
python api_server.py

# Met Docker
docker-compose up

# Development mode met auto-reload
uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
```

De API is beschikbaar op `http://localhost:8000` met automatische documentatie op `/docs`.

## Testing

Het project bevat een uitgebreide test suite voor zowel de CLI tool als de REST API.

### Test Suite Uitvoeren

```bash
# Alle tests
pytest

# Met coverage
pytest --cov=. --cov-report=html

# Specifieke test file
pytest tests/test_api_server.py

# Verbose output
pytest -v
```

### Test Structuur

- `tests/test_api_server.py` - REST API endpoint tests
- `tests/test_ha_entsoe.py` - CLI tool en core functionaliteit tests
- `tests/conftest.py` - Shared test fixtures en configuratie

### CI/CD Pipeline

GitHub Actions workflow voor automated testing:

- Runs op elke push en pull request
- Test tegen Python 3.9, 3.10, 3.11
- Includes linting en code quality checks
- Automated deployment bij successful tests

## Systeemvereisten

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
