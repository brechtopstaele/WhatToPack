
from __future__ import annotations
from datetime import date
from typing import Optional, Tuple
from flask import current_app
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "packpal/1.0 (+contact: you@example.com)"}
HTTP_TIMEOUT = 12

def geocode_location_nominatim(q: str) -> Optional[Tuple[float, float]]:
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"q": q, "format": "json", "limit": 1},
            headers=NOMINATIM_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        arr = r.json()
        if arr:
            return float(arr[0]["lat"]), float(arr[0]["lon"])
    except Exception:
        return None
    return None

def fetch_weather_open_meteo(
    lat: float, lon: float, start: date, end: date
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
                "timezone": "auto",
                "temperature_unit": "celsius",
                "precipitation_unit": "mm",
            },
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        js = r.json()
        daily = js.get("daily", {})
        tmax = daily.get("temperature_2m_max", []) or []
        tmin = daily.get("temperature_2m_min", []) or []
        precip = daily.get("precipitation_sum", []) or []
        snow = daily.get("snowfall_sum", []) or []
        avg_c = sum((a + b) / 2 for a, b in zip(tmax, tmin)) / len(tmax) if (tmax and tmin) else None
        return avg_c, (sum(precip) if precip else None), (sum(snow) if snow else None)
    except Exception:
        return None, None, None
