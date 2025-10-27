#!/usr/bin/env python3
"""
FastAPI server for ENTSO-E energy prices.
Provides endpoints for current day, tomorrow and custom dates.
"""

import os
import math
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
import traceback

import pytz
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
import uvicorn

# ============================================================================
# IMPORT HA_ENTSOE MODULE
# ============================================================================

try:
    import ha_entsoe as entsoe
    from ha_entsoe import (
        EntsoeError,
        EntsoeServerError,
        EntsoeNotFound,
        EntsoeUnauthorized,
        EntsoeForbidden,
        EntsoeRateLimited,
        EntsoeParseError,
    )
except Exception as e:
    raise RuntimeError(f"Could not import ha_entsoe.py: {e}")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# ============================================================================
# LOGGING SETUP
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

logger = logging.getLogger("entsoe_api")
logger.info(f"Starting ENTSO-E Home Automation API - Log level: {LOG_LEVEL}")

# ============================================================================
# CONSTANTS
# ============================================================================

EIC_OPTIONS = {
    "Netherlands": "10YNL----------L",
    "Belgium": "10YBE----------2",
    "Germany": "10Y1001A1001A83F",
}

DEFAULT_ZONE = os.getenv("ZONE_EIC", EIC_OPTIONS["Netherlands"])
DEFAULT_TIMEZONE = "Europe/Amsterdam"

# Timezone configuration - ALWAYS use Dutch time
NL_TZ = pytz.timezone("Europe/Amsterdam")

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="ENTSO‑E Home Automation API",
    description=(
        "Small wrapper for ENTSO‑E data (prices, load, production, net position) "
        "with simple endpoints focused on home automation. "
        "Supports both PT60M (hourly) and PT15M (15-minute) resolution."
    ),
    version="2.9.0",
)

# ============================================================================
# MIDDLEWARE & EXCEPTION HANDLERS
# ============================================================================


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all requests with timing and error tracking"""
    start_time = datetime.now(NL_TZ)
    request_id = f"req_{int(start_time.timestamp())}"

    # Log request
    logger.info(
        f"[{request_id}] {request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'}"
    )

    try:
        response = await call_next(request)

        # Calculate execution time
        execution_time = (datetime.now(NL_TZ) - start_time).total_seconds() * 1000

        # Log response
        logger.info(
            f"[{request_id}] Response: {response.status_code} "
            f"in {execution_time:.2f}ms"
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response

    except ValueError as e:
        # Handle validation errors (like date format) with proper status code
        execution_time = (datetime.now(NL_TZ) - start_time).total_seconds() * 1000
        logger.warning(
            f"[{request_id}] Validation error after {execution_time:.2f}ms: {str(e)}"
        )
        return error_response(e, request_id)
    except Exception as e:
        execution_time = (datetime.now(NL_TZ) - start_time).total_seconds() * 1000
        logger.error(
            f"[{request_id}] Request failed after {execution_time:.2f}ms: {str(e)}"
        )
        return error_response(e, request_id)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle FastAPI validation errors"""
    request_id = request.headers.get(
        "X-Request-ID", f"err_{int(datetime.now().timestamp())}"
    )

    logger.warning(f"[{request_id}] Validation error: {exc}")

    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Invalid request parameters",
            "details": exc.errors(),
            "error_id": request_id,
            "timestamp": datetime.now(NL_TZ).isoformat(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTP exceptions"""
    request_id = request.headers.get(
        "X-Request-ID", f"err_{int(datetime.now().timestamp())}"
    )

    logger.warning(f"[{request_id}] HTTP exception: {exc.status_code} - {exc.detail}")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP_ERROR",
            "message": exc.detail,
            "status": exc.status_code,
            "error_id": request_id,
            "timestamp": datetime.now(NL_TZ).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all other unhandled exceptions"""
    request_id = request.headers.get(
        "X-Request-ID", f"err_{int(datetime.now().timestamp())}"
    )

    logger.error(f"[{request_id}] Unhandled exception: {str(exc)}", exc_info=True)

    return error_response(exc, request_id)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def error_response(e, request_id: Optional[str] = None):
    """Helper function to create consistent error responses with enhanced logging"""
    error_id = request_id or f"err_{int(datetime.now().timestamp())}"

    if isinstance(e, EntsoeServerError):
        error_msg = str(e)
        status_code = getattr(e, "status", 502)
        error_code = getattr(e, "code", "SERVER_ERROR")

        logger.error(
            f"[{error_id}] ENTSO-E server error: {error_msg} "
            f"(status={status_code}, code={error_code})"
        )

        return JSONResponse(
            status_code=status_code,
            content={
                "error": "ENTSO-E API error",
                "message": error_msg,
                "status": status_code,
                "code": error_code,
                "error_id": error_id,
                "timestamp": datetime.now(NL_TZ).isoformat(),
            },
        )
    elif isinstance(e, EntsoeError):
        error_msg = str(e)
        logger.error(
            f"[{error_id}] ENTSO-E error: {error_msg} (status={e.status}, code={e.code})"
        )

        return JSONResponse(
            status_code=e.status,
            content={
                "error": e.code,
                "message": error_msg,
                "status": e.status,
                "code": e.code,
                "details": e.details,
                "error_id": error_id,
                "timestamp": datetime.now(NL_TZ).isoformat(),
            },
        )
    elif isinstance(e, ValueError) and (
        "Invalid isoformat string" in str(e) or "Invalid date format" in str(e)
    ):
        # Handle date parsing errors specifically
        error_msg = str(e)
        logger.warning(f"[{error_id}] Date validation error: {error_msg}")

        return JSONResponse(
            status_code=422,
            content={
                "error": "VALIDATION_ERROR",
                "message": error_msg,
                "status": 422,
                "code": "INVALID_DATE_FORMAT",
                "error_id": error_id,
                "timestamp": datetime.now(NL_TZ).isoformat(),
            },
        )
    else:
        error_msg = str(e)
        logger.error(f"[{error_id}] Unexpected error: {error_msg}", exc_info=True)

        # Include stack trace in debug mode
        debug_info = {}
        if LOG_LEVEL == "DEBUG":
            debug_info["traceback"] = traceback.format_exc()

        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": error_msg,
                "type": type(e).__name__,
                "error_id": error_id,
                "timestamp": datetime.now(NL_TZ).isoformat(),
                **debug_info,
            },
        )


def validate_date_string(date_str: str) -> date:
    """Validate and parse date string with better error messages"""
    if not date_str:
        raise ValueError("Date parameter is required")

    try:
        parsed_date = date.fromisoformat(date_str)

        # Check if date is reasonable (not too far in past/future)
        today = date.today()
        min_date = today - timedelta(days=365)  # 1 year ago
        max_date = today + timedelta(days=7)  # 1 week ahead

        if parsed_date < min_date:
            raise ValueError(
                f"Date {date_str} is too far in the past (minimum: {min_date})"
            )
        if parsed_date > max_date:
            raise ValueError(
                f"Date {date_str} is too far in the future (maximum: {max_date})"
            )

        return parsed_date
    except ValueError as e:
        if "Invalid isoformat string" in str(e):
            raise ValueError(
                f"Invalid date format '{date_str}'. Please use YYYY-MM-DD format (e.g., 2023-10-28)"
            )
        raise


def validate_zone_code(zone: str) -> str:
    """Validate EIC zone code format"""
    if not zone:
        raise ValueError("Zone parameter is required")

    # Basic EIC code validation (should be 16 characters, start with digits)
    if len(zone) != 16:
        raise ValueError(f"Invalid EIC zone code '{zone}'. Must be 16 characters long")

    if not zone[:2].isdigit():
        raise ValueError(f"Invalid EIC zone code '{zone}'. Must start with 2 digits")

    return zone


def create_metadata(
    endpoint: str,
    request_params: Dict[str, Any],
    execution_time_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Create metadata object with request info.

    Args:
        endpoint: Endpoint name
        request_params: Dictionary with request parameters
        execution_time_ms: Optional execution time in milliseconds

    Returns:
        Metadata dictionary
    """
    metadata = {
        "endpoint": endpoint,
        "request_params": request_params,
        "timestamp": datetime.now(NL_TZ).isoformat(),
        "timezone": DEFAULT_TIMEZONE,
    }

    if execution_time_ms is not None:
        metadata["execution_time_ms"] = round(execution_time_ms, 2)

    return metadata


# ============================================================================
# STATISTICS HELPERS
# ============================================================================


def calculate_std_dev(prices: List[float]) -> float:
    """
    Calculate standard deviation of prices.

    Args:
        prices: List of prices (ct/kWh)

    Returns:
        Standard deviation (σ)
    """
    if len(prices) < 2:
        return 0.0

    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    return math.sqrt(variance)


def is_std_dev_relevant(std_dev: float, price_range: float, slot_count: int) -> bool:
    """
    Determine if standard deviation is statistically relevant to show.

    Criteria:
    - Minimum 3 slots (otherwise not meaningful)
    - Standard deviation > 0.1 ct/kWh (otherwise negligible)
    - Standard deviation > 5% of range (otherwise too small relative to variation)

    Args:
        std_dev: Standard deviation
        price_range: Max - min price in block
        slot_count: Number of slots in block

    Returns:
        True if relevant to show
    """
    if slot_count < 3:
        return False

    if std_dev < 0.1:
        return False

    if price_range > 0 and (std_dev / price_range) < 0.05:
        return False

    return True


def get_rank_icon(rank: int) -> str:
    """
    Get emoji icon for rank position.

    Args:
        rank: Position (1 = cheapest)

    Returns:
        Emoji string
    """
    icons = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }
    return icons.get(rank, f"#{rank}")


# ============================================================================
# TIME HELPERS (NEDERLANDSE TIJD)
# ============================================================================


def belongs_to_today(hour_local: str) -> bool:
    """
    Check if a slot belongs to today (not after midnight).
    Slots between 00:00 - 06:00 we consider as "early tomorrow".
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
    Check if an INDIVIDUAL slot has completely passed (DUTCH TIME).

    A slot is only past when the END time has passed.

    Args:
        hour_local: Timestamp string "YYYY-MM-DD HH:MM"
        slot_date: Date of the slot
        resolution_minutes: Resolution in minutes (60 or 15)

    Returns:
        True if slot is completely past
    """
    # Use DUTCH time!
    now = datetime.now(NL_TZ)
    today = now.date()

    # If the date is in the past, it's definitely past
    if slot_date < today:
        return True

    # If the date is in the future, it's definitely not past
    if slot_date > today:
        return False

    # For today: check if the slot is COMPLETELY past
    try:
        dt = datetime.strptime(hour_local, "%Y-%m-%d %H:%M")
        # Make timezone-aware with Dutch time
        dt = NL_TZ.localize(dt)
        end_dt = dt + timedelta(minutes=resolution_minutes)

        # Slot is only past when the end time is PAST
        is_past = now > end_dt

        if LOG_LEVEL == "DEBUG":
            logger.debug(
                f"      Individual slot {hour_local.split()[1]}: "
                f"end={end_dt.strftime('%H:%M')}, now={now.strftime('%H:%M')}, "
                f"is_past={is_past}"
            )

        return is_past

    except Exception as e:
        logger.warning(f"⚠️  Could not parse timestamp {hour_local}: {e}")
        return False


def is_current_or_future_slot(
    hour_local: str, slot_date: date, resolution_minutes: int = 60
) -> bool:
    """Check if a slot is active or future."""
    return not is_past_slot(hour_local, slot_date, resolution_minutes)


def detect_resolution(slots: List[Dict]) -> int:
    """
    Detect the resolution of the slots (in minutes).

    Returns:
        60 for PT60M (hourly)
        15 for PT15M (15-minute)
    """
    if not slots or len(slots) < 2:
        return 60

    # Check resolution field if present
    if "resolution" in slots[0]:
        res_text = slots[0]["resolution"].upper()
        if "PT15M" in res_text:
            return 15
        elif "PT60M" in res_text or "PT1H" in res_text:
            return 60

    # Fallback: calculate from time between first two slots
    try:
        t1 = datetime.strptime(slots[0]["hour_local"], "%Y-%m-%d %H:%M")
        t2 = datetime.strptime(slots[1]["hour_local"], "%Y-%m-%d %H:%M")
        diff_min = int((t2 - t1).total_seconds() / 60)

        if diff_min == 15:
            return 15
        elif diff_min == 60:
            return 60
    except Exception:
        pass

    return 60


def format_time_range(start: str, end: str, resolution_minutes: int = 60) -> str:
    """
    Format time range based on resolution.

    Args:
        start: Start time string "YYYY-MM-DD HH:MM"
        end: Start time of LAST slot "YYYY-MM-DD HH:MM"
        resolution_minutes: Resolution in minutes (60 or 15)

    Returns:
        Formatted string "HH:MM - HH:MM"
    """
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M")

        # IMPORTANT: end is the START of the last slot
        # So we need to ADD resolution_minutes for the real end time
        final_dt = end_dt + timedelta(minutes=resolution_minutes)

        if LOG_LEVEL == "DEBUG":
            logger.debug(
                f"      format_time_range: {start.split()[1]} -> {start_dt.strftime('%H:%M')}, "
                f"{end.split()[1]} + {resolution_minutes}min -> {final_dt.strftime('%H:%M')}"
            )

        return f"{start_dt.strftime('%H:%M')} - {final_dt.strftime('%H:%M')}"

    except Exception as e:
        logger.warning(f"⚠️  Could not format time range: {e}")
        return "Unknown"


def calculate_total_duration(positions: List[int], resolution_minutes: int = 60) -> int:
    """
    Calculate total duration in minutes of a group of positions.

    Args:
        positions: List of position numbers
        resolution_minutes: Resolution in minutes (60 or 15)

    Returns:
        Total duration in minutes
    """
    if not positions:
        return 0
    return len(positions) * resolution_minutes


def get_day_label(target_date: date) -> str:
    """Determine English label based on date."""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    if target_date == today:
        return "Today"
    elif target_date == tomorrow:
        return "Tomorrow"
    else:
        days_en = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        months_en = [
            "",
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]

        day_name = days_en[target_date.weekday()]
        month_name = months_en[target_date.month]

        return f"{day_name} {target_date.day} {month_name}"


# ============================================================================
# GROUPING & PROCESSING
# ============================================================================


def group_consecutive_slots(
    slots: List[Dict],
    max_gap_minutes: int = 30,
    max_price_gap_ct: float = 2.0,
    resolution_minutes: int = 60,
) -> List[Dict]:
    """
    Group consecutive slots with small gaps AND comparable prices.

    Supports both PT60M (hourly) and PT15M (15-minute) resolution.

    Args:
        slots: List of slot dictionaries
        max_gap_minutes: Maximum time gap between slots
        max_price_gap_ct: Maximum price difference within a group (ct/kWh)
        resolution_minutes: Resolution in minutes (60 or 15)

    Returns:
        Groups sorted by average price (cheapest first).
    """
    if not slots:
        return []

    logger.debug(
        f"Grouping {len(slots)} slots with max_gap={max_gap_minutes}min, "
        f"max_price_gap={max_price_gap_ct}ct"
    )

    # Sort by position
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

        # Calculate time difference based on resolution
        position_diff = curr["position"] - prev["position"]
        time_gap_minutes = position_diff * resolution_minutes

        # Calculate potential new min/max prices
        potential_min = min(current_group["min_price"], curr["ct_per_kwh"])
        potential_max = max(current_group["max_price"], curr["ct_per_kwh"])
        potential_price_gap = potential_max - potential_min

        # Check both conditions
        can_merge = (
            time_gap_minutes <= max_gap_minutes + resolution_minutes
            and potential_price_gap <= max_price_gap_ct
        )

        if can_merge:
            # Add to current group
            current_group["end"] = curr["hour_local"]
            current_group["slots"].append(curr)
            current_group["positions"].append(curr["position"])
            current_group["min_price"] = potential_min
            current_group["max_price"] = potential_max
        else:
            # Save current group and start new one
            groups.append(current_group)
            logger.debug(
                f"Group completed: {current_group['start'].split()[1]} to "
                f"{current_group['end'].split()[1]} ({len(current_group['slots'])} slots)"
            )
            current_group = {
                "start": curr["hour_local"],
                "end": curr["hour_local"],
                "slots": [curr],
                "positions": [curr["position"]],
                "min_price": curr["ct_per_kwh"],
                "max_price": curr["ct_per_kwh"],
            }

    # Add last group
    groups.append(current_group)
    logger.debug(
        f"Group completed: {current_group['start'].split()[1]} to "
        f"{current_group['end'].split()[1]} ({len(current_group['slots'])} slots)"
    )

    # Calculate average price per group
    for group in groups:
        avg_price = sum(s["ct_per_kwh"] for s in group["slots"]) / len(group["slots"])
        group["avg_price"] = avg_price

    # Sort by average price (cheapest first)
    sorted_groups = sorted(groups, key=lambda g: g["avg_price"])
    logger.info(f"Created {len(sorted_groups)} price blocks from {len(slots)} slots")

    # DEBUG: Log the first few blocks
    if LOG_LEVEL == "DEBUG":
        for i, block in enumerate(sorted_groups[:5], 1):
            logger.debug(
                f"   Block {i}: start={block['start'].split()[1]}, "
                f"end={block['end'].split()[1]}, "
                f"slots={len(block['slots'])}, avg={block['avg_price']:.3f}ct"
            )

    return sorted_groups


def find_most_expensive_hour(
    all_slots: List[Dict], slot_date: date, resolution_minutes: int = 60
) -> Optional[Dict]:
    """
    Find the most expensive consecutive hour (or equivalent in 15-min slots).

    For PT60M: directly the most expensive slot
    For PT15M: find the most expensive consecutive block of 4 slots (= 60 min)

    Args:
        all_slots: All slots of the day
        slot_date: Date
        resolution_minutes: Resolution (60 or 15)

    Returns:
        Dictionary with most expensive hour info, or None
    """
    if not all_slots:
        return None

    logger.debug(f"Finding most expensive hour (resolution={resolution_minutes}min)")

    # Filter only future slots
    today = date.today()
    is_today = slot_date == today

    if is_today:
        future_slots = [
            s
            for s in all_slots
            if is_current_or_future_slot(s["hour_local"], slot_date, resolution_minutes)
        ]
        logger.debug(f"Filtering future slots: {len(all_slots)} -> {len(future_slots)}")
    else:
        future_slots = all_slots

    if not future_slots:
        logger.warning("No future slots available for expensive hour calculation")
        return None

    if resolution_minutes == 60:
        # PT60M: simply the most expensive slot
        most_expensive = max(future_slots, key=lambda s: s["ct_per_kwh"])

        return {
            "time_range": format_time_range(
                most_expensive["hour_local"],
                most_expensive["hour_local"],
                resolution_minutes,
            ),
            "duration_minutes": 60,
            "avg_price": round(most_expensive["ct_per_kwh"], 3),
            "min_price": round(most_expensive["ct_per_kwh"], 3),
            "max_price": round(most_expensive["ct_per_kwh"], 3),
            "slots": [most_expensive],
        }

    else:
        # PT15M: find most expensive consecutive 60 minutes (4 slots)
        sorted_slots = sorted(future_slots, key=lambda s: s["position"])

        window_size = 4
        max_avg = -float("inf")
        best_window = None

        for i in range(len(sorted_slots) - window_size + 1):
            window = sorted_slots[i : i + window_size]

            # Check if slots are consecutive
            is_consecutive = True
            for j in range(len(window) - 1):
                if window[j + 1]["position"] - window[j]["position"] > 1:
                    is_consecutive = False
                    break

            if is_consecutive:
                avg_price = sum(s["ct_per_kwh"] for s in window) / len(window)
                if avg_price > max_avg:
                    max_avg = avg_price
                    best_window = window

        if best_window:
            prices = [s["ct_per_kwh"] for s in best_window]
            return {
                "time_range": format_time_range(
                    best_window[0]["hour_local"],
                    best_window[-1]["hour_local"],
                    resolution_minutes,
                ),
                "duration_minutes": 60,
                "avg_price": round(sum(prices) / len(prices), 3),
                "min_price": round(min(prices), 3),
                "max_price": round(max(prices), 3),
                "slots": best_window,
            }
        else:
            # Fallback: simply the most expensive single slot
            most_expensive = max(future_slots, key=lambda s: s["ct_per_kwh"])
            return {
                "time_range": format_time_range(
                    most_expensive["hour_local"],
                    most_expensive["hour_local"],
                    resolution_minutes,
                ),
                "duration_minutes": 15,
                "avg_price": round(most_expensive["ct_per_kwh"], 3),
                "min_price": round(most_expensive["ct_per_kwh"], 3),
                "max_price": round(most_expensive["ct_per_kwh"], 3),
                "slots": [most_expensive],
            }


def process_day_data(
    day_data: Dict,
    slot_date: date,
    max_blocks: int = 6,
    max_time_gap_minutes: int = 60,
    max_price_gap_ct: float = 2.0,
) -> Dict:
    """
    Process data voor één dag - SIMPEL gesorteerd op prijs.

    Strategie:
    1. Groepeer alle goedkope slots in blokken
    2. Sorteer op gemiddelde prijs (goedkoopste eerst)
    3. Neem top max_blocks
    4. Rank 1 = goedkoopste (🥇), rank 2 = 🥈, rank 3 = 🥉, etc.
    5. Voeg "avoid" slot toe voor duurste uur
    6. KLAAR!

    Args:
        day_data: Dictionary met cheapest_slots, all_slots en average_ct_per_kwh
        slot_date: Datum van de slots
        max_blocks: Gewenst aantal tijdsblokken
        max_time_gap_minutes: Max tijd tussen slots in een blok
        max_price_gap_ct: Initiele max prijsverschil binnen een blok (ct/kWh)

    Returns:
        Processed data met time_blocks en avoid_slot
    """
    all_slots = day_data.get("cheapest_slots", [])
    all_day_slots = day_data.get("all_slots", [])
    avg_price = day_data.get("average_ct_per_kwh", 0)

    logger.info(f"🔄 Processing {len(all_slots)} slots for {slot_date.isoformat()}")

    if not all_slots:
        logger.warning(f"⚠️  No slots available for {slot_date.isoformat()}")
        return {
            "date": slot_date.isoformat(),
            "average_ct_per_kwh": round(avg_price, 3),
            "time_blocks": [],
            "future_blocks_count": 0,
            "total_blocks_count": 0,
            "resolution_minutes": 60,
            "avoid_slot": None,
        }

    # Detecteer resolutie
    resolution_minutes = detect_resolution(all_slots)
    logger.info(f"📊 Detected resolution: {resolution_minutes} minutes")

    today = date.today()
    is_today = slot_date == today

    # STAP 1: Filter nachtelijke slots (00:00-06:00) alleen voor vandaag
    filtered_slots = all_slots
    if is_today:
        filtered_slots = [
            slot for slot in all_slots if belongs_to_today(slot["hour_local"])
        ]
        logger.debug(
            f"🌙 Filtered night slots: {len(all_slots)} -> {len(filtered_slots)} slots"
        )

    # STAP 2: Probeer eerst met de gevraagde max_price_gap
    current_price_gap = max_price_gap_ct
    grouped_slots = []
    fallback_applied = False

    grouped_slots = group_consecutive_slots(
        filtered_slots,
        max_gap_minutes=max_time_gap_minutes,
        max_price_gap_ct=current_price_gap,
        resolution_minutes=resolution_minutes,
    )

    logger.info(
        f"📦 Initial grouping: {len(grouped_slots)} blocks with "
        f"price_gap={current_price_gap:.2f}ct"
    )

    # STAP 3: Als we te weinig blokken hebben, VERKLEIN price_gap stapsgewijs
    if len(grouped_slots) < max_blocks:
        fallback_applied = True
        logger.warning(
            f"⚠️  Fallback activated: got {len(grouped_slots)} blocks, need {max_blocks}"
        )

        # Probeer met halve price gap
        current_price_gap = max_price_gap_ct * 0.5
        logger.debug(f"🔄 Retry with price_gap={current_price_gap:.2f}ct")
        grouped_slots = group_consecutive_slots(
            filtered_slots,
            max_gap_minutes=max_time_gap_minutes,
            max_price_gap_ct=current_price_gap,
            resolution_minutes=resolution_minutes,
        )
        logger.info(f"📦 After retry: {len(grouped_slots)} blocks")

        # Als nog steeds te weinig, verklein verder
        if len(grouped_slots) < max_blocks and current_price_gap > 0.3:
            current_price_gap = max(0.3, max_price_gap_ct * 0.25)
            logger.debug(f"🔄 Further reducing to price_gap={current_price_gap:.2f}ct")
            grouped_slots = group_consecutive_slots(
                filtered_slots,
                max_gap_minutes=max_time_gap_minutes,
                max_price_gap_ct=current_price_gap,
                resolution_minutes=resolution_minutes,
            )
            logger.info(f"📦 Final attempt: {len(grouped_slots)} blocks")

    # STAP 4: Sorteer op prijs en neem top max_blocks
    selected_blocks = grouped_slots[:max_blocks]
    if selected_blocks:
        logger.info(
            f"✅ Selected top {len(selected_blocks)} blocks "
            f"(cheapest: {selected_blocks[0]['avg_price']:.3f}ct)"
        )
    else:
        logger.warning("⚠️ No blocks selected - empty grouped_slots")

    # STAP 5: Converteer naar timeblocks met correcte "verstreken" detectie
    time_blocks = []
    # GEBRUIK NEDERLANDSE TIJD!
    now = datetime.now(NL_TZ)
    logger.info(f"🕐 Current time: {now.strftime('%Y-%m-%d %H:%M:%S')} (NL)")

    for rank, group in enumerate(selected_blocks, start=1):
        prices = [s["ct_per_kwh"] for s in group["slots"]]
        avg = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price

        # Bereken standaarddeviatie
        std_dev = calculate_std_dev(prices)

        # BELANGRIJKSTE DEEL: Check of blok verstreken is
        last_slot = group["slots"][-1]
        first_slot = group["slots"][0]
        is_future = True  # Default: toekomstig

        try:
            # Parse laatste slot tijd
            last_slot_time = datetime.strptime(
                last_slot["hour_local"], "%Y-%m-%d %H:%M"
            )
            # Maak timezone-aware met NEDERLANDSE TIJD
            last_slot_time = NL_TZ.localize(last_slot_time)

            # Bereken wanneer het laatste slot eindigt
            last_slot_end = last_slot_time + timedelta(minutes=resolution_minutes)

            # Blok is verstreken als huidige tijd VOORBIJ de eindtijd is
            is_past_block = now > last_slot_end
            is_future = not is_past_block

            # UITGEBREIDE DEBUG LOGGING
            if LOG_LEVEL == "DEBUG":
                time_range_display = format_time_range(
                    group["start"], group["end"], resolution_minutes
                )
                logger.debug(
                    f"   🔍 Block {rank} analysis:\n"
                    f"      Time range: {time_range_display}\n"
                    f"      First slot: {first_slot['hour_local']}\n"
                    f"      Last slot:  {last_slot['hour_local']}\n"
                    f"      Last slot end: {last_slot_end.strftime('%Y-%m-%d %H:%M')}\n"
                    f"      Current time:  {now.strftime('%Y-%m-%d %H:%M')}\n"
                    f"      Comparison: {now.strftime('%H:%M')} > "
                    f"{last_slot_end.strftime('%H:%M')} = {is_past_block}\n"
                    f"      ➜ is_past={is_past_block}, is_future={is_future}"
                )

        except Exception as e:
            logger.error(
                f"❌ Could not determine if block {rank} is past: {e}", exc_info=True
            )
            is_future = True

        # Bereken display time_range
        time_range = format_time_range(group["start"], group["end"], resolution_minutes)

        # Status emoji voor logging
        status_emoji = "⏭️" if is_future else "✅"
        logger.info(
            f"{status_emoji} Rank {rank}: {time_range} @ {avg:.3f}ct (is_future={is_future})"
        )

        block_data = {
            "rank": rank,
            "rank_icon": get_rank_icon(rank),
            "time_range": time_range,
            "duration_minutes": calculate_total_duration(
                group["positions"], resolution_minutes
            ),
            "actual_slot_count": len(group["slots"]),
            "avg_price": round(avg, 3),
            "min_price": round(min_price, 3),
            "max_price": round(max_price, 3),
            "price_variance": round(price_range, 3),
            "is_best": avg < avg_price * 0.85,
            "is_future": is_future,
            "individual_slots": [
                {
                    "time": s["hour_local"].split(" ")[1],
                    "price": round(s["ct_per_kwh"], 3),
                    "is_past": is_past_slot(
                        s["hour_local"], slot_date, resolution_minutes
                    ),
                }
                for s in group["slots"]
            ],
        }

        # Voeg standaarddeviatie toe ALLEEN als statistisch relevant
        if is_std_dev_relevant(std_dev, price_range, len(prices)):
            block_data["price_std_dev"] = round(std_dev, 3)
            if LOG_LEVEL == "DEBUG":
                logger.debug(f"      σ={std_dev:.3f}ct (relevant)")

        time_blocks.append(block_data)

    # STAP 6: Vind duurste uur voor "avoid" slot
    avoid_slot = None
    if all_day_slots:
        logger.info("🔍 Finding most expensive hour...")
        expensive_hour = find_most_expensive_hour(
            all_day_slots, slot_date, resolution_minutes
        )
        if expensive_hour:
            # Check of dit uur toekomstig is
            try:
                # Parse laatste slot van het duurste blok
                last_expensive = expensive_hour["slots"][-1]
                last_time = datetime.strptime(
                    last_expensive["hour_local"], "%Y-%m-%d %H:%M"
                )
                # NEDERLANDSE TIJD
                last_time = NL_TZ.localize(last_time)
                last_end = last_time + timedelta(minutes=resolution_minutes)

                is_future_avoid = now <= last_end

                if LOG_LEVEL == "DEBUG":
                    logger.debug(
                        f"   🔍 Expensive hour analysis:\n"
                        f"      Time: {expensive_hour['time_range']}\n"
                        f"      Last slot end: {last_end.strftime('%H:%M')}\n"
                        f"      Current: {now.strftime('%H:%M')}\n"
                        f"      is_future: {is_future_avoid}"
                    )

            except Exception as e:
                logger.warning(f"⚠️  Could not parse expensive hour time: {e}")
                is_future_avoid = True

            avoid_slot = {
                "time_range": expensive_hour["time_range"],
                "duration_minutes": expensive_hour["duration_minutes"],
                "avg_price": expensive_hour["avg_price"],
                "min_price": expensive_hour["min_price"],
                "max_price": expensive_hour["max_price"],
                "price_variance": round(
                    expensive_hour["max_price"] - expensive_hour["min_price"], 3
                ),
                "is_future": is_future_avoid,
                "individual_slots": [
                    {
                        "time": s["hour_local"].split(" ")[1],
                        "price": round(s["ct_per_kwh"], 3),
                        "is_past": is_past_slot(
                            s["hour_local"], slot_date, resolution_minutes
                        ),
                    }
                    for s in expensive_hour["slots"]
                ],
            }
            logger.info(
                f"⚠️  Most expensive hour: {avoid_slot['time_range']} "
                f"@ {avoid_slot['avg_price']:.3f}ct (is_future={is_future_avoid})"
            )

    # Tel toekomstige blokken
    future_count = sum(1 for b in time_blocks if b["is_future"])
    logger.info(
        f"📊 Summary: {len(time_blocks)} blocks total, "
        f"{future_count} future, {len(time_blocks) - future_count} past"
    )

    result = {
        "date": slot_date.isoformat(),
        "average_ct_per_kwh": round(avg_price, 3),
        "time_blocks": time_blocks,
        "avoid_slot": avoid_slot,
        "future_blocks_count": future_count,
        "total_blocks_count": len(time_blocks),
        "resolution_minutes": resolution_minutes,
    }

    # Voeg fallback info toe indien gebruikt
    if fallback_applied:
        result["fallback_info"] = {
            "applied": True,
            "original_price_gap": round(max_price_gap_ct, 2),
            "adjusted_price_gap": round(current_price_gap, 2),
            "reason": (
                f"Auto-verkleind van {max_price_gap_ct:.2f} naar "
                f"{current_price_gap:.2f} om {max_blocks} blokken te krijgen"
            ),
        }
        logger.info(
            f"ℹ️  Fallback applied: {max_price_gap_ct:.2f}ct → {current_price_gap:.2f}ct"
        )

    return result


# ============================================================================
# ROUTES
# ============================================================================


@app.get("/", tags=["meta"], summary="Service Info")
def root():
    """Root endpoint met API info."""
    logger.info("GET / - Service info requested")
    return {
        "service": "ENTSO‑E Home Automation API",
        "version": "2.9.0",
        "timezone": DEFAULT_TIMEZONE,
        "features": [
            "Supports PT60M (hourly) and PT15M (15-minute) resolution",
            "Uses Dutch timezone (Europe/Amsterdam) for all calculations",
            "Smart price-aware grouping with automatic fallback",
            "Rank 1 = cheapest block (🥇), rank 2 = 🥈, rank 3 = 🥉, etc.",
            "Statistical standard deviation (σ) when relevant",
            "Auto-adjusts price gap when too few blocks found",
            "Simple price-based ranking",
            "Avoid slot: most expensive hour to avoid",
            "Request metadata in all responses",
            "Configurable logging (INFO/DEBUG)",
            "Dutch language labels",
        ],
        "docs": "/docs",
        "endpoints": {
            "prices_basic": "/energy/prices/cheapest-basic",
            "prices_advanced": "/energy/prices/cheapest-advanced",
            "dayahead": "/energy/prices/dayahead",
            "health": "/system/health",
        },
        "route_recommendations": {
            "simple_use_cases": "Use /energy/prices/cheapest-basic for simple home automation",
            "advanced_use_cases": "Use /energy/prices/cheapest-advanced for complex scenarios",
        },
        "log_level": LOG_LEVEL,
    }


@app.get("/system/health", tags=["system"], summary="Health check")
def system_health():
    """Health check endpoint."""
    try:
        logger.debug("GET /system/health - Health check")
        key_ok = bool(os.getenv("ENTSOE_API_KEY"))

        result = {
            "status": "ok",
            "entsoe_api_key_loaded": key_ok,
            "time_zone": DEFAULT_TIMEZONE,
            "current_time_nl": datetime.now(NL_TZ).isoformat(),
            "log_level": LOG_LEVEL,
        }

        logger.info(f"Health check: API key={'OK' if key_ok else 'MISSING'}")
        return result

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
    start_time = datetime.now(NL_TZ)

    try:
        # Parse datum (default: morgen)
        if date_str:
            target_date = validate_date_string(date_str)
        else:
            target_date = date.today() + timedelta(days=1)

        logger.info(
            f"GET /energy/prices/dayahead - date={target_date.isoformat()}, zone={zone}"
        )

        print(target_date)

        rows = entsoe.get_day_ahead_prices(target_date, zone)

        # Detecteer resolutie
        resolution = detect_resolution(rows) if rows else 60

        execution_time = (datetime.now(NL_TZ) - start_time).total_seconds() * 1000
        logger.info(
            f"Fetched {len(rows)} price slots ({resolution}min resolution) "
            f"in {execution_time:.2f}ms"
        )
        result = {
            "date": target_date.isoformat(),
            "zone": zone,
            "prices": rows,
            "total_slots": len(rows),
            "resolution_minutes": resolution,
            "metadata": create_metadata(
                "energy/prices/dayahead",
                {"date": target_date.isoformat(), "zone": zone},
                execution_time,
            ),
        }

        print(result)
        return result

    except Exception as e:
        return error_response(e)


@app.get(
    "/energy/prices/cheapest-basic",
    tags=["energy"],
    summary="Simple cheapest hours (basic home automation)",
    description=(
        "Simple route for basic home automation:\n\n"
        "**Functionality:**\n"
        "- Returns the N cheapest hours of the day\n"
        "- Optional: consecutive hours only\n"
        "- Simple price-based sorting\n"
        "- Fast response, minimal overhead\n"
        "- **Uses Dutch time (Europe/Amsterdam)**\n"
        "- Automatic detection of PT60M (hourly) or PT15M (15-min) resolution\n"
        "- Marks past vs future hours\n\n"
        "**Perfect for:**\n"
        "- Simple charging schedules\n"
        "- Basic smart devices\n"
        "- Quick integrations\n"
        "- When you don't need complex grouping\n\n"
        "**Parameters:**\n"
        "- `hours`: Number of cheapest hours (1-24, default: 4)\n"
        "- `consecutive`: Consecutive hours only (default: false)\n"
        "- `date`: Date YYYY-MM-DD (default: today)\n"
        "- `zone`: EIC code area (default: Netherlands)"
    ),
)
def energy_prices_cheapest_basic(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Date YYYY-MM-DD (default: today)",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code area"),
    hours: int = Query(4, ge=1, le=24, description="Number of cheapest hours (1-24)"),
    consecutive: bool = Query(False, description="Consecutive hours only"),
):
    """Simple cheapest hours for basic home automation."""
    start_time = datetime.now(NL_TZ)

    try:
        # Parse datum (default: vandaag)
        if date_str:
            target_date = validate_date_string(date_str)
        else:
            target_date = date.today()

        logger.info(
            f"GET /energy/prices/cheapest-basic - date={target_date.isoformat()}, "
            f"zone={zone}, hours={hours}, consecutive={consecutive}"
        )

        # Haal alle prijsdata op
        all_prices = entsoe.get_day_ahead_prices(target_date, zone)

        if not all_prices:
            raise EntsoeServerError(
                f"Geen prijsdata beschikbaar voor {target_date.isoformat()}", status=404
            )

        logger.debug(f"Fetched {len(all_prices)} total price slots")

        # Detecteer resolutie
        resolution_minutes = detect_resolution(all_prices)

        # Filter nachtelijke slots voor vandaag
        today = date.today()
        is_today = target_date == today

        if is_today:
            filtered_slots = [
                slot for slot in all_prices if belongs_to_today(slot["hour_local"])
            ]
            logger.debug(
                f"Filtered night slots: {len(all_prices)} -> {len(filtered_slots)}"
            )
        else:
            filtered_slots = all_prices

        if consecutive:
            # Vind beste aaneengesloten blok
            sorted_slots = sorted(filtered_slots, key=lambda s: s["position"])

            best_avg = float("inf")
            best_block = []

            for i in range(len(sorted_slots) - hours + 1):
                block = sorted_slots[i : i + hours]

                # Check of slots aaneengesloten zijn
                is_consecutive_block = True
                for j in range(len(block) - 1):
                    if block[j + 1]["position"] - block[j]["position"] > 1:
                        is_consecutive_block = False
                        break

                if is_consecutive_block:
                    avg_price = sum(s["ct_per_kwh"] for s in block) / len(block)
                    if avg_price < best_avg:
                        best_avg = avg_price
                        best_block = block

            if best_block:
                cheapest_hours = best_block
            else:
                # Fallback: gewoon de goedkoopste uren
                cheapest_hours = sorted(filtered_slots, key=lambda s: s["ct_per_kwh"])[
                    :hours
                ]
                logger.warning(
                    "No consecutive block found, using cheapest individual hours"
                )
        else:
            # Gewoon de goedkoopste uren
            cheapest_hours = sorted(filtered_slots, key=lambda s: s["ct_per_kwh"])[
                :hours
            ]

        # Sorteer op tijd voor output
        cheapest_hours = sorted(cheapest_hours, key=lambda s: s["position"])

        # Bereken statistieken
        prices = [h["ct_per_kwh"] for h in cheapest_hours]
        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)

        # Bereken overall dag gemiddelde
        day_avg = sum(s["ct_per_kwh"] for s in all_prices) / len(all_prices)

        # Converteer naar output format
        result_hours = []
        for hour in cheapest_hours:
            is_past = is_past_slot(hour["hour_local"], target_date, resolution_minutes)

            result_hours.append(
                {
                    "time": hour["hour_local"].split(" ")[1],  # Alleen tijd deel
                    "time_range": format_time_range(
                        hour["hour_local"], hour["hour_local"], resolution_minutes
                    ),
                    "price_ct_per_kwh": round(hour["ct_per_kwh"], 3),
                    "is_past": is_past,
                    "is_future": not is_past,
                    "position": hour["position"],
                }
            )

        execution_time = (datetime.now(NL_TZ) - start_time).total_seconds() * 1000

        result = {
            "date": target_date.isoformat(),
            "label": get_day_label(target_date),
            "zone": zone,
            "hours_requested": hours,
            "consecutive_required": consecutive,
            "hours_found": len(result_hours),
            "resolution_minutes": resolution_minutes,
            "cheapest_hours": result_hours,
            "statistics": {
                "avg_price_ct_per_kwh": round(avg_price, 3),
                "min_price_ct_per_kwh": round(min_price, 3),
                "max_price_ct_per_kwh": round(max_price, 3),
                "price_range_ct_per_kwh": round(max_price - min_price, 3),
                "day_average_ct_per_kwh": round(day_avg, 3),
                "savings_vs_day_avg": round(day_avg - avg_price, 3),
            },
            "future_hours_count": sum(1 for h in result_hours if h["is_future"]),
            "generated_at": datetime.now(NL_TZ).isoformat(),
            "metadata": create_metadata(
                "energy/prices/cheapest-basic",
                {
                    "date": target_date.isoformat(),
                    "zone": zone,
                    "hours": hours,
                    "consecutive": consecutive,
                },
                execution_time,
            ),
        }

        logger.info(
            f"Found {len(result_hours)} cheapest hours in {execution_time:.2f}ms"
        )
        return result

    except Exception as e:
        return error_response(e)


@app.get(
    "/energy/prices/cheapest-advanced",
    tags=["energy"],
    summary="Advanced time blocks + most expensive hour to avoid",
    description=(
        "Advanced intelligent time blocks for complex home automation:\n\n"
        "**Ranking:**\n"
        "- Rank 1 🥇 = Cheapest block of the day\n"
        "- Rank 2 🥈 = Second cheapest\n"
        "- Rank 3 🥉 = Third cheapest\n"
        "- Rank 4-12 = 4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟...\n"
        "- **avoid_slot** ⚠️ = Most expensive hour to avoid\n\n"
        "**Advanced Features:**\n"
        "- Analyzes all hours of the day\n"
        "- **Uses Dutch time (Europe/Amsterdam)** for all calculations\n"
        "- Automatic detection of PT60M (hourly) or PT15M (15-min) resolution\n"
        "- Groups consecutive slots with comparable prices\n"
        "- **Standard deviation (σ)**: shows price spread within block (only when statistically relevant)\n"
        "- **Avoid slot**: most expensive consecutive hour (for PT15M: 4 slots = 60 min)\n"
        "- **Smart fallback**: automatically reduces max_price_gap when too few blocks found\n"
        "- Filters night slots (00:00-06:00) for today\n"
        "- Marks past vs future slots\n"
        "- Perfect for complex charging schedules and advanced smart devices\n\n"
        "**Parameters:**\n"
        "- `max_blocks`: Desired number of time blocks (1-12)\n"
        "- `max_time_gap`: Max minutes between slots in one block (15-180)\n"
        "- `max_price_gap`: **Maximum** price difference (ct/kWh) within one block (0.3-10.0)\n"
        "- `price_threshold_pct`: Analyze only slots below this percentile (10-100)\n\n"
        "**Logging:**\n"
        "- Set LOG_LEVEL=DEBUG for detailed execution logs\n"
        "- Set LOG_LEVEL=INFO for summary logs (default)"
    ),
)
def energy_prices_cheapest_advanced(
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Datum YYYY-MM-DD (default: vandaag)",
    ),
    zone: Optional[str] = Query(DEFAULT_ZONE, description="EIC code gebied"),
    max_blocks: int = Query(
        6, ge=1, le=12, description="Gewenst aantal tijdsblokken (1-12)"
    ),
    max_time_gap: int = Query(
        60, ge=15, le=180, description="Max minuten tussen slots in één blok (15-180)"
    ),
    max_price_gap: float = Query(
        1.5,
        ge=0.3,
        le=10.0,
        description="Maximale prijsverschil (ct/kWh) binnen blok (0.3-10.0)",
    ),
    price_threshold_pct: int = Query(
        50,
        ge=10,
        le=100,
        description="Analyseer alleen slots onder dit percentiel (10-100)",
    ),
):
    """Smart cheapest hours + most expensive hour to avoid."""
    start_time = datetime.now(NL_TZ)

    try:
        # Parse datum (default: vandaag)
        if date_str:
            target_date = validate_date_string(date_str)
        else:
            target_date = date.today()

        logger.info(
            f"GET /energy/prices/cheapest - date={target_date.isoformat()}, "
            f"zone={zone}, max_blocks={max_blocks}, "
            f"max_time_gap={max_time_gap}, max_price_gap={max_price_gap}, "
            f"threshold={price_threshold_pct}%"
        )

        # Haal ALLE prijsdata op voor de dag
        all_prices = entsoe.get_day_ahead_prices(target_date, zone)

        if not all_prices:
            raise EntsoeServerError(
                f"Geen prijsdata beschikbaar voor {target_date.isoformat()}", status=404
            )

        logger.debug(f"Fetched {len(all_prices)} total price slots")

        # Bereken gemiddelde en threshold
        avg = sum(r["ct_per_kwh"] for r in all_prices) / len(all_prices)

        # Sorteer prijzen en neem het juiste percentiel
        sorted_prices = sorted([r["ct_per_kwh"] for r in all_prices])
        threshold_index = int(len(sorted_prices) * (price_threshold_pct / 100.0))
        price_threshold = sorted_prices[min(threshold_index, len(sorted_prices) - 1)]

        logger.debug(
            f"Average price: {avg:.3f}ct, "
            f"threshold ({price_threshold_pct}%): {price_threshold:.3f}ct"
        )

        # Filter slots onder de threshold
        cheapest = [r for r in all_prices if r["ct_per_kwh"] <= price_threshold]

        # Als we te weinig slots hebben, neem de goedkoopste helft
        if len(cheapest) < 3:
            logger.warning(
                f"Only {len(cheapest)} slots below threshold, using top 50% instead"
            )
            cheapest = sorted(all_prices, key=lambda r: r["ct_per_kwh"])[
                : len(all_prices) // 2
            ]
            price_threshold = cheapest[-1]["ct_per_kwh"] if cheapest else 0

        logger.info(
            f"Analyzing {len(cheapest)} cheapest slots "
            f"(threshold: {price_threshold:.3f}ct)"
        )

        # Process data - inclusief alle slots voor "avoid" berekening
        day_data = {
            "cheapest_slots": cheapest,
            "all_slots": all_prices,  # Voor duurste uur
            "average_ct_per_kwh": avg,
        }

        processed = process_day_data(
            day_data,
            target_date,
            max_blocks=max_blocks,
            max_time_gap_minutes=max_time_gap,
            max_price_gap_ct=max_price_gap,
        )

        execution_time = (datetime.now(NL_TZ) - start_time).total_seconds() * 1000

        # Voeg metadata toe
        processed["label"] = get_day_label(target_date)
        processed["generated_at"] = datetime.now(NL_TZ).isoformat()
        processed["zone"] = zone
        processed["price_threshold_ct_per_kwh"] = round(price_threshold, 3)
        processed["config"] = {
            "max_time_gap_minutes": max_time_gap,
            "max_price_gap_ct": max_price_gap,
            "price_threshold_pct": price_threshold_pct,
            "analyzed_slots_count": len(cheapest),
            "total_slots_in_day": len(all_prices),
        }
        processed["metadata"] = create_metadata(
            "energy/prices/cheapest",
            {
                "date": target_date.isoformat(),
                "zone": zone,
                "max_blocks": max_blocks,
                "max_time_gap": max_time_gap,
                "max_price_gap": max_price_gap,
                "price_threshold_pct": price_threshold_pct,
            },
            execution_time,
        )

        logger.info(f"Completed in {execution_time:.2f}ms")

        return processed

    except Exception as e:
        return error_response(e)


# ============================================================================
# RUN SERVER
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting server on {host}:{port} (timezone: {DEFAULT_TIMEZONE})")

    uvicorn.run(app, host=host, port=port, log_level=LOG_LEVEL.lower(), access_log=True)
