#!/usr/bin/env python3
"""
ha_entsoe.py

ENTSO-E integratie met:
- Robuuste tijd-as logica (PT15M/PT60M, timeInterval.start, DST, deduplicatie per timestamp)
- Consistente foutafhandeling en retries
- Bestandscache en optionele ruwe XML opslag in DATA_ROOT/YYYY/MM/
- Configureerbare toggles voor A68 variaties tussen gateways
- Planning helper die A68 overslaat voor toekomstige datums

.ENV voorbeeld:
  ENTSOE_API_KEY=your_security_token
  ZONE_EIC=10YNL----------L
  TIME_ZONE=Europe/Amsterdam

  MAX_RETRIES=4
  BACKOFF_BASE=1.7
  BACKOFF_CAP_SECONDS=30
  HTTP_READ_TIMEOUT=45

  CACHE_DIR=/app/cache
  SAVE_RAW=1
  DATA_ROOT=/data

  TTL_PRICES=86400
  TTL_LOAD_DA=86400
  TTL_LOAD_ACT=900
  TTL_GEN=10800
  TTL_NETPOSBO=3600
  TTL_EXCH=10800

  SKIP_A68_FOR_FUTURE=1
  REQUIRE_IN_DOMAIN_A68=0
  A68_REQUIRE_PROCESS_TYPE=0
  A68_PROCESS_TYPE=A16

  EXCH_FROM_EIC=10YNL----------L
  EXCH_TO_EIC=10YBE----------2
"""

import os
import sys
import json
import time
import math
import random
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Iterable
from datetime import datetime, date, timedelta, timezone
from xml.etree import ElementTree as ET

import requests
from dateutil import tz, parser as dtparser

# .env laden
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Env helpers
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


def getenv_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# Basisconfig
API_ENDPOINT = "https://web-api.tp.entsoe.eu/api"

# API_ENDPOINT = "https://newtransparency.entsoe.eu/market/energyPrices/load"

ZONE_EIC_DEFAULT = getenv_str("ZONE_EIC", "10YNL----------L")
TIME_ZONE_NAME = getenv_str("TIME_ZONE", "Europe/Amsterdam")
TZ_LOCAL = tz.gettz(TIME_ZONE_NAME)

MAX_RETRIES = getenv_int("MAX_RETRIES", 4)
BACKOFF_BASE = getenv_float("BACKOFF_BASE", 1.7)
BACKOFF_CAP_SECONDS = getenv_float("BACKOFF_CAP_SECONDS", 30.0)
HTTP_READ_TIMEOUT = getenv_int("HTTP_READ_TIMEOUT", 45)

# Cache + opslag
CACHE_DIR = Path(getenv_str("CACHE_DIR", "./cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DATA_ROOT = Path(getenv_str("DATA_ROOT", "./data")).resolve()
SAVE_RAW = getenv_str("SAVE_RAW", "1").lower() not in ("0", "false", "no", "")
try:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# TTLs
TTL_PRICES_DEFAULT = getenv_int("TTL_PRICES", 24 * 3600)
TTL_LOAD_DA_DEFAULT = getenv_int("TTL_LOAD_DA", 24 * 3600)
TTL_LOAD_ACT_DEFAULT = getenv_int("TTL_LOAD_ACT", 900)
TTL_GEN_DEFAULT = getenv_int("TTL_GEN", 3 * 3600)
TTL_NETPOS_DEFAULT = getenv_int("TTL_NETPOS", 3600)
TTL_EXCH_DEFAULT = getenv_int("TTL_EXCH", 3 * 3600)

# Toggles A68
SKIP_A68_FOR_FUTURE = getenv_bool("SKIP_A68_FOR_FUTURE", True)
REQUIRE_IN_DOMAIN_A68 = getenv_bool("REQUIRE_IN_DOMAIN_A68", False)
A68_REQUIRE_PROCESS_TYPE = getenv_bool("A68_REQUIRE_PROCESS_TYPE", False)
A68_PROCESS_TYPE = getenv_str("A68_PROCESS_TYPE", "A16")

# Document types
DOC_A44_PRICES = "A44"
DOC_A65_LOAD_DA = "A65"
DOC_A68_LOAD_ACT = "A68"
DOC_A69_GEN_FORECAST = "A69"
DOC_A75_NET_POSITION = "A75"
DOC_A01_SCHED_EXCH = "A01"

# Voor api_server.py compat: expose defaults
EXCH_FROM_EIC_DEFAULT = getenv_str("EXCH_FROM_EIC", ZONE_EIC_DEFAULT)
EXCH_TO_EIC_DEFAULT = getenv_str("EXCH_TO_EIC", "10YBE----------2")


# Error model
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


# Tijd helpers
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


def parse_iso_dt(s: str) -> datetime:
    dt = dtparser.isoparse(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_resolution_to_timedelta(res_text: Optional[str]) -> timedelta:
    if not res_text:
        return timedelta(hours=1)
    r = res_text.upper()
    if r.startswith("PT") and r.endswith("M"):
        minutes = int(r[2:-1])
        return timedelta(minutes=minutes)
    if r.startswith("PT") and r.endswith("H"):
        hours = int(r[2:-1])
        return timedelta(hours=hours)
    if r == "P1D":
        return timedelta(days=1)
    return timedelta(hours=1)


# XML parse helpers
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


# Tijd-as extractors
def _safe_float(txt: Optional[str]) -> Optional[float]:
    if txt is None:
        return None
    try:
        return float(txt)
    except Exception:
        return None


def ts_points_to_series(d: date, ts: ET.Element, local_tz=TZ_LOCAL) -> List[Dict]:
    periods = ts.findall(".//{*}Period")
    items: List[Dict] = []

    if not periods:
        ti_ts = ts.find(".//{*}timeInterval")
        start_text = ti_ts.findtext(".//{*}start") if ti_ts is not None else None
        res_text = ts.findtext(".//{*}resolution")
        res_td = resolve_resolution_to_timedelta(res_text or "PT60M")
        start_dt_utc = (
            parse_iso_dt(start_text)
            if start_text
            else datetime(d.year, d.month, d.day, 0, 0, tzinfo=timezone.utc)
        )
        for p in ts.findall(".//{*}Point"):
            pos_txt = p.findtext(".//{*}position")
            if not pos_txt:
                continue
            try:
                ipos = int(float(pos_txt))
            except Exception:
                continue
            stamp_utc = start_dt_utc + (ipos - 1) * res_td
            stamp_local = stamp_utc.astimezone(local_tz)
            items.append(
                {
                    "timestamp_local": stamp_local,
                    "price": _safe_float(p.findtext(".//{*}price.amount")),
                    "quantity": _safe_float(p.findtext(".//{*}quantity")),
                    "resolution": res_text or "PT60M",
                }
            )
        return items

    for period in periods:
        ti = period.find(".//{*}timeInterval")
        start_text = ti.findtext(".//{*}start") if ti is not None else None
        res_text = period.findtext(".//{*}resolution") or ts.findtext(
            ".//{*}resolution"
        )
        res_td = resolve_resolution_to_timedelta(res_text or "PT60M")
        start_dt_utc = (
            parse_iso_dt(start_text)
            if start_text
            else datetime(d.year, d.month, d.day, 0, 0, tzinfo=timezone.utc)
        )

        for p in period.findall(".//{*}Point"):
            pos_txt = p.findtext(".//{*}position")
            if not pos_txt:
                continue
            try:
                ipos = int(float(pos_txt))
            except Exception:
                continue
            stamp_utc = start_dt_utc + (ipos - 1) * res_td
            stamp_local = stamp_utc.astimezone(local_tz)
            items.append(
                {
                    "timestamp_local": stamp_local,
                    "price": _safe_float(p.findtext(".//{*}price.amount")),
                    "quantity": _safe_float(p.findtext(".//{*}quantity")),
                    "resolution": res_text or "PT60M",
                }
            )
    return items


def coalesce_by_timestamp(
    items: List[Dict], prefer: str = "last", op: str = "mean"
) -> List[Dict]:
    from collections import defaultdict

    buckets = defaultdict(list)
    for it in items:
        buckets[it["timestamp_local"]].append(it)
    merged: List[Dict] = []
    for ts, arr in buckets.items():
        if prefer in ("last", "first"):
            merged.append(arr[-1] if prefer == "last" else arr[0])
        else:
            prices = [x["price"] for x in arr if x["price"] is not None]
            qtys = [x["quantity"] for x in arr if x["quantity"] is not None]
            avg_price = sum(prices) / len(prices) if prices else None
            avg_qty = sum(qtys) / len(qtys) if qtys else None
            base = dict(arr[-1])
            base["price"] = avg_price
            base["quantity"] = avg_qty
            merged.append(base)
    merged.sort(key=lambda x: x["timestamp_local"])
    return merged


# Opslag helpers
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


def _data_file_path(params: dict, ext: str = "xml") -> Path:
    d = _infer_date_from_params(params)
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
    if d:
        folder = DATA_ROOT / f"{d.year:04d}" / f"{d.month:02d}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        fname = "_".join(parts + [d.isoformat()]) + f".{ext}"
        return folder / fname
    else:
        folder = DATA_ROOT / "unknown-date"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        fname = "_".join(parts + ["unknown"]) + f".{ext}"
        return folder / fname


# HTTP wrapper
def request_entsoe(
    params: Dict, cache_key: Optional[str] = None, cache_ttl_s: Optional[int] = None
) -> str:
    if cache_key and cache_ttl_s:
        cache_file = CACHE_DIR / f"{cache_key}.xml"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age <= cache_ttl_s:
                return cache_file.read_text(encoding="utf-8")

    params = dict(params)
    params["securityToken"] = require_api_key()

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(API_ENDPOINT, params=params, timeout=HTTP_READ_TIMEOUT)
            status = resp.status_code
            logging.info(f"Request {attempt} - Status: {status}")
            if status == 200:
                text = resp.text
                if cache_key and cache_ttl_s:
                    try:
                        (CACHE_DIR / f"{cache_key}.xml").write_text(
                            text, encoding="utf-8"
                        )
                    except Exception:
                        pass
                if SAVE_RAW:
                    path = _data_file_path(params)
                    try:
                        path.write_text(text, encoding="utf-8")
                    except Exception:
                        pass
                return text

            err_detail = extract_entsoe_error(resp.text) or resp.text[:200]
            details = {
                "entsoe_message": err_detail,
                "http_status": status,
                "request_params": {
                    k: v for k, v in params.items() if k != "securityToken"
                },
            }

            if status == 401:
                raise EntsoeUnauthorized(
                    f"401 Unauthorized: {err_detail}", details=details
                )
            if status == 403:
                raise EntsoeForbidden(f"403 Forbidden: {err_detail}", details=details)
            if status == 404:
                raise EntsoeNotFound(f"404 Not Found: {err_detail}", details=details)
            if status == 429:
                raise EntsoeRateLimited(
                    f"429 Too Many Requests: {err_detail}", details=details
                )
            if 500 <= status < 600:
                raise EntsoeServerError(
                    f"{status} Server Error: {err_detail}", status=502, details=details
                )
            raise EntsoeError(
                f"HTTP {status}: {err_detail}",
                status=status,
                code="CLIENT_ERROR",
                details=details,
            )

        except (EntsoeRateLimited, EntsoeServerError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(
                    min(BACKOFF_CAP_SECONDS, (BACKOFF_BASE**attempt))
                    * (1 + 0.1 * random.random())
                )
                continue
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(
                    min(BACKOFF_CAP_SECONDS, (BACKOFF_BASE**attempt))
                    * (1 + 0.1 * random.random())
                )
                continue
            break
        except EntsoeError:
            raise
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(
                    min(BACKOFF_CAP_SECONDS, (BACKOFF_BASE**attempt))
                    * (1 + 0.1 * random.random())
                )
                continue
            break

    if isinstance(last_exc, EntsoeError):
        raise last_exc
    raise EntsoeServerError(
        "ENTSO-E request failed after retries",
        details={"last_exception": str(last_exc)},
    )


# Normalisatie helpers
def eur_mwh_to_ct_kwh(v: float) -> float:
    return v / 10.0


def rows_from_items_price(items: List[Dict]) -> List[Dict]:
    items = coalesce_by_timestamp(items, prefer="last")
    rows: List[Dict] = []
    for idx, it in enumerate(items, start=1):
        if it["price"] is None:
            continue
        ts_local = it["timestamp_local"]
        res_text = it.get("resolution") or "PT60M"
        rows.append(
            {
                "position": idx,
                "hour_local": ts_local.strftime("%Y-%m-%d %H:%M"),
                "eur_per_mwh": round(it["price"], 6),
                "ct_per_kwh": round(eur_mwh_to_ct_kwh(it["price"]), 6),
                "resolution": res_text,
            }
        )
    return rows


def rows_from_items_quantity(items: List[Dict], quantity_key_out: str) -> List[Dict]:
    items = coalesce_by_timestamp(items, prefer="last")
    rows: List[Dict] = []
    for idx, it in enumerate(items, start=1):
        q = it["quantity"]
        if q is None:
            continue
        ts_local = it["timestamp_local"]
        res_text = it.get("resolution") or "PT60M"
        rows.append(
            {
                "position": idx,
                "hour_local": ts_local.strftime("%Y-%m-%d %H:%M"),
                quantity_key_out: round(q, 3),
                "resolution": res_text,
            }
        )
    return rows


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
    xml = request_entsoe(
        params, cache_key=f"A44_{zone}_{d.isoformat()}", cache_ttl_s=cache_ttl_s
    )
    root = parse_xml(xml)
    items: List[Dict] = []
    for ts in pick_timeseries(root):
        items.extend(ts_points_to_series(d, ts, local_tz=TZ_LOCAL))
    return rows_from_items_price(items)


def get_day_ahead_total_load_forecast(
    d: date, zone: str = ZONE_EIC_DEFAULT, cache_ttl_s: int = TTL_LOAD_DA_DEFAULT
) -> List[Dict]:
    start, end = local_span_day(d)
    params = {
        "documentType": DOC_A65_LOAD_DA,
        "processType": "A01",
        "outBiddingZone_Domain": zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    xml = request_entsoe(
        params, cache_key=f"A65_DA_{zone}_{d.isoformat()}", cache_ttl_s=cache_ttl_s
    )
    root = parse_xml(xml)
    items: List[Dict] = []
    for ts in pick_timeseries(root):
        items.extend(ts_points_to_series(d, ts, local_tz=TZ_LOCAL))
    return rows_from_items_quantity(items, "forecast_mw")


def _build_params_a68(d: date, zone: str) -> Dict[str, str]:
    start, end = local_span_day(d)
    params = {
        "documentType": DOC_A68_LOAD_ACT,
        "outBiddingZone_Domain": zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    if REQUIRE_IN_DOMAIN_A68:
        params["in_Domain"] = zone
    if A68_REQUIRE_PROCESS_TYPE:
        params["processType"] = A68_PROCESS_TYPE
    return params


def get_total_load(
    d: date,
    zone: str = ZONE_EIC_DEFAULT,
    ttl_da: int = TTL_LOAD_DA_DEFAULT,
    ttl_act: int = TTL_LOAD_ACT_DEFAULT,
) -> Dict[str, List[Dict]]:
    start, end = local_span_day(d)
    # Day-ahead
    params_da = {
        "documentType": DOC_A65_LOAD_DA,
        "processType": "A01",
        "outBiddingZone_Domain": zone,
        "periodStart": fmt_period(start),
        "periodEnd": fmt_period(end),
    }
    xml_da = request_entsoe(
        params_da, cache_key=f"A65_{zone}_{d.isoformat()}", cache_ttl_s=ttl_da
    )
    root_da = parse_xml(xml_da)
    items_da: List[Dict] = []
    for ts in pick_timeseries(root_da):
        items_da.extend(ts_points_to_series(d, ts, local_tz=TZ_LOCAL))
    rows_da = rows_from_items_quantity(items_da, "load_mw")

    # Actual
    params_act = _build_params_a68(d, zone)
    xml_act = request_entsoe(
        params_act, cache_key=f"A68_{zone}_{d.isoformat()}", cache_ttl_s=ttl_act
    )
    root_act = parse_xml(xml_act)
    items_act: List[Dict] = []
    for ts in pick_timeseries(root_act):
        items_act.extend(ts_points_to_series(d, ts, local_tz=TZ_LOCAL))
    rows_act = rows_from_items_quantity(items_act, "load_mw")

    return {"day_ahead": rows_da, "actual": rows_act}


def _parse_generation_rows(d: date, root: ET.Element) -> List[Dict]:
    enriched: List[Dict] = []
    for ts in pick_timeseries(root):
        ptype = ts.findtext(".//{*}productionType")
        psr = ts.findtext(".//{*}psrType")
        items = ts_points_to_series(d, ts, local_tz=TZ_LOCAL)
        for it in items:
            enriched.append(
                {
                    "timestamp_local": it["timestamp_local"],
                    "quantity": it["quantity"],
                    "resolution": it.get("resolution") or "PT60M",
                    "production_type": ptype,
                    "psr_type": psr,
                }
            )

    # Dedup per (timestamp, psr_type or production_type)
    from collections import defaultdict

    buckets = defaultdict(list)
    for it in enriched:
        key = (
            it["timestamp_local"],
            it.get("psr_type") or it.get("production_type") or "ALL",
        )
        buckets[key].append(it)

    merged: List[Dict] = []
    for key, arr in buckets.items():
        arr.sort(key=lambda x: x["timestamp_local"])
        merged.append(arr[-1])

    merged.sort(key=lambda x: (x.get("psr_type") or "", x["timestamp_local"]))
    rows: List[Dict] = []
    for idx, it in enumerate(merged, start=1):
        q = it["quantity"]
        if q is None:
            continue
        rows.append(
            {
                "position": idx,
                "hour_local": it["timestamp_local"].strftime("%Y-%m-%d %H:%M"),
                "production_type": it.get("production_type") or "UNKNOWN",
                "psr_type": it.get("psr_type"),
                "forecast_mw": round(q, 3),
                "resolution": it.get("resolution") or "PT60M",
            }
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
        xml = request_entsoe(
            params,
            cache_key=f"A69_{zone}_{d.isoformat()}_{cache_suf}",
            cache_ttl_s=cache_ttl_s,
        )
        root = parse_xml(xml)
        return _parse_generation_rows(d, root)

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
    items: List[Dict] = []
    for ts in pick_timeseries(root):
        items.extend(ts_points_to_series(d, ts, local_tz=TZ_LOCAL))
    return rows_from_items_quantity(items, "net_position_mw")


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
    items: List[Dict] = []
    for ts in pick_timeseries(root):
        items.extend(ts_points_to_series(d, ts, local_tz=TZ_LOCAL))
    return rows_from_items_quantity(items, "scheduled_mw")


# Planning helpers
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
    today = date.today()
    prices = get_day_ahead_prices(d, zone)
    if not prices:
        raise EntsoeServerError("No prices – cannot create a plan.", status=502)
    cheapest = plan_cheapest_hours(prices, share_pct=30.0)

    gen = get_generation_forecast(d, zone, psr_types=["B16", "B18", "B19"])

    if SKIP_A68_FOR_FUTURE and d > today:
        da_rows = get_day_ahead_total_load_forecast(d, zone)
        load_da_map = merge_with_fallback(da_rows, "forecast_mw", default=0.0)
    else:
        load = get_total_load(d, zone)
        load_da_map = merge_with_fallback(load["day_ahead"], "load_mw", default=0.0)

    wind_solar_mw: Dict[int, float] = {}
    for r in gen:
        pos = int(r["position"])
        wind_solar_mw[pos] = wind_solar_mw.get(pos, 0.0) + float(r["forecast_mw"])

    price_map = merge_with_fallback(prices, "ct_per_kwh", default=999.0)
    price_list = [price_map.get(p, 999.0) for p in sorted(price_map.keys())]
    load_list = [load_da_map.get(p, 0.0) for p in sorted(load_da_map.keys())]
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


# CLI (optioneel; kan gebruikt worden voor testen)
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


def main():
    if len(sys.argv) < 2:
        print(
            "Commands: prices | load | gen-forecast | netpos | exchanges | plan",
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
