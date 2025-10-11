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
        "met eenvoudige endpoints gericht op home automation. "
        "Ondersteunt zowel PT60M (hourly) als PT15M (15-minuten) resolutie."
    ),
    version="2.1.0",
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
# SMART CHEAPEST HOURS LOGIC (SUPPORTS PT60M & PT15M)
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


def is_past_slot(
    hour_local: str, slot_date: date, resolution_minutes: int = 60
) -> bool:
    """
    Check of een slot volledig verstreken is.

    Args:
        hour_local: Timestamp string "YYYY-MM-DD HH:MM"
        slot_date: Datum van het slot
        resolution_minutes: Resolutie in minuten (60 of 15)
    """
    now = datetime.now(entsoe.TZ_LOCAL)
    today = now.date()

    if slot_date != today:
        return slot_date < today

    try:
        dt = datetime.strptime(hour_local, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=entsoe.TZ_LOCAL)
        end_dt = dt + timedelta(minutes=resolution_minutes)
        return now >= end_dt
    except Exception:
        return False


def is_current_or_future_slot(
    hour_local: str, slot_date: date, resolution_minutes: int = 60
) -> bool:
    """Check of een slot actief of toekomstig is."""
    return not is_past_slot(hour_local, slot_date, resolution_minutes)


def detect_resolution(slots: List[Dict]) -> int:
    """
    Detecteer de resolutie van de slots (in minuten).

    Returns:
        60 voor PT60M (hourly)
        15 voor PT15M (15-minuten)
    """
    if not slots or len(slots) < 2:
        # Default: hourly
        return 60

    # Controleer resolution veld indien aanwezig
    if "resolution" in slots[0]:
        res_text = slots[0]["resolution"].upper()
        if "PT15M" in res_text:
            return 15
        elif "PT60M" in res_text or "PT1H" in res_text:
            return 60

    # Fallback: bereken uit position verschil
    sorted_slots = sorted(slots[:10], key=lambda s: s["position"])
    if len(sorted_slots) >= 2:
        # Check verschil tussen opeenvolgende posities
        diff = sorted_slots[1]["position"] - sorted_slots[0]["position"]
        # Als positions stappen met 1 en we weten dat hourly data position = uur
        # Dan is diff=1 hourly (60 min) en diff=4 zou 15-min kunnen zijn (4x15min=60min)
        # Maar in onze data is position altijd incrementeel per slot
        # Dus we kijken naar hoeveel slots per uur we verwachten
        pass

    # Veilige default
    return 60


def group_consecutive_slots(
    slots: List[Dict],
    max_gap_minutes: int = 30,
    max_price_gap_ct: float = 2.0,
    resolution_minutes: int = 60,
) -> List[Dict]:
    """
    Groepeer opeenvolgende slots met kleine tussenpozen EN vergelijkbare prijzen.

    Ondersteunt zowel PT60M (hourly) als PT15M (15-minuten) resolutie.

    Args:
        slots: Lijst met slot dictionaries
        max_gap_minutes: Maximale tijd gap tussen slots
        max_price_gap_ct: Maximaal prijsverschil binnen een groep (ct/kWh)
        resolution_minutes: Resolutie in minuten (60 of 15)

    Returns:
        Groepen gesorteerd op gemiddelde prijs (goedkoopste eerst).
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
        "min_price": sorted_slots[0]["ct_per_kwh"],
        "max_price": sorted_slots[0]["ct_per_kwh"],
    }

    for i in range(1, len(sorted_slots)):
        prev = sorted_slots[i - 1]
        curr = sorted_slots[i]

        # Bereken tijdsverschil op basis van resolutie
        # Position increment van 1 = resolution_minutes verschil
        position_diff = curr["position"] - prev["position"]
        time_gap_minutes = position_diff * resolution_minutes

        # Bereken potentiële nieuwe min/max prijzen
        potential_min = min(current_group["min_price"], curr["ct_per_kwh"])
        potential_max = max(current_group["max_price"], curr["ct_per_kwh"])
        potential_price_gap = potential_max - potential_min

        # Check beide voorwaarden:
        # 1. Tijd gap is acceptabel
        # 2. Prijs gap blijft binnen limiet
        can_merge = (
            time_gap_minutes <= max_gap_minutes
            and potential_price_gap <= max_price_gap_ct
        )

        if can_merge:
            # Voeg toe aan huidige groep
            current_group["end"] = curr["hour_local"]
            current_group["slots"].append(curr)
            current_group["positions"].append(curr["position"])
            current_group["min_price"] = potential_min
            current_group["max_price"] = potential_max
        else:
            # Sla huidige groep op en start nieuwe
            groups.append(current_group)
            current_group = {
                "start": curr["hour_local"],
                "end": curr["hour_local"],
                "slots": [curr],
                "positions": [curr["position"]],
                "min_price": curr["ct_per_kwh"],
                "max_price": curr["ct_per_kwh"],
            }

    # Voeg laatste groep toe
    groups.append(current_group)

    # Bereken gemiddelde prijs per groep
    for group in groups:
        avg_price = sum(s["ct_per_kwh"] for s in group["slots"]) / len(group["slots"])
        group["avg_price"] = avg_price

    # Sorteer op gemiddelde prijs (goedkoopste eerst)
    return sorted(groups, key=lambda g: g["avg_price"])


def calculate_total_duration(positions: List[int], resolution_minutes: int = 60) -> int:
    """
    Bereken totale duur in minuten van een groep posities.

    Args:
        positions: Lijst van position nummers
        resolution_minutes: Resolutie in minuten (60 of 15)

    Returns:
        Totale duur in minuten
    """
    if not positions:
        return 0
    # (laatste - eerste) * resolutie + resolutie voor de laatste slot zelf
    span = max(positions) - min(positions)
    return span * resolution_minutes + resolution_minutes


def format_time_range(start: str, end: str, resolution_minutes: int = 60) -> str:
    """
    Formateer tijd range op basis van resolutie.

    Args:
        start: Start tijd string "YYYY-MM-DD HH:MM"
        end: End tijd string "YYYY-MM-DD HH:MM"
        resolution_minutes: Resolutie in minuten (60 of 15)

    Returns:
        Formatted string "HH:MM - HH:MM"
    """
    try:
        # Parse start tijd
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")

        # Parse end tijd
        end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M")

        # Voeg resolutie toe aan eindtijd (einde van het laatste slot)
        final_dt = end_dt + timedelta(minutes=resolution_minutes)

        return f"{start_dt.strftime('%H:%M')} - {final_dt.strftime('%H:%M')}"
    except Exception:
        return "Unknown"


def process_day_data(
    day_data: Dict,
    slot_date: date,
    max_blocks: int = 6,
    max_time_gap_minutes: int = 30,
    max_price_gap_ct: float = 2.0,
) -> Dict:
    """
    Process data voor één dag.

    Detecteert automatisch PT60M of PT15M resolutie.

    Args:
        day_data: Dictionary met cheapest_slots en average_ct_per_kwh
        slot_date: Datum van de slots
        max_blocks: Maximaal aantal tijdsblokken (default 6)
        max_time_gap_minutes: Max tijd tussen slots in een blok
        max_price_gap_ct: Max prijsverschil binnen een blok (ct/kWh)

    Returns:
        Processed data met time_blocks
    """
    all_slots = day_data.get("cheapest_slots", [])
    avg_price = day_data.get("average_ct_per_kwh", 0)

    if not all_slots:
        return {
            "date": slot_date.isoformat(),
            "average_ct_per_kwh": round(avg_price, 3),
            "time_blocks": [],
            "future_blocks_count": 0,
            "total_blocks_count": 0,
            "resolution_minutes": 60,
        }

    # Detecteer resolutie
    resolution_minutes = detect_resolution(all_slots)

    today = date.today()
    is_today = slot_date == today

    # STAP 1: Filter nachtelijke slots (00:00-06:00) alleen voor vandaag
    filtered_slots = all_slots
    if is_today:
        filtered_slots = [
            slot for slot in all_slots if belongs_to_today(slot["hour_local"])
        ]

    # STAP 2: Groepeer opeenvolgende slots met tijd én prijs constraints
    grouped_slots = group_consecutive_slots(
        filtered_slots,
        max_gap_minutes=max_time_gap_minutes,
        max_price_gap_ct=max_price_gap_ct,
        resolution_minutes=resolution_minutes,
    )

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
        is_future = is_current_or_future_slot(
            first_slot["hour_local"], slot_date, resolution_minutes
        )

        time_blocks.append(
            {
                "rank": idx + 1,
                "time_range": format_time_range(
                    group["start"], group["end"], resolution_minutes
                ),
                "duration_minutes": calculate_total_duration(
                    group["positions"], resolution_minutes
                ),
                "actual_slot_count": len(group["slots"]),
                "avg_price": round(avg, 3),
                "min_price": round(min_price, 3),
                "max_price": round(max_price, 3),
                "price_variance": round(max_price - min_price, 3),
                "is_best": avg < avg_price * 0.85,  # 15% goedkoper dan gemiddelde
                "is_future": is_future,
                "individual_slots": [
                    {
                        "time": s["hour_local"].split(" ")[1],  # "HH:MM"
                        "price": round(s["ct_per_kwh"], 3),
                        "is_past": is_past_slot(
                            s["hour_local"], slot_date, resolution_minutes
                        ),
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
        "resolution_minutes": resolution_minutes,
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
        "version": "2.1.0",
        "features": [
            "Supports PT60M (hourly) and PT15M (15-minute) resolution",
            "Smart price-aware grouping",
            "Configurable time and price gaps",
            "Dutch language labels",
        ],
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

        # Detecteer resolutie
        resolution = 60
        if rows and "resolution" in rows[0]:
            res_text = rows[0]["resolution"].upper()
            if "PT15M" in res_text:
                resolution = 15

        return {
            "date": d.isoformat(),
            "zone": zone,
            "prices": rows,
            "total_slots": len(rows),
            "resolution_minutes": resolution,
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
        "- Analyseert ALLE uren van de dag\n"
        "- Automatische detectie van PT60M (hourly) of PT15M (15-min) resolutie\n"
        "- Groepeert opeenvolgende slots met vergelijkbare prijzen\n"
        "- Filtert nachtelijke slots (00:00-06:00) voor vandaag\n"
        "- Markeert verstreken vs toekomstige slots\n"
        "- Perfect voor laadschema's en slimme apparaten\n\n"
        "**Parameters:**\n"
        "- `max_blocks`: Max aantal tijdsblokken in response (1-12)\n"
        "- `max_time_gap`: Max minuten tussen slots in één blok (15-120)\n"
        "  * Voor PT60M: 60 = max 1 uur gap, 30 = alleen direct opeenvolgend\n"
        "  * Voor PT15M: 30 = max 2 slots gap, 15 = alleen direct opeenvolgend\n"
        "- `max_price_gap`: Max prijsverschil (ct/kWh) binnen één blok (0.5-5.0)\n"
        "- `price_threshold_pct`: Alleen slots onder dit percentiel (default: 50 = goedkoopste helft)\n\n"
        "**Response velden:**\n"
        "- `resolution_minutes`: 60 (hourly) of 15 (15-min)\n"
        "- `price_variance`: Prijsverschil min-max binnen blok\n"
        "- `is_future`: true = nog te gebruiken, false = verstreken\n"
        "- `is_best`: true = >15% goedkoper dan daggemiddelde"
    ),
)
def energy_prices_cheapest(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Datum YYYY-MM-DD (default: vandaag)",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied"),
    max_blocks: int = Query(
        6, ge=1, le=12, description="Max aantal tijdsblokken in response (1-12)"
    ),
    max_time_gap: int = Query(
        60, ge=15, le=180, description="Max minuten tussen slots in één blok (15-180)"
    ),
    max_price_gap: float = Query(
        2.0,
        ge=0.5,
        le=5.0,
        description="Max prijsverschil (ct/kWh) binnen één blok (0.5-5.0)",
    ),
    price_threshold_pct: int = Query(
        50,
        ge=10,
        le=100,
        description="Analyseer alleen slots onder dit percentiel (10-100, default 50 = goedkoopste helft)",
    ),
):
    """
    Smart cheapest hours - analyseert alle uren van de dag.

    Response format:
    {
      "label": "Vandaag",
      "date": "2025-10-10",
      "average_ct_per_kwh": 9.52,
      "price_threshold_ct_per_kwh": 8.15,
      "resolution_minutes": 60,
      "time_blocks": [...],
      "future_blocks_count": 2,
      "total_blocks_count": 6,
      "config": {
        "max_time_gap_minutes": 60,
        "max_price_gap_ct": 2.0,
        "price_threshold_pct": 50
      },
      "generated_at": "2025-10-10T22:45:00+02:00",
      "zone": "10YNL----------L"
    }
    """
    try:
        # Parse datum (default: vandaag)
        target_date = date.fromisoformat(date_str) if date_str else date.today()

        # Haal ALLE prijsdata op voor de dag
        all_prices = entsoe.get_day_ahead_prices(target_date, zone)

        if not all_prices:
            raise entsoe.EntsoeServerError(
                f"Geen prijsdata beschikbaar voor {target_date.isoformat()}", status=404
            )

        # Bereken gemiddelde en threshold
        avg = sum(r["ct_per_kwh"] for r in all_prices) / len(all_prices)

        # Sorteer prijzen en neem het juiste percentiel
        sorted_prices = sorted([r["ct_per_kwh"] for r in all_prices])
        threshold_index = int(len(sorted_prices) * (price_threshold_pct / 100.0))
        price_threshold = sorted_prices[min(threshold_index, len(sorted_prices) - 1)]

        # Filter slots onder de threshold
        cheapest = [r for r in all_prices if r["ct_per_kwh"] <= price_threshold]

        # Als we te weinig slots hebben, neem de goedkoopste helft
        if len(cheapest) < 3:
            cheapest = sorted(all_prices, key=lambda r: r["ct_per_kwh"])[
                : len(all_prices) // 2
            ]
            price_threshold = cheapest[-1]["ct_per_kwh"] if cheapest else 0

        # Process data
        day_data = {"cheapest_slots": cheapest, "average_ct_per_kwh": avg}

        processed = process_day_data(
            day_data,
            target_date,
            max_blocks=max_blocks,
            max_time_gap_minutes=max_time_gap,
            max_price_gap_ct=max_price_gap,
        )

        # Voeg metadata toe
        processed["label"] = get_day_label(target_date)
        processed["generated_at"] = datetime.now(entsoe.TZ_LOCAL).isoformat()
        processed["zone"] = zone
        processed["price_threshold_ct_per_kwh"] = round(price_threshold, 3)
        processed["config"] = {
            "max_time_gap_minutes": max_time_gap,
            "max_price_gap_ct": max_price_gap,
            "price_threshold_pct": price_threshold_pct,
            "analyzed_slots_count": len(cheapest),
            "total_slots_in_day": len(all_prices),
        }

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
