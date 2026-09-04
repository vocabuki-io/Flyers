#!/usr/bin/env python3
"""
gcal_to_events.py — merge a Google Calendar API "events.list" JSON export into
data/events.json for the vocabuki flyer-collection site.

Usage:
    python3 scripts/gcal_to_events.py data/gcal_export.json

Reads the raw Google Calendar export (a dict with an "events" list, as
returned by the Calendar API's events.list), filters/normalizes it into the
site's event schema, and merges it into data/events.json next to it
(../data/events.json relative to this script — i.e. always
<repo>/data/events.json), preserving any existing manual edits.

Rules:
  - Skip events whose summary starts with "[タスク]" (personal task entries,
    not club events).
  - Skip all-day events (those with start.date instead of start.dateTime) —
    the calendar uses all-day entries for unrelated reminders/tasks.
  - The event date is the JST calendar date of start.dateTime. All dateTime
    values in the export already carry a +09:00 (JST) offset, so the date is
    simply the first 10 characters (YYYY-MM-DD).
  - holiday = weekday is Friday or Saturday. Everything else is included
    with holiday=false — the owner can flip it in the UI (e.g. for a
    "祝前日" — eve-of-holiday — event that doesn't land on a Fri/Sat).
  - Merge semantics against an existing data/events.json:
      * gcal-sourced events are matched by gcalId.
      * For a match: title/date are refreshed from the calendar; holiday,
        tweetUrl, image, and note are left untouched (the owner's edits win).
      * A gcal event not seen before is added fresh (holiday computed by the
        rule above, tweetUrl/image=null, note="").
      * Any existing manual (source: "manual") events are kept as-is and are
        never touched by this script.
      * Final events list is sorted by (date, title).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVENTS_JSON = REPO_ROOT / "data" / "events.json"

ANNIVERSARY = "2026-09-26"
RANGE_FROM = "2025-08-01"
RANGE_TO = "2026-09-30"

TASK_PREFIX = "[タスク]"


def slugify(title: str) -> str:
    """Best-effort romanize/strip a title down to [a-z0-9-]."""
    # Decompose accented latin chars to plain ascii where possible.
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def make_id(date: str, title: str) -> str:
    slug = slugify(title)
    if not slug:
        # Title is all Japanese (or otherwise unrepresentable) -> short hash.
        h = hashlib.sha1(title.encode("utf-8")).hexdigest()[:6]
        slug = h
    return f"{date}-{slug}"


def compute_holiday(date: str, title: str) -> bool:
    import datetime

    weekday = datetime.date.fromisoformat(date).weekday()  # Mon=0 .. Sun=6
    return weekday in (4, 5)  # Fri or Sat only


def load_gcal_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("events", raw.get("items", []))


def normalize_gcal_events(raw_events: list[dict]) -> list[dict]:
    normalized = []
    for e in raw_events:
        summary = e.get("summary", "") or ""
        if summary.startswith(TASK_PREFIX):
            continue
        start = e.get("start", {})
        date_time = start.get("dateTime")
        if not date_time:
            # All-day event (has "date" instead of "dateTime") -> skip.
            continue
        date = date_time[:10]
        gcal_id = e.get("id")
        normalized.append(
            {
                "date": date,
                "title": summary,
                "holiday": compute_holiday(date, summary),
                "source": "gcal",
                "gcalId": gcal_id,
                "tweetUrl": None,
                "image": None,
                "note": "",
            }
        )
    return normalized


def merge(existing: dict | None, new_gcal_events: list[dict]) -> dict:
    existing_events = (existing or {}).get("events", [])
    by_gcal_id = {
        ev["gcalId"]: ev
        for ev in existing_events
        if ev.get("source") == "gcal" and ev.get("gcalId")
    }
    manual_events = [ev for ev in existing_events if ev.get("source") != "gcal"]

    merged_gcal_events = []
    for new_ev in new_gcal_events:
        gcal_id = new_ev["gcalId"]
        old_ev = by_gcal_id.get(gcal_id)
        if old_ev is not None:
            # Refresh title/date, keep owner-editable fields.
            merged_ev = dict(old_ev)
            merged_ev["date"] = new_ev["date"]
            merged_ev["title"] = new_ev["title"]
            # id is derived from date+title; recompute in case either changed,
            # but keep the old id if it was already customized (rare) — here
            # we simply regenerate from the (possibly updated) date/title so
            # ids stay meaningful. Existing id is only replaced if it would
            # actually change the slug basis.
            merged_ev["id"] = old_ev.get("id") or make_id(
                new_ev["date"], new_ev["title"]
            )
            merged_gcal_events.append(merged_ev)
        else:
            new_ev = dict(new_ev)
            new_ev["id"] = make_id(new_ev["date"], new_ev["title"])
            merged_gcal_events.append(new_ev)

    all_events = manual_events + merged_gcal_events
    all_events.sort(key=lambda ev: (ev["date"], ev["title"]))

    return {
        "anniversary": ANNIVERSARY,
        "range": {"from": RANGE_FROM, "to": RANGE_TO},
        "events": all_events,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <gcal_export.json>", file=sys.stderr)
        sys.exit(1)

    export_path = Path(sys.argv[1])
    raw_events = load_gcal_events(export_path)
    new_gcal_events = normalize_gcal_events(raw_events)

    existing = None
    if EVENTS_JSON.exists():
        with EVENTS_JSON.open("r", encoding="utf-8") as f:
            existing = json.load(f)

    merged = merge(existing, new_gcal_events)

    EVENTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_JSON.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")

    holiday_count = sum(1 for e in merged["events"] if e["holiday"])
    print(
        f"wrote {EVENTS_JSON} — {len(merged['events'])} events "
        f"({holiday_count} holiday, {len(merged['events']) - holiday_count} non-holiday)"
    )


if __name__ == "__main__":
    main()
