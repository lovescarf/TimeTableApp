from __future__ import annotations

import os
import calendar as pycalendar
from datetime import datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


# Read + insert events (needed for Day View quick-add).
# If you previously authorized with readonly only, you'll be prompted to reconnect.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"


def _load_creds() -> Credentials | None:
    if not os.path.exists(TOKEN_PATH):
        return None
    return Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)


def _save_creds(creds: Credentials) -> None:
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def ensure_valid_creds() -> Credentials | None:
    creds = _load_creds()
    if not creds:
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_creds(creds)
            return creds
        except Exception:
            return None

    return None


def build_oauth_flow(redirect_uri: str) -> Flow:
    flow = Flow.from_client_secrets_file(CREDENTIALS_PATH, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def calendar_month_window_utc(dt: datetime) -> tuple[str, str]:
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    _, last_day = pycalendar.monthrange(dt.year, dt.month)
    end = dt.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0).isoformat() + "Z"
    return start, end


def fetch_month_events(creds: Credentials, dt: datetime) -> list[dict[str, Any]]:
    service = build("calendar", "v3", credentials=creds)
    time_min, time_max = calendar_month_window_utc(dt)

    all_events: list[dict[str, Any]] = []
    for cal_id in ["primary", "en.indian#holiday@group.v.calendar.google.com"]:
        events_result = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        all_events.extend(events_result.get("items", []))

    formatted: list[dict[str, Any]] = []
    for e in all_events:
        title = e.get("summary", "No Title")
        if "birthday" in title.lower():
            continue
        start_raw = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
        if not start_raw:
            continue
        dt_obj = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))

        formatted.append(
            {
                "title": title,
                "start_raw": start_raw,
                "is_all_day": "T" not in start_raw,
                "date": dt_obj.strftime("%Y-%m-%d"),
                "day": dt_obj.strftime("%a"),
                "day_num": dt_obj.strftime("%d"),
                "time_24h": dt_obj.strftime("%H:%M") if "T" in start_raw else None,
            }
        )

    formatted.sort(key=lambda x: (x["date"], x["time_24h"] or "00:00", x["title"]))
    return formatted


def add_calendar_event(
    creds: Credentials,
    *,
    calendar_id: str,
    title: str,
    date_yyyy_mm_dd: str,
    time_24h: str,
    duration_minutes: int = 30,
) -> dict[str, Any]:
    """
    Create a timed event on the given date at the given time.
    Uses local-floating time; Google Calendar will interpret in the user's calendar timezone.
    """
    service = build("calendar", "v3", credentials=creds)

    start_dt = f"{date_yyyy_mm_dd}T{time_24h}:00"
    # naive end time computed on the backend route to keep this helper simple
    end_dt = None
    try:
        hh, mm = time_24h.split(":")
        total = int(hh) * 60 + int(mm) + int(duration_minutes)
        end_hh = (total // 60) % 24
        end_mm = total % 60
        end_dt = f"{date_yyyy_mm_dd}T{end_hh:02d}:{end_mm:02d}:00"
    except Exception:
        end_dt = f"{date_yyyy_mm_dd}T{time_24h}:30"

    body = {
        "summary": title,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
    }

    return service.events().insert(calendarId=calendar_id, body=body).execute()

