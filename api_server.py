#!/usr/bin/env python3
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from collections import defaultdict
import math

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
        "met eenvoudige endpoints gericht op home automation. "
        "Uitgebreid met `/energy/*`, `/load/*`, `/generation/*`, `/balancing/*`, `/system/*`."
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
# SMART CHEAPEST HOURS LOGIC (from n8n)
# ============================================================================


def belongs_to_today(hour_local: str) -> bool:
    """Check of een slot tot vandaag behoort (niet na middernacht)."""
    try:
        # Parse hour_local: "2025-10-10 02:45"
        dt = datetime.strptime(hour_local, "%Y-%m-%d %H:%M")
        # Slots tussen 00:00 - 06:00 beschouwen we als "morgen vroeg"
        return dt.hour >= 6
    except Exception:
        return True


def is_past_slot(hour_local: str, slot_date: date) -> bool:
    """Check of een slot volledig verstreken is (eindtijd bereikt)."""
    now = datetime.now(entsoe.TZ_LOCAL)
    today = now.date()

    # Als het niet vandaag is, check de datum
    if slot_date != today:
        return slot_date < today

    try:
        # Parse de starttijd
        dt = datetime.strptime(hour_local, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=entsoe.TZ_LOCAL)

        # Voeg 15 minuten toe voor eindtijd (standaard slot duur)
        end_dt = dt + timedelta(minutes=15)

        # Verstreken = huidige tijd is >= eindtijd
        return now >= end_dt
    except Exception:
        return False


def is_current_or_future_slot(hour_local: str, slot_date: date) -> bool:
    """Check of een slot actief of toekomstig is."""
    return not is_past_slot(hour_local, slot_date)


def group_consecutive_slots(slots: List[Dict], max_gap_minutes: int = 30) -> List[Dict]:
    """
    Groepeer opeenvolgende slots met kleine tussenpozen.
    Sorteer groepen op gemiddelde prijs (goedkoopste eerst).
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

        # Bereken het verschil in posities (elke positie = 15 minuten)
        position_gap = curr["position"] - prev["position"]

        # Voeg toe aan groep als het verschil <= max_gap_minutes / 15
        if position_gap <= max_gap_minutes / 15:
            current_group["end"] = curr["hour_local"]
            current_group["slots"].append(curr)
            current_group["positions"].append(curr["position"])
        else:
            # Start nieuwe groep
            groups.append(current_group)
            current_group = {
                "start": curr["hour_local"],
                "end": curr["hour_local"],
                "slots": [curr],
                "positions": [curr["position"]],
            }

    groups.append(current_group)

    # Sorteer groepen op gemiddelde prijs (goedkoopste eerst)
    for group in groups:
        avg_price = sum(s["ct_per_kwh"] for s in group["slots"]) / len(group["slots"])
        group["avg_price"] = avg_price

    return sorted(groups, key=lambda g: g["avg_price"])


def format_time_range(start: str, end: str) -> str:
    """Formateer tijd range met +15 minuten aan eindtijd."""
    try:
        # Extract tijd van start (formaat: "2025-10-11 13:30")
        start_time = start.split(" ")[1]  # "13:30"
        start_h, start_m = map(int, start_time.split(":"))

        # Extract tijd van end
        end_time = end.split(" ")[1]
        end_h, end_m = map(int, end_time.split(":"))

        # Voeg 15 minuten toe aan eindtijd
        final_h = end_h
        final_m = end_m + 15

        # Handel minuten overflow af
        if final_m >= 60:
            final_m -= 60
            final_h += 1

        # Handel uur overflow af (middernacht)
        if final_h >= 24:
            final_h -= 24

        # Format output
        start_formatted = f"{start_h:02d}:{start_m:02d}"
        end_formatted = f"{final_h:02d}:{final_m:02d}"

        return f"{start_formatted} - {end_formatted}"
    except Exception:
        return "Unknown"


def calculate_total_duration(positions: List[int]) -> int:
    """Bereken totale duur inclusief gaps."""
    if not positions:
        return 0
    return (max(positions) - min(positions) + 1) * 15


def find_additional_future_slots(
    all_slots: List[Dict], slot_date: date, current_blocks: List[Dict], needed: int = 4
) -> List[Dict]:
    """Vind extra toekomstige slots uit alle cheapest_slots."""
    now = datetime.now(entsoe.TZ_LOCAL)
    today = now.date()

    # Alleen voor vandaag
    if slot_date != today:
        return []

    # Vind alle slots die in de toekomst liggen EN tot vandaag behoren
    future_slots = [
        slot
        for slot in all_slots
        if belongs_to_today(slot["hour_local"])
        and is_current_or_future_slot(slot["hour_local"], slot_date)
    ]

    # Sorteer op prijs (goedkoopste eerst)
    sorted_by_price = sorted(future_slots, key=lambda s: s["ct_per_kwh"])

    # Haal de tijden van slots die al in currentBlocks zitten
    used_slot_times = set()
    for block in current_blocks:
        for slot in block["individual_slots"]:
            used_slot_times.add(slot["time"])

    # Vind nieuwe slots die nog niet gebruikt zijn
    new_slots = []
    for slot in sorted_by_price:
        time_str = slot["hour_local"].split(" ")[1][:5]  # "HH:MM"
        if time_str not in used_slot_times:
            new_slots.append(slot)
        if len(new_slots) >= needed:
            break

    # Converteer naar timeblocks
    extra_blocks = []
    for idx, slot in enumerate(new_slots):
        time_str = slot["hour_local"].split(" ")[1][:5]
        extra_blocks.append(
            {
                "rank": len(current_blocks) + idx + 1,
                "time_range": format_time_range(slot["hour_local"], slot["hour_local"]),
                "duration_minutes": 15,
                "actual_slot_count": 1,
                "avg_price": round(slot["ct_per_kwh"], 3),
                "min_price": round(slot["ct_per_kwh"], 3),
                "max_price": round(slot["ct_per_kwh"], 3),
                "is_best": False,
                "is_extra": True,
                "individual_slots": [{"time": time_str, "price": slot["ct_per_kwh"]}],
            }
        )

    return extra_blocks


def process_day_data(day_data: Dict, slot_date: date) -> Dict:
    """Process data voor één dag (main logic from n8n)."""
    all_slots = day_data.get("cheapest_slots", [])
    avg_price = day_data.get("average_ct_per_kwh", 0)

    # Voor vandaag: filter slots die na middernacht zijn
    today = date.today()
    is_today = slot_date == today

    filtered_slots = all_slots
    if is_today:
        # Filter alleen slots die tot vandaag behoren (niet na middernacht)
        filtered_slots = [
            slot for slot in all_slots if belongs_to_today(slot["hour_local"])
        ]

    # Groepeer slots
    grouped_slots = group_consecutive_slots(filtered_slots, max_gap_minutes=30)

    # Converteer naar timeblocks
    time_blocks = []
    for idx, group in enumerate(grouped_slots):
        avg = sum(s["ct_per_kwh"] for s in group["slots"]) / len(group["slots"])
        min_price = min(s["ct_per_kwh"] for s in group["slots"])
        max_price = max(s["ct_per_kwh"] for s in group["slots"])

        time_blocks.append(
            {
                "rank": idx + 1,
                "time_range": format_time_range(group["start"], group["end"]),
                "duration_minutes": calculate_total_duration(group["positions"]),
                "actual_slot_count": len(group["slots"]),
                "avg_price": round(avg, 3),
                "min_price": round(min_price, 3),
                "max_price": round(max_price, 3),
                "is_best": avg < avg_price * 0.8,  # 20% onder gemiddelde
                "is_extra": False,
                "individual_slots": [
                    {
                        "time": s["hour_local"].split(" ")[1][:5],
                        "price": s["ct_per_kwh"],
                    }
                    for s in group["slots"]
                ],
            }
        )

    # Check hoeveel toekomstige blocks er zijn
    future_blocks = [
        block
        for block in time_blocks
        if any(
            is_current_or_future_slot(
                f"{slot_date.isoformat()} {slot['time']}", slot_date
            )
            for slot in block["individual_slots"]
        )
    ]

    # Als er minder dan 4 toekomstige blocks zijn voor vandaag, voeg extra toe
    final_blocks = time_blocks
    if is_today and len(future_blocks) < 4:
        needed = 4 - len(future_blocks)
        extra_slots = find_additional_future_slots(
            all_slots, slot_date, time_blocks, needed
        )

        if extra_slots:
            final_blocks = time_blocks + extra_slots
            # Re-sorteer op prijs
            final_blocks = sorted(final_blocks, key=lambda b: b["avg_price"])
            # Re-number ranks
            for idx, block in enumerate(final_blocks, 1):
                block["rank"] = idx

    return {
        "date": slot_date.isoformat(),
        "average_ct_per_kwh": avg_price,
        "time_blocks": final_blocks,
        "has_extra_slots": any(b.get("is_extra", False) for b in final_blocks),
    }


def get_day_label(target_date: date) -> str:
    """Bepaal label op basis van datum."""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    if target_date == today:
        return "Vandaag"
    elif target_date == tomorrow:
        return "Morgen"
    else:
        # Nederlands formaat: "vrijdag 11 oktober"
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
# META & CONFIG
# ============================================================================
@app.get("/", tags=["meta"], summary="Service Info")
def root():
    return {
        "service": "ENTSO‑E Home Automation API",
        "version": "2.0.0",
        "docs": "/docs",
        "home_use_endpoints": [
            "/energy/prices/dayahead",
            "/energy/prices/cheapest",
            "/load/forecast/dayahead",
            "/generation/forecast/wind-solar",
            "/balancing/state/current",
            "/system/health",
        ],
    }


@app.get("/system/health", tags=["system"], summary="Health‑check")
def system_health():
    """Eenvoudige health‑check endpoint voor monitoring."""
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


# ============================================================================
# ENERGY / PRICES
# ============================================================================
@app.get(
    "/energy/prices/cheapest",
    tags=["energy"],
    summary="Slimme goedkoopste tijdsblokken (Smart Charging Ready)",
    description=(
        "Geeft gegroepeerde tijdsblokken terug met intelligente filtering:\n"
        "- Groepeert opeenvolgende slots (max 30 min gap)\n"
        "- Filtert automatisch nachtelijke slots (00:00-06:00) voor vandaag\n"
        "- Markeert verstreken slots\n"
        "- Voegt extra slots toe als er <4 toekomstige zijn\n"
        "- Sorteer op prijs (goedkoopste eerst)\n\n"
        "Perfect voor home automation en laadschema's!"
    ),
)
def energy_prices_cheapest(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Datum YYYY-MM-DD. Default: vandaag",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied."),
    count: int = Query(20, description="Aantal goedkoopste slots om te analyseren."),
):
    """
    Smart cheapest hours endpoint met volledige n8n logica.

    Returns een structuur klaar voor direct gebruik in apps:
    {
      "label": "Vandaag",
      "date": "2025-10-10",
      "average_ct_per_kwh": 9.52,
      "time_blocks": [
        {
          "rank": 1,
          "time_range": "11:30 - 12:00",
          "duration_minutes": 30,
          "actual_slot_count": 2,
          "avg_price": 6.935,
          "min_price": 6.774,
          "max_price": 7.096,
          "is_best": true,
          "is_extra": false,
          "individual_slots": [
            {"time": "11:30", "price": 6.774},
            {"time": "11:45", "price": 7.096}
          ]
        }
      ],
      "has_extra_slots": false,
      "generated_at": "2025-10-10T22:45:00+02:00",
      "zone": "10YNL----------L"
    }
    """
    try:
        # Parse datum (default: vandaag)
        if date_str:
            target_date = date.fromisoformat(date_str)
        else:
            target_date = date.today()

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

        # Process day data
        day_data = {"cheapest_slots": cheapest, "average_ct_per_kwh": avg}

        processed = process_day_data(day_data, target_date)
        processed["label"] = get_day_label(target_date)
        processed["generated_at"] = datetime.now(entsoe.TZ_LOCAL).isoformat()
        processed["zone"] = zone

        return processed

    except Exception as e:
        return error_response(e)


def energy_prices_dayahead(
    date_str: Optional[str] = Query(
        (date.today() + timedelta(days=1)).isoformat(),
        alias="date",
        description="Datum YYYY‑MM‑DD (standaard morgen).",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied."),
):
    try:
        d = parse_date_or_default(date_str)
        rows = entsoe.get_day_ahead_prices(
            d, zone, cache_ttl_s=entsoe.TTL_PRICES_DEFAULT
        )
        return {"date": d.isoformat(), "zone": zone, "prices": rows}
    except Exception as e:
        return error_response(e)


@app.get(
    "/energy/prices/cheapest",
    tags=["energy"],
    summary="Slimme goedkoopste tijdsblokken (Smart Charging Ready)",
    description=(
        "Geeft gegroepeerde tijdsblokken terug met intelligente filtering:\n"
        "- Groepeert opeenvolgende slots (max 30 min gap)\n"
        "- Filtert automatisch nachtelijke slots (00:00-06:00) voor vandaag\n"
        "- Markeert verstreken slots\n"
        "- Voegt extra slots toe als er <4 toekomstige zijn\n"
        "- Sorteer op prijs (goedkoopste eerst)\n\n"
        "Perfect voor home automation en laadschema's!"
    ),
)
def energy_prices_cheapest(
    dates: Optional[str] = Query(
        None,
        description="Comma-separated datums (YYYY-MM-DD). Default: vandaag,morgen",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied."),
    count: int = Query(
        20, description="Aantal goedkoopste slots per dag om te analyseren."
    ),
):
    """
    Smart cheapest hours endpoint met volledige n8n logica.

    Returns een structuur klaar voor direct gebruik in apps:
    {
      "days": [
        {
          "label": "Vandaag",
          "date": "2025-10-10",
          "average_ct_per_kwh": 9.52,
          "time_blocks": [...],
          "has_extra_slots": false
        }
      ],
      "generated_at": "2025-10-10T22:45:00Z",
      "total_days": 2
    }
    """
    try:
        # Parse datums
        if dates:
            date_list = [date.fromisoformat(d.strip()) for d in dates.split(",")]
        else:
            # Default: vandaag en morgen
            today = date.today()
            date_list = [today, today + timedelta(days=1)]

        processed_days = []

        for target_date in date_list:
            # Haal prijsdata op
            prices = entsoe.get_day_ahead_prices(target_date, zone)

            if not prices:
                continue

            # Bereken gemiddelde
            avg = sum(r["ct_per_kwh"] for r in prices) / len(prices)

            # Neem de goedkoopste slots
            cheapest = sorted(prices, key=lambda r: r["ct_per_kwh"])[:count]

            # Process day data
            day_data = {"cheapest_slots": cheapest, "average_ct_per_kwh": avg}

            processed = process_day_data(day_data, target_date)
            processed["label"] = get_day_label(target_date)

            processed_days.append(processed)

        return {
            "days": processed_days,
            "generated_at": datetime.now(entsoe.TZ_LOCAL).isoformat(),
            "total_days": len(processed_days),
            "zone": zone,
        }

    except Exception as e:
        return error_response(e)


# ============================================================================
# LOAD / FORECAST
# ============================================================================
@app.get(
    "/load/forecast/dayahead",
    tags=["load"],
    summary="Day‑ahead load forecast (ENTSO‑E A65)",
)
def load_forecast_dayahead(
    date_str: Optional[str] = Query(
        (date.today() + timedelta(days=1)).isoformat(), alias="date"
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE),
):
    try:
        d = parse_date_or_default(date_str)
        rows = entsoe.get_day_ahead_total_load_forecast(d, zone)
        return {"date": d.isoformat(), "zone": zone, "forecast": rows}
    except Exception as e:
        return error_response(e)


# ============================================================================
# GENERATION / WIND + SOLAR
# ============================================================================
@app.get(
    "/generation/forecast/wind-solar",
    tags=["generation"],
    summary="Voorspelling wind en zon opwek",
    description="Haalt A69 day‑ahead generation forecast voor wind en zon (B18/B16/B19).",
)
def generation_forecast_wind_solar(
    date_str: Optional[str] = Query(
        (date.today() + timedelta(days=1)).isoformat(), alias="date"
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE),
):
    try:
        d = parse_date_or_default(date_str)
        rows = entsoe.get_generation_forecast(d, zone, psr_types=["B16", "B18", "B19"])
        return {"date": d.isoformat(), "zone": zone, "wind_solar_forecast": rows}
    except Exception as e:
        return error_response(e)


# ============================================================================
# BALANCING / CURRENT STATE
# ============================================================================
@app.get(
    "/balancing/state/current",
    tags=["balancing"],
    summary="Huidige balanceringsstatus",
    description="Synthetische endpoint op basis van net‑positie (NL positief = export = overschot).",
)
def balancing_state_current(
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC zone code."),
):
    try:
        today = date.today()
        rows = entsoe.get_net_position(today, zone)
        last = rows[-1] if rows else None
        if not last:
            raise entsoe.EntsoeError("Geen netpositie‑data.")
        state = "export" if last["net_position_mw"] > 0 else "import"
        return {
            "date": today.isoformat(),
            "zone": zone,
            "current_state": state,
            "last_measurement": last,
        }
    except Exception as e:
        return error_response(e)
