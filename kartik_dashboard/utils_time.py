from __future__ import annotations

from datetime import datetime, timedelta


def hhmm_to_minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def minutes_to_hhmm(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def subtract_minutes(hhmm: str, minutes: int) -> str:
    return minutes_to_hhmm(hhmm_to_minutes(hhmm) - minutes)


def add_minutes(hhmm: str, minutes: int) -> str:
    return minutes_to_hhmm(hhmm_to_minutes(hhmm) + minutes)


def now_utc() -> datetime:
    return datetime.utcnow()


def apply_streak(streak_count: int, last_login_at: datetime | None, now: datetime) -> tuple[int, datetime]:
    """
    Rules (as requested):
    - First login: streak = 1
    - If >24 hours since last login: +1
    - If >48 hours since last login: reset to 1
    - Otherwise (same day / within 24h): keep
    """
    if last_login_at is None:
        return 1, now

    delta = now - last_login_at
    if delta > timedelta(hours=48):
        return 1, now
    if delta > timedelta(hours=24):
        return max(1, int(streak_count)) + 1, now
    return max(1, int(streak_count)), now

