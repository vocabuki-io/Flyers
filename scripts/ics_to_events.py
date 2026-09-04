#!/usr/bin/env python3
"""
ics_to_events.py — merge a TimeTree calendar .ics export into data/events.json
for the vocabuki flyer-collection site.

Usage:
    python3 scripts/ics_to_events.py data/timetree_export.ics

Reads a TimeTree ICS export (RFC 5545), filters/normalizes it into the
site's event schema, and merges it into data/events.json next to it
(always <repo>/data/events.json, resolved relative to this script),
preserving events from other sources (gcal, manual) and any existing
manual edits untouched.

Rules:
  - Only VEVENTs whose CATEGORIES is "休日営業" or "平日営業" are imported —
    every other category (レギュラー, 休み希望, 三階作業, Campus Union,
    運営予定, 臨時スタッフ, 在宅作業, or no category at all) is a staff-shift
    entry, not a club event, and is skipped.
  - Only events dated before 2026-06-01 are imported — the Google Calendar
    export (scripts/gcal_to_events.py) covers 2026-06-01 onward, so this
    keeps the two sources from overlapping.
  - date = the YYYYMMDD found in DTSTART (whether a bare all-day
    "DTSTART:YYYYMMDD" or a "DTSTART;TZID=Asia/Tokyo:YYYYMMDDTHHMMSS"), i.e.
    the first 8 characters of the value after the property's colon.
  - holiday = weekday is Friday or Saturday (same rule as the gcal
    script) — everything else is included with holiday=false, and the
    owner can flip it in the UI.
  - icsCategory keeps the raw CATEGORIES value ("休日営業"/"平日営業") for
    reference.
  - An event carrying an RRULE is a recurring series. Expanding a series
    is out of scope here — none of the 休日営業/平日営業 events in the
    source export need it (verified against the actual export) — so any
    such VEVENT is skipped, with a warning printed to stderr, rather than
    silently mis-imported.
  - Continuation lines per RFC 5545 (a line starting with a single space
    is a folded continuation of the previous line) are unfolded before
    parsing.
  - Merge semantics against an existing data/events.json:
      * timetree-sourced events are matched by icsUid (the VEVENT's UID).
      * For a match: title/date/icsCategory/holiday-basis are refreshed
        from the ICS; the owner-editable fields (holiday, tweetUrl, image,
        note) are left untouched.
      * A timetree event not seen before is added fresh (holiday computed
        by the rule above, tweetUrl/image=null, note="").
      * All non-timetree events (gcal, manual) are kept exactly as-is.
      * Final events list is sorted by (date, title).
"""
from __future__ import annotations

import datetime
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

WANTED_CATEGORIES = {"休日営業", "平日営業"}
CUTOFF_DATE = "20260601"  # exclusive upper bound (YYYYMMDD), gcal covers from here on


def slugify(title: str) -> str:
    """Best-effort romanize/strip a title down to [a-z0-9-]."""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def make_id(date: str, title: str) -> str:
    slug = slugify(title)
    if not slug:
        h = hashlib.sha1(title.encode("utf-8")).hexdigest()[:6]
        slug = h
    return f"{date}-{slug}"


def compute_holiday(date: str) -> bool:
    weekday = datetime.date.fromisoformat(date).weekday()  # Mon=0 .. Sun=6
    return weekday in (4, 5)  # Fri or Sat only


def unescape_ics_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def unfold_lines(raw: str) -> list[str]:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith(" ") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def parse_vevents(lines: list[str]) -> list[dict]:
    """Parse VEVENT blocks into {PROPNAME: raw_value} dicts.

    Only the first occurrence of a property name is kept per event (fine
    for the single-valued properties this script reads: SUMMARY, DTSTART,
    CATEGORIES, UID, RRULE).
    """
    events: list[dict] = []
    current: dict | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key_part, value = line.split(":", 1)
        prop_name = key_part.split(";", 1)[0]
        current.setdefault(prop_name, value)
    return events


def normalize_ics_events(raw_events: list[dict]) -> list[dict]:
    normalized = []
    skipped_rrule = 0
    for e in raw_events:
        category = e.get("CATEGORIES", "")
        if category not in WANTED_CATEGORIES:
            continue
        if "RRULE" in e:
            summary = e.get("SUMMARY", "(no title)")
            print(
                f"warning: skipping recurring VEVENT (RRULE present): "
                f"{e.get('DTSTART', '?')} {summary!r} uid={e.get('UID', '?')}",
                file=sys.stderr,
            )
            skipped_rrule += 1
            continue
        dtstart = e.get("DTSTART", "")
        if len(dtstart) < 8:
            continue
        yyyymmdd = dtstart[:8]
        if yyyymmdd >= CUTOFF_DATE:
            continue
        date = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        title = unescape_ics_text(e.get("SUMMARY", ""))
        uid = e.get("UID")
        normalized.append(
            {
                "date": date,
                "title": title,
                "holiday": compute_holiday(date),
                "source": "timetree",
                "icsUid": uid,
                "icsCategory": category,
                "tweetUrl": None,
                "image": None,
                "note": "",
            }
        )
    if skipped_rrule:
        print(f"skipped {skipped_rrule} recurring (RRULE) VEVENT(s) among wanted categories", file=sys.stderr)
    return normalized


def load_ics_events(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    lines = unfold_lines(raw)
    return parse_vevents(lines)


def merge(existing: dict | None, new_ics_events: list[dict]) -> dict:
    existing_events = (existing or {}).get("events", [])
    by_ics_uid = {
        ev["icsUid"]: ev
        for ev in existing_events
        if ev.get("source") == "timetree" and ev.get("icsUid")
    }
    other_events = [ev for ev in existing_events if ev.get("source") != "timetree"]

    merged_ics_events = []
    for new_ev in new_ics_events:
        uid = new_ev["icsUid"]
        old_ev = by_ics_uid.get(uid)
        if old_ev is not None:
            merged_ev = dict(old_ev)
            merged_ev["date"] = new_ev["date"]
            merged_ev["title"] = new_ev["title"]
            merged_ev["icsCategory"] = new_ev["icsCategory"]
            merged_ev["id"] = old_ev.get("id") or make_id(new_ev["date"], new_ev["title"])
            merged_ics_events.append(merged_ev)
        else:
            new_ev = dict(new_ev)
            new_ev["id"] = make_id(new_ev["date"], new_ev["title"])
            merged_ics_events.append(new_ev)

    all_events = other_events + merged_ics_events
    all_events.sort(key=lambda ev: (ev["date"], ev["title"]))

    return {
        "anniversary": ANNIVERSARY,
        "range": {"from": RANGE_FROM, "to": RANGE_TO},
        "events": all_events,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <timetree_export.ics>", file=sys.stderr)
        sys.exit(1)

    ics_path = Path(sys.argv[1])
    raw_events = load_ics_events(ics_path)
    new_ics_events = normalize_ics_events(raw_events)

    existing = None
    if EVENTS_JSON.exists():
        with EVENTS_JSON.open("r", encoding="utf-8") as f:
            existing = json.load(f)

    merged = merge(existing, new_ics_events)

    EVENTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_JSON.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")

    imported = len(new_ics_events)
    holiday_count = sum(1 for e in new_ics_events if e["holiday"])
    kyujitsu = sum(1 for e in new_ics_events if e["icsCategory"] == "休日営業")
    heijitsu = sum(1 for e in new_ics_events if e["icsCategory"] == "平日営業")
    print(
        f"wrote {EVENTS_JSON} — imported {imported} timetree events "
        f"(休日営業={kyujitsu}, 平日営業={heijitsu}, holiday(Fri/Sat)={holiday_count}); "
        f"total events in file: {len(merged['events'])}"
    )


if __name__ == "__main__":
    main()
