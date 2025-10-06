#!/usr/bin/env python3
import os
from datetime import date, timedelta
from typing import List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

# Import core logic
try:
    import ha_entsoe as entsoe
except Exception as e:
    raise RuntimeError(f"Could not import ha_entsoe.py: {e}")

# Load .env so defaults appear based on user config
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# Resolve defaults from environment or ha_entsoe constants
DEFAULT_ZONE = os.getenv("ZONE_EIC", entsoe.ZONE_EIC_DEFAULT)
DEFAULT_TIMEZONE = os.getenv("TIME_ZONE", entsoe.TIME_ZONE_NAME)
DEFAULT_FROM_EIC = os.getenv("EXCH_FROM_EIC", entsoe.EXCH_FROM_EIC_DEFAULT)
DEFAULT_TO_EIC = os.getenv("EXCH_TO_EIC", entsoe.EXCH_TO_EIC_DEFAULT)

app = FastAPI(
    title="ENTSO-E Home Automation API",
    description=(
        "A simple wrapper around ENTSO-E to fetch prices, load, generation forecast, "
        "net position, and scheduled exchanges, plus a planning helper.\n\n"
        "Defaults shown here are loaded from your .env when available."
    ),
    version="1.3.0",
)


def parse_date_or_default(d: Optional[str]) -> date:
    if d:
        return date.fromisoformat(d)
    return date.today() + timedelta(days=1)


def default_zone() -> str:
    return DEFAULT_ZONE


def error_response(e: Exception) -> JSONResponse:
    if isinstance(e, entsoe.EntsoeError):
        payload = {"error": e.to_dict()}
        return JSONResponse(status_code=e.status, content=payload)
    wrapped = entsoe.EntsoeError(str(e), status=500, code="CLIENT_ERROR")
    payload = {"error": wrapped.to_dict()}
    return JSONResponse(status_code=wrapped.status, content=payload)


@app.get("/", tags=["meta"], summary="Service Info")
def root():
    return {
        "service": "ENTSO-E Home Automation API",
        "docs": "/docs",
        "endpoints": [
            "/prices",
            "/load",
            "/gen-forecast",
            "/netpos",
            "/exchanges",
            "/plan",
            "/config",
        ],
    }


@app.get("/config", tags=["meta"], summary="Resolved Configuration")
def get_config():
    return {
        "api_endpoint": entsoe.API_ENDPOINT,
        "zone_default": DEFAULT_ZONE,
        "time_zone": DEFAULT_TIMEZONE,
        "cache_dir": str(entsoe.CACHE_DIR),
        "ttls": {
            "prices": entsoe.TTL_PRICES_DEFAULT,
            "load_da": entsoe.TTL_LOAD_DA_DEFAULT,
            "load_act": entsoe.TTL_LOAD_ACT_DEFAULT,
            "gen": entsoe.TTL_GEN_DEFAULT,
            "netpos": entsoe.TTL_NETPOS_DEFAULT,
            "exch": entsoe.TTL_EXCH_DEFAULT,
        },
        "run_loop": {
            "tick_seconds": entsoe.TICK_SECONDS_DEFAULT,
            "exch_from_eic": DEFAULT_FROM_EIC,
            "exch_to_eic": DEFAULT_TO_EIC,
        },
    }


@app.get(
    "/prices",
    tags=["prices"],
    summary="Get Day-Ahead Prices",
    description="Returns hourly day-ahead electricity prices for the requested date and bidding zone.",
)
def get_prices(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to next day if omitted.",
        examples={
            "default": {"summary": "Tomorrow (default)", "value": None},
            "specific": {"summary": "Specific date", "value": "2025-01-15"},
        },
    ),
    zone: Optional[str] = Query(
        None,
        description="Bidding zone EIC code.",
        example=DEFAULT_ZONE,
    ),
    cache_ttl_s: Optional[int] = Query(
        None,
        ge=0,
        description=f"Cache TTL in seconds. Default from .env or {entsoe.TTL_PRICES_DEFAULT}.",
        example=entsoe.TTL_PRICES_DEFAULT,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        ttl = cache_ttl_s if cache_ttl_s is not None else entsoe.TTL_PRICES_DEFAULT
        rows = entsoe.get_day_ahead_prices(day, z, cache_ttl_s=ttl)
        return {"date": day.isoformat(), "zone": z, "prices": rows}
    except Exception as e:
        return error_response(e)


@app.get(
    "/load",
    tags=["load"],
    summary="Get Total Load (Day-Ahead and Actual)",
    description="Returns hourly total load for the requested date and zone: day-ahead forecast and actuals.",
)
def get_load(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to next day for DA; Actuals use same date.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        None,
        description="Bidding zone EIC code.",
        example=DEFAULT_ZONE,
    ),
    ttl_da: Optional[int] = Query(
        None,
        ge=0,
        description=f"Cache TTL for day-ahead load (seconds). Default from .env or {entsoe.TTL_LOAD_DA_DEFAULT}.",
        example=entsoe.TTL_LOAD_DA_DEFAULT,
    ),
    ttl_act: Optional[int] = Query(
        None,
        ge=0,
        description=f"Cache TTL for actual load (seconds). Default from .env or {entsoe.TTL_LOAD_ACT_DEFAULT}.",
        example=entsoe.TTL_LOAD_ACT_DEFAULT,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        tda = ttl_da if ttl_da is not None else entsoe.TTL_LOAD_DA_DEFAULT
        tact = ttl_act if ttl_act is not None else entsoe.TTL_LOAD_ACT_DEFAULT
        payload = entsoe.get_total_load(day, z, ttl_da=tda, ttl_act=tact)
        return {"date": day.isoformat(), "zone": z, "load": payload}
    except Exception as e:
        return error_response(e)


@app.get(
    "/gen-forecast",
    tags=["generation"],
    summary="Get Generation Forecast",
    description="Returns hourly generation forecast for the requested date and zone. Optionally filter by PSR types.",
)
def get_gen_forecast(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to next day if omitted.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        None,
        description="Bidding zone EIC code.",
        example=DEFAULT_ZONE,
    ),
    psr: Optional[List[str]] = Query(
        None,
        description="Optional list of PSR types, e.g., B16 (Solar), B18 (Wind Onshore), B19 (Wind Offshore). If omitted, returns all.",
        example=["B16", "B18", "B19"],
    ),
    cache_ttl_s: Optional[int] = Query(
        None,
        ge=0,
        description=f"Cache TTL in seconds. Default from .env or {entsoe.TTL_GEN_DEFAULT}.",
        example=entsoe.TTL_GEN_DEFAULT,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        ttl = cache_ttl_s if cache_ttl_s is not None else entsoe.TTL_GEN_DEFAULT
        rows = entsoe.get_generation_forecast(day, z, cache_ttl_s=ttl, psr_types=psr)
        return {
            "date": day.isoformat(),
            "zone": z,
            "psr_types": psr or ["ALL"],
            "generation_forecast": rows,
        }
    except Exception as e:
        return error_response(e)


@app.get(
    "/netpos",
    tags=["net position"],
    summary="Get Net Position",
    description="Returns hourly net position for the requested date and zone.",
)
def get_net_position(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to next day if omitted.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        None,
        description="Bidding zone EIC code.",
        example=DEFAULT_ZONE,
    ),
    cache_ttl_s: Optional[int] = Query(
        None,
        ge=0,
        description=f"Cache TTL in seconds. Default from .env or {entsoe.TTL_NETPOS_DEFAULT}.",
        example=entsoe.TTL_NETPOS_DEFAULT,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        ttl = cache_ttl_s if cache_ttl_s is not None else entsoe.TTL_NETPOS_DEFAULT
        rows = entsoe.get_net_position(day, z, cache_ttl_s=ttl)
        return {"date": day.isoformat(), "zone": z, "net_position": rows}
    except Exception as e:
        return error_response(e)


@app.get(
    "/exchanges",
    tags=["exchanges"],
    summary="Get Scheduled Exchanges",
    description="Returns scheduled exchanges for the requested date and pair of bidding zones.",
)
def get_exchanges(
    date_str: str = Query(
        ...,
        alias="date",
        description="Date in YYYY-MM-DD.",
        example=date.today().isoformat(),
    ),
    from_zone: str = Query(
        ...,
        description="From bidding zone EIC code.",
        example=DEFAULT_FROM_EIC,
    ),
    to_zone: str = Query(
        ...,
        description="To bidding zone EIC code.",
        example=DEFAULT_TO_EIC,
    ),
    cache_ttl_s: Optional[int] = Query(
        None,
        ge=0,
        description=f"Cache TTL in seconds. Default from .env or {entsoe.TTL_EXCH_DEFAULT}.",
        example=entsoe.TTL_EXCH_DEFAULT,
    ),
):
    try:
        day = date.fromisoformat(date_str)
        ttl = cache_ttl_s if cache_ttl_s is not None else entsoe.TTL_EXCH_DEFAULT
        rows = entsoe.get_scheduled_exchanges(day, from_zone, to_zone, cache_ttl_s=ttl)
        return {
            "date": day.isoformat(),
            "from_zone": from_zone,
            "to_zone": to_zone,
            "scheduled_exchanges": rows,
        }
    except ValueError:
        err = entsoe.EntsoeError(
            "Invalid date format. Use YYYY-MM-DD.",
            status=422,
            code="VALIDATION_ERROR",
            details={"param": "date", "value": date_str},
        )
        return error_response(err)
    except Exception as e:
        return error_response(e)


@app.get(
    "/plan",
    tags=["planning"],
    summary="Suggest Automation Plan",
    description="Suggests cheaper/greener hours for the requested date and zone based on prices, load, and generation forecast.",
)
def plan(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to next day if omitted.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        None,
        description="Bidding zone EIC code.",
        example=DEFAULT_ZONE,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        plan_obj = entsoe.suggest_automation(day, z)
        return JSONResponse(content=plan_obj)
    except Exception as e:
        return error_response(e)
