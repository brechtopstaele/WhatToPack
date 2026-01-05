
from __future__ import annotations
from pathlib import Path
from flask import Flask
from flask_migrate import Migrate
from .extensions import db
from .models import Trip, Item  # ensure models are imported for create_all
from .blueprints.main import bp as main_bp
from .blueprints.rules import bp as rules_bp
from .services.rules_storage import get_weather_mode


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config["SECRET_KEY"] = "change-this-in-production"

    # Windows/Docker safe instance folder
    instance_dir = Path(app.instance_path)
    instance_dir.mkdir(parents=True, exist_ok=True)

    # SQLite file under instance/
    db_path = instance_dir / "packpal.sqlite"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.as_posix()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Init extensions
    db.init_app(app)

    # Create tables on first run
    with app.app_context():
        db.create_all()

    # Migrations
    migrate = Migrate(app, db)

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(rules_bp)

    # Context processor: inject weather_mode into all templates
    @app.context_processor
    def inject_globals():
        try:
            mode = get_weather_mode()
        except Exception:
            mode = "offline"
        return {"weather_mode": mode}

    return app
