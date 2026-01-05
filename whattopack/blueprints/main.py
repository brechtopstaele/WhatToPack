
from __future__ import annotations
from datetime import datetime
from typing import Dict, List
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from ..extensions import db
from ..models import Trip, Item
from ..domain.util import days_between, infer_meteorological_season, decide_temp_profile
from ..domain.engine import RuleEngine
from ..services.rules_storage import load_rules, get_weather_mode, set_weather_mode
from ..services.weather import geocode_location_nominatim, fetch_weather_open_meteo

bp = Blueprint("main", __name__)

ACTIVITY_CHOICES = ["ski", "hiking", "citytrip", "beach", "camping", "business", "photography", "diving"]

@bp.get("/")
def home():
    return redirect(url_for("main.list_trips"))

@bp.route("/trips", methods=["GET"], endpoint="list_trips")
def list_trips():
    trips = Trip.query.order_by(Trip.id.desc()).all()
    counts = {
        t.id: {
            "total": Item.query.filter_by(trip_id=t.id).count(),
            "packed": Item.query.filter_by(trip_id=t.id, packed=True).count(),
        }
        for t in trips
    }
    return render_template("trips.html", trips=trips, counts=counts)

@bp.get("/plan", endpoint="plan")
def plan():
    return render_template("plan.html", activity_choices=ACTIVITY_CHOICES)

@bp.post("/plan")
def create_and_generate():
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

    # Weather/season inference
    lat = lon = None
    avg_c = precip = snow = None
    season = "autumn"
    weather_source = "none"

    mode = get_weather_mode()
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
        start_date=start_date, end_date=end_date,
        season=season, temp_profile=temp_profile,
        avg_temp_c=avg_c, precip_mm=precip, snowfall_mm=snow,
        weather_source=weather_source,
        laundry_every_n_days=max(1, laundry_n),
        carry_on_only=carry_on_only,
        activities=",".join(activities),
        latitude=lat, longitude=lon,
    )
    db.session.add(trip)
    db.session.commit()

    # Apply rules
    rules = load_rules()
    items = RuleEngine(rules).compute(trip)
    for (iname, category, qty) in items:
        db.session.add(Item(trip_id=trip.id, name=iname, category=category, quantity=qty, packed=False))
    db.session.commit()

    return redirect(url_for("main.trip_detail", trip_id=trip.id))

@bp.get("/trips/<int:trip_id>")
def trip_detail(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    items = Item.query.filter_by(trip_id=trip.id).order_by(Item.category, Item.id).all()
    grouped: Dict[str, List[Item]] = {}
    for i in items:
        grouped.setdefault(i.category or "Misc", []).append(i)
    packed = sum(1 for i in items if i.packed)
    total = len(items)
    return render_template("trip_detail.html", trip=trip, grouped=grouped, total=total, packed=packed)

# Item actions
@bp.post("/items/<int:item_id>/toggle")
def toggle_item(item_id):
    item = Item.query.get_or_404(item_id)
    item.packed = not item.packed
    db.session.commit()
    return redirect(url_for("main.trip_detail", trip_id=item.trip_id))

# JSON endpoint
@bp.post("/api/items/<int:item_id>/toggle")
def api_toggle_item(item_id):
    item = Item.query.get_or_404(item_id)
    item.packed = not item.packed
    db.session.commit()
    # also send category counts if you want a progress bar update
    packed_count = Item.query.filter_by(trip_id=item.trip_id, packed=True).count()
    total_count = Item.query.filter_by(trip_id=item.trip_id).count()
    return jsonify({
        "ok": True,
        "item_id": item.id,
        "packed": item.packed,
        "trip_id": item.trip_id,
        "progress": {"packed": packed_count, "total": total_count}
    })

@bp.post("/items/<int:item_id>/qty")
def set_qty(item_id):
    item = Item.query.get_or_404(item_id)
    try:
        delta = int(request.form.get("delta", "0"))
    except ValueError:
        delta = 0
    item.quantity = max(1, item.quantity + delta)
    db.session.commit()
    return redirect(url_for("main.trip_detail", trip_id=item.trip_id))

# JSON endpoint
@bp.post("/api/items/<int:item_id>/qty")
def api_set_qty(item_id):
    item = Item.query.get_or_404(item_id)
    try:
        delta = int(request.json.get("delta", 0)) if request.is_json else int(request.form.get("delta", 0))
    except Exception:
        delta = 0
    item.quantity = max(1, item.quantity + delta)
    db.session.commit()
    return jsonify({
        "ok": True,
        "item_id": item.id,
        "quantity": item.quantity
    })

@bp.post("/items/<int:item_id>/delete")
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    trip_id = item.trip_id
    db.session.delete(item)
    db.session.commit()
    flash("Item deleted.", "success")
    return redirect(url_for("main.trip_detail", trip_id=trip_id))

# JSON endpoint
@bp.post("/api/items/<int:item_id>/delete")
def api_delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    trip_id = item.trip_id
    db.session.delete(item)
    db.session.commit()
    packed = Item.query.filter_by(trip_id=trip_id, packed=True).count()
    total = Item.query.filter_by(trip_id=trip_id).count()
    return jsonify({
        "ok": True,
        "item_id": item_id,
        "deleted": True,
        "progress": {"packed": packed, "total": total}
    })

@bp.post("/trips/<int:trip_id>/category/mark_all")
def mark_category_packed(trip_id):
    category = (request.form.get("category") or "").strip()
    q = Item.query.filter_by(trip_id=trip_id)
    if category:
        q = q.filter_by(category=category)
    q.update({Item.packed: True})
    db.session.commit()
    return redirect(url_for("main.trip_detail", trip_id=trip_id))

@bp.post("/trips/<int:trip_id>/delete")
def delete_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    db.session.delete(trip)
    db.session.commit()
    flash("Trip deleted.", "success")
    return redirect(url_for("main.list_trips"))

# Trip import/export & regenerate
@bp.get("/trips/<int:trip_id>/export")
def export_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    items = Item.query.filter_by(trip_id=trip.id).all()
    return jsonify({
        "trip": {
            "name": trip.name, "destination": trip.destination,
            "start_date": trip.start_date.isoformat(), "end_date": trip.end_date.isoformat(),
            "season": trip.season, "temp_profile": trip.temp_profile,
            "avg_temp_c": trip.avg_temp_c, "precip_mm": trip.precip_mm, "snowfall_mm": trip.snowfall_mm,
            "weather_source": trip.weather_source, "activities": [a for a in (trip.activities or "").split(",") if a],
            "laundry_every_n_days": trip.laundry_every_n_days, "carry_on_only": trip.carry_on_only,
            "latitude": trip.latitude, "longitude": trip.longitude
        },
        "items": [{"name": i.name, "category": i.category, "qty": i.quantity, "packed": i.packed} for i in items]
    })

@bp.post("/trips/<int:trip_id>/import")
def import_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    data = request.get_json(silent=True) or {}
    arr = data.get("items", [])
    for obj in arr:
        iname = (obj.get("name") or "").strip()
        if not iname: continue
        db.session.add(Item(
            trip_id=trip.id, name=iname, category=(obj.get("category") or "Misc"),
            quantity=max(1, int(obj.get("qty") or 1)), packed=bool(obj.get("packed", False))
        ))
    db.session.commit()
    flash(f"Imported {len(arr)} items.", "success")
    return redirect(url_for("main.trip_detail", trip_id=trip.id))

@bp.post("/trips/<int:trip_id>/regenerate", endpoint="regenerate_trip_items")
def regenerate_trip_items(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if bool(request.form.get("replace")):
        Item.query.filter_by(trip_id=trip.id).delete()
    rules = load_rules()
    computed = RuleEngine(rules).compute(trip)
    for (iname, category, qty) in computed:
        db.session.add(Item(trip_id=trip.id, name=iname, category=category, quantity=max(1, int(qty)), packed=False))
    db.session.commit()
    flash("Items regenerated from current rules.", "success")
    return redirect(url_for("main.trip_detail", trip_id=trip.id))

# Weather toggle
@bp.post("/settings/weather")
def toggle_weather():
    mode = get_weather_mode()
    set_weather_mode("online" if mode == "offline" else "offline")
    flash(f"Weather mode set to {'online' if mode == 'offline' else 'offline'}", "success")
    return redirect(request.referrer or url_for("rules.rules_page"))

# Debug endpoint map
@bp.get("/_site_map")
def _site_map():
    from flask import current_app
    routes = [{"endpoint": r.endpoint, "rule": r.rule} for r in current_app.url_map.iter_rules()]
    return jsonify(routes)
