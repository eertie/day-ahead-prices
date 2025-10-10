#!/usr/bin/env python3
import os
from datetime import date, timedelta
from typing import List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

try:
    import ha_entsoe as entsoe
except Exception as e:
    raise RuntimeError(f"Could not import ha_entsoe.py: {e}")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# Preset EIC options for dropdown in docs
EIC_OPTIONS = {
    "Netherlands": "10YNL----------L",
    "Belgium": "10YBE----------2",
    "Germany": "10Y1001A1001A83F",
}

DEFAULT_ZONE = os.getenv("ZONE_EIC", EIC_OPTIONS["Netherlands"])
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
    version="1.5.0",
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
            "/load-da-forecast",
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
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to tomorrow.",
        examples={
            "default": {
                "summary": "Tomorrow (default)",
                "value": (date.today() + timedelta(days=1)).isoformat(),
            },
            "specific": {"summary": "Specific date", "value": "2025-01-15"},
        },
    ),
    zone: Optional[str] = Query(
        DEFAULT_ZONE,
        description="Bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),  # dropdown in docs
        example=DEFAULT_ZONE,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        rows = entsoe.get_day_ahead_prices(
            day, z, cache_ttl_s=entsoe.TTL_PRICES_DEFAULT
        )
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
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to tomorrow for DA; Actuals use same date.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        DEFAULT_ZONE,
        description="Bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),
        example=DEFAULT_ZONE,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        payload = entsoe.get_total_load(
            day,
            z,
            ttl_da=entsoe.TTL_LOAD_DA_DEFAULT,
            ttl_act=entsoe.TTL_LOAD_ACT_DEFAULT,
        )
        return {"date": day.isoformat(), "zone": z, "load": payload}
    except Exception as e:
        return error_response(e)


@app.get(
    "/load-da-forecast",
    tags=["load"],
    summary="6.1.B Day-ahead Total Load Forecast (A65, A01)",
    description="Returns hourly Day-ahead Total Load Forecast for the requested day and zone (documentType=A65, processType=A01).",
)
def get_load_da_forecast(
    date_str: Optional[str] = Query(
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to tomorrow.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        DEFAULT_ZONE,
        description="EIC code of Control Area, Bidding Zone or Country.",
        enum=list(EIC_OPTIONS.values()),
        example=DEFAULT_ZONE,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        rows = entsoe.get_day_ahead_total_load_forecast(
            day, z, cache_ttl_s=entsoe.TTL_LOAD_DA_DEFAULT
        )
        return {
            "date": day.isoformat(),
            "zone": z,
            "day_ahead_total_load_forecast": rows,
        }
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
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to tomorrow.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        DEFAULT_ZONE,
        description="Bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),
        example=DEFAULT_ZONE,
    ),
    psr: Optional[List[str]] = Query(
        None,
        description=(
            "Optional PSR types. Common examples: "
            "B16 = Solar, B18 = Wind Onshore, B19 = Wind Offshore. "
            "If omitted, returns all."
        ),
        example=["B16", "B18", "B19"],
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        rows = entsoe.get_generation_forecast(
            day, z, cache_ttl_s=entsoe.TTL_GEN_DEFAULT, psr_types=psr
        )
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
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to tomorrow.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        DEFAULT_ZONE,
        description="Bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),
        example=DEFAULT_ZONE,
    ),
):
    try:
        day = parse_date_or_default(date_str)
        z = zone or default_zone()
        rows = entsoe.get_net_position(day, z, cache_ttl_s=entsoe.TTL_NETPOS_DEFAULT)
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
        (date.today()).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD.",
        example=date.today().isoformat(),
    ),
    from_zone: str = Query(
        EIC_OPTIONS["Netherlands"],
        description="From bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),
        example=DEFAULT_FROM_EIC,
    ),
    to_zone: str = Query(
        EIC_OPTIONS["Belgium"],
        description="To bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),
        example=DEFAULT_TO_EIC,
    ),
):
    try:
        day = date.fromisoformat(date_str)
        rows = entsoe.get_scheduled_exchanges(
            day, from_zone, to_zone, cache_ttl_s=entsoe.TTL_EXCH_DEFAULT
        )
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
    description="Suggests cheaper/greener hours for the requested date and zone based on prices (A44), day-ahead load (A65) and generation forecast (A69). Actual load (A68) is skipped for future dates.",
)
def plan(
    date_str: Optional[str] = Query(
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Date in YYYY-MM-DD. Defaults to tomorrow.",
        example=(date.today() + timedelta(days=1)).isoformat(),
    ),
    zone: Optional[str] = Query(
        DEFAULT_ZONE,
        description="Bidding zone EIC code.",
        enum=list(EIC_OPTIONS.values()),
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
