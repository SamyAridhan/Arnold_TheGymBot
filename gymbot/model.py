"""Pure logic: program, exercise settings, history lookups, parsing, formatting.
No network here, so it is easy to test."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SESSIONS = ("UB1", "LB1", "UB2", "LB2")


def num(v) -> int | None:
    """Sheet cell -> int, or None when blank/not a number."""
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def yes(v) -> bool:
    return str(v).strip().lower() in ("yes", "y", "true", "1")


# --------------------------------------------------------------- exercises
@dataclass
class ExCfg:
    exercise: str
    variant: str
    unit: str = "plates"          # plates | lb | reps
    steps: list[int] = field(default_factory=list)
    warmups: int = 1
    working_sets: int = 2
    one_side: bool = False
    setup_note: str = ""

    @property
    def reps_only(self) -> bool:
        return self.unit == "reps"


class Program:
    def __init__(self, program_rows: list[dict], exercise_rows: list[dict]):
        self.exercise_rows = exercise_rows
        self.by_session: dict[str, list[str]] = {s: [] for s in SESSIONS}
        for r in sorted(program_rows, key=lambda r: (str(r["session"]), num(r["order"]) or 0)):
            self.by_session.setdefault(str(r["session"]), []).append(str(r["exercise"]))

    def all_exercises(self) -> list[str]:
        names = []
        for r in self.exercise_rows:
            if r["exercise"] not in names:
                names.append(r["exercise"])
        return names

    def _rows(self, exercise: str) -> list[dict]:
        return [r for r in self.exercise_rows if r["exercise"] == exercise]

    def variants(self, exercise: str) -> list[str]:
        rows = [r for r in self._rows(exercise) if not yes(r.get("hidden"))]
        rows.sort(key=lambda r: not yes(r.get("default")))
        return [str(r["variant"]) for r in rows] or ["Usual"]

    def default_variant(self, exercise: str) -> str:
        return self.variants(exercise)[0]

    def cfg(self, exercise: str, variant: str) -> ExCfg:
        rows = self._rows(exercise)
        base = next((r for r in rows if yes(r.get("default"))), rows[0] if rows else {})
        own = next((r for r in rows if str(r["variant"]) == variant), {})

        def pick(k):
            v = own.get(k, "")
            return v if v != "" else base.get(k, "")

        steps = [n for n in (num(s) for s in str(pick("steps")).split(",")) if n is not None]
        return ExCfg(
            exercise=exercise, variant=variant,
            unit=str(pick("unit") or "plates"),
            steps=sorted(set(steps)),
            warmups=num(pick("warmups")) if num(pick("warmups")) is not None else 1,
            working_sets=num(pick("working_sets")) or 2,
            one_side=yes(own.get("one_side", "")),
            setup_note=str(own.get("setup_note", "") or ""),
        )


def plan_slots(cfg: ExCfg, first: bool) -> list[str]:
    """W1.. then S1..; the first exercise started in a session gets two warm-ups."""
    w = max(cfg.warmups, 2) if first else cfg.warmups
    return [f"W{i}" for i in range(1, w + 1)] + [f"S{i}" for i in range(1, cfg.working_sets + 1)]


def step(cfg: ExCfg, load: int, up: bool) -> int:
    if cfg.steps:
        if up:
            bigger = [s for s in cfg.steps if s > load]
            return bigger[0] if bigger else load + 1
        smaller = [s for s in cfg.steps if s < load]
        return smaller[-1] if smaller else 0
    return load + 1 if up else max(0, load - 1)


# ----------------------------------------------------------------- history
def session_order(sid: str, rows: list[dict]) -> tuple:
    """Dated sessions sort after legacy ones, by date then time; legacy by number."""
    dated = [r for r in rows if r.get("date")]
    if dated:
        return (1, str(dated[0]["date"]), min(str(r.get("set_time", "")) for r in rows), sid)
    m = re.search(r"(\d+)", sid)
    return (0, "", f"{int(m[1]):06d}" if m else "", sid)


@dataclass
class LastRecord:
    session_id: str
    session: str
    date: str
    sets: dict[str, dict]        # slot -> set row
    note: str = ""


def last_record(sets_rows: list[dict], notes_rows: list[dict], exercise: str, variant: str,
                exclude: str | None = None) -> LastRecord | None:
    by_sid: dict[str, list[dict]] = {}
    for r in sets_rows:
        if r["exercise"] == exercise and str(r["variant"]) == variant and r["session_id"] != exclude:
            by_sid.setdefault(str(r["session_id"]), []).append(r)
    if not by_sid:
        return None
    sid = max(by_sid, key=lambda s: session_order(s, by_sid[s]))
    rows = by_sid[sid]
    note = next((str(n["note"]) for n in notes_rows if n["session_id"] == sid
                 and n["exercise"] == exercise and str(n["variant"]) == variant and n.get("note")), "")
    return LastRecord(sid, str(rows[0]["session"]), str(rows[0].get("date") or ""),
                      {str(r["slot"]): r for r in rows}, note)


def last_done(sessions_rows: list[dict], session: str) -> str:
    dates = [str(r["date"]) for r in sessions_rows
             if r["session"] == session and r.get("date") and r.get("status") != "open"]
    return max(dates) if dates else ""


# ----------------------------------------------------------------- parsing
SET_RE = re.compile(r"^\s*(\d+)\s*(?:[x×*]\s*|\s+)(\d+)\s*(.*?)\s*$", re.I)
ONE_RE = re.compile(r"^\s*(\d+)\s*(.*?)\s*$")


def parse_set(text: str, reps_only: bool) -> tuple[int | None, int, str] | None:
    """'7 9', '7x9', '7 9 +', '5 4 dropped to 4'. Reps-only: '12', '10+2'.
    A single number on a loaded exercise means reps at the current load (load=None)."""
    if not reps_only:
        m = SET_RE.match(text)
        if m:
            return int(m[1]), int(m[2]), m[3]
    m = ONE_RE.match(text)
    if m:
        return None, int(m[1]), m[2]
    return None


# -------------------------------------------------------------- formatting
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def nice_date(iso: str) -> str:
    from datetime import date
    try:
        d = date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{DAYS[d.weekday()]} {d.day}"


def fmt_load(load, unit: str) -> str:
    n = num(load)
    if n is None:
        return ""
    if unit == "lb":
        return "BW" if n == 0 else f"{n}lb"
    return str(n)


def fmt_set(row: dict | None, unit: str) -> str:
    if not row:
        return ""
    reps = num(row.get("reps"))
    r = "?" if reps is None else str(reps)
    if unit == "reps":
        return r
    return f"{fmt_load(row.get('load'), unit)} x {r}"
