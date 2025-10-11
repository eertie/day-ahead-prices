#!/usr/bin/env python3
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any

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
    title="ENTSO‑E Home Automation API",
    description=(
        "Kleine wrapper voor ENTSO‑E‑data (prijzen, load, productie, netpositie) "
        "met eenvoudige endpoints gericht op home automation."
    ),
    version="2.0.0",
)


def parse_date_or_default(d: Optional[str]) -> date:
    return date.fromisoformat(d) if d else (date.today() + timedelta(days=1))


def default_zone() -> str:
    return DEFAULT_ZONE


def error_response(e: Exception) -> JSONResponse:
    if isinstance(e, entsoe.EntsoeError):
        payload = {"error": e.to_dict()}
        return JSONResponse(status_code=e.status, content=payload)
    wrapped = entsoe.EntsoeError(str(e), status=500, code="CLIENT_ERROR")
    return JSONResponse(
        status_code=wrapped.status, content={"error": wrapped.to_dict()}
    )


# ============================================================================
# SMART CHEAPEST HOURS LOGIC (SIMPLIFIED)
# ============================================================================


def belongs_to_today(hour_local: str) -> bool:
    """
    Check of een slot tot vandaag behoort (niet na middernacht).
    Slots tussen 00:00 - 06:00 beschouwen we als "morgen vroeg".
    """
    try:
        dt = datetime.strptime(hour_local, "%Y-%m-%d %H:%M")
        return dt.hour >= 6
    except Exception:
        return True


def is_past_slot(hour_local: str, slot_date: date) -> bool:
    """Check of een slot volledig verstreken is (eindtijd + 15 min bereikt)."""
    now = datetime.now(entsoe.TZ_LOCAL)
    today = now.date()

    if slot_date != today:
        return slot_date < today

    try:
        dt = datetime.strptime(hour_local, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=entsoe.TZ_LOCAL)
        end_dt = dt + timedelta(minutes=15)
        return now >= end_dt
    except Exception:
        return False


def is_current_or_future_slot(hour_local: str, slot_date: date) -> bool:
    """Check of een slot actief of toekomstig is."""
    return not is_past_slot(hour_local, slot_date)


def group_consecutive_slots(slots: List[Dict], max_gap_minutes: int = 30) -> List[Dict]:
    """
    Groepeer opeenvolgende slots met kleine tussenpozen.
    Returns groepen gesorteerd op gemiddelde prijs (goedkoopste eerst).
    """
    if not slots:
        return []

    # Sorteer op positie
    sorted_slots = sorted(slots, key=lambda s: s["position"])

    groups = []
    current_group = {
        "start": sorted_slots[0]["hour_local"],
        "end": sorted_slots[0]["hour_local"],
        "slots": [sorted_slots[0]],
        "positions": [sorted_slots[0]["position"]],
    }

    for i in range(1, len(sorted_slots)):
        prev = sorted_slots[i - 1]
        curr = sorted_slots[i]

        position_gap = curr["position"] - prev["position"]

        # Voeg toe aan groep als gap <= max_gap_minutes / 15
        if position_gap <= max_gap_minutes / 15:
            current_group["end"] = curr["hour_local"]
            current_group["slots"].append(curr)
            current_group["positions"].append(curr["position"])
        else:
            groups.append(current_group)
            current_group = {
                "start": curr["hour_local"],
                "end": curr["hour_local"],
                "slots": [curr],
                "positions": [curr["position"]],
            }

    groups.append(current_group)

    # Bereken gemiddelde prijs per groep en sorteer
    for group in groups:
        avg_price = sum(s["ct_per_kwh"] for s in group["slots"]) / len(group["slots"])
        group["avg_price"] = avg_price

    return sorted(groups, key=lambda g: g["avg_price"])


def format_time_range(start: str, end: str) -> str:
    """Formateer tijd range: start - (end + 15 min)."""
    try:
        start_time = start.split(" ")[1]
        start_h, start_m = map(int, start_time.split(":"))

        end_time = end.split(" ")[1]
        end_h, end_m = map(int, end_time.split(":"))

        # Voeg 15 minuten toe aan eindtijd
        final_m = end_m + 15
        final_h = end_h

        if final_m >= 60:
            final_m -= 60
            final_h += 1

        if final_h >= 24:
            final_h -= 24

        start_formatted = f"{start_h:02d}:{start_m:02d}"
        end_formatted = f"{final_h:02d}:{final_m:02d}"

        return f"{start_formatted} - {end_formatted}"
    except Exception:
        return "Unknown"


def calculate_total_duration(positions: List[int]) -> int:
    """Bereken totale duur inclusief gaps (in minuten)."""
    if not positions:
        return 0
    return (max(positions) - min(positions) + 1) * 15


def process_day_data(day_data: Dict, slot_date: date, max_blocks: int = 6) -> Dict:
    """
    Process data voor één dag.

    Returns:
    - Maximaal {max_blocks} tijdsblokken
    - Gesorteerd op prijs (goedkoopste eerst)
    - Met duidelijke is_future/is_past markers
    """
    all_slots = day_data.get("cheapest_slots", [])
    avg_price = day_data.get("average_ct_per_kwh", 0)

    today = date.today()
    is_today = slot_date == today

    # STAP 1: Filter nachtelijke slots (00:00-06:00) alleen voor vandaag
    filtered_slots = all_slots
    if is_today:
        filtered_slots = [
            slot for slot in all_slots if belongs_to_today(slot["hour_local"])
        ]

    # STAP 2: Groepeer opeenvolgende slots (max 30 min gap)
    grouped_slots = group_consecutive_slots(filtered_slots, max_gap_minutes=30)

    # STAP 3: Neem de goedkoopste {max_blocks} groepen
    top_groups = grouped_slots[:max_blocks]

    # STAP 4: Converteer naar timeblocks
    time_blocks = []
    for idx, group in enumerate(top_groups):
        avg = sum(s["ct_per_kwh"] for s in group["slots"]) / len(group["slots"])
        min_price = min(s["ct_per_kwh"] for s in group["slots"])
        max_price = max(s["ct_per_kwh"] for s in group["slots"])

        # Check of eerste slot van blok toekomstig is
        first_slot = group["slots"][0]
        is_future = is_current_or_future_slot(first_slot["hour_local"], slot_date)

        time_blocks.append(
            {
                "rank": idx + 1,
                "time_range": format_time_range(group["start"], group["end"]),
                "duration_minutes": calculate_total_duration(group["positions"]),
                "actual_slot_count": len(group["slots"]),
                "avg_price": round(avg, 3),
                "min_price": round(min_price, 3),
                "max_price": round(max_price, 3),
                "is_best": avg < avg_price * 0.85,  # 15% goedkoper dan gemiddelde
                "is_future": is_future,
                "individual_slots": [
                    {
                        "time": s["hour_local"].split(" ")[1][:5],  # "HH:MM"
                        "price": round(s["ct_per_kwh"], 3),
                        "is_past": is_past_slot(s["hour_local"], slot_date),
                    }
                    for s in group["slots"]
                ],
            }
        )

    # Tel toekomstige blokken
    future_count = sum(1 for b in time_blocks if b["is_future"])

    return {
        "date": slot_date.isoformat(),
        "average_ct_per_kwh": round(avg_price, 3),
        "time_blocks": time_blocks,
        "future_blocks_count": future_count,
        "total_blocks_count": len(time_blocks),
    }


def get_day_label(target_date: date) -> str:
    """Bepaal Nederlands label op basis van datum."""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    if target_date == today:
        return "Vandaag"
    elif target_date == tomorrow:
        return "Morgen"
    else:
        days_nl = [
            "maandag",
            "dinsdag",
            "woensdag",
            "donderdag",
            "vrijdag",
            "zaterdag",
            "zondag",
        ]
        months_nl = [
            "",
            "januari",
            "februari",
            "maart",
            "april",
            "mei",
            "juni",
            "juli",
            "augustus",
            "september",
            "oktober",
            "november",
            "december",
        ]

        day_name = days_nl[target_date.weekday()]
        month_name = months_nl[target_date.month]

        return f"{day_name} {target_date.day} {month_name}"


# ============================================================================
# ROUTES
# ============================================================================


@app.get("/", tags=["meta"], summary="Service Info")
def root():
    return {
        "service": "ENTSO‑E Home Automation API",
        "version": "2.0.0",
        "docs": "/docs",
        "endpoints": {
            "prices": "/energy/prices/cheapest",
            "dayahead": "/energy/prices/dayahead",
            "load": "/load/forecast/dayahead",
            "generation": "/generation/forecast/wind-solar",
            "balancing": "/balancing/state/current",
            "health": "/system/health",
        },
    }


@app.get("/system/health", tags=["system"], summary="Health check")
def system_health():
    """Health check endpoint."""
    try:
        key_ok = bool(os.getenv("ENTSOE_API_KEY"))
        return {
            "status": "ok",
            "entsoe_api_key_loaded": key_ok,
            "time_zone": DEFAULT_TIMEZONE,
            "cache_dir": str(entsoe.CACHE_DIR),
        }
    except Exception as e:
        return error_response(e)


@app.get(
    "/energy/prices/dayahead",
    tags=["energy"],
    summary="Dag‑ahead prijzen (ENTSO‑E A44)",
)
def energy_prices_dayahead(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Datum YYYY‑MM‑DD (standaard: morgen)",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied"),
):
    """Haal alle day-ahead prijzen op voor een specifieke datum."""
    try:
        d = parse_date_or_default(date_str)
        rows = entsoe.get_day_ahead_prices(
            d, zone, cache_ttl_s=entsoe.TTL_PRICES_DEFAULT
        )

        return {
            "date": d.isoformat(),
            "zone": zone,
            "prices": rows,
            "total_slots": len(rows),
        }
    except Exception as e:
        return error_response(e)


@app.get(
    "/energy/prices/cheapest",
    tags=["energy"],
    summary="Slimme goedkoopste tijdsblokken",
    description=(
        "Intelligente tijdsblokken voor home automation:\n\n"
        "**Features:**\n"
        "- Groepeert opeenvolgende slots (max 30 min gap)\n"
        "- Filtert nachtelijke slots (00:00-06:00) voor vandaag\n"
        "- Markeert verstreken vs toekomstige slots\n"
        "- Toont maximaal 6 goedkoopste blokken\n"
        "- Perfect voor laadschema's en slimme apparaten\n\n"
        "**Velden:**\n"
        "- `is_future`: true = nog te gebruiken, false = verstreken\n"
        "- `is_best`: true = >15% goedkoper dan daggemiddelde\n"
        "- `is_past`: per individueel slot"
    ),
)
def energy_prices_cheapest(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Datum YYYY-MM-DD (default: vandaag)",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied"),
    count: int = Query(
        20, ge=5, le=50, description="Aantal goedkoopste slots om te analyseren (5-50)"
    ),
    max_blocks: int = Query(
        6, ge=1, le=12, description="Max aantal tijdsblokken in response (1-12)"
    ),
):
    """
    Smart cheapest hours - klaar voor directe UI integratie.

    Response format:
    {
      "label": "Vandaag",
      "date": "2025-10-10",
      "average_ct_per_kwh": 9.52,
      "time_blocks": [...],
      "future_blocks_count": 2,
      "total_blocks_count": 6,
      "generated_at": "2025-10-10T22:45:00+02:00",
      "zone": "10YNL----------L"
    }
    """
    try:
        # Parse datum (default: vandaag)
        target_date = date.fromisoformat(date_str) if date_str else date.today()

        # Haal prijsdata op
        prices = entsoe.get_day_ahead_prices(target_date, zone)

        if not prices:
            raise entsoe.EntsoeServerError(
                f"Geen prijsdata beschikbaar voor {target_date.isoformat()}", status=404
            )

        # Bereken gemiddelde
        avg = sum(r["ct_per_kwh"] for r in prices) / len(prices)

        # Neem de goedkoopste slots
        cheapest = sorted(prices, key=lambda r: r["ct_per_kwh"])[:count]

        # Process data
        day_data = {"cheapest_slots": cheapest, "average_ct_per_kwh": avg}

        processed = process_day_data(day_data, target_date, max_blocks=max_blocks)

        # Voeg metadata toe
        processed["label"] = get_day_label(target_date)
        processed["generated_at"] = datetime.now(entsoe.TZ_LOCAL).isoformat()
        processed["zone"] = zone

        return processed

    except Exception as e:
        return error_response(e)


@app.get(
    "/load/forecast/dayahead",
    tags=["load"],
    summary="Day‑ahead load forecast (ENTSO‑E A65)",
)
def load_forecast_dayahead(
    date_str: Optional[str] = Query(
        None, alias="date", description="Datum YYYY‑MM‑DD (default: morgen)"
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied"),
):
    """Haal day-ahead load forecast op."""
    try:
        d = parse_date_or_default(date_str)
        rows = entsoe.get_day_ahead_total_load_forecast(d, zone)

        return {
            "date": d.isoformat(),
            "zone": zone,
            "forecast": rows,
            "total_periods": len(rows),
        }
    except Exception as e:
        return error_response(e)


@app.get(
    "/generation/forecast/wind-solar",
    tags=["generation"],
    summary="Wind en zon opwek voorspelling",
)
def generation_forecast_wind_solar(
    date_str: Optional[str] = Query(
        None, alias="date", description="Datum YYYY‑MM‑DD (default: morgen)"
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied"),
):
    """Haal wind en zonne-energie forecast op (A69, B16/B18/B19)."""
    try:
        d = parse_date_or_default(date_str)
        rows = entsoe.get_generation_forecast(d, zone, psr_types=["B16", "B18", "B19"])

        return {
            "date": d.isoformat(),
            "zone": zone,
            "wind_solar_forecast": rows,
            "total_periods": len(rows),
        }
    except Exception as e:
        return error_response(e)


@app.get(
    "/balancing/state/current",
    tags=["balancing"],
    summary="Huidige balanceringsstatus",
)
def balancing_state_current(
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC zone code"),
):
    """
    Huidige netpositie status.
    Positief = export (overschot), Negatief = import (tekort).
    """
    try:
        today = date.today()
        rows = entsoe.get_net_position(today, zone)

        if not rows:
            raise entsoe.EntsoeError("Geen netpositie data beschikbaar")

        last = rows[-1]
        state = "export" if last["net_position_mw"] > 0 else "import"

        return {
            "date": today.isoformat(),
            "zone": zone,
            "current_state": state,
            "last_measurement": last,
        }
    except Exception as e:
        return error_response(e)
