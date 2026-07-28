"""IMPORT-1: parse strength-training logs exported by Strong, Hevy, and
FitNotes into normalized sessions, and resolve free-text exercise names to the
bundled catalog. Pure functions (no DB) so they're unit-testable; the API layer
handles persistence.

Apple Health is intentionally NOT handled here: its export (export.xml) carries
only HKWorkout duration/calorie envelopes and bodyweight records — no per-set
weight×reps — so a strength-set import from it would be empty. iPhone users are
steered to export from Strong/Hevy directly (see the Settings import card copy).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime, timezone
from typing import Any

from ..analytics.strength import CATALOG_BY_ID

KG_TO_LB = 2.20462

# --------------------------------------------------------------------------
# Exercise name -> catalog slug resolution
# --------------------------------------------------------------------------
# Parens are treated as separators so equipment moves INTO the token set:
# "Bench Press (Dumbbell)" and catalog "Dumbbell Bench Press" both -> the same
# {bench, dumbbell, press} set. Separator class also splits commas.
_SEP = re.compile(r"[\s_/+\-,()]+")


def _tokens(name: str) -> frozenset[str]:
    """Order-independent, equipment-inclusive token set for exact matching.
    Lowercase, split on separators (parens included), and stem a trailing
    plural 's' (len>3) so 'Curls' == 'Curl'. Deliberately NO fuzzy step —
    difflib was mapping antonyms (incline<->decline) to the wrong catalog
    entry with a false "matched" flag."""
    out: set[str] = set()
    for w in _SEP.split((name or "").lower()):
        w = w.strip()
        if not w:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.add(w)
    return frozenset(out)


# Built once: token-set -> slug. Two catalog names with the same token set
# collapse (setdefault keeps the first); acceptable for a coarse map.
_TOKEN_INDEX: dict[frozenset[str], str] = {}
for _slug, _meta in CATALOG_BY_ID.items():
    _TOKEN_INDEX.setdefault(_tokens(_meta.get("name", _slug)), _slug)
    _TOKEN_INDEX.setdefault(_tokens(_slug), _slug)


def _slugify_raw(name: str) -> str:
    """Fallback exercise_id for an unmatched import — keep it stable + readable
    so re-imports land on the same id and per-exercise history accumulates."""
    s = _SEP.sub("_", (name or "").strip())
    s = re.sub(r"[^A-Za-z0-9_]", "", s)
    return ("import_" + s)[:128] or "import_unknown"


def resolve_exercise(name: str) -> tuple[str, bool]:
    """Map a free-text exercise name to a catalog slug by EXACT token-set match
    (equipment-inclusive, order/plural-independent). No fuzzy matching — a
    near-miss returns a stable slugified raw name with matched=False so the row
    persists and degrades gracefully, but is never silently mis-attributed to a
    *different* lift (the incline<->decline trap)."""
    toks = _tokens(name)
    if toks and toks in _TOKEN_INDEX:
        return (_TOKEN_INDEX[toks], True)
    return (_slugify_raw(name), False)


# --------------------------------------------------------------------------
# Date + number parsing
# --------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d %b %Y, %H:%M", "%d %b %Y", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y",
)


def _parse_dt(s: str) -> datetime | None:
    """Parse a source timestamp. Source apps write LOCAL wall-clock with no
    offset; we LABEL it UTC (not convert) so the stored instant is deterministic
    and — critically — the calendar date is preserved (StrengthWorkout.date is
    taken from .date()). Without this, a naive datetime into a timestamptz
    column would be interpreted against the DB session's timezone."""
    s = (s or "").strip()
    if not s:
        return None
    dt: datetime | None = None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _num(s: Any) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _to_lb(weight: float | None, unit: str) -> float | None:
    if weight is None:
        return None
    return round(weight * KG_TO_LB, 1) if unit == "kg" else round(weight, 1)


def _rpe_to_rating(rpe: float | None) -> int | None:
    """RPE 6-10 (10 = maximal) -> app rating 1-5 (1 = failed/max effort,
    5 = easy). rating = 11 - rpe, clamped."""
    if rpe is None:
        return None
    return max(1, min(5, round(11 - rpe)))


# --------------------------------------------------------------------------
# Source detection + per-format row parsing
# --------------------------------------------------------------------------
def _sniff(text: str) -> tuple[str, list[str]]:
    """Return (delimiter, header_fields). Strong older exports use ';'."""
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    header = [h.strip().strip('"') for h in first.split(delim)]
    return delim, header


def detect_source(header: list[str]) -> str | None:
    h = {c.lower() for c in header}
    if "weight_kg" in h and "set_index" in h:
        return "hevy"
    if "workout name" in h and "set order" in h:
        return "strong"
    if "weight unit" in h and "exercise" in h and "category" in h:
        return "fitnotes"
    return None


_SET_TYPE_MAP = {
    "normal": "working", "working": "working", "": "working",
    "warmup": "warmup", "warm up": "warmup", "warm-up": "warmup", "w": "warmup",
    "failure": "failure", "fail": "failure",
    "dropset": "drop", "drop set": "drop", "drop": "drop",
}


def _norm_set_type(raw: str) -> str:
    return _SET_TYPE_MAP.get((raw or "").strip().lower(), "working")


def parse_rows(text: str, source: str, strong_unit: str = "kg") -> list[dict[str, Any]]:
    """Parse a CSV export into flat normalized set-rows. Each row:
    {date: date, when: datetime|None, workout: str, exercise: str,
     set_number: int, weight_lb: float|None, reps: int|None,
     set_type: str, rating: int|None, notes: str}."""
    delim, _ = _sniff(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    out: list[dict[str, Any]] = []
    # FitNotes has no set-order column — number sets per (date, exercise).
    fitnotes_counter: dict[tuple[str, str], int] = {}
    for r in reader:
        row = {(k or "").strip(): (v.strip() if isinstance(v, str) else v)
               for k, v in r.items()}
        if source == "strong":
            when = _parse_dt(row.get("Date", ""))
            if when is None:
                continue
            order_raw = row.get("Set Order", "")
            reps = _num(row.get("Reps"))
            weight = _num(row.get("Weight"))
            rec = {
                "when": when, "date": when.date(),
                "workout": row.get("Workout Name") or "Imported",
                "exercise": row.get("Exercise Name") or "",
                "set_number": int(_num(order_raw) or 0) if order_raw not in ("W", "") else 0,
                "weight_lb": _to_lb(weight, strong_unit),
                "reps": int(reps) if reps is not None else None,
                "set_type": "warmup" if str(order_raw).upper() == "W" else "working",
                "rating": _rpe_to_rating(_num(row.get("RPE"))),
                "notes": row.get("Notes") or "",
            }
        elif source == "hevy":
            when = _parse_dt(row.get("start_time", "") or row.get("start_time ", ""))
            when = when or _parse_dt(row.get("end_time", ""))
            if when is None:
                continue
            reps = _num(row.get("reps"))
            weight = _num(row.get("weight_kg"))
            idx = _num(row.get("set_index"))
            rec = {
                "when": when, "date": when.date(),
                "workout": row.get("title") or "Imported",
                "exercise": row.get("exercise_title") or "",
                "set_number": (int(idx) + 1) if idx is not None else 0,  # 0-based -> 1
                "weight_lb": _to_lb(weight, "kg"),  # Hevy is always kg
                "reps": int(reps) if reps is not None else None,
                "set_type": _norm_set_type(row.get("set_type", "")),
                "rating": _rpe_to_rating(_num(row.get("rpe"))),
                "notes": row.get("exercise_notes") or "",
                "superset": row.get("superset_id") or None,
            }
        elif source == "fitnotes":
            when = _parse_dt(row.get("Date", ""))
            if when is None:
                continue
            ex = row.get("Exercise") or ""
            key = (when.date().isoformat(), ex)
            fitnotes_counter[key] = fitnotes_counter.get(key, 0) + 1
            reps = _num(row.get("Reps"))
            weight = _num(row.get("Weight"))
            unit = "kg" if (row.get("Weight Unit") or "").lower().startswith(("kg", "kilo")) else "lb"
            rec = {
                "when": when, "date": when.date(),
                "workout": "Imported",
                "exercise": ex,
                "set_number": fitnotes_counter[key],
                "weight_lb": _to_lb(weight, unit),
                "reps": int(reps) if reps is not None else None,
                "set_type": "working",
                "rating": None,
                "notes": row.get("Comment") or "",
            }
        else:
            raise ValueError(f"unknown source {source!r}")
        if not rec["exercise"] or rec["reps"] is None:
            continue  # skip header echoes / cardio-only / blank rows
        out.append(rec)
    return out


def group_sessions(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """Group flat rows into sessions (workouts). Strong/Hevy group by
    (date, workout name); FitNotes by date alone. Returns a list of
    {date, when, workout, seed, exercises: [{exercise, exercise_id, matched,
    superset, notes, sets: [row...]}]}."""
    sessions: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        # Key Strong/Hevy sessions on the exact start time (all a session's rows
        # share it) so same-name two-a-days on one day stay separate; FitNotes
        # has no session/time, so a session is a whole date.
        if source == "fitnotes":
            skey = (r["date"],)
        else:
            skey = (r["when"], r["workout"])
        sess = sessions.get(skey)
        if sess is None:
            sess = {"date": r["date"], "when": r["when"], "workout": r["workout"],
                    "exercises": {}, "order": []}
            sessions[skey] = sess
        exname = r["exercise"]
        ex = sess["exercises"].get(exname)
        if ex is None:
            slug, matched = resolve_exercise(exname)
            ex = {"exercise": exname, "exercise_id": slug, "matched": matched,
                  "superset": r.get("superset"), "notes": r.get("notes") or "",
                  "sets": []}
            sess["exercises"][exname] = ex
            sess["order"].append(exname)
        ex["sets"].append(r)
    # finalize: stable set numbering + deterministic seed per session
    result = []
    for skey, sess in sessions.items():
        exercises = [sess["exercises"][name] for name in sess["order"]]
        for ex in exercises:
            ex["sets"].sort(key=lambda s: (s["set_number"], s.get("when") or sess["when"]))
            for i, s in enumerate(ex["sets"], start=1):
                s["set_number"] = i
        # Seed = the session's natural identity (start time for Strong/Hevy,
        # date for FitNotes) — NOT its exercise list, so editing a past session
        # and re-exporting still dedups instead of creating a second workout.
        if source == "fitnotes":
            natural = f"fitnotes|{sess['date'].isoformat()}"
        else:
            wkey = sess["when"].isoformat() if sess["when"] else sess["date"].isoformat()
            natural = f"{source}|{wkey}|{sess['workout']}"
        seed = "import:" + source + ":" + hashlib.sha1(natural.encode()).hexdigest()[:16]
        result.append({"date": sess["date"], "when": sess["when"],
                       "workout": sess["workout"], "seed": seed,
                       "exercises": exercises})
    result.sort(key=lambda s: s["date"])
    return result
