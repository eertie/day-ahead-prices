#!/usr/bin/env python3
"""
ha_entsoe.py
Robuuste ENTSO-E integratie met:
- Consistente foutafhandeling (gestructureerde JSON in CLI en te gebruiken door API)
- Retry met capped exponential backoff + jitter
- Bestandscache én optioneel bewaren van ruwe XML-responses onder DATA_ROOT/YYYY/MM/
- Duidelijke .env configuratie met veilige defaults

"""

import os
import sys
import json
import time
import math
import random
import signal
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Iterable
from datetime import datetime, date, timedelta
from xml.etree import ElementTree as ET

import requests
from dateutil import tz

# .env laden
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Helpers om env waarden te lezen
def getenv_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v.strip() if v and v.strip() else default


def getenv_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        logging.warning(f"Invalid int for {name}={v!r}, using default {default}")
        return default


def getenv_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return float(v)
    except Exception:
        logging.warning(f"Invalid float for {name}={v!r}, using default {default}")
        return default


# Basisconfig
API_ENDPOINT = "https://web-api.tp.entsoe.eu/api"

ZONE_EIC_DEFAULT = getenv_str("ZONE_EIC", "10YNL----------L")
TIME_ZONE_NAME = getenv_str("TIME_ZONE", "Europe/Amsterdam")
TZ_LOCAL = tz.gettz(TIME_ZONE_NAME)

MAX_RETRIES = getenv_int("MAX_RETRIES", 4)
BACKOFF_BASE = getenv_float("BACKOFF_BASE", 1.7)
BACKOFF_CAP_SECONDS = getenv_float("BACKOFF_CAP_SECONDS", 30.0)

# Cache
CACHE_DIR = Path(getenv_str("CACHE_DIR", "./cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Ruwe data opslag
DATA_ROOT = Path(getenv_str("DATA_ROOT", "./data")).resolve()
SAVE_RAW = getenv_str("SAVE_RAW", "1").lower() not in ("0", "false", "no", "")

try:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
except Exception:
    # Niet fataal, we loggen alleen als wegschrijven faalt
    pass

# TTLs
TTL_PRICES_DEFAULT = getenv_int("TTL_PRICES", 24 * 3600)
TTL_LOAD_DA_DEFAULT = getenv_int("TTL_LOAD_DA", 24 * 3600)
TTL_LOAD_ACT_DEFAULT = getenv_int("TTL_LOAD_ACT", 900)
TTL_GEN_DEFAULT = getenv_int("TTL_GEN", 3 * 3600)
TTL_NETPOS_DEFAULT = getenv_int("TTL_NETPOS", 3600)
TTL_EXCH_DEFAULT = getenv_int("TTL_EXCH", 3 * 3600)

# Run-loop en exchanges
TICK_SECONDS_DEFAULT = getenv_int("TICK_SECONDS", 5)
EXCH_FROM_EIC_DEFAULT = getenv_str("EXCH_FROM_EIC", ZONE_EIC_DEFAULT)
EXCH_TO_EIC_DEFAULT = getenv_str("EXCH_TO_EIC", "10YBE----------2")

# Document types
DOC_A44_PRICES = "A44"
DOC_A65_LOAD_DA = "A65"
DOC_A68_LOAD_ACT = "A68"
DOC_A69_GEN_FORECAST = "A69"
DOC_A01_SCHED_EXCH = "A01"
DOC_A75_NET_POSITION = "A75"


# Foutmodel
class EntsoeError(Exception):
    def __init__(
        self,
        message: str,
        status: int = 500,
        code: str = "CLIENT_ERROR",
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


class EntsoeUnauthorized(EntsoeError):
    def __init__(self, message="Unauthorized – check ENTSOE_API_KEY", details=None):
        super().__init__(message, status=401, code="UNAUTHORIZED", details=details)


class EntsoeForbidden(EntsoeError):
    def __init__(
        self, message="Forbidden – access denied for this resource", details=None
    ):
        super().__init__(message, status=403, code="FORBIDDEN", details=details)


class EntsoeNotFound(EntsoeError):
    def __init__(self, message="Resource not found", details=None):
        super().__init__(message, status=404, code="NOT_FOUND", details=details)


class EntsoeRateLimited(EntsoeError):
    def __init__(
        self, message="Too Many Requests – rate limited by ENTSO-E", details=None
    ):
        super().__init__(message, status=429, code="RATE_LIMITED", details=details)


class EntsoeServerError(EntsoeError):
    def __init__(self, message="ENTSO-E server error", status=502, details=None):
        super().__init__(message, status=status, code="SERVER_ERROR", details=details)


class EntsoeParseError(EntsoeError):
    def __init__(self, message="XML parse error", details=None):
        super().__init__(message, status=500, code="PARSE_ERROR", details=details)


# Helpers tijd/format
def require_api_key() -> str:
    token = os.getenv("ENTSOE_API_KEY")
    if not token or not token.strip():
        raise EntsoeUnauthorized(
            "ENTSOE_API_KEY missing. Put it in .env or environment."
        )
    return token.strip()


def dt_local(d: date, h: int = 0, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ_LOCAL)


def fmt_period(dt_: datetime) -> str:
    return dt_.strftime("%Y%m%d%H%M")


def local_span_day(d: date) -> Tuple[datetime, datetime]:
    return dt_local(d, 0, 0), dt_local(d, 23, 0)


def backoff_sleep(attempt: int):
    delay = min(BACKOFF_CAP_SECONDS, (BACKOFF_BASE**attempt))
    jitter = 0.1 * delay * random.random()
    time.sleep(delay + jitter)


def parse_xml(xml_text: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise EntsoeParseError(f"XML parse error: {e}")


def extract_entsoe_error(xml_text: str) -> Optional[str]:
    try:
        root = ET.fromstring(xml_text)
        msg = root.findtext(".//{*}text") or root.findtext(".//{*}Message")
        if msg:
            return msg.strip()
    except Exception:
        return None
    return None


def pick_timeseries(root: ET.Element) -> List[ET.Element]:
    ts = root.findall(".//{*}TimeSeries")
    if not ts:
        err = root.findtext(".//{*}text") or root.findtext(".//{*}Message")
        if err:
            raise EntsoeServerError(
                f"ENTSO-E error: {err}", status=502, details={"entsoe_message": err}
            )
        raise EntsoeServerError("No TimeSeries found.", status=502)
    return ts


def hour_from_position(d: date, pos: int) -> datetime:
    return dt_local(d, 0, 0) + timedelta(hours=pos - 1)


def safe_float(txt: Optional[str]) -> Optional[float]:
    if txt is None:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def ensure_ascending_positions(rows: List[Dict]) -> List[Dict]:
    rows.sort(key=lambda r: r["position"])
    return rows


# Opslag helpers (ruwe XML)
def _infer_date_from_params(params: dict) -> Optional[date]:
    ps = params.get("periodStart")
    if not ps or len(ps) < 8:
        return None
    try:
        return date(int(ps[0:4]), int(ps[4:6]), int(ps[6:8]))
    except Exception:
        return None


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)


def _data_file_path(params: dict, ext: str = "xml") -> Optional[Path]:
    d = _infer_date_from_params(params)
    if not d:
        return None
    doc = params.get("documentType") or "UNK"
    in_dom = params.get("in_Domain") or params.get("inBiddingZone_Domain") or ""
    out_dom = params.get("out_Domain") or params.get("outBiddingZone_Domain") or ""
    parts = [_safe_name(doc)]
    if in_dom and out_dom:
        parts += [_safe_name(in_dom), "to", _safe_name(out_dom)]
    else:
        zone = out_dom or in_dom or ""
        if zone:
            parts.append(_safe_name(zone))
    parts.append(d.isoformat())
    fname = "_".join([p for p in parts if p]) + f".{ext}"
    folder = DATA_ROOT / f"{d.year:04d}" / f"{d.month:02d}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return folder / fname


# HTTP wrapper (cache + opslag + robuuste fouten)
def request_entsoe(
    params: Dict, cache_key: Optional[str] = None, cache_ttl_s: Optional[int] = None
) -> str:
    # Cache lezen
    if cache_key and cache_ttl_s:
        cache_file = CACHE_DIR / f"{cache_key}.xml"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age <= cache_ttl_s:
                return cache_file.read_text(encoding="utf-8")

    token = require_api_key()
    params = dict(params)
    params["securityToken"] = token

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            READ_T = int(os.getenv("HTTP_READ_TIMEOUT", "45"))
            resp = requests.get(API_ENDPOINT, params=params, timeout=READ_T)
            status = resp.status_code

            if status == 200:
                text = resp.text
                # Cache schrijven
                if cache_key and cache_ttl_s:
                    try:
                        (CACHE_DIR / f"{cache_key}.xml").write_text(
                            text, encoding="utf-8"
                        )
                    except Exception as e:
                        logging.debug(f"Cache write skipped: {e}")
                # Ruwe opslag
                if SAVE_RAW:
                    path = _data_file_path(params)
                    if path is not None:
                        try:
                            path.write_text(text, encoding="utf-8")
                        except Exception as e:
                            logging.debug(f"Data write skipped for {path}: {e}")
                return text

            err_detail = extract_entsoe_error(resp.text) or resp.text[:200]
            base_details = {
                "entsoe_message": err_detail,
                "http_status": status,
                "request_params": {
                    k: v for k, v in params.items() if k != "securityToken"
                },
            }

            if status == 401:
                raise EntsoeUnauthorized(
                    f"401 Unauthorized: {err_detail}", details=base_details
                )
            if status == 403:
                raise EntsoeForbidden(
                    f"403 Forbidden: {err_detail}", details=base_details
                )
            if status == 404:
                raise EntsoeNotFound(
                    f"404 Not Found: {err_detail}", details=base_details
                )
            if status == 429:
                raise EntsoeRateLimited(
                    f"429 Too Many Requests: {err_detail}", details=base_details
                )
            if 500 <= status < 600:
                raise EntsoeServerError(
                    f"{status} Server Error: {err_detail}",
                    status=502,
                    details=base_details,
                )

            raise EntsoeError(
                f"HTTP {status}: {err_detail}",
                status=status,
                code="CLIENT_ERROR",
                details=base_details,
            )

        except (EntsoeRateLimited, EntsoeServerError) as e:
            last_exc = e
            logging.warning(f"ENTSO-E retryable error (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                backoff_sleep(attempt)
                continue
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            logging.warning(f"Network error (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                backoff_sleep(attempt)
                continue
            break
        except EntsoeError:
            raise
        except Exception as e:
            last_exc = e
            logging.warning(f"Unexpected error (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                backoff_sleep(attempt)
                continue
            break

    if isinstance(last_exc, EntsoeError):
        raise last_exc
    raise EntsoeServerError(
        "ENTSO-E request failed after {MAX_RETRIES} attempts",
        details={"last_exception": str(last_exc)},
    )


# Normalisatie
def eur_mwh_to_ct_kwh(v: float) -> float:
    return v / 10.0


# Datasets
def get_day_ahead_prices(
    d: date, zone: str = ZONE_EIC_DEFAULT, cache_ttl_s: int = TTL_PRICES_DEFAULT
) -> List[Dict]:
    start, end = local_span_day(d)
    params = {
        "documentType": DOC_A44_PRICES,
        "in_Domain": zone,
        "out_Domain": zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    cache_key = f"A44_{zone}_{d.isoformat()}"
    xml = request_entsoe(params, cache_key=cache_key, cache_ttl_s=cache_ttl_s)
    root = parse_xml(xml)
    rows: List[Dict] = []
    for ts in pick_timeseries(root):
        for p in ts.findall(".//{*}Point"):
            pos = safe_float(p.findtext(".//{*}position"))
            price = safe_float(p.findtext(".//{*}price.amount"))
            if pos is None or price is None:
                continue
            pos = int(pos)
            hstart = hour_from_position(d, pos)
            rows.append(
                {
                    "position": pos,
                    "hour_local": hstart.strftime("%Y-%m-%d %H:%M"),
                    "eur_per_mwh": round(price, 6),
                    "ct_per_kwh": round(eur_mwh_to_ct_kwh(price), 6),
                }
            )
    return ensure_ascending_positions(rows)


def get_total_load(
    d: date,
    zone: str = ZONE_EIC_DEFAULT,
    ttl_da: int = TTL_LOAD_DA_DEFAULT,
    ttl_act: int = TTL_LOAD_ACT_DEFAULT,
) -> Dict[str, List[Dict]]:
    start, end = local_span_day(d)
    params_da = {
        "documentType": DOC_A65_LOAD_DA,
        "outBiddingZone_Domain": zone,
        "processType": "A01",
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    params_act = {
        "documentType": DOC_A68_LOAD_ACT,
        "outBiddingZone_Domain": zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    xml_da = request_entsoe(
        params_da, cache_key=f"A65_{zone}_{d.isoformat()}", cache_ttl_s=ttl_da
    )
    xml_act = request_entsoe(
        params_act, cache_key=f"A68_{zone}_{d.isoformat()}", cache_ttl_s=ttl_act
    )
    root_da = parse_xml(xml_da)
    root_act = parse_xml(xml_act)

    def parse_load(root: ET.Element) -> List[Dict]:
        rows: List[Dict] = []
        for ts in pick_timeseries(root):
            for p in ts.findall(".//{*}Point"):
                pos = safe_float(p.findtext(".//{*}position"))
                qty = safe_float(p.findtext(".//{*}quantity"))
                if pos is None or qty is None:
                    continue
                pos = int(pos)
                dt_h = hour_from_position(d, pos)
                rows.append(
                    {
                        "position": pos,
                        "hour_local": dt_h.strftime("%Y-%m-%d %H:%M"),
                        "load_mwh": round(qty, 3),
                        "load_mw": round(qty, 3),
                    }
                )
        return ensure_ascending_positions(rows)

    return {"day_ahead": parse_load(root_da), "actual": parse_load(root_act)}


def _parse_generation_rows(d: date, xml: str) -> List[Dict]:
    root = parse_xml(xml)
    rows: List[Dict] = []
    for ts in pick_timeseries(root):
        ptype = ts.findtext(".//{*}productionType") or "UNKNOWN"
        psr = ts.findtext(".//{*}psrType") or None
        for p in ts.findall(".//{*}Point"):
            pos = safe_float(p.findtext(".//{*}position"))
            qty = safe_float(p.findtext(".//{*}quantity"))
            if pos is None or qty is None:
                continue
            pos = int(pos)
            dt_h = hour_from_position(d, pos)
            rows.append(
                {
                    "position": pos,
                    "hour_local": dt_h.strftime("%Y-%m-%d %H:%M"),
                    "production_type": ptype,
                    "psr_type": psr,
                    "forecast_mw": round(qty, 3),
                }
            )
    rows.sort(
        key=lambda r: (r.get("psr_type") or "", r["production_type"], r["position"])
    )
    return rows


def get_generation_forecast(
    d: date,
    zone: str = ZONE_EIC_DEFAULT,
    cache_ttl_s: int = TTL_GEN_DEFAULT,
    psr_types: Optional[Iterable[str]] = None,
) -> List[Dict]:
    start, end = local_span_day(d)

    def call_one(psr: Optional[str]) -> List[Dict]:
        params = {
            "documentType": DOC_A69_GEN_FORECAST,
            "processType": "A01",
            "in_Domain": zone,
            "out_Domain": zone,
            "periodStart": fmt_period(start),
            "periodEnd": fmt_period(end),
        }
        cache_suf = "ALL"
        if psr:
            params["psrType"] = psr
            cache_suf = psr
        cache_key = f"A69_{zone}_{d.isoformat()}_{cache_suf}"
        xml = request_entsoe(params, cache_key=cache_key, cache_ttl_s=cache_ttl_s)
        return _parse_generation_rows(d, xml)

    if psr_types:
        merged: List[Dict] = []
        for psr in psr_types:
            merged.extend(call_one(psr))
        merged.sort(key=lambda r: (r.get("psr_type") or "", r["position"]))
        return merged
    else:
        return call_one(None)


def get_net_position(
    d: date, zone: str = ZONE_EIC_DEFAULT, cache_ttl_s: int = TTL_NETPOS_DEFAULT
) -> List[Dict]:
    start, end = local_span_day(d)
    params = {
        "documentType": DOC_A75_NET_POSITION,
        "in_Domain": zone,
        "out_Domain": zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    xml = request_entsoe(
        params, cache_key=f"A75_{zone}_{d.isoformat()}", cache_ttl_s=cache_ttl_s
    )
    root = parse_xml(xml)
    rows: List[Dict] = []
    for ts in pick_timeseries(root):
        for p in ts.findall(".//{*}Point"):
            pos = safe_float(p.findtext(".//{*}position"))
            qty = safe_float(p.findtext(".//{*}quantity"))
            if pos is None or qty is None:
                continue
            pos = int(pos)
            dt_h = hour_from_position(d, pos)
            rows.append(
                {
                    "position": pos,
                    "hour_local": dt_h.strftime("%Y-%m-%d %H:%M"),
                    "net_position_mw": round(qty, 3),
                }
            )
    return ensure_ascending_positions(rows)


def get_scheduled_exchanges(
    d: date, from_zone: str, to_zone: str, cache_ttl_s: int = TTL_EXCH_DEFAULT
) -> List[Dict]:
    start, end = local_span_day(d)
    params = {
        "documentType": DOC_A01_SCHED_EXCH,
        "in_Domain": from_zone,
        "out_Domain": to_zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    xml = request_entsoe(
        params,
        cache_key=f"A01_{from_zone}_{to_zone}_{d.isoformat()}",
        cache_ttl_s=cache_ttl_s,
    )
    root = parse_xml(xml)
    rows: List[Dict] = []
    for ts in pick_timeseries(root):
        for p in ts.findall(".//{*}Point"):
            pos = safe_float(p.findtext(".//{*}position"))
            qty = safe_float(p.findtext(".//{*}quantity"))
            if pos is None or qty is None:
                continue
            pos = int(pos)
            dt_h = hour_from_position(d, pos)
            rows.append(
                {
                    "position": pos,
                    "hour_local": dt_h.strftime("%Y-%m-%d %H:%M"),
                    "scheduled_mw": round(qty, 3),
                }
            )
    return ensure_ascending_positions(rows)


# Planning
def percentile_threshold(values: List[float], pct: float) -> float:
    if not values:
        return float("nan")
    x = sorted(values)
    k = max(0, min(len(x) - 1, int(round((pct / 100.0) * (len(x) - 1)))))
    return x[k]


def plan_cheapest_hours(prices_rows: List[Dict], share_pct: float = 30.0) -> List[int]:
    vals = [(r["position"], r["ct_per_kwh"]) for r in prices_rows]
    if not vals:
        return []
    vals.sort(key=lambda t: t[1])
    n = len(vals)
    k = max(1, int(math.ceil(n * (share_pct / 100.0))))
    return sorted([pos for pos, _ in vals[:k]])


def merge_with_fallback(rows: List[Dict], key: str, default: float) -> Dict[int, float]:
    m: Dict[int, float] = {}
    for r in rows:
        m[int(r["position"])] = float(r.get(key, default))
    if m:
        for pos in range(1, max(m.keys()) + 1):
            if pos not in m:
                m[pos] = default
    return m


def suggest_automation(d: date, zone: str = ZONE_EIC_DEFAULT) -> Dict:
    prices = get_day_ahead_prices(d, zone)
    if not prices:
        raise EntsoeServerError("No prices – cannot create a plan.", status=502)
    cheapest = plan_cheapest_hours(prices, share_pct=30.0)

    gen = get_generation_forecast(d, zone, psr_types=["B16", "B18", "B19"])
    load = get_total_load(d, zone)

    wind_solar_mw: Dict[int, float] = {}
    for r in gen:
        pos = int(r["position"])
        wind_solar_mw[pos] = wind_solar_mw.get(pos, 0.0) + float(r["forecast_mw"])

    price_map = merge_with_fallback(prices, "ct_per_kwh", default=999.0)
    load_da_map = merge_with_fallback(load["day_ahead"], "load_mw", default=0.0)

    price_list = [price_map.get(p, 999.0) for p in price_map]
    load_list = [load_da_map.get(p, 0.0) for p in load_da_map]
    price_p30 = percentile_threshold(price_list, 30)
    load_p80 = percentile_threshold(load_list, 80)

    recommended: List[int] = []
    for pos in sorted(price_map.keys()):
        cheap = price_map[pos] <= price_p30
        green = wind_solar_mw.get(pos, 0.0) > 0.0
        not_peak = load_da_map.get(pos, 0.0) <= load_p80
        if cheap and (green or not_peak):
            recommended.append(pos)

    rec_set = sorted(set(recommended + cheapest))

    return {
        "date": d.isoformat(),
        "zone": zone,
        "cheapest_hours_positions": cheapest,
        "recommended_hours_positions": rec_set,
        "thresholds": {
            "price_p30_ct_per_kwh": (
                round(price_p30, 4) if isinstance(price_p30, float) else None
            ),
            "load_p80_mw": round(load_p80, 1) if isinstance(load_p80, float) else None,
        },
    }


# CLI
def parse_date(arg: Optional[str]) -> date:
    return date.fromisoformat(arg) if arg else (date.today() + timedelta(days=1))


def _print_error(e: EntsoeError):
    err = {"error": e.to_dict()}
    print(json.dumps(err, indent=2, ensure_ascii=False), file=sys.stderr)


def cmd_prices(args: List[str]):
    try:
        d = parse_date(args[0] if len(args) >= 1 else None)
        zone = args[1] if len(args) >= 2 else ZONE_EIC_DEFAULT
        rows = get_day_ahead_prices(d, zone)
        print(
            json.dumps(
                {"date": d.isoformat(), "zone": zone, "prices": rows},
                indent=2,
                ensure_ascii=False,
            )
        )
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)


def cmd_load(args: List[str]):
    try:
        d = parse_date(args[0] if len(args) >= 1 else None)
        zone = args[1] if len(args) >= 2 else ZONE_EIC_DEFAULT
        payload = get_total_load(d, zone)
        print(
            json.dumps(
                {"date": d.isoformat(), "zone": zone, "load": payload},
                indent=2,
                ensure_ascii=False,
            )
        )
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)


def cmd_gen_forecast(args: List[str]):
    try:
        d = parse_date(args[0] if len(args) >= 1 else None)
        zone = args[1] if len(args) >= 2 else ZONE_EIC_DEFAULT
        psr_types = args[2:] if len(args) >= 3 else None
        rows = get_generation_forecast(d, zone, psr_types=psr_types)
        out = {
            "date": d.isoformat(),
            "zone": zone,
            "psr_types": psr_types or ["ALL"],
            "generation_forecast": rows,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)


def cmd_netpos(args: List[str]):
    try:
        d = parse_date(args[0] if len(args) >= 1 else None)
        zone = args[1] if len(args) >= 2 else ZONE_EIC_DEFAULT
        rows = get_net_position(d, zone)
        print(
            json.dumps(
                {"date": d.isoformat(), "zone": zone, "net_position": rows},
                indent=2,
                ensure_ascii=False,
            )
        )
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)


def cmd_exchanges(args: List[str]):
    try:
        if len(args) < 3:
            raise EntsoeError(
                "Usage: exchanges [YYYY-MM-DD] FROM_EIC TO_EIC",
                status=400,
                code="BAD_REQUEST",
            )
        d = date.fromisoformat(args[0])
        from_zone = args[1]
        to_zone = args[2]
        rows = get_scheduled_exchanges(d, from_zone, to_zone)
        print(
            json.dumps(
                {
                    "date": d.isoformat(),
                    "from_zone": from_zone,
                    "to_zone": to_zone,
                    "scheduled_exchanges": rows,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)


def cmd_plan(args: List[str]):
    try:
        d = parse_date(args[0] if len(args) >= 1 else None)
        zone = args[1] if len(args) >= 2 else ZONE_EIC_DEFAULT
        plan = suggest_automation(d, zone)
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)


def cmd_run_loop(args: List[str]):
    zone = ZONE_EIC_DEFAULT
    from_zone = EXCH_FROM_EIC_DEFAULT
    to_zone = EXCH_TO_EIC_DEFAULT
    tick = TICK_SECONDS_DEFAULT

    ttl_prices = TTL_PRICES_DEFAULT
    ttl_load_da = TTL_LOAD_DA_DEFAULT
    ttl_load_act = TTL_LOAD_ACT_DEFAULT
    ttl_gen = TTL_GEN_DEFAULT
    ttl_netpos = TTL_NETPOS_DEFAULT
    ttl_exch = TTL_EXCH_DEFAULT

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--zone":
            zone = args[i + 1]
            i += 2
        elif a == "--from":
            from_zone = args[i + 1]
            i += 2
        elif a == "--to":
            to_zone = args[i + 1]
            i += 2
        elif a == "--tick":
            tick = int(args[i + 1])
            i += 2
        elif a == "--prices-ttl":
            ttl_prices = int(args[i + 1])
            i += 2
        elif a == "--load-da-ttl":
            ttl_load_da = int(args[i + 1])
            i += 2
        elif a == "--load-act-ttl":
            ttl_load_act = int(args[i + 1])
            i += 2
        elif a == "--gen-ttl":
            ttl_gen = int(args[i + 1])
            i += 2
        elif a == "--netpos-ttl":
            ttl_netpos = int(args[i + 1])
            i += 2
        elif a == "--exch-ttl":
            ttl_exch = int(args[i + 1])
            i += 2
        else:
            raise EntsoeError(
                f"Unknown run-loop option: {a}", status=400, code="BAD_REQUEST"
            )

    POLL_INTERVALS = {
        "A44": ttl_prices,
        "A65": ttl_load_da,
        "A68": ttl_load_act,
        "A69": ttl_gen,
        "A75": ttl_netpos,
        "A01": ttl_exch,
    }
    next_run = {k: 0.0 for k in POLL_INTERVALS.keys()}
    stop_flag = {"stop": False}

    def handle_sigterm(sig, frame):
        logging.info("Stop signal received, shutting down run-loop...")
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)

    logging.info(f"Run-loop started for zone={zone}, exchanges {from_zone}->{to_zone}")

    def jitter(sec: int) -> float:
        return sec * (1.0 + 0.1 * random.random())

    while not stop_flag["stop"]:
        now = time.time()
        try:
            if now >= next_run["A44"]:
                d_prices = date.today() + timedelta(days=1)
                get_day_ahead_prices(d_prices, zone, cache_ttl_s=ttl_prices)
                next_run["A44"] = now + jitter(POLL_INTERVALS["A44"])
                logging.info("A44 (prices) refreshed")

            if now >= next_run["A65"]:
                d_da = date.today() + timedelta(days=1)
                get_total_load(d_da, zone, ttl_da=ttl_load_da, ttl_act=ttl_load_act)[
                    "day_ahead"
                ]
                next_run["A65"] = now + jitter(POLL_INTERVALS["A65"])
                logging.info("A65 (load day-ahead) refreshed")

            if now >= next_run["A68"]:
                d_act = date.today()
                get_total_load(d_act, zone, ttl_da=ttl_load_da, ttl_act=ttl_load_act)[
                    "actual"
                ]
                next_run["A68"] = now + jitter(POLL_INTERVALS["A68"])
                logging.info("A68 (load actual) refreshed")

            if now >= next_run["A69"]:
                d_gen = date.today() + timedelta(days=1)
                get_generation_forecast(d_gen, zone, cache_ttl_s=ttl_gen)
                next_run["A69"] = now + jitter(POLL_INTERVALS["A69"])
                logging.info("A69 (generation forecast) refreshed")

            if now >= next_run["A75"]:
                d_np = date.today()
                get_net_position(d_np, zone, cache_ttl_s=ttl_netpos)
                next_run["A75"] = now + jitter(POLL_INTERVALS["A75"])
                logging.info("A75 (net position) refreshed")

            if now >= next_run["A01"]:
                d_ex = date.today()
                get_scheduled_exchanges(d_ex, from_zone, to_zone, cache_ttl_s=ttl_exch)
                next_run["A01"] = now + jitter(POLL_INTERVALS["A01"])
                logging.info("A01 (scheduled exchanges) refreshed")

        except EntsoeUnauthorized as e:
            logging.error(f"{e}. Stopping loop.")
            break
        except EntsoeError as e:
            logging.warning(f"Run-loop handled error [{e.code}] status {e.status}: {e}")
        except Exception as e:
            logging.warning(f"Run-loop unexpected error: {e}")

        time.sleep(tick)


# Entrypoint
def main():
    if len(sys.argv) < 2:
        print(
            "Commands: prices | load | gen-forecast | netpos | exchanges | plan | run-loop",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    try:
        if cmd == "prices":
            cmd_prices(args)
        elif cmd == "load":
            cmd_load(args)
        elif cmd == "gen-forecast":
            cmd_gen_forecast(args)
        elif cmd == "netpos":
            cmd_netpos(args)
        elif cmd == "exchanges":
            cmd_exchanges(args)
        elif cmd == "plan":
            cmd_plan(args)
        elif cmd == "run-loop":
            cmd_run_loop(args)
        else:
            raise EntsoeError(f"Unknown command: {cmd}", status=400, code="BAD_REQUEST")
    except EntsoeError as e:
        _print_error(e)
        sys.exit(1)
    except Exception as e:
        err = EntsoeError(str(e), status=500, code="CLIENT_ERROR")
        _print_error(err)
        sys.exit(1)


if __name__ == "__main__":
    main()
