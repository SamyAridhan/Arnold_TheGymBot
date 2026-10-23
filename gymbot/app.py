"""The bot: one screen message edited in place, a router for taps and typed text,
and one loop that ties it together."""
from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import model as m


def esc(s) -> str:
    return html.escape(str(s), quote=False)

from .clock import Clock, parse_stamp, stamp
from .store import Store
from .telegram import TelegramError, keyboard

COMMANDS = [("go", "Home / start a session"), ("undo", "Remove the last logged set"),
            ("test", "Try a session without touching your real log"),
            ("cleartest", "Delete everything in the Test tabs")]


@dataclass
class Active:
    session_id: str
    session: str
    date: str
    start: datetime
    test: bool = False
    reopened: bool = False                      # editing a finished session from History
    extra: list[str] = field(default_factory=list)          # exercises added from other sessions
    variant: dict[str, str] = field(default_factory=dict)   # exercise -> chosen variant
    extra_slots: dict[str, int] = field(default_factory=dict)
    first: str | None = None                    # first exercise with a logged set
    cur: str | None = None                      # exercise on screen
    slot: str | None = None                     # slot the stepper is on
    editing: bool = False
    load: int = 0
    reps: int = 0
    last_activity: datetime | None = None


@dataclass
class Finished:
    session_id: str
    session: str
    test: bool
    text: str


class App:
    def __init__(self, chat_id: int, tg, store: Store, clock: Clock,
                 idle_close_min: int = 90, log=print):
        self.chat_id, self.tg, self.store, self.clock = chat_id, tg, store, clock
        self.idle = timedelta(minutes=idle_close_min)
        self.log = log
        self.screen: int | None = None
        self.view = "home"
        self.active: Active | None = None
        self.finished: Finished | None = None
        self.prompt: str | None = None
        self.hint = ""
        self.toast = ""
        self.lists: dict[str, list] = {}
        self.hist_sid: str | None = None
        self.test_setup: dict[tuple[str, str], str] = {}

    # ================================================================ startup
    def start(self) -> None:
        self.store.load()
        self.program = m.Program(self.store.rows("program"), self.store.rows("exercises"))
        for test in (False, True):
            row = next((r for r in self.store.rows("sessions", test) if r.get("status") == "open"), None)
            if row:
                self._resume(row, test)
                self.view = "pick"
                break

    # =============================================================== helpers
    def now(self) -> datetime:
        return self.clock.now()

    def a(self) -> Active:
        assert self.active
        return self.active

    def session_exercises(self) -> list[str]:
        a = self.a()
        out = list(self.program.by_session.get(a.session, []))
        return out + [e for e in a.extra if e not in out]

    def today_sets(self, exercise: str | None = None, variant: str | None = None) -> list[dict]:
        a = self.a()
        return [r for r in self.store.rows("sets", a.test) if r["session_id"] == a.session_id
                and (exercise is None or r["exercise"] == exercise)
                and (variant is None or str(r["variant"]) == variant)]

    def variant_of(self, ex: str) -> str:
        return self.a().variant.get(ex) or self.program.default_variant(ex)

    def cfg(self, ex: str, var: str) -> m.ExCfg:
        c = self.program.cfg(ex, var)
        if self.active and self.active.test and (ex, var) in self.test_setup:
            c.setup_note = self.test_setup[(ex, var)]
        return c

    def slots(self, ex: str, var: str) -> list[str]:
        a = self.a()
        first = a.first is None or a.first == ex
        plan = m.plan_slots(self.cfg(ex, var), first)
        extras = [f"X{i}" for i in range(1, a.extra_slots.get(f"{ex}|{var}", 0) + 1)]
        logged = [str(r["slot"]) for r in self.today_sets(ex, var)]
        return plan + extras + [s for s in logged if s not in plan + extras]

    def last(self, ex: str, var: str) -> m.LastRecord | None:
        a = self.a()
        return m.last_record(self.store.rows("sets"), self.store.rows("notes"), ex, var,
                             exclude=a.session_id)

    def _key(self, ex: str, var: str, slot: str) -> dict:
        return {"session_id": self.a().session_id, "exercise": ex, "variant": var, "slot": slot}

    def _saved(self, ok: bool, msg: str = "Saved") -> None:
        self.toast = msg if ok else "Saved here. Sheet unreachable, retrying."

    # ========================================================= session life
    def start_session(self, session: str, test: bool) -> None:
        now = self.now()
        date = now.date().isoformat()
        if test:
            sid = f"TEST-{now:%Y%m%d-%H%M%S}-{session}"
        else:
            taken = {r["session_id"] for r in self.store.rows("sessions")}
            sid, n = f"{date}-{session}", 2
            while sid in taken:
                sid, n = f"{date}-{session}-{n}", n + 1
        ok = self.store.append("sessions", {"session_id": sid, "session": session, "date": date,
                                            "start_time": f"{now:%H:%M}", "status": "open"}, test)
        self.active = Active(sid, session, date, now, test=test, last_activity=now)
        self.finished = None
        self._saved(ok, f"{session} started")
        exs = self.session_exercises()
        self.open_exercise(exs[0]) if exs else self.set_view("pick")

    def _resume(self, row: dict, test: bool, reopened: bool = False) -> None:
        sid = str(row["session_id"])
        tz = self.clock.tz
        start = datetime.combine(
            datetime.fromisoformat(str(row.get("date") or self.now().date().isoformat())).date(),
            datetime.strptime(str(row.get("start_time") or "00:00"), "%H:%M").time(), tz)
        a = Active(sid, str(row["session"]), str(row.get("date") or ""), start, test, reopened)
        self.active = a
        sets = sorted(self.today_sets(), key=lambda r: str(r["set_time"]))
        planned = self.program.by_session.get(a.session, [])
        for r in sets:
            ex = r["exercise"]
            a.first = a.first or ex
            a.variant[ex] = str(r["variant"])
            if ex not in planned and ex not in a.extra:
                a.extra.append(ex)
            if str(r["slot"]).startswith("X"):
                k = f"{ex}|{r['variant']}"
                a.extra_slots[k] = max(a.extra_slots.get(k, 0), int(str(r["slot"])[1:] or 1))
        times = [t for t in (parse_stamp(r["set_time"], tz) for r in sets) if t]
        a.last_activity = self.now() if reopened else max(times + [start])

    def finish(self, auto: bool = False) -> None:
        a = self.a()
        sets = self.today_sets()
        if not sets and not a.reopened:
            ok = self.store.delete("sessions", {"session_id": a.session_id}, a.test)
            self.active, self.finished = None, None
            self._saved(ok, "Empty session removed")
            self.set_view("test_home" if a.test else "home")
            return
        tz = self.clock.tz
        times = [t for t in (parse_stamp(r["set_time"], tz) for r in sets) if t]
        end = max(times) if (auto and times) else self.now()
        values = {"status": "done"}
        if not a.reopened:
            values["end_time"] = f"{end:%H:%M}"
        ok = self.store.update("sessions", {"session_id": a.session_id}, values, a.test)
        mins = max(0, int((end - a.start).total_seconds() // 60))
        head = (f"✅ {a.session} logged · {mins} min · {len(sets)} sets" if not a.reopened
                else f"✅ {a.session} {m.nice_date(a.date)} updated · {len(sets)} sets")
        if auto:
            head = f"Auto-closed after {self.idle.seconds // 60} min with no sets.\n" + head
        self.finished = Finished(a.session_id, a.session, a.test, head + "\n\n" + self.summary(sets))
        self.active = None
        self._saved(ok, "Session saved")
        self.set_view("finish")

    def summary(self, sets: list[dict]) -> str:
        lines, seen = [], []
        for r in sets:
            k = (r["exercise"], str(r["variant"]))
            if k not in seen:
                seen.append(k)
        for ex, var in seen:
            rows = [r for r in sets if r["exercise"] == ex and str(r["variant"]) == var]
            unit = str(rows[0].get("unit") or "plates")
            name = ex if var in ("Usual", "") else f"{ex} ({var})"
            lines.append(f"{esc(name)}: " + ", ".join(m.fmt_set(r, unit) for r in rows))
        return "\n".join(lines)

    # ============================================================ exercise card
    def open_exercise(self, ex: str) -> None:
        a = self.a()
        a.cur, a.slot, a.editing = ex, None, False
        self.set_view("card")

    def _sync_stepper(self) -> None:
        """Point the stepper at the next open slot, prefilled from last time."""
        a = self.a()
        if a.editing:
            return
        ex = a.cur
        var = self.variant_of(ex)
        done = {str(r["slot"]) for r in self.today_sets(ex, var)}
        nxt = next((s for s in self.slots(ex, var) if s not in done), None)
        if nxt == a.slot:
            return
        a.slot = nxt
        if nxt is None:
            return
        cfg = self.cfg(ex, var)
        last = self.last(ex, var)
        src = last.sets.get(nxt) if last else None
        if not src:
            today = self.today_sets(ex, var)
            src = today[-1] if today else None
        a.load = m.num(src.get("load")) if src and m.num(src.get("load")) is not None else (
            cfg.steps[0] if cfg.steps else 0)
        a.reps = m.num(src.get("reps")) or 0 if src else 0

    def log_set(self, load: int | None = None, reps: int | None = None, tag: str = "") -> None:
        a = self.a()
        ex, var = a.cur, self.variant_of(a.cur)
        cfg = self.cfg(ex, var)
        slot = a.slot
        load = a.load if load is None else load
        reps = a.reps if reps is None else reps
        a.load, a.reps = load, reps
        stored_load = "" if cfg.reps_only else load
        if a.editing:
            values = {"load": stored_load, "reps": reps}
            if tag:
                values["tag"] = tag
            ok = self.store.update("sets", self._key(ex, var, slot), values, a.test)
            a.editing, a.slot = False, None
            self._saved(ok, f"{slot} updated")
        else:
            row = {"set_time": stamp(self.now()), "session_id": a.session_id, "date": a.date,
                   "session": a.session, "exercise": ex, "variant": var, "slot": slot,
                   "load": stored_load, "unit": cfg.unit, "reps": reps, "tag": tag}
            ok = self.store.append("sets", row, a.test)
            a.first = a.first or ex
            a.last_activity = self.now()
            a.slot = None
            self._saved(ok, f"{slot} saved")
            done = {str(r["slot"]) for r in self.today_sets(ex, var)}
            if all(s in done for s in self.slots(ex, var)):
                self._saved(ok, f"{ex} done")
                self.set_view("pick")
                return
        self.set_view("card")

    def card(self) -> tuple[str, list]:
        a = self.a()
        self._sync_stepper()
        ex, var = a.cur, self.variant_of(a.cur)
        cfg = self.cfg(ex, var)
        exs = self.session_exercises()
        pos = f"{exs.index(ex) + 1}/{len(exs)}" if ex in exs else "+"
        today = {str(r["slot"]): r for r in self.today_sets(ex, var)}
        last = self.last(ex, var)

        head = [f"<b>{esc(ex)}</b> · {esc(var)}   {pos}"]
        if cfg.one_side:
            head.append("<i>reps per side</i>")
        if cfg.setup_note:
            head.append(f"Setup: {esc(cfg.setup_note)}")
        if last:
            when = (f"{m.nice_date(last.date)} ({last.session})" if last.date
                    else f"older log ({last.session})")
            note = f' · "{esc(last.note)}"' if last.note else ""
            head.append(f"Last: {when}{note}")
        else:
            head.append("Last: —")

        def cell(row, slot):
            s = m.fmt_set(row, cfg.unit)
            t = str(row.get("tag") or "") if row else ""
            return (s + (" " + t[:6] if t else "")).strip()

        grid = ["     Last        Today"]
        for s in self.slots(ex, var):
            lt = cell(last.sets.get(s) if last else None, s)
            if s in today and not (a.editing and a.slot == s):
                td = cell(today[s], s) + " ✓"
            elif s == a.slot:
                td = "▸ " + m.fmt_set({"load": a.load, "reps": a.reps}, cfg.unit)
            else:
                td = ""
            grid.append(f"{s:<4} {lt:<11} {td}")
        text = "\n".join(head) + "\n<pre>" + esc("\n".join(grid)) + "</pre>"
        if a.slot is None:
            text += "\nAll sets logged."

        rows: list = []
        if a.slot:
            if not cfg.reps_only:
                unit = "plates" if cfg.unit == "plates" else cfg.unit
                label = "BW" if (cfg.unit == "lb" and a.load == 0) else f"{a.load} {unit}"
                rows.append([("−", "lm"), (label, "noop"), ("+", "lp")])
            rows.append([("−", "rm"), (f"{a.reps} reps", "noop"), ("+", "rp")])
            if a.editing:
                rows.append([(f"💾 Update {a.slot}", "log"), ("🗑 Delete", "del"), ("Cancel", "cxl")])
            else:
                rows.append([(f"✅ Log {a.slot}", "log")])
        logged = [s for s in self.slots(ex, var) if s in today]
        for i in range(0, len(logged), 4):
            rows.append([(f"✏ {s}", f"ed:{s}") for s in logged[i:i + 4]])
        rows.append([("➕ Set", "x"), ("🔁 Variant", "var"), ("📝 Notes", "nt")])
        rows.append([("📋 Pick next", "pn")])
        return text, rows

    # ================================================================= views
    def set_view(self, view: str) -> None:
        self.view = view

    def build(self) -> tuple[str, list]:
        v = self.view
        if self.prompt:
            text, rows = self.prompt_text(), [[("Cancel", "pc")]]
        elif v == "card" and self.active and self.active.cur:
            text, rows = self.card()
        elif v == "pick" and self.active:
            text, rows = self.pick()
        elif v == "add" and self.active:
            text, rows = self.add()
        elif v == "variant" and self.active:
            text, rows = self.variants()
        elif v == "notes" and self.active:
            text, rows = self.notes()
        elif v == "finish" and self.finished:
            text, rows = self.finish_view()
        elif v == "history":
            text, rows = self.history()
        elif v == "hist_item":
            text, rows = self.hist_item()
        elif v == "test_home" and not self.active:
            text, rows = self.test_home()
        else:
            self.view = "home"
            text, rows = self.home()
        test = (self.active and self.active.test) or (v == "test_home") or (
            v == "finish" and self.finished and self.finished.test)
        if test:
            text = "🧪 <b>TEST</b> · not your real log\n" + text
        if self.hint:
            text += f"\n\n{esc(self.hint)}"
            self.hint = ""
        if self.store.pending:
            text += f"\n\n⚠ {self.store.pending} change(s) waiting to save to the sheet"
        return text, rows

    def home(self) -> tuple[str, list]:
        if self.active:
            a = self.active
            n = len(self.today_sets())
            label = f"test {a.session}" if a.test else a.session
            return (f"<b>Gym log</b>\nOpen: {label} · {n} sets · since {a.start:%H:%M}",
                    [[(f"▶ Resume {a.session}", "res")], [("🏁 Finish it", "fin")]])
        sess = self.store.rows("sessions")
        cells = [f"{s}  {m.nice_date(m.last_done(sess, s)) or '—':<7}" for s in m.SESSIONS]
        grid = f"{cells[0]}  {cells[1]}\n{cells[2]}  {cells[3]}"
        return ("<b>Gym log</b>\n<pre>" + esc(grid) + "</pre>",
                [[(s, f"go:{s}") for s in m.SESSIONS], [("📜 History", "hist")]])

    def test_home(self) -> tuple[str, list]:
        return ("<b>Test session</b>\nPick one to try. Sets save to the Test tabs in your sheet, "
                "so you can check saving without touching your real log.",
                [[(s, f"tgo:{s}") for s in m.SESSIONS], [("⬅ Home", "h")]])

    def pick(self) -> tuple[str, list]:
        a = self.a()
        exs = self.session_exercises()
        rows = []
        for i, ex in enumerate(exs):
            n = len(self.today_sets(ex))
            rows.append([(f"✓ {ex} · {n}" if n else ex, f"ex:{i}")])
        rows.append([("➕ Add exercise", "add"), ("🏁 Finish", "fin")])
        if a.cur:
            rows.append([("⬅ Back to card", "card")])
        done = sum(1 for ex in exs if self.today_sets(ex))
        return f"<b>{a.session} · pick next</b>\n{done} of {len(exs)} done · ✓ = sets logged", rows

    def add(self) -> tuple[str, list]:
        have = self.session_exercises()
        others = [e for e in self.program.all_exercises() if e not in have]
        self.lists["add"] = others
        rows = [[(e, f"ax:{i}")] for i, e in enumerate(others)]
        rows.append([("⬅ Back", "pn")])
        return "<b>Add an exercise</b>\nFrom any session:", rows

    def variants(self) -> tuple[str, list]:
        a = self.a()
        ex = a.cur
        vs = self.program.variants(ex)
        cur = self.variant_of(ex)
        self.lists["var"] = vs
        rows = [[(("● " if v == cur else "○ ") + v, f"v:{i}")] for i, v in enumerate(vs)]
        rows.append([("➕ New variant", "vnew"), ("⬅ Back", "card")])
        return (f"<b>{esc(ex)} · pick variant</b>\n"
                "Last switches to that variant's own record.", rows)

    def notes(self) -> tuple[str, list]:
        a = self.a()
        ex, var = a.cur, self.variant_of(a.cur)
        wn = next((str(n["note"]) for n in self.store.rows("notes", a.test)
                   if n["session_id"] == a.session_id and n["exercise"] == ex
                   and str(n["variant"]) == var), "")
        sn = self.cfg(ex, var).setup_note
        text = (f"<b>{esc(ex)} · Notes</b>\n"
                f"Workout note (today only): {esc(wn) or '—'}\n"
                f"Setup note (shows every time): {esc(sn) or '—'}")
        return text, [[("📝 Workout note", "ntw"), ("🔧 Setup note", "nts")], [("⬅ Back", "card")]]

    def finish_view(self) -> tuple[str, list]:
        f = self.finished
        rows = [[("📝 Session note", "sn"), ("🏠 Home", "h")]]
        if f.test:
            rows.insert(0, [("🔍 Check save", "chk"), ("🧹 Clear test data", "clr")])
        return f.text, rows

    def history(self) -> tuple[str, list]:
        sess = [r for r in self.store.rows("sessions") if r.get("date") and r.get("status") == "done"]
        sess.sort(key=lambda r: (str(r["date"]), str(r.get("start_time", ""))), reverse=True)
        sess = sess[:10]
        self.lists["hist"] = [str(r["session_id"]) for r in sess]
        rows = []
        for i, r in enumerate(sess):
            dur = ""
            if r.get("start_time") and r.get("end_time"):
                t0 = datetime.strptime(str(r["start_time"]), "%H:%M")
                t1 = datetime.strptime(str(r["end_time"]), "%H:%M")
                dur = f"  {int((t1 - t0).total_seconds() // 60) % 1440} min"
            rows.append([(f"{m.nice_date(r['date'])}  {r['session']}{dur}", f"hs:{i}")])
        rows.append([("🏠 Home", "h")])
        return ("<b>History</b>" + ("" if sess else "\nNothing logged yet."), rows)

    def hist_item(self) -> tuple[str, list]:
        sid = self.hist_sid
        row = next((r for r in self.store.rows("sessions") if r["session_id"] == sid), None)
        if not row:
            return "Session not found.", [[("⬅ History", "hist")]]
        sets = [r for r in self.store.rows("sets") if r["session_id"] == sid]
        note = f"\nNote: {esc(str(row['note']))}" if row.get("note") else ""
        text = f"<b>{row['session']} · {m.nice_date(row['date'])}</b>{note}\n\n{self.summary(sets)}"
        return text, [[("✏ Edit", "he"), ("⬅ History", "hist")]]

    def prompt_text(self) -> str:
        a = self.active
        ex = esc(a.cur) if a and a.cur else ""
        return {
            "workout": f"Type a workout note for <b>{ex}</b> (today only). Send - to clear it.",
            "setup": f"Type the setup note for <b>{ex}</b>, e.g. seat 4. Send - to clear it.",
            "variant": f"Type a name for the new <b>{ex}</b> variant, e.g. Cable or Single arm.",
            "session": "Type a note for the whole session, e.g. light day, knee weak. Send - to clear it.",
        }[self.prompt]

    # ================================================================ render
    def render(self, fresh: bool = False) -> None:
        text, rows = self.build()
        kb = keyboard(rows)
        if self.screen and not fresh:
            try:
                self.tg.edit(self.chat_id, self.screen, text, kb)
                return
            except TelegramError as e:
                if "not modified" in str(e):
                    return
                self.log(f"edit failed, sending new screen: {e}")
        if self.screen and fresh:
            try:
                self.tg.delete(self.chat_id, self.screen)
            except TelegramError:
                pass
        self.screen = self.tg.send(self.chat_id, text, kb)

    # ================================================================ inputs
    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            q = update["callback_query"]
            if q.get("from", {}).get("id") != self.chat_id:
                return
            msg = q.get("message") or {}
            if msg.get("message_id"):
                self.screen = msg["message_id"]
            self.toast = ""
            self.on_tap(q.get("data", ""))
            try:
                self.tg.answer(q["id"], self.toast)
            except TelegramError:
                pass
            self.render()
        elif "message" in update:
            msg = update["message"]
            if msg.get("chat", {}).get("id") != self.chat_id or "text" not in msg:
                return
            self.on_text(msg["text"].strip(), msg["message_id"])

    def on_text(self, text: str, message_id: int) -> None:
        if text.startswith("/"):
            self.on_command(text.split()[0][1:].split("@")[0].lower())
            return
        try:
            self.tg.delete(self.chat_id, message_id)   # keep the chat clean
        except TelegramError:
            pass
        if self.prompt:
            self.on_prompt(text)
        elif self.active and self.view == "card" and self.active.cur:
            a = self.active
            self._sync_stepper()
            cfg = self.cfg(a.cur, self.variant_of(a.cur))
            parsed = m.parse_set(text, cfg.reps_only) if a.slot else None
            if parsed:
                load, reps, tag = parsed
                self.log_set(load=a.load if load is None else load, reps=reps, tag=tag)
            else:
                self.hint = "Couldn't read that. Try 7 9, 7x9 or 7 9 +." if a.slot else \
                    "All sets on this exercise are logged. Tap ➕ Set for an extra one."
        else:
            self.hint = "Open an exercise first, then type plates and reps, e.g. 7 9."
        self.render()

    def on_command(self, cmd: str) -> None:
        self.prompt = None
        if cmd in ("start", "go"):
            self.view = "card" if self.active and self.active.cur else ("pick" if self.active else "home")
        elif cmd == "undo":
            self.undo()
        elif cmd == "test":
            if self.active and not self.active.test:
                self.hint = "Finish your open session first, then start a test."
                self.view = "home"
            else:
                self.view = "pick" if self.active else "test_home"
        elif cmd == "cleartest":
            if self.active and self.active.test:
                self.hint = "Finish the test session first."
            else:
                ok = self.store.clear_test()
                self.hint = "Test tabs cleared." if ok else "Clearing test tabs, will retry."
                self.finished = None
                self.view = "home"
        self.render(fresh=True)

    def on_prompt(self, text: str) -> None:
        kind, self.prompt = self.prompt, None
        value = "" if text.strip() == "-" else text.strip()
        if kind == "session":
            f = self.finished
            ok = self.store.update("sessions", {"session_id": f.session_id}, {"note": value}, f.test)
            self._saved(ok, "Session note saved")
            self.hint = "Session note saved." if value else "Session note cleared."
            return
        a = self.a()
        ex, var = a.cur, self.variant_of(a.cur)
        if kind == "workout":
            notes = self.store.rows("notes", a.test)
            match = {"session_id": a.session_id, "exercise": ex, "variant": var}
            if any(all(str(n[k]) == str(v) for k, v in match.items()) for n in notes):
                self.store.update("notes", match, {"note": value}, a.test)
            else:
                self.store.append("notes", {**match, "date": a.date, "note": value}, a.test)
            self.hint = "Workout note saved." if value else "Workout note cleared."
            self.view = "notes"
        elif kind == "setup":
            if a.test:
                self.test_setup[(ex, var)] = value
                self.hint = "Setup note kept for this test only."
            else:
                rows = self.store.rows("exercises")
                if any(r["exercise"] == ex and str(r["variant"]) == var for r in rows):
                    self.store.update("exercises", {"exercise": ex, "variant": var}, {"setup_note": value})
                else:
                    self.store.append("exercises", {"exercise": ex, "variant": var, "default": "no",
                                                    "hidden": "no", "setup_note": value})
                self.hint = "Setup note saved." if value else "Setup note cleared."
            self.view = "notes"
        elif kind == "variant":
            name = value[:30]
            if not name:
                self.view = "variant"
                return
            if name not in self.program.variants(ex):
                base = self.program.cfg(ex, self.program.default_variant(ex))
                row = {"exercise": ex, "variant": name, "default": "no", "unit": base.unit,
                       "hidden": "no", "one_side": "no"}
                if a.test:
                    self.store.rows("exercises").append(row)   # memory only during a test
                else:
                    self.store.append("exercises", row)
            a.variant[ex] = name
            a.slot, a.editing = None, False
            self.hint = f"Switched to {name}."
            self.view = "card"

    def undo(self) -> None:
        if not self.active:
            self.hint = "No open session to undo in."
            return
        a = self.active
        sets = self.today_sets()
        if not sets:
            self.hint = "Nothing logged yet in this session."
            return
        r = max(sets, key=lambda r: str(r["set_time"]))
        ok = self.store.delete("sets", self._key(r["exercise"], str(r["variant"]), str(r["slot"])), a.test)
        if a.first == r["exercise"] and not self.today_sets(r["exercise"]):
            a.first = None
        a.variant[r["exercise"]] = str(r["variant"])
        a.cur, a.slot, a.editing = r["exercise"], None, False
        self._saved(ok, "Removed")
        self.hint = f"Removed {r['slot']} of {r['exercise']}."
        self.view = "card"

    def on_tap(self, data: str) -> None:
        cmd, _, arg = data.partition(":")
        a = self.active
        self.prompt = None if cmd != "noop" else self.prompt

        if cmd == "noop":
            return
        if cmd == "h":
            self.view = "home"
        elif cmd in ("go", "tgo"):
            if a:
                self.hint = "A session is already open."
                self.view = "home"
            else:
                self.start_session(arg, test=(cmd == "tgo"))
        elif cmd == "res":
            self.view = "card" if a and a.cur else "pick"
        elif cmd == "hist":
            self.view = "history"
        elif cmd == "hs":
            ids = self.lists.get("hist", [])
            if arg.isdigit() and int(arg) < len(ids):
                self.hist_sid = ids[int(arg)]
                self.view = "hist_item"
        elif cmd == "he":
            if a:
                self.hint = "Finish the open session first."
                self.view = "home"
            else:
                row = next((r for r in self.store.rows("sessions") if r["session_id"] == self.hist_sid), None)
                if row:
                    self.store.update("sessions", {"session_id": self.hist_sid}, {"status": "open"})
                    self._resume(row, test=False, reopened=True)
                    self.view = "pick"
        elif cmd == "sn" and self.finished:
            self.prompt = "session"
        elif cmd == "chk" and self.finished:
            self.check_save()
        elif cmd == "clr":
            ok = self.store.clear_test()
            self.finished = None
            self._saved(ok, "Test data cleared")
            self.hint = "Test tabs cleared."
            self.view = "home"
        elif not a:
            self.hint = "That session is closed."
            self.view = "home"
        # --- everything below needs an open session
        elif cmd == "fin":
            self.finish()
        elif cmd == "pn":
            self.view = "pick"
        elif cmd == "card":
            self.view = "card" if a.cur else "pick"
        elif cmd == "ex":
            exs = self.session_exercises()
            if arg.isdigit() and int(arg) < len(exs):
                self.open_exercise(exs[int(arg)])
        elif cmd == "add":
            self.view = "add"
        elif cmd == "ax":
            others = self.lists.get("add", [])
            if arg.isdigit() and int(arg) < len(others):
                a.extra.append(others[int(arg)])
                self.open_exercise(others[int(arg)])
        elif a.cur is None:
            self.view = "pick"
        # --- everything below needs an exercise on screen
        elif cmd in ("lm", "lp", "rm", "rp"):
            self._sync_stepper()
            if a.slot:
                cfg = self.cfg(a.cur, self.variant_of(a.cur))
                if cmd == "lp":
                    a.load = m.step(cfg, a.load, True)
                elif cmd == "lm":
                    a.load = m.step(cfg, a.load, False)
                elif cmd == "rp":
                    a.reps += 1
                else:
                    a.reps = max(0, a.reps - 1)
            self.view = "card"
        elif cmd == "log":
            self._sync_stepper()
            if a.slot:
                self.log_set()
        elif cmd == "ed":
            var = self.variant_of(a.cur)
            row = next((r for r in self.today_sets(a.cur, var) if str(r["slot"]) == arg), None)
            if row:
                a.slot, a.editing = arg, True
                a.load = m.num(row.get("load")) or 0
                a.reps = m.num(row.get("reps")) or 0
            self.view = "card"
        elif cmd == "del" and a.editing:
            var = self.variant_of(a.cur)
            ok = self.store.delete("sets", self._key(a.cur, var, a.slot), a.test)
            self._saved(ok, f"{a.slot} deleted")
            if a.first == a.cur and not self.today_sets(a.cur):
                a.first = None
            a.slot, a.editing = None, False
            self.view = "card"
        elif cmd == "cxl":
            a.slot, a.editing = None, False
            self.view = "card"
        elif cmd == "x":
            k = f"{a.cur}|{self.variant_of(a.cur)}"
            a.extra_slots[k] = a.extra_slots.get(k, 0) + 1
            a.slot, a.editing = None, False
            self.view = "card"
        elif cmd == "var":
            self.view = "variant"
        elif cmd == "v":
            vs = self.lists.get("var", [])
            if arg.isdigit() and int(arg) < len(vs):
                a.variant[a.cur] = vs[int(arg)]
                a.slot, a.editing = None, False
            self.view = "card"
        elif cmd == "vnew":
            self.prompt = "variant"
        elif cmd == "nt":
            self.view = "notes"
        elif cmd == "ntw":
            self.prompt = "workout"
        elif cmd == "nts":
            self.prompt = "setup"
        elif cmd == "pc":
            pass

    def check_save(self) -> None:
        f = self.finished
        expected = [r for r in self.store.rows("sets", True) if r["session_id"] == f.session_id]
        try:
            got = [r for r in self.store.reread("sets", True) if r["session_id"] == f.session_id]
            sess = [r for r in self.store.reread("sessions", True) if r["session_id"] == f.session_id]
        except Exception as e:  # noqa: BLE001
            self.hint = f"Couldn't read the sheet: {e}"
            return

        def key(r):
            return (r["exercise"], str(r["variant"]), str(r["slot"]), str(r["load"]), str(r["reps"]), str(r["tag"]))
        missing = [r for r in expected if key(r) not in {key(g) for g in got}]
        status = sess[0].get("status") if sess else "missing"
        if self.store.pending:
            self.hint = f"⚠ {self.store.pending} change(s) still waiting to reach the sheet."
        elif not missing and len(got) == len(expected) and status == "done":
            self.hint = (f"🔍 Check passed: {len(got)}/{len(expected)} sets are in 'Test Sets' "
                         f"and match, and the session is marked done.")
        else:
            self.hint = (f"🔍 Check FAILED: sheet has {len(got)} of {len(expected)} sets, "
                         f"{len(missing)} differ, session status '{status}'.")

    # ================================================================== loop
    def tick(self) -> None:
        if self.store.pending:
            self.store.flush()
        a = self.active
        if a and a.last_activity and self.now() - a.last_activity > self.idle:
            self.finish(auto=True)
            self.render()

    def run(self, max_runtime: int = 0) -> None:
        self.start()
        try:
            self.tg.set_commands(COMMANDS)
        except Exception as e:  # noqa: BLE001
            self.log(f"setMyCommands failed: {e}")
        deadline = time.monotonic() + max_runtime if max_runtime else None
        offset = 0
        while deadline is None or time.monotonic() < deadline:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.log(f"tick failed: {e}")
            try:
                wait = 30 if deadline is None else max(1, min(30, int(deadline - time.monotonic())))
                updates = self.tg.updates(offset, wait)
            except Exception as e:  # noqa: BLE001  (409 during a handover, network blips)
                self.log(f"getUpdates failed: {e}")
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception as e:  # noqa: BLE001  one bad update never kills the bot
                    self.log(f"update failed: {e!r}")
        if not self.store.flush():
            self.log(f"WARNING: exiting with {self.store.pending} unsaved change(s)")
