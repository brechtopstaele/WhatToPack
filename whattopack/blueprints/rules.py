
from __future__ import annotations
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from ..services.rules_storage import load_rules, save_rules
from pathlib import Path
from flask import current_app

bp = Blueprint("rules", __name__)

@bp.get("/rules", endpoint="rules_page")
def rules_page():
    rules = load_rules()
    return render_template("rules.html", rules=rules)

@bp.post("/rules/import")
def import_rules():
    file = request.files.get("file")
    if not file:
        flash("No file uploaded", "error")
        return redirect(url_for("rules_page"))
    try:
        import json
        data = json.load(file)
        if not isinstance(data, dict) or "items" not in data:
            raise ValueError("Rules JSON must contain an 'items' array")
        save_rules(data)
        flash("Rules updated", "success")
    except Exception as e:
        flash(f"Invalid JSON: {e}", "error")
    return redirect(url_for("rules_page"))

@bp.get("/rules/export")
def export_rules():
    load_rules()  # ensure file exists
    path = Path(current_app.instance_path) / "rules.json"
    return send_file(path, as_attachment=True)
