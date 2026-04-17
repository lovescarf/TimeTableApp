from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .extensions import db
from .models import Alarm, Task, User
from .services_google_calendar import (
    add_calendar_event,
    build_oauth_flow,
    ensure_valid_creds,
    fetch_month_events,
    _save_creds,  # type: ignore
)
from .utils_time import add_minutes, apply_streak, hhmm_to_minutes, now_utc, subtract_minutes


bp = Blueprint("routes", __name__)


def _serialize_task(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "time_24h": task.time,
        "status": task.status,
        "completed": bool(task.completed),
    }


def _serialize_alarm(alarm: Alarm) -> dict:
    return {
        "id": alarm.id,
        "time_24h": alarm.time,
        "label": alarm.label,
        "is_active": bool(alarm.is_active),
        "task_id": alarm.task_id,
    }


def _shift_flexible_tasks(user_id: int, minutes: int, after_minutes: int | None = None) -> list[int]:
    flexible_tasks = (
        Task.query.filter_by(user_id=user_id, status="Flexible")
        .order_by(Task.time.asc(), Task.created_at.asc())
        .all()
    )
    shifted_task_ids: list[int] = []
    for task in flexible_tasks:
        task_minutes = hhmm_to_minutes(task.time)
        if after_minutes is not None and task_minutes <= after_minutes:
            continue
        task.time = add_minutes(task.time, minutes)
        shifted_task_ids.append(task.id)
        if task.alarm:
            task.alarm.time = add_minutes(task.alarm.time, minutes)
    return shifted_task_ids


def _apply_automatic_shift_for_user(user: User) -> dict:
    now_minutes = datetime.now().hour * 60 + datetime.now().minute
    pending_tasks = (
        Task.query.filter_by(user_id=user.id, completed=False)
        .order_by(Task.time.asc(), Task.created_at.asc())
        .all()
    )
    bypassed_task = None
    for task in pending_tasks:
        task_minutes = hhmm_to_minutes(task.time)
        if task_minutes < now_minutes:
            bypassed_task = task
        else:
            break

    if bypassed_task is None:
        return {"shifted": False, "shifted_minutes": 0, "shifted_task_ids": [], "bypassed_task_id": None}

    bypassed_minutes = hhmm_to_minutes(bypassed_task.time)
    elapsed = now_minutes - bypassed_minutes
    if elapsed <= 0:
        return {"shifted": False, "shifted_minutes": 0, "shifted_task_ids": [], "bypassed_task_id": None}

    shifted_task_ids = _shift_flexible_tasks(user.id, elapsed, after_minutes=bypassed_minutes)
    bypassed_task.completed = True
    db.session.commit()
    return {
        "shifted": bool(shifted_task_ids),
        "shifted_minutes": elapsed,
        "shifted_task_ids": shifted_task_ids,
        "bypassed_task_id": bypassed_task.id,
    }


def _current_user() -> User | None:
    uid = session.get("user_id")
    if not uid:
        return None
    return User.query.get(int(uid))


def _login_required():
    user = _current_user()
    if not user:
        return redirect(url_for("routes.login"))
    return None


@bp.route("/")
def root():
    user = _current_user()
    if user:
        return redirect(url_for("routes.dashboard"))
    return redirect(url_for("routes.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("index.html", mode="login")

    username = (request.form.get("username") or "Kartik").strip()
    pin = (request.form.get("pin") or "").strip()
    if not pin:
        return render_template("index.html", mode="login", error="PIN is required.", username=username), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_pin(pin):
        return render_template("index.html", mode="login", error="Invalid username or PIN.", username=username), 401

    now = now_utc()
    new_streak, new_last = apply_streak(user.streak_count, user.last_login_at, now)
    user.streak_count = new_streak
    user.last_login_at = new_last
    db.session.commit()

    session["user_id"] = user.id
    return redirect(url_for("routes.dashboard"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("index.html", mode="register")

    username = (request.form.get("username") or "Kartik").strip()
    pin = (request.form.get("pin") or "").strip()
    pin2 = (request.form.get("pin2") or "").strip()

    if not username:
        return render_template("index.html", mode="register", error="Username is required."), 400
    if not pin or len(pin) < 4:
        return render_template("index.html", mode="register", error="PIN must be at least 4 digits.", username=username), 400
    if pin != pin2:
        return render_template("index.html", mode="register", error="PINs do not match.", username=username), 400

    if User.query.filter_by(username=username).first():
        return render_template("index.html", mode="register", error="That username already exists.", username=username), 409

    user = User(username=username, streak_count=1, last_login_at=None)
    user.set_pin(pin)
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    # First successful login should set baseline
    now = now_utc()
    user.streak_count, user.last_login_at = apply_streak(user.streak_count, user.last_login_at, now)
    db.session.commit()

    return redirect(url_for("routes.dashboard"))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("routes.login"))


@bp.route("/dashboard")
def dashboard():
    guard = _login_required()
    if guard:
        return guard
    user = _current_user()
    assert user is not None
    return render_template("dashboard.html", username=user.username, streak=user.streak_count)


# -----------------------
# JSON APIs (Tasks/Alarms)
# -----------------------

@bp.route("/api/me")
def api_me():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401
    return jsonify(
        {
            "username": user.username,
            "streak": user.streak_count,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }
    )


@bp.route("/api/tasks", methods=["GET", "POST"])
def api_tasks():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    if request.method == "GET":
        tasks = (
            Task.query.filter_by(user_id=user.id)
            .order_by(Task.time.asc(), Task.created_at.asc())
            .all()
        )
        return jsonify([_serialize_task(t) for t in tasks])

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    time_24h = (data.get("time_24h") or "").strip()
    status = (data.get("status") or "Flexible").strip()
    alarm_offset_min = int(data.get("alarm_offset_min", 5))

    if not title:
        return jsonify({"error": "title_required"}), 400
    if not time_24h or len(time_24h) != 5 or ":" not in time_24h:
        return jsonify({"error": "time_required"}), 400
    if status not in ("Fixed", "Flexible"):
        return jsonify({"error": "invalid_status"}), 400
    if alarm_offset_min < 0 or alarm_offset_min > 120:
        return jsonify({"error": "invalid_alarm_offset"}), 400

    task = Task(user_id=user.id, title=title, time=time_24h, status=status, completed=False)
    db.session.add(task)
    db.session.flush()  # get task.id

    alarm_time = subtract_minutes(time_24h, alarm_offset_min) if alarm_offset_min else time_24h
    alarm = Alarm(
        user_id=user.id,
        task_id=task.id,
        time=alarm_time,
        label=f"{title}",
        is_active=True,
    )
    db.session.add(alarm)
    db.session.commit()

    return jsonify(
        {
            "task": _serialize_task(task),
            "alarm": {"id": alarm.id, "time_24h": alarm.time, "label": alarm.label, "is_active": alarm.is_active},
        }
    ), 201


@bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_task_delete(task_id: int):
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    task = Task.query.filter_by(id=task_id, user_id=user.id).first()
    if not task:
        return jsonify({"error": "not_found"}), 404

    db.session.delete(task)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/shift-tasks", methods=["POST"])
def api_shift_tasks():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    try:
        minutes = int(data.get("minutes_wasted", 0))
    except Exception:
        return jsonify({"error": "invalid_minutes"}), 400

    if minutes <= 0 or minutes > 12 * 60:
        return jsonify({"error": "minutes_out_of_range"}), 400

    shifted_task_ids = _shift_flexible_tasks(user.id, minutes)

    db.session.commit()

    tasks = (
        Task.query.filter_by(user_id=user.id)
        .order_by(Task.time.asc(), Task.created_at.asc())
        .all()
    )
    alarms = (
        Alarm.query.filter_by(user_id=user.id)
        .order_by(Alarm.time.asc(), Alarm.created_at.asc())
        .all()
    )
    return jsonify(
        {
            "shifted_minutes": minutes,
            "shifted_task_ids": shifted_task_ids,
            "tasks": [_serialize_task(t) for t in tasks],
            "alarms": [_serialize_alarm(a) for a in alarms],
        }
    )


@bp.route("/api/toggle-task", methods=["POST"])
def api_toggle_task():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    if task_id is None:
        return jsonify({"error": "task_id_required"}), 400

    task = Task.query.filter_by(id=int(task_id), user_id=user.id).first()
    if not task:
        return jsonify({"error": "not_found"}), 404

    if "completed" in data:
        task.completed = bool(data.get("completed"))
    else:
        task.completed = not bool(task.completed)
    db.session.commit()
    return jsonify({"ok": True, "task": _serialize_task(task)})


@bp.route("/api/auto-shift-check", methods=["POST"])
def api_auto_shift_check():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    shift_result = _apply_automatic_shift_for_user(user)
    if not shift_result["shifted"]:
        return jsonify(shift_result)

    tasks = (
        Task.query.filter_by(user_id=user.id)
        .order_by(Task.time.asc(), Task.created_at.asc())
        .all()
    )
    alarms = (
        Alarm.query.filter_by(user_id=user.id)
        .order_by(Alarm.time.asc(), Alarm.created_at.asc())
        .all()
    )
    shift_result["tasks"] = [_serialize_task(t) for t in tasks]
    shift_result["alarms"] = [_serialize_alarm(a) for a in alarms]
    return jsonify(shift_result)


@bp.route("/api/alarms", methods=["GET", "POST"])
def api_alarms():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    if request.method == "GET":
        alarms = (
            Alarm.query.filter_by(user_id=user.id)
            .order_by(Alarm.time.asc(), Alarm.created_at.asc())
            .all()
        )
        return jsonify([_serialize_alarm(a) for a in alarms])

    data = request.get_json(silent=True) or {}
    time_24h = (data.get("time_24h") or "").strip()
    label = (data.get("label") or "Alarm").strip()
    is_active = bool(data.get("is_active", True))

    if not time_24h or len(time_24h) != 5 or ":" not in time_24h:
        return jsonify({"error": "time_required"}), 400

    alarm = Alarm(user_id=user.id, time=time_24h, label=label, is_active=is_active)
    db.session.add(alarm)
    db.session.commit()
    return jsonify({"id": alarm.id, "time_24h": alarm.time, "label": alarm.label, "is_active": alarm.is_active}), 201


@bp.route("/api/alarms/<int:alarm_id>", methods=["PATCH", "DELETE"])
def api_alarm_update_delete(alarm_id: int):
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    alarm = Alarm.query.filter_by(id=alarm_id, user_id=user.id).first()
    if not alarm:
        return jsonify({"error": "not_found"}), 404

    if request.method == "DELETE":
        db.session.delete(alarm)
        db.session.commit()
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    if "is_active" in data:
        alarm.is_active = bool(data["is_active"])
    if "label" in data:
        alarm.label = (data.get("label") or alarm.label).strip()
    db.session.commit()
    return jsonify({"ok": True})


# -----------------------
# Google Calendar (OAuth + Month data)
# -----------------------

@bp.route("/google/login")
def google_login():
    user = _current_user()
    if not user:
        return redirect(url_for("routes.login"))

    redirect_uri = url_for("routes.google_callback", _external=True)
    flow = build_oauth_flow(redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        # Ensures a verifier is generated for PKCE on this authorization request.
        code_challenge_method="S256",
    )
    session["google_oauth_state"] = state
    # Persist verifier because callback rebuilds Flow in a new request.
    session["google_oauth_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@bp.route("/google/callback")
def google_callback():
    user = _current_user()
    if not user:
        return redirect(url_for("routes.login"))

    request_state = request.args.get("state")
    session_state = session.get("google_oauth_state")
    if not request_state or not session_state or request_state != session_state:
        return redirect(url_for("routes.dashboard"))

    redirect_uri = url_for("routes.google_callback", _external=True)
    flow = build_oauth_flow(redirect_uri=redirect_uri)
    flow.code_verifier = session.get("google_oauth_code_verifier")
    try:
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        _save_creds(creds)
    except Exception:
        session.pop("google_oauth_state", None)
        session.pop("google_oauth_code_verifier", None)
        return redirect(url_for("routes.dashboard"))

    session.pop("google_oauth_state", None)
    session.pop("google_oauth_code_verifier", None)
    return redirect(url_for("routes.dashboard"))


@bp.route("/api/calendar/month")
def api_calendar_month():
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    creds = ensure_valid_creds()
    if not creds:
        return jsonify({"error": "google_not_connected"}), 401

    now = datetime.utcnow()
    events = fetch_month_events(creds, now)
    dot_days = sorted({e["date"] for e in events})
    return jsonify({"events": events, "dot_days": dot_days, "month": now.strftime("%Y-%m")})


@bp.route("/api/add-event", methods=["POST"])
def api_add_event():
    """
    Quick-add Google Calendar event (primary calendar).
    Expects: { title, date: 'YYYY-MM-DD', time_24h: 'HH:MM' }
    """
    user = _current_user()
    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    date_str = (data.get("date") or "").strip()
    time_24h = (data.get("time_24h") or "").strip()

    if not title:
        return jsonify({"error": "title_required"}), 400
    if len(date_str) != 10 or date_str.count("-") != 2:
        return jsonify({"error": "date_required"}), 400
    if not time_24h or len(time_24h) != 5 or ":" not in time_24h:
        return jsonify({"error": "time_required"}), 400

    creds = ensure_valid_creds()
    if not creds:
        return jsonify({"error": "google_not_connected"}), 401

    try:
        created = add_calendar_event(
            creds,
            calendar_id="primary",
            title=title,
            date_yyyy_mm_dd=date_str,
            time_24h=time_24h,
            duration_minutes=30,
        )
        return jsonify({"ok": True, "htmlLink": created.get("htmlLink")})
    except Exception as e:
        # Common case: token missing required scope -> prompt reconnect.
        msg = str(e)
        if "insufficient" in msg.lower() or "scope" in msg.lower() or "forbidden" in msg.lower():
            return jsonify({"error": "google_reauth_required"}), 401
        return jsonify({"error": "google_api_error", "detail": msg}), 500



