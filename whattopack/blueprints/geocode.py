
from __future__ import annotations
from flask import Blueprint, request, jsonify
import os, requests

bp = Blueprint("geocode", __name__, url_prefix="/api")

MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN")  # public-scoped token

@bp.get("/geocode")
def geocode():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"features": []})

    params = {
        "access_token": MAPBOX_TOKEN,
        "autocomplete": "true",
        "limit": request.args.get("limit", 7),
        "language": request.args.get("language"),           # e.g. 'nl'
        "types": request.args.get("types", "place,locality,address,poi"),
        "country": request.args.get("country"),              # e.g. 'be'
        "proximity": request.args.get("proximity")           # "lon,lat" for bias
    }
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{requests.utils.quote(q)}.json"
    r = requests.get(url, params={k: v for k, v in params.items() if v})
    r.raise_for_status()
    data = r.json()

    features = [
        {
            "id": f["id"],
            "text": f.get("text"),
            "place_name": f.get("place_name"),
            "center": f.get("center"),
        }
        for f in data.get("features", [])
    ]
    return jsonify({"features": features})

