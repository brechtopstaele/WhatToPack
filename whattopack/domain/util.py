
from __future__ import annotations
from datetime import date
from typing import Optional

def days_between(start: date, end: date) -> int:
    return max(1, (end - start).days + 1)

def infer_meteorological_season(lat: Optional[float], d: date) -> str:
    m = d.month
    if lat is not None and abs(lat) < 10:
        return "tropical"
    northern = (lat is None) or (lat >= 0)
    if northern:
        if m in (12, 1, 2): return "winter"
        if m in (3, 4, 5): return "spring"
        if m in (6, 7, 8): return "summer"
        return "autumn"
    else:
        if m in (6, 7, 8): return "winter"
        if m in (9, 10, 11): return "spring"
        if m in (12, 1, 2): return "summer"
        return "autumn"

def decide_temp_profile(avg_c: Optional[float]) -> str:
    if avg_c is None: return "mild"
    if avg_c < 5: return "cold"
    if avg_c < 15: return "mild"
    if avg_c < 25: return "warm"
    return "hot"
