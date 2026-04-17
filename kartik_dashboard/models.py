from __future__ import annotations

from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, default="Kartik")
    pin_hash = db.Column(db.String(255), nullable=False)
    streak_count = db.Column(db.Integer, nullable=False, default=1)
    last_login_at = db.Column(db.DateTime, nullable=True)

    tasks = db.relationship("Task", backref="user", lazy=True, cascade="all, delete-orphan")
    alarms = db.relationship("Alarm", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_pin(self, pin: str) -> None:
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin: str) -> bool:
        return check_password_hash(self.pin_hash, pin)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    # Stored as "HH:MM" (24h) for comparison/alarms; UI always shows 12h.
    time = db.Column(db.String(5), nullable=False)
    status = db.Column(db.String(16), nullable=False)  # "Fixed" | "Flexible"
    completed = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    alarm = db.relationship("Alarm", backref="task", uselist=False, cascade="all, delete-orphan")


class Alarm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)

    # Stored as "HH:MM" (24h)
    time = db.Column(db.String(5), nullable=False)
    label = db.Column(db.String(200), nullable=False, default="Alarm")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

