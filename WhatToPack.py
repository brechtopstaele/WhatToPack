
# app.py
import os
from pathlib import Path
from datetime import datetime
from math import ceil
from typing import List, Dict, Tuple

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = "change-this-in-production"

# Ensure the instance directory exists (this is where we’ll store the DB)
instance_dir = Path(app.instance_path)
instance_dir.mkdir(parents=True, exist_ok=True)


# Build an absolute path to the DB file (forward slashes are OK on Windows for SQLAlchemy)
db_file = instance_dir / "packpal.sqlite"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

CATEGORIES = [
    "Documents", "Clothing", "Outerwear", "Footwear", "Toiletries",
    "Electronics", "Medication", "Outdoor", "Beach", "Business", "Photography", "Misc"
]

ACTIVITY_CHOICES = [
    "ski", "hiking", "citytrip", "beach", "camping", "business", "photography", "diving"
]

TEMP_CHOICES = ["cold", "mild", "warm", "hot"]  # user-selected temperature profile

# --- Models ---
class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140))
    destination = db.Column(db.String(140), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    temp_profile = db.Column(db.String(20), nullable=False)  # cold|mild|warm|hot
    laundry_every_n_days = db.Column(db.Integer, default=3)
    carry_on_only = db.Column(db.Boolean, default=True)
    activities = db.Column(db.String(240), default="")  # comma-separated tags

    items = db.relationship("Item", backref="trip", cascade="all, delete-orphan", lazy=True)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), default="Misc")
    quantity = db.Column(db.Integer, default=1)
    packed = db.Column(db.Boolean, default=False, index=True)

# Initialize DB once at startup
with app.app_context():
    print(f"[DB] Using {db_file}")  # helpful when debugging
    db.create_all()

# --- Helper: rules engine ---
def days_between(start: datetime.date, end: datetime.date) -> int:
    d = (end - start).days + 1
    return max(1, d)

def base_essentials() -> List[Tuple[str, str, int]]:
    return [
        ("Passport/ID", "Documents", 1),
        ("Wallet (cards, cash)", "Documents", 1),
        ("Phone", "Electronics", 1),
        ("Phone charger + cable", "Electronics", 1),
        ("Travel adapter", "Electronics", 1),
        ("Power bank", "Electronics", 1),
        ("Medications", "Medication", 1),
        ("Toothbrush", "Toiletries", 1),
        ("Toothpaste", "Toiletries", 1),
        ("Deodorant", "Toiletries", 1),
        ("Sunscreen", "Toiletries", 1),
    ]

def clothing_for_trip(days: int, temp: str, laundry_n: int) -> List[Tuple[str, str, int]]:
    # Pack for the longest stretch between laundries
    cycle = min(days, max(1, laundry_n))

    # Baseline quantities scaled by temperature
    underwear = cycle
    socks = cycle

    tshirts = ceil(cycle * (0.8 if temp in ("warm", "hot") else 0.5))
    longsleeves = ceil(cycle * (0.6 if temp in ("cold", "mild") else 0.2))
    sweaters = 2 if temp == "cold" else (1 if temp == "mild" else 0)

    pants = ceil(cycle / (1.5 if temp in ("cold", "mild") else 2.0))
    shorts = ceil(cycle / 2.0) if temp in ("warm", "hot") else 0

    outerwear = (1 if temp in ("cold", "mild") else 0)

    footwear_pairs = 2 if temp == "cold" else 1  # boots + sneakers in cold

    items = [
        ("Underwear", "Clothing", underwear),
        ("Socks", "Clothing", socks),
        ("T-shirts (quick-dry if possible)", "Clothing", tshirts),
        ("Long-sleeve tops", "Clothing", longsleeves),
        ("Sweater/Fleece", "Outerwear", sweaters) if sweaters else None,
        ("Pants", "Clothing", pants),
        ("Shorts", "Clothing", shorts) if shorts else None,
        ("Sleepwear", "Clothing", 1),
        ("Light rain jacket", "Outerwear", 1) if temp in ("mild", "warm", "hot") else None,
        ("Warm jacket/coat", "Outerwear", outerwear) if outerwear else None,
        ("Comfortable shoes", "Footwear", 1),
        ("Additional footwear", "Footwear", footwear_pairs - 1) if footwear_pairs > 1 else None,
        ("Cap/sun hat", "Misc", 1) if temp in ("warm", "hot") else None,
        ("Beanie + gloves", "Misc", 1) if temp == "cold" else None,
        ("Sunglasses", "Misc", 1),
        ("Reusable water bottle", "Misc", 1),
    ]
    return [i for i in items if i]

def activities_pack(acts: List[str], cycle: int, temp: str) -> List[Tuple[str, str, int]]:
    items: List[Tuple[str, str, int]] = []
    if "ski" in acts:
        items += [
            ("Ski jacket", "Outerwear", 1),
            ("Ski pants", "Clothing", 1),
            ("Thermal base layers", "Clothing", max(1, ceil(cycle * 0.7))),
            ("Ski socks", "Clothing", max(1, cycle)),
            ("Gloves/mittens", "Misc", 1),
            ("Beanie/neck gaiter", "Misc", 1),
            ("Goggles", "Outdoor", 1),
        ]
    if "hiking" in acts:
        items += [
            ("Hiking socks", "Clothing", max(1, cycle)),
            ("Quick-dry shirts", "Clothing", max(1, ceil(cycle * 0.8))),
            ("Trekking pants", "Clothing", max(1, ceil(cycle / 2))),
            ("Rain jacket", "Outerwear", 1),
            ("Trail shoes/boots", "Footwear", 1),
            ("Daypack", "Outdoor", 1),
            ("Water bladder/bottle", "Outdoor", 1),
            ("Small first-aid kit", "Outdoor", 1),
        ]
    if "citytrip" in acts:
        items += [
            ("Nicer outfit (dinner/museums)", "Clothing", 1),
            ("Daypack/sling", "Misc", 1),
            ("Comfortable walking shoes", "Footwear", 1),
        ]
    if "beach" in acts:
        items += [
            ("Swimwear", "Beach", 2),
            ("Flip-flops", "Beach", 1),
            ("Beach towel (microfiber)", "Beach", 1),
            ("After-sun lotion", "Toiletries", 1),
        ]
    if "camping" in acts:
        items += [
            ("Headlamp", "Outdoor", 1),
            ("Bug spray", "Toiletries", 1),
            ("Multi-tool", "Outdoor", 1),
            ("Sleeping bag/pad (if needed)", "Outdoor", 1),
        ]
    if "business" in acts:
        items += [
            ("Dress shirt", "Business", max(1, ceil(cycle / 2))),
            ("Blazer/jacket", "Business", 1),
            ("Slacks/skirt", "Business", 1),
            ("Dress shoes", "Business", 1),
            ("Laptop + charger", "Electronics", 1),
        ]
    if "photography" in acts:
        items += [
            ("Camera body", "Photography", 1),
            ("Lenses", "Photography", 1),
            ("SD cards", "Photography", 1),
            ("Battery + charger", "Photography", 1),
            ("Cleaning kit", "Photography", 1),
        ]
    if "diving" in acts:
        items += [
            ("Dive computer", "Outdoor", 1),
            ("Mask/snorkel (if not renting)", "Outdoor", 1),
            ("Rash guard/wetsuit (seasonal)", "Outdoor", 1),
        ]
    # Temperature nuance
    if temp == "hot":
        items.append(("Extra electrolyte sachets", "Outdoor", 1))
    if temp == "cold":
        items.append(("Extra warm mid-layer", "Outerwear", 1))
    return items

def compute_pack_for_trip(trip: Trip) -> List[Tuple[str, str, int]]:
    days = days_between(trip.start_date, trip.end_date)
    cycle = min(days, max(1, trip.laundry_every_n_days))
    temp = trip.temp_profile

    acts = [a.strip() for a in (trip.activities or "").split(",") if a.strip()]
    essentials = base_essentials()
    clothing = clothing_for_trip(days, temp, trip.laundry_every_n_days)
    act_specific = activities_pack(acts, cycle, temp)

    # Carry-on only constraints: collapse bulky items if necessary (hint for human)
    if trip.carry_on_only:
        # No change to quantities, but add a reminder item
        act_specific.append(("Travel-size bottles only", "Toiletries", 1))

    # Merge items with the same name/category by summing quantities
    merged: Dict[Tuple[str, str], int] = {}
    for name, cat, qty in essentials + clothing + act_specific:
        key = (name, cat)
        merged[key] = merged.get(key, 0) + max(1, int(qty))

    return [(name, cat, qty) for (name, cat), qty in merged.items()]

# --- Routes ---
@app.get("/")
def home():
    return redirect(url_for("plan"))

@app.get("/plan")
def plan():
    return render_template("plan.html", temp_choices=TEMP_CHOICES, activity_choices=ACTIVITY_CHOICES)

@app.post("/plan")
def create_and_generate():
    name = (request.form.get("name") or "").strip()
    destination = (request.form.get("destination") or "").strip()
    start = request.form.get("start_date")
    end = request.form.get("end_date")
    temp_profile = (request.form.get("temp_profile") or "mild").strip()
    laundry_n = int(request.form.get("laundry_every_n_days") or 3)
    carry_on_only = bool(request.form.get("carry_on_only"))
    activities = request.form.getlist("activities")  # list of selected tags

    # Validate
    if not destination or not start or not end:
        flash("Destination and both dates are required.", "error")
        return redirect(url_for("plan"))
    if temp_profile not in TEMP_CHOICES:
        temp_profile = "mild"

    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
        if end_date < start_date:
            raise ValueError("End date must be after start date.")
    except Exception as e:
        flash(f"Invalid dates: {e}", "error")
        return redirect(url_for("plan"))

    trip = Trip(
        name=name or f"{destination} trip",
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        temp_profile=temp_profile,
        laundry_every_n_days=max(1, laundry_n),
        carry_on_only=carry_on_only,
        activities=",".join(activities),
    )
    db.session.add(trip)
    db.session.commit()

    # Generate items
    items = compute_pack_for_trip(trip)
    for (name, category, qty) in items:
        db.session.add(Item(trip_id=trip.id, name=name, category=category, quantity=qty, packed=False))
    db.session.commit()

    return redirect(url_for("trip_detail", trip_id=trip.id))

@app.get("/trips/<int:trip_id>")
def trip_detail(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    items = Item.query.filter_by(trip_id=trip.id).order_by(Item.category, Item.id).all()
    grouped: Dict[str, List[Item]] = {cat: [] for cat in CATEGORIES}
    for i in items:
        grouped.setdefault(i.category or "Misc", []).append(i)
    packed = sum(1 for i in items if i.packed)
    total = len(items)
    return render_template("trip_detail.html", trip=trip, grouped=grouped, total=total, packed=packed)

# Item operations
@app.post("/items/<int:item_id>/toggle")
def toggle_item(item_id):
    item = Item.query.get_or_404(item_id)
    item.packed = not item.packed
    db.session.commit()
    return redirect(url_for("trip_detail", trip_id=item.trip_id))

@app.post("/items/<int:item_id>/qty")
def adjust_qty(item_id):
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

# Export / Import JSON
@app.get("/trips/<int:trip_id>/export")
def export_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    items = Item.query.filter_by(trip_id=trip.id).all()
    return jsonify({
        "trip": {
            "name": trip.name, "destination": trip.destination,
            "start_date": trip.start_date.isoformat(),
            "end_date": trip.end_date.isoformat(),
            "temp_profile": trip.temp_profile,
            "laundry_every_n_days": trip.laundry_every_n_days,
            "carry_on_only": trip.carry_on_only,
            "activities": [a for a in (trip.activities or "").split(",") if a],
        },
        "items": [
            {"name": i.name, "category": i.category, "qty": i.quantity, "packed": i.packed}
            for i in items
        ]
    })

@app.post("/trips/<int:trip_id>/import")
def import_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    for obj in items:
        name = (obj.get("name") or "").strip()
        if not name:
            continue
        db.session.add(Item(
            trip_id=trip.id,
            name=name,
            category=(obj.get("category") or "Misc"),
            quantity=max(1, int(obj.get("qty") or 1)),
            packed=bool(obj.get("packed", False)),
        ))
    db.session.commit()
    flash(f"Imported {len(items)} items.", "success")
    return redirect(url_for("trip_detail", trip_id=trip.id))

if __name__ == "__main__":
    app.run(debug=True)
