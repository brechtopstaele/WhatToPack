
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict
from flask import current_app

DEFAULT_RULES: Dict[str, Any] = {
    # Keep this minimal; your full default is loaded in main at first use if file missing
    "rules_version": "1.0",
    "meta": {"name": "Default"},
    "items": [],
    "post_processing": {"merge_duplicates": True, "floor_min": 1},
}

def _rules_path() -> Path:
    return Path(current_app.instance_path) / "rules.json"

def _mode_path() -> Path:
    return Path(current_app.instance_path) / "weather_mode.txt"

def load_rules() -> Dict[str, Any]:
    path = _rules_path()
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_RULES, indent=2), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))

def save_rules(data: Dict[str, Any]) -> None:
    _rules_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def get_weather_mode() -> str:
    p = _mode_path()
    return p.read_text().strip() if p.exists() else "offline"

def set_weather_mode(mode: str) -> None:
    _mode_path().write_text(mode)
