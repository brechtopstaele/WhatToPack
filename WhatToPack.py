
from __future__ import annotations

import ast
import json
import math
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy


# =============================================================================
# App configuration (Windows-safe, Docker-friendly)
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = "change-this-in-production"

# Ensure instance path <project>/instance exists
app.instance_path = str(BASE_DIR / "instance")
Path(app.instance_path).mkdir(parents=True, exist_ok=True)

# SQLite file lives under instance/
DB_FILE = Path(app.instance_path) / "packpal.sqlite"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_FILE.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =============================================================================
# Models
# =============================================================================


class Trip(db.Model):
    __tablename__ = "trip"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(140))
    destination = db.Column(db.String(140), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Inferred fields (season/weather summary)
    season = db.Column(db.String(20))  # winter/spring/summer/autumn/tropical
    temp_profile = db.Column(db.String(20))  # cold/mild/warm/hot
    avg_temp_c = db.Column(db.Float)
    precip_mm = db.Column(db.Float)
    snowfall_mm = db.Column(db.Float)
    weather_source = db.Column(db.String(40))  # 'open-meteo'|'heuristic'|'none'

    # Preferences
    laundry_every_n_days = db.Column(db.Integer, default=3)
    carry_on_only = db.Column(db.Boolean, default=True)
    activities = db.Column(db.String(240), default="")  # comma-separated

    # Optional geocoded coordinates
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    items = db.relationship(
        "Item", backref="trip", cascade="all, delete-orphan", lazy=True
    )


class Item(db.Model):
    __tablename__ = "item"

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), default="Misc", index=True)
    quantity = db.Column(db.Integer, default=1)
    packed = db.Column(db.Boolean, default=False, index=True)


with app.app_context():
    print(f"[DB] Using {DB_FILE}")
    db.create_all()


# =============================================================================
# Constants & simple storage (rules + weather mode)
# =============================================================================

ACTIVITY_CHOICES = [
    "ski",
    "hiking",
    "citytrip",
    "beach",
    "camping",
    "business",
    "photography",
    "diving",
]

# Paths
RULES_PATH = Path(app.instance_path) / "rules.json"
WEATHER_MODE_PATH = Path(app.instance_path) / "weather_mode.txt"

# External requests configs
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "packpal/1.0 (+contact: you@example.com)"}
HTTP_TIMEOUT = 12  # seconds

DEFAULT_RULES: Dict[str, Any] = {
    "rules_version": "1.0",
    "meta": {"name": "Default PackPal rules", "description": "Baseline items + activities"},
    "items": [
        # Essentials
        {"name": "Passport/ID", "category": "Documents", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Wallet (cards, cash)", "category": "Documents", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Phone", "category": "Electronics", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Phone charger + cable", "category": "Electronics", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Travel adapter", "category": "Electronics", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Power bank", "category": "Electronics", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Medications", "category": "Medication", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Toothbrush", "category": "Toiletries", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Toothpaste", "category": "Toiletries", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Deodorant", "category": "Toiletries", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Sunscreen", "category": "Toiletries", "conditions": {"always": True}, "quantity": {"calc": "1"}},

        # Baseline clothing
        {"name": "Underwear", "category": "Clothing", "conditions": {"always": True}, "quantity": {"calc": "cycle"}},
        {"name": "Socks", "category": "Clothing", "conditions": {"always": True}, "quantity": {"calc": "cycle"}},
        {"name": "T-shirts (quick-dry)", "category": "Clothing", "conditions": {"temp_in": ["warm", "hot"]}, "quantity": {"calc": "ceil(cycle*0.8)"}},
        {"name": "Long-sleeve tops", "category": "Clothing", "conditions": {"temp_in": ["cold", "mild"]}, "quantity": {"calc": "ceil(cycle*0.6)"}},
        {"name": "Sweater/Fleece", "category": "Outerwear", "conditions": {"temp_in": ["cold", "mild"]}, "quantity": {"calc": "min(2, ceil(days/4))"}},

        # NOTE: this keeps your original ternary; evaluator supports it
        {"name": "Pants", "category": "Clothing", "conditions": {"always": True},
         "quantity": {"calc": "ceil(cycle / (1.5 if temp_profile in ['cold','mild'] else 2.0))"}},

        {"name": "Shorts", "category": "Clothing", "conditions": {"temp_in": ["warm", "hot"]}, "quantity": {"calc": "ceil(cycle/2)"}},
        {"name": "Sleepwear", "category": "Clothing", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Light rain jacket", "category": "Outerwear", "conditions": {"temp_in": ["mild", "warm", "hot"]}, "quantity": {"calc": "1"}},
        {"name": "Warm jacket/coat", "category": "Outerwear", "conditions": {"season_in": ["winter"]}, "quantity": {"calc": "1"}},
        {"name": "Comfortable shoes", "category": "Footwear", "conditions": {"always": True}, "quantity": {"calc": "1"}},
        {"name": "Cap/sun hat", "category": "Misc", "conditions": {"temp_in": ["warm", "hot"]}, "quantity": {"calc": "1"}},
        {"name": "Beanie + gloves", "category": "Misc", "conditions": {"temp_in": ["cold"]}, "quantity": {"calc": "1"}},

        # Weather-informed extras
        {"name": "Umbrella or rain cover", "category": "Outdoor",
         "conditions": {"any": [{"precip_mm_gt": 5}, {"activity_in": ["hiking"]}]}, "quantity": {"calc": "1"}},
        {"name": "Hand warmers", "category": "Misc",
         "conditions": {"any": [{"snowfall_mm_gt": 5}, {"season_in": ["winter"]}]}, "quantity": {"calc": "1"}},
        {"name": "Travel-size bottles", "category": "Toiletries",
         "conditions": {"carry_on_only": True}, "quantity": {"calc": "1"}},

        # Activities
        {"name": "Hiking socks", "category": "Clothing", "conditions": {"activity_in": ["hiking"]}, "quantity": {"calc": "max(1, cycle)"}},
        {"name": "Quick-dry shirts", "category": "Clothing", "conditions": {"activity_in": ["hiking"]}, "quantity": {"calc": "ceil(cycle*0.8)"}},
        {"name": "Trekking pants", "category": "Clothing", "conditions": {"activity_in": ["hiking"]}, "quantity": {"calc": "max(1, ceil(cycle/2))"}},
        {"name": "Trail shoes/boots", "category": "Footwear", "conditions": {"activity_in": ["hiking"]}, "quantity": {"calc": "1"}},
        {"name": "Daypack", "category": "Outdoor", "conditions": {"activity_in": ["hiking", "citytrip"]}, "quantity": {"calc": "1"}},

        {"name": "Ski jacket", "category": "Outerwear", "conditions": {"activity_in": ["ski"]}, "quantity": {"calc": "1"}},
        {"name": "Ski pants", "category": "Clothing", "conditions": {"activity_in": ["ski"]}, "quantity": {"calc": "1"}},
        {"name": "Thermal base layers", "category": "Clothing", "conditions": {"activity_in": ["ski"]}, "quantity": {"calc": "max(1, ceil(cycle*0.7))"}},
        {"name": "Ski socks", "category": "Clothing", "conditions": {"activity_in": ["ski"]}, "quantity": {"calc": "max(1, cycle)"}},
        {"name": "Goggles", "category": "Outdoor", "conditions": {"activity_in": ["ski"]}, "quantity": {"calc": "1"}},

        {"name": "Swimwear", "category": "Beach", "conditions": {"activity_in": ["beach"]}, "quantity": {"calc": "2"}},
        {"name": "Flip-flops", "category": "Beach", "conditions": {"activity_in": ["beach"]}, "quantity": {"calc": "1"}},
        {"name": "Beach towel (microfiber)", "category": "Beach", "conditions": {"activity_in": ["beach"]}, "quantity": {"calc": "1"}},

        {"name": "Nicer outfit", "category": "Clothing", "conditions": {"activity_in": ["citytrip", "business"]}, "quantity": {"calc": "1"}},
        {"name": "Laptop + charger", "category": "Electronics", "conditions": {"activity_in": ["business"]}, "quantity": {"calc": "1"}},
    ],
    "post_processing": {"merge_duplicates": True, "floor_min": 1},
}


def load_rules() -> Dict[str, Any]:
    """Load rules JSON from instance/rules.json (create default if missing)."""
    if not RULES_PATH.exists():
        RULES_PATH.write_text(json.dumps(DEFAULT_RULES, indent=2), encoding="utf-8")
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def save_rules(data: Dict[str, Any]) -> None:
    """Persist rules JSON to instance/rules.json."""
    RULES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_weather_mode() -> str:
    """Get global weather mode: 'online' or 'offline' (default)."""
    return WEATHER_MODE_PATH.read_text().strip() if WEATHER_MODE_PATH.exists() else "offline"


def set_weather_mode(mode: str) -> None:
    """Set global weather mode."""
    WEATHER_MODE_PATH.write_text(mode)


# =============================================================================
# Weather & Season inference helpers
# =============================================================================


def infer_meteorological_season(lat: Optional[float], d: date) -> str:
    """Return meteorological season ('winter'/'spring'/'summer'/'autumn'/'tropical')."""
    m = d.month
    if lat is not None and abs(lat) < 10:
        return "tropical"
    northern = (lat is None) or (lat >= 0)
    if northern:
        if m in (12, 1, 2):
            return "winter"
        if m in (3, 4, 5):
            return "spring"
        if m in (6, 7, 8):
            return "summer"
        return "autumn"
    else:
        if m in (6, 7, 8):
            return "winter"
        if m in (9, 10, 11):
            return "spring"
        if m in (12, 1, 2):
            return "summer"
        return "autumn"


def decide_temp_profile(avg_c: Optional[float]) -> str:
    """Map average temperature (°C) to one of cold/mild/warm/hot (mild if unknown)."""
    if avg_c is None:
        return "mild"
    if avg_c < 5:
        return "cold"
    if avg_c < 15:
        return "mild"
    if avg_c < 25:
        return "warm"
    return "hot"


def days_between(start: date, end: date) -> int:
    return max(1, (end - start).days + 1)


def geocode_location_nominatim(q: str) -> Optional[Tuple[float, float]]:
    """Forward geocode using Nominatim public endpoint. Returns (lat, lon) or None."""
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
    """
    Fetch daily Open‑Meteo summary for date range.
    Returns (avg_temp_c, precip_sum_mm, snowfall_sum_mm).
    """
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


# =============================================================================
# RuleEngine with SafeExprEvaluator
# =============================================================================


class SafeExprEvaluator:
    """
    Safely evaluate small arithmetic/boolean expressions used in quantity.calc.
    Supported:
      - Literals, names from ALLOWED_NAMES
      - +, -, *, /, //, %
      - unary +, -
      - Functions: ceil, floor, round, min, max
      - Conditional (X if cond else Y)
      - Comparisons: == != < <= > >= in / not in (with constant list/tuple)
    """

    ALLOWED_FUNCS = {
        "ceil": math.ceil,
        "floor": math.floor,
        "round": round,
        "min": min,
        "max": max,
    }
    ALLOWED_NAMES = {"days", "cycle", "avg_temp_c", "precip_mm", "snowfall_mm", "temp_profile"}

    def eval(self, expression: str, context: dict) -> int:
        node = ast.parse(str(expression), mode="eval")
        value = self._eval_node(node.body, context)
        return max(1, int(math.ceil(float(value))))

    def _eval_node(self, node, ctx):
        # Literals & names
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.ALLOWED_NAMES:
                raise ValueError(f"Unknown name '{node.id}'")
            return ctx.get(node.id, 0)

        # Arithmetic
        if isinstance(node, ast.BinOp):
            l = self._eval_node(node.left, ctx)
            r = self._eval_node(node.right, ctx)
            if isinstance(node.op, ast.Add):
                return l + r
            if isinstance(node.op, ast.Sub):
                return l - r
            if isinstance(node.op, ast.Mult):
                return l * r
            if isinstance(node.op, ast.Div):
                return l / r
            if isinstance(node.op, ast.FloorDiv):
                return l // r
            if isinstance(node.op, ast.Mod):
                return l % r
            raise ValueError("Operator not allowed")

        if isinstance(node, ast.UnaryOp):
            o = self._eval_node(node.operand, ctx)
            if isinstance(node.op, ast.UAdd):
                return +o
            if isinstance(node.op, ast.USub):
                return -o

        # Whitelisted functions (NOTE: correct scope, not nested under UnaryOp)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn not in self.ALLOWED_FUNCS:
                raise ValueError(f"Function '{fn}' not allowed")
            args = [self._eval_node(a, ctx) for a in node.args]
            return self.ALLOWED_FUNCS[fn](*args)

        # Conditional expression: X if cond else Y
        if isinstance(node, ast.IfExp):
            cond = self._eval_bool(node.test, ctx)
            return self._eval_node(node.body if cond else node.orelse, ctx)

        # Comparisons -> return 1 or 0 (so arithmetic can continue)
        if isinstance(node, ast.Compare):
            return 1 if self._eval_bool(node, ctx) else 0

        raise ValueError("Unsupported expression")

    # Boolean helpers
    def _eval_bool(self, node, ctx) -> bool:
        if isinstance(node, ast.Name):
            return bool(ctx.get(node.id, None))

        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value

        if isinstance(node, ast.Compare):
            left_val = self._eval_node(node.left, ctx)
            result = True
            for op, comparator in zip(node.ops, node.comparators):
                right_val = self._eval_comparator_value(comparator, ctx)
                if isinstance(op, ast.Eq):
                    ok = (left_val == right_val)
                elif isinstance(op, ast.NotEq):
                    ok = (left_val != right_val)
                elif isinstance(op, ast.Lt):
                    ok = (left_val < right_val)
                elif isinstance(op, ast.LtE):
                    ok = (left_val <= right_val)
                elif isinstance(op, ast.Gt):
                    ok = (left_val > right_val)
                elif isinstance(op, ast.GtE):
                    ok = (left_val >= right_val)
                elif isinstance(op, ast.In):
                    ok = self._in_membership(left_val, right_val)
                elif isinstance(op, ast.NotIn):
                    ok = not self._in_membership(left_val, right_val)
                else:
                    raise ValueError("Comparison operator not allowed")

                if not ok:
                    result = False
                    break
                left_val = right_val  # support chained comparisons
            return result

        raise ValueError("Unsupported boolean expression")

    def _eval_comparator_value(self, node, ctx):
        # allow constants, names, lists/tuples of constants, or simple arithmetic/calls
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.ALLOWED_NAMES:
                raise ValueError(f"Unknown name '{node.id}'")
            return ctx.get(node.id, None)
        if isinstance(node, (ast.List, ast.Tuple)):
            vals = []
            for elt in node.elts:
                if isinstance(elt, ast.Constant):
                    vals.append(elt.value)
                else:
                    raise ValueError("Only constant lists/tuples allowed")
            return tuple(vals)
        if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Call, ast.IfExp, ast.Compare)):
            return self._eval_node(node, ctx)
        raise ValueError("Unsupported comparator value")

    @staticmethod
    def _in_membership(left, right) -> bool:
        if isinstance(right, (list, tuple)):
            return left in right
        return False


def cond_pass(cond: dict, ctx: dict) -> bool:
    """Evaluate rule.conditions against trip context."""
    if not cond:
        return False
    if cond.get("always"):
        return True

    # Flags
    if "carry_on_only" in cond and bool(cond["carry_on_only"]) != bool(ctx["carry_on_only"]):
        return False

    # Membership
    if "season_in" in cond and ctx["season"] not in cond["season_in"]:
        return False
    if "temp_in" in cond and ctx["temp_profile"] not in cond["temp_in"]:
        return False
    if "activity_in" in cond:
        have = set(ctx["activities"])
        want = set(cond["activity_in"])
        if have.isdisjoint(want):
            return False

    # Numeric thresholds (ignore None values)
    if "days_ge" in cond and not (ctx["days"] >= cond["days_ge"]):
        return False
    if "days_le" in cond and not (ctx["days"] <= cond["days_le"]):
        return False
    if "cycle_ge" in cond and not (ctx["cycle"] >= cond["cycle_ge"]):
        return False
    if "cycle_le" in cond and not (ctx["cycle"] <= cond["cycle_le"]):
        return False
    if "avg_temp_c_lt" in cond and ctx["avg_temp_c"] is not None and not (ctx["avg_temp_c"] < cond["avg_temp_c_lt"]):
        return False
    if "avg_temp_c_ge" in cond and ctx["avg_temp_c"] is not None and not (ctx["avg_temp_c"] >= cond["avg_temp_c_ge"]):
        return False
    if "precip_mm_gt" in cond and ctx["precip_mm"] is not None and not (ctx["precip_mm"] > cond["precip_mm_gt"]):
        return False
    if "snowfall_mm_gt" in cond and ctx["snowfall_mm"] is not None and not (ctx["snowfall_mm"] > cond["snowfall_mm_gt"]):
        return False

    # Logic combinators
    def eval_block(b) -> bool:
        return cond_pass(b, ctx)

    if "all" in cond and not all(eval_block(b) for b in cond["all"]):
        return False
    if "any" in cond and cond["any"] and not any(eval_block(b) for b in cond["any"]):
        return False
    if "not" in cond and eval_block(cond["not"]):
        return False

    return True


class RuleEngine:
    """Apply data-driven packing rules to a given Trip."""

    def __init__(self, rules: dict):
        self.rules = rules
        self.evalr = SafeExprEvaluator()

    def compute(self, trip: Trip) -> List[Tuple[str, str, int]]:
        days = days_between(trip.start_date, trip.end_date)
        cycle = min(days, max(1, trip.laundry_every_n_days))
        ctx = {
            "days": days,
            "cycle": cycle,
            "season": trip.season or "autumn",
            "temp_profile": trip.temp_profile or "mild",
            "avg_temp_c": trip.avg_temp_c,
            "precip_mm": trip.precip_mm,
            "snowfall_mm": trip.snowfall_mm,
            "carry_on_only": bool(trip.carry_on_only),
            "activities": [a for a in (trip.activities or "").split(",") if a],
        }

        out: List[Tuple[str, str, int]] = []
        for rule in self.rules.get("items", []):
            if cond_pass(rule.get("conditions", {}), ctx):
                calc = (rule.get("quantity") or {}).get("calc", "1")
                qty = self.evalr.eval(calc, {**ctx, "temp_profile": ctx["temp_profile"]})
                out.append((rule["name"], rule["category"], qty))

        # Post-processing: merge duplicates, enforce floor_min
        if self.rules.get("post_processing", {}).get("merge_duplicates", True):
            merged: Dict[Tuple[str, str], int] = {}
            for n, c, q in out:
                merged[(n, c)] = merged.get((n, c), 0) + q
            out = [(n, c, q) for (n, c), q in merged.items()]

        floor_min = int(self.rules.get("post_processing", {}).get("floor_min", 1))
        out = [(n, c, max(floor_min, q)) for (n, c, q) in out]
        return out


# =============================================================================
# Routes
# =============================================================================


@app.route("/", methods=["GET"])
def home():
    return redirect(url_for("list_trips"))


@app.route("/trips", methods=["GET"], endpoint="list_trips")
def list_trips():
    trips = Trip.query.order_by(Trip.id.desc()).all()
    counts = {
        t.id: {
            "total": Item.query.filter_by(trip_id=t.id).count(),
            "packed": Item.query.filter_by(trip_id=t.id, packed=True).count(),
        }
        for t in trips
    }
    return render_template("trips.html", trips=trips, counts=counts, weather_mode=get_weather_mode())


@app.get("/plan")
def plan():
    return render_template("plan.html", activity_choices=ACTIVITY_CHOICES, weather_mode=get_weather_mode())


@app.post("/plan")
def create_and_generate():
    # Gather inputs
    name = (request.form.get("name") or "").strip()
    destination = (request.form.get("destination") or "").strip()
    start = request.form.get("start_date")
    end = request.form.get("end_date")
    laundry_n = int(request.form.get("laundry_every_n_days") or 3)
    carry_on_only = bool(request.form.get("carry_on_only"))
    activities = request.form.getlist("activities")

    if not destination or not start or not end:
        flash("Destination and both dates are required.", "error")
        return redirect(url_for("plan"))

    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
        if end_date < start_date:
            raise ValueError("End date must be after start date.")
    except Exception as e:
        flash(f"Invalid dates: {e}", "error")
        return redirect(url_for("plan"))

    # Weather/season inference from simple toggle file
    lat = lon = None
    avg_c = precip = snow = None
    season = "autumn"
    weather_source = "none"

    mode = get_weather_mode()  # 'online' or 'offline'
    if mode == "online":
        coords = geocode_location_nominatim(destination)
        if coords:
            lat, lon = coords
            season = infer_meteorological_season(lat, start_date)
            avg_c, precip, snow = fetch_weather_open_meteo(lat, lon, start_date, end_date)
            weather_source = "open-meteo"
        else:
            season = infer_meteorological_season(None, start_date)
            weather_source = "heuristic"
    else:
        season = infer_meteorological_season(None, start_date)
        weather_source = "heuristic"

    temp_profile = decide_temp_profile(avg_c)

    trip = Trip(
        name=name or f"{destination} trip",
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        season=season,
        temp_profile=temp_profile,
        avg_temp_c=avg_c,
        precip_mm=precip,
        snowfall_mm=snow,
        weather_source=weather_source,
        laundry_every_n_days=max(1, laundry_n),
        carry_on_only=carry_on_only,
        activities=",".join(activities),
        latitude=lat,
        longitude=lon,
    )
    db.session.add(trip)
    db.session.commit()

    # Apply rules
    rules = load_rules()
    engine = RuleEngine(rules)
    items = engine.compute(trip)
    for (iname, category, qty) in items:
        db.session.add(
            Item(trip_id=trip.id, name=iname, category=category, quantity=qty, packed=False)
        )
    db.session.commit()

    return redirect(url_for("trip_detail", trip_id=trip.id))


@app.get("/trips/<int:trip_id>")
def trip_detail(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    items = Item.query.filter_by(trip_id=trip.id).order_by(Item.category, Item.id).all()
    grouped: Dict[str, List[Item]] = {}
    for i in items:
        grouped.setdefault(i.category or "Misc", []).append(i)
    packed = sum(1 for i in items if i.packed)
    total = len(items)
    return render_template(
        "trip_detail.html",
        trip=trip,
        grouped=grouped,
        total=total,
        packed=packed,
        weather_mode=get_weather_mode(),
    )


# --- Item actions -------------------------------------------------------------


@app.post("/items/<int:item_id>/toggle")
def toggle_item(item_id):
    item = Item.query.get_or_404(item_id)
    item.packed = not item.packed
    db.session.commit()
    return redirect(url_for("trip_detail", trip_id=item.trip_id))


@app.post("/items/<int:item_id>/qty")
def set_qty(item_id):
    item = Item.query.get_or_404(item_id)
    try:
        delta = int(request.form.get("delta", "0"))
    except ValueError:
        delta = 0
    item.quantity = max(1, item.quantity + delta)
    db.session.commit()
    return redirect(url_for("trip_detail", trip_id=item.trip_id))


@app.post("/items/<int:item_id>/delete")
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    trip_id = item.trip_id
    db.session.delete(item)
    db.session.commit()
    flash("Item deleted.", "success")
    return redirect(url_for("trip_detail", trip_id=trip_id))


@app.post("/trips/<int:trip_id>/category/mark_all")
def mark_category_packed(trip_id):
    category = (request.form.get("category") or "").strip()
    q = Item.query.filter_by(trip_id=trip_id)
    if category:
        q = q.filter_by(category=category)
    q.update({Item.packed: True})
    db.session.commit()
    return redirect(url_for("trip_detail", trip_id=trip_id))


@app.post("/trips/<int:trip_id>/delete")
def delete_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    db.session.delete(trip)
    db.session.commit()
    flash("Trip deleted.", "success")
    return redirect(url_for("list_trips"))


# --- Trip import/export & regenerate ------------------------------------------


@app.get("/trips/<int:trip_id>/export")
def export_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    items = Item.query.filter_by(trip_id=trip.id).all()
    return jsonify(
        {
            "trip": {
                "name": trip.name,
                "destination": trip.destination,
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
                "season": trip.season,
                "temp_profile": trip.temp_profile,
                "avg_temp_c": trip.avg_temp_c,
                "precip_mm": trip.precip_mm,
                "snowfall_mm": trip.snowfall_mm,
                "weather_source": trip.weather_source,
                "activities": [a for a in (trip.activities or "").split(",") if a],
                "laundry_every_n_days": trip.laundry_every_n_days,
                "carry_on_only": trip.carry_on_only,
                "latitude": trip.latitude,
                "longitude": trip.longitude,
            },
            "items": [
                {"name": i.name, "category": i.category, "qty": i.quantity, "packed": i.packed}
                for i in items
            ],
        }
    )


@app.post("/trips/<int:trip_id>/import")
def import_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    data = request.get_json(silent=True) or {}
    arr = data.get("items", [])
    for obj in arr:
        iname = (obj.get("name") or "").strip()
        if not iname:
            continue
        db.session.add(
            Item(
                trip_id=trip.id,
                name=iname,
                category=(obj.get("category") or "Misc"),
                quantity=max(1, int(obj.get("qty") or 1)),
                packed=bool(obj.get("packed", False)),
            )
        )
    db.session.commit()
    flash(f"Imported {len(arr)} items.", "success")
    return redirect(url_for("trip_detail", trip_id=trip.id))


@app.post("/trips/<int:trip_id>/regenerate")
def regenerate_trip_items(trip_id):
    """
    Re-apply current rules to the given trip.
    If 'replace' is provided, existing items are deleted first.
    """
    trip = Trip.query.get_or_404(trip_id)

    if bool(request.form.get("replace")):
        Item.query.filter_by(trip_id=trip.id).delete()

    rules = load_rules()
    engine = RuleEngine(rules)
    computed = engine.compute(trip)

    for (iname, category, qty) in computed:
        db.session.add(
            Item(
                trip_id=trip.id,
                name=iname,
                category=category,
                quantity=max(1, int(qty)),
                packed=False,
            )
        )
    db.session.commit()
    flash("Items regenerated from current rules.", "success")
    return redirect(url_for("trip_detail", trip_id=trip.id))


# --- Rules page + import/export -----------------------------------------------


@app.get("/rules")
def rules_page():
    rules = load_rules()
    return render_template("rules.html", rules=rules, weather_mode=get_weather_mode())


@app.post("/rules/import")
def import_rules():
    file = request.files.get("file")
    if not file:
        flash("No file uploaded", "error")
        return redirect(url_for("rules_page"))
    try:
        data = json.load(file)
        if not isinstance(data, dict) or "items" not in data:
            raise ValueError("Rules JSON must contain an 'items' array")
        save_rules(data)
        flash("Rules updated", "success")
    except Exception as e:
        flash(f"Invalid JSON: {e}", "error")
    return redirect(url_for("rules_page"))


@app.get("/rules/export")
def export_rules():
    load_rules()  # ensure file exists
    return send_file(RULES_PATH, as_attachment=True)


# --- Weather toggle (global) --------------------------------------------------


@app.post("/settings/weather")
def toggle_weather():
    mode = get_weather_mode()
    new_mode = "online" if mode == "offline" else "offline"
    set_weather_mode(new_mode)
    flash(f"Weather mode set to {new_mode}", "success")
    return redirect(request.referrer or url_for("rules_page"))


# --- Debug: list endpoints ----------------------------------------------------


@app.get("/_site_map")
def _site_map():
    routes = [{"endpoint": r.endpoint, "rule": r.rule} for r in app.url_map.iter_rules()]
    return jsonify(routes)


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    app.run(debug=True)
