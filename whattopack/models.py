
from __future__ import annotations
from .extensions import db

class Trip(db.Model):
    __tablename__ = "trip"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140))
    destination = db.Column(db.String(140), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Inferred fields
    season = db.Column(db.String(20))          # winter/spring/summer/autumn/tropical
    temp_profile = db.Column(db.String(20))    # cold/mild/warm/hot
    avg_temp_c = db.Column(db.Float)
    precip_mm = db.Column(db.Float)
    snowfall_mm = db.Column(db.Float)
    weather_source = db.Column(db.String(40))  # 'open-meteo'|'heuristic'|'none'

    # Preferences
    laundry_every_n_days = db.Column(db.Integer, default=3)
    carry_on_only = db.Column(db.Boolean, default=True)
    activities = db.Column(db.String(240), default="")  # comma-separated

    # Optional geocoded
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    items = db.relationship("Item", backref="trip", cascade="all, delete-orphan", lazy=True)


class Item(db.Model):
    __tablename__ = "item"

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), default="Misc", index=True)
    quantity = db.Column(db.Integer, default=1)
    packed = db.Column(db.Boolean, default=False, index=True)
