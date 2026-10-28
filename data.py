"""NASA POWER monthly regional precipitation access with an in-process cache."""
from __future__ import annotations
import time
import requests
from datetime import date
from threading import Lock

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/monthly/regional"
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = Lock()

# Small, transparent rectangular study areas around representative locations.
# These are analysis boxes, not official administrative or watershed boundaries.
REGIONS = {
    "Kuala Lumpur, Malaysia": {"latitude_min": 2.75, "latitude_max": 3.50, "longitude_min": 101.30, "longitude_max": 102.05},
    "Dhaka, Bangladesh": {"latitude_min": 23.45, "latitude_max": 24.15, "longitude_min": 90.05, "longitude_max": 90.80},
    "Sungai Petani, Malaysia": {"latitude_min": 5.30, "latitude_max": 6.00, "longitude_min": 100.15, "longitude_max": 100.80},
    "Amazonia, Brazil": {"latitude_min": -3.85, "latitude_max": -3.10, "longitude_min": -62.60, "longitude_max": -61.85},
    "Nairobi, Kenya": {"latitude_min": -1.65, "latitude_max": -0.95, "longitude_min": 36.45, "longitude_max": 37.20},
    "Phoenix, Arizona, USA": {"latitude_min": 33.05, "latitude_max": 33.80, "longitude_min": -112.45, "longitude_max": -111.70},
    "London, United Kingdom": {"latitude_min": 51.15, "latitude_max": 51.90, "longitude_min": -0.55, "longitude_max": 0.20},
    "Tokyo, Japan": {"latitude_min": 35.30, "latitude_max": 36.05, "longitude_min": 139.25, "longitude_max": 140.00},
}

class DataSourceError(RuntimeError):
    pass


def get_monthly_precip_region(bounds: dict, start_year: int, end_year: int) -> dict:
    lat_min = float(bounds["latitude_min"]); lat_max = float(bounds["latitude_max"])
    lon_min = float(bounds["longitude_min"]); lon_max = float(bounds["longitude_max"])
    if not (-90 <= lat_min < lat_max <= 90 and -180 <= lon_min < lon_max <= 180):
        raise ValueError("Region bounds must be ordered and within valid latitude/longitude ranges.")
    if start_year < 1981 or end_year > date.today().year - 1 or start_year >= end_year:
        raise ValueError("Choose a period from 1981 through the last complete calendar year, with start before end.")
    key = (round(lat_min, 3), round(lat_max, 3), round(lon_min, 3), round(lon_max, 3), start_year, end_year)
    now = time.time()
    with _lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < 3600:
            return cached[1]
    params = {
        "parameters": "PRECTOTCORR", "community": "AG",
        "latitude-min": lat_min, "latitude-max": lat_max,
        "longitude-min": lon_min, "longitude-max": lon_max,
        "start": start_year, "end": end_year, "format": "JSON",
    }
    try:
        response = requests.get(NASA_POWER_URL, params=params, timeout=60,
                                headers={"User-Agent": "TrendLens/0.1 (NASA Space Apps Challenge project)"})
        response.raise_for_status()
        payload = response.json()
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise DataSourceError("NASA POWER returned no grid cells for this bounding box and period. Try a larger region or another period.")
        # Aggregate monthly cell values using cosine-latitude area weights. This is
        # an area-weighted regional grid-cell mean approximation, not a watershed mask.
        numerator: dict[str, float] = {}
        denominator: dict[str, float] = {}
        cell_count: dict[str, int] = {}
        valid_cells = 0
        for feature in features:
            values = feature.get("properties", {}).get("parameter", {}).get("PRECTOTCORR", {})
            coords = feature.get("geometry", {}).get("coordinates", [])
            try:
                latitude = float(coords[1])
            except (IndexError, TypeError, ValueError):
                latitude = (lat_min + lat_max) / 2
            weight = max(0.0001, abs(__import__("math").cos(__import__("math").radians(latitude))))
            cell_has_data = False
            for stamp, raw in values.items():
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                # NASA POWER monthly/annual uses -999 as its fill value and YYYY13
                # for annual summary; only real monthly values are aggregated here.
                if value < 0 or len(stamp) != 6 or int(stamp[4:6]) not in range(1, 13):
                    continue
                numerator[stamp] = numerator.get(stamp, 0.0) + value * weight
                denominator[stamp] = denominator.get(stamp, 0.0) + weight
                cell_count[stamp] = cell_count.get(stamp, 0) + 1
                cell_has_data = True
            valid_cells += int(cell_has_data)
        monthly = {stamp: numerator[stamp] / denominator[stamp]
                   for stamp in numerator if denominator.get(stamp, 0) > 0}
        if not monthly:
            raise DataSourceError("NASA POWER returned grid cells but no valid monthly precipitation values.")
        out = {
            "monthly": monthly, "source": "NASA POWER", "parameter": "PRECTOTCORR",
            "units": "mm/day", "bounds": {"latitude_min": lat_min, "latitude_max": lat_max, "longitude_min": lon_min, "longitude_max": lon_max},
            "grid_cells_returned": len(features), "grid_cells_with_data": valid_cells,
            "monthly_cell_counts": cell_count,
            "start_year": start_year, "end_year": end_year,
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_url": response.url,
            "product_note": "NASA POWER monthly corrected precipitation (PRECTOTCORR), mm/day. Each monthly regional value is a cosine-latitude-weighted mean of available grid cells in the selected rectangular bounding box; annual summaries are day-weighted means of valid monthly regional values.",
        }
        with _lock:
            _cache[key] = (now, out)
        return out
    except requests.RequestException as exc:
        raise DataSourceError(f"Could not retrieve NASA POWER regional data ({exc.__class__.__name__}). Check the deployment's outbound internet access and try again.") from exc
    except ValueError as exc:
        if isinstance(exc, DataSourceError):
            raise
        raise DataSourceError("NASA POWER returned a response that could not be parsed.") from exc


def annualize(monthly: dict) -> tuple[list[int], list[float], dict[int, int]]:
    """Day-weight monthly values into annual means; require at least 10 months/year."""
    import calendar
    grouped: dict[int, list[tuple[float, int]]] = {}
    for stamp, raw in monthly.items():
        if raw is None or str(raw).strip() in ("", "-999", "-999.0"):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        year, month = int(stamp[:4]), int(stamp[4:6])
        # Defensive guard: NASA POWER's YYYY13 annual summary is not a month.
        if month < 1 or month > 12:
            continue
        grouped.setdefault(year, []).append((value, calendar.monthrange(year, month)[1]))
    years, values, counts = [], [], {}
    for year in sorted(grouped):
        entries = grouped[year]
        counts[year] = len(entries)
        if len(entries) >= 10:
            denom = sum(days for _, days in entries)
            values.append(sum(v * days for v, days in entries) / denom)
            years.append(year)
    return years, values, counts
