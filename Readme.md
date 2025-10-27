# ENTSO-E Day-Ahead Energy Prices API

## Overview

This application provides a REST API and CLI tool for retrieving European energy prices via the ENTSO‑E Transparency Platform. The project is designed for integration with home automation systems and smart energy management.

## Project Structure

```
├── api_server.py           # FastAPI REST server
├── ha_entsoe.py           # CLI tool and core functionality
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container configuration
├── docker-compose.yml    # Docker Compose setup
├── .env                  # Environment variables (API keys)
├── .gitignore           # Git ignore rules
├── pytest.ini          # Test configuration
├── logging.json         # Logging configuration
├── tests/               # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api_server.py
│   └── test_ha_entsoe.py
├── .github/workflows/   # CI/CD pipeline
│   └── ci.yml
├── cache/              # API response cache
├── data/               # Processed data storage
└── ENTSO‑E codes.md    # Reference for country/zone codes
```

## Key Features

- **REST API**: FastAPI-based web service for energy prices
- **CLI Tool**: Command-line interface for direct data access
- **Caching**: Intelligent caching of API responses
- **Docker Support**: Containerized deployment
- **Automated Testing**: Comprehensive test suite with pytest
- **CI/CD Pipeline**: GitHub Actions for automated testing and deployment
- **Environment Configuration**: .env support for API keys
- **Timezone Handling**: Correct processing of CET/CEST and 23/24/25-hour days
- **Rate Limiting**: Respect for ENTSO-E API limits with exponential backoff
- **Data Normalization**: Uniform units and time handling
- **Fallback Mechanisms**: Robust error handling for missing data

## REST API

The FastAPI server provides a web interface for retrieving energy prices:

### API Endpoints

- `GET /` - API documentation and status
- `GET /energy/prices/dayahead` - Day-ahead prices for specific country
- `GET /energy/prices/cheapest` - Cheapest hours analysis
- `GET /health` - Health check endpoint

### Starting the API Server

```bash
# Local
python api_server.py

# With Docker
docker-compose up

# Development mode with auto-reload
uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
```

The API is available at `http://localhost:8000` with automatic documentation at `/docs`.

## Testing

The project contains a comprehensive test suite for both the CLI tool and the REST API.

### Running the Test Suite

```bash
# All tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific test file
pytest tests/test_api_server.py

# Verbose output
pytest -v
```

### Test Structure

- `tests/test_api_server.py` - REST API endpoint tests
- `tests/test_ha_entsoe.py` - CLI tool and core functionality tests
- `tests/conftest.py` - Shared test fixtures and configuration

### CI/CD Pipeline

GitHub Actions workflow for automated testing:

- Runs on every push and pull request
- Tests against Python 3.9, 3.10, 3.11
- Includes linting and code quality checks
- Automated deployment on successful tests

## System Requirements

- Python 3.9+
- Internet access
- ENTSO‑E API key (securityToken)

## Installation

```bash
pip install python-dotenv requests python-dateutil pytz
```

Create a `.env` file in the project directory:

```
ENTSOE_API_KEY=your_security_token
```

## EIC Codes (Netherlands + Direct Neighbors for Exchanges)

- NL (Netherlands, bidding zone): `10YNL----------L`
- BE (Belgium, for NL↔BE exchanges): `10YBE----------2`
- DE‑LU (Germany‑Luxembourg, for NL↔DE exchanges): `10Y1001A1001A83F`

Note: This tool is NL-oriented; use `10YNL----------L` as default zone. For exchanges you can combine NL with BE or DE‑LU.

## Usage

General form:

```bash
python ha_entsoe.py command [args]
```

### Commands

#### prices [YYYY-MM-DD] [ZONE_EIC]

Day‑Ahead prices (default: tomorrow, zone NL)

Examples:

```bash
python ha_entsoe.py prices
python ha_entsoe.py prices 2025-10-07 10YNL----------L
```

#### load [YYYY-MM-DD] [ZONE_EIC]

Total Load Day‑Ahead (A65) and Actual (A68)

Example:

```bash
python ha_entsoe.py load 2025-10-07 10YNL----------L
```

#### gen-forecast [YYYY-MM-DD] [ZONE_EIC] [psrType...]

Generation Forecasts (A69) with optional psrType filters

Examples:

```bash
# All types in one call (NL):
python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L

# Solar only (PV):
python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L B16

# Wind Onshore + Offshore + Solar:
python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L B19 B18 B16
```

Common psrType codes:

- B16: Solar (Photovoltaic)
- B18: Wind Offshore
- B19: Wind Onshore

#### netpos [YYYY-MM-DD] [ZONE_EIC]

Net Position (A75: import/export)

Example:

```bash
python ha_entsoe.py netpos 2025-10-07 10YNL----------L
```

#### exchanges [YYYY-MM-DD] FROM_EIC TO_EIC

Scheduled Commercial Exchanges (A01) for NL↔BE or NL↔DE‑LU

Examples:

```bash
# NL → BE:
python ha_entsoe.py exchanges 2025-10-07 10YNL----------L 10YBE----------2

# NL → DE‑LU:
python ha_entsoe.py exchanges 2025-10-07 10YNL----------L 10Y1001A1001A83F
```

#### plan [YYYY-MM-DD] [ZONE_EIC]

Example decision rules based on prices (percentile), load and wind/solar:

```bash
python ha_entsoe.py plan
python ha_entsoe.py plan 2025-10-07 10YNL----------L
```

### Run-loop (Continuous Mode)

Start:

```bash
python ha_entsoe.py run-loop
```

Useful options:

- `--zone 10YNL----------L`
- `--from 10YNL----------L --to 10YBE----------2`
- `--prices-ttl 86400 --load-da-ttl 86400 --load-act-ttl 900 --gen-ttl 10800 --netpos-ttl 3600 --exch-ttl 10800`
- `--tick 5` (main loop sleep in seconds)

Examples:

```bash
# Basic NL run (with BE exchanges):
python ha_entsoe.py run-loop --zone 10YNL----------L --from 10YNL----------L --to 10YBE----------2

# Actual load more frequently (every 10 min):
python ha_entsoe.py run-loop --load-act-ttl 600
```

## Datasets and Parameters (According to ENTSO‑E API)

### Day-Ahead Prices (A44)

- Params: documentType=A44, in_Domain=10YNL----------L, out_Domain=10YNL----------L, periodStart/End
- Unit: EUR/MWh (converted to ct/kWh)

### Total Load – Day Ahead (A65)

- Params: documentType=A65, outBiddingZone_Domain=10YNL----------L, processType=A01, periodStart/End
- Unit: MWh per hour

### Total Load – Actual (A68)

- Params: documentType=A68, outBiddingZone_Domain=10YNL----------L, periodStart/End
- Unit: MWh per hour

### Generation Forecasts (A69) with psrType

- Params: documentType=A69, processType=A01, in_Domain=out_Domain=10YNL----------L, periodStart/End
- Optional: psrType in query (B16, B18, B19). With multiple psrTypes the tool makes multiple API calls and merges results.
- Unit: MW

### Net Position (A75)

- Params: documentType=A75, in_Domain=out_Domain=10YNL----------L, periodStart/End
- Interpretation: positive ≈ export, negative ≈ import (verify locally)

### Scheduled Commercial Exchanges (A01)

- Params: documentType=A01, in_Domain=FROM, out_Domain=TO, periodStart/End
- Direction NL→BE or NL→DE‑LU (reverse gives opposite flow)

## Time and Timezones

- ENTSO‑E uses CET/CEST (Europe/Brussels).
- periodStart/periodEnd format: yyyymmddhhmm.
- A delivery day can have 23/24/25 time slots due to summer/winter time. The tool maps positions to local hours and processes this automatically.

## psrType Filters: Why and How

### Why Filter?

- Less payload and faster responses.
- Focus on relevant "green hours" (wind/solar).

### How to Use?

Add one or more psrType codes after date and EIC:

```bash
python ha_entsoe.py gen-forecast 2025-10-07 10YNL----------L B16 B18 B19
```

### Default in 'plan':

The plan logic uses B16, B18, B19 to determine "green hours" (sums of MW).

## Best Practices (Rate Limits and Stability)

### Caching and TTLs:

- A44/A65/A69: 1–4x per day is enough (e.g. just after publication around 13:00–15:00 CET/CEST)
- A68 (Actual): every 5–30 min (start with 15 min)
- A75 (Net Position): every ~60 min
- A01 (Exchanges): every 1–6 hours

### Jitter and Backoff:

- The run‑loop adds jitter and has exponential backoff on errors/429s.

### Fallbacks:

- For missing points the tool uses safe defaults (high price, 0 MW, etc.).

## Frequently Asked Questions

**When are day‑ahead prices available?**
Usually between 13:00 and 15:00 CET/CEST for the next day.

**Why do I see 23 or 25 hours?**
Daylight saving time transition. The tool maps positions to local hours.

**Net Position seems "reversed"?**
Check a sample day or import/export definitions in your use‑case and document the convention.

## Troubleshooting

**"ENTSOE_API_KEY missing"**
Check .env and environment.

**HTTP 429 Too Many Requests**
Increase TTLs, lower polling, or use run‑loop with jitter; plan calls spread out.

**"No TimeSeries found"**
Publication not yet available, wrong time window or parameters. Try later or expand your window.

## License and Attribution

- Data: ENTSO‑E Transparency Platform. Respect the Terms & Conditions.
- Mention "Source: ENTSO‑E Transparency Platform" in UIs/exports where applicable.

## Changelog (Brief)

- v1.1: psrType‑filters (A69), extended README (NL), NL‑focus.
- v1.0: Run‑loop, caching, plan‑heuristic, CLI‑commands.

## Contact and Extensions

Want additional NL data points (balancing prices, outages) or more automation rules? Open an issue or share your wishes.
