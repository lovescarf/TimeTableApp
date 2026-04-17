import os
from flask import Flask
from sqlalchemy import inspect, text

from .extensions import db
from .routes import bp as routes_bp


def create_app() -> Flask:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    templates_dir = os.path.join(project_root, "templates")
    static_dir = os.path.join(project_root, "static")

    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=templates_dir,
        static_folder=static_dir,
    )

    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()
        inspector = inspect(db.engine)
        if inspector.has_table("task"):
            columns = {col["name"] for col in inspector.get_columns("task")}
            if "completed" not in columns:
                db.session.execute(text("ALTER TABLE task ADD COLUMN completed BOOLEAN NOT NULL DEFAULT 0"))
                db.session.commit()

    app.register_blueprint(routes_bp)
    return app

