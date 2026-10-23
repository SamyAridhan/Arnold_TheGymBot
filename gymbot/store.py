"""Google Sheet storage.

Every tab is a Table. The Store keeps an in-memory copy of each tab (read once at
startup), changes that copy immediately, and pushes each change to the sheet
through a FIFO queue. If the sheet can't be reached, changes stay queued and are
retried; nothing is dropped.

Test mode uses separate tabs ("Test Sets", "Test Sessions", "Test Notes") so a
test session never touches the real log.
"""
from __future__ import annotations

import json
from typing import Callable

HEADERS = {
    "sets": ["set_time", "session_id", "date", "session", "exercise", "variant",
             "slot", "load", "unit", "reps", "tag"],
    "sessions": ["session_id", "session", "date", "start_time", "end_time", "status", "note"],
    "notes": ["session_id", "date", "exercise", "variant", "note"],
    "program": ["session", "order", "exercise"],
    "exercises": ["exercise", "variant", "default", "unit", "steps", "warmups",
                  "working_sets", "one_side", "setup_note", "hidden", "kg_per_plate"],
}
REAL_TABS = {"sets": "Sets", "sessions": "Sessions", "notes": "Notes",
             "program": "Program", "exercises": "Exercises"}
TEST_TABS = {"sets": "Test Sets", "sessions": "Test Sessions", "notes": "Test Notes"}
LOGGED = ("sets", "sessions", "notes")   # the tabs that have a test twin


def _match(row: dict, match: dict) -> bool:
    return all(str(row.get(k, "")) == str(v) for k, v in match.items())


# --------------------------------------------------------------------- tables
class MemoryTable:
    """In-memory tab, used by tests and the demo. `fail` simulates outages."""

    def __init__(self, headers: list[str], rows: list[dict] | None = None):
        self.headers = headers
        self.rows = [{h: r.get(h, "") for h in headers} for r in rows or []]
        self.fail = 0

    def _check(self):
        if self.fail:
            self.fail -= 1
            raise IOError("simulated sheet outage")

    def read(self) -> list[dict]:
        self._check()
        return [dict(r) for r in self.rows]

    def append(self, row: dict) -> None:
        self._check()
        self.rows.append({h: row.get(h, "") for h in self.headers})

    def update(self, match: dict, values: dict) -> bool:
        self._check()
        for r in self.rows:
            if _match(r, match):
                r.update({k: v for k, v in values.items() if k in self.headers})
                return True
        return False

    def delete(self, match: dict) -> bool:
        self._check()
        for i, r in enumerate(self.rows):
            if _match(r, match):
                del self.rows[i]
                return True
        return False

    def clear(self) -> None:
        self._check()
        self.rows.clear()


class GSheetTable:
    """One worksheet of the real Google Sheet (via gspread)."""

    def __init__(self, ws):
        self.ws = ws
        self.headers = ws.row_values(1)

    def read(self) -> list[dict]:
        return self.ws.get_all_records(default_blank="")

    def append(self, row: dict) -> None:
        self.ws.append_row([row.get(h, "") for h in self.headers],
                           value_input_option="RAW", insert_data_option="INSERT_ROWS",
                           table_range="A1")

    def _find(self, match: dict) -> int | None:
        values = self.ws.get_all_values()
        hdr = values[0]
        for i, r in enumerate(values[1:], start=2):
            r = r + [""] * (len(hdr) - len(r))
            if all(str(r[hdr.index(k)]) == str(v) for k, v in match.items()):
                return i
        return None

    def update(self, match: dict, values: dict) -> bool:
        from gspread.utils import rowcol_to_a1
        i = self._find(match)
        if i is None:
            return False
        data = [{"range": rowcol_to_a1(i, self.headers.index(k) + 1), "values": [[v]]}
                for k, v in values.items() if k in self.headers]
        self.ws.batch_update(data, value_input_option="RAW")
        return True

    def delete(self, match: dict) -> bool:
        i = self._find(match)
        if i is None:
            return False
        self.ws.delete_rows(i)
        return True

    def clear(self) -> None:
        # Clearing (not deleting) rows avoids Sheets' "can't delete all rows" error.
        self.ws.batch_clear(["A2:Z"])


def open_google_sheet(sheet_id: str, credentials_json: str) -> tuple[dict, dict]:
    """Open the sheet, create any missing tab, and return (real, test) tables."""
    import gspread
    gc = gspread.service_account_from_dict(json.loads(credentials_json))
    book = gc.open_by_key(sheet_id)
    existing = {ws.title: ws for ws in book.worksheets()}

    def table(key: str, title: str) -> GSheetTable:
        ws = existing.get(title)
        if ws is None:
            ws = book.add_worksheet(title=title, rows=1000, cols=len(HEADERS[key]))
            ws.append_row(HEADERS[key], value_input_option="RAW")
        have = ws.row_values(1)
        lacking = [h for h in HEADERS[key] if h not in have]
        if lacking:
            raise SystemExit(f"Tab '{title}' is missing columns: {', '.join(lacking)}")
        return GSheetTable(ws)

    real = {k: table(k, t) for k, t in REAL_TABS.items()}
    test = {k: table(k, t) for k, t in TEST_TABS.items()}
    return real, test


# ---------------------------------------------------------------------- store
class Store:
    def __init__(self, real: dict, test: dict, log: Callable[[str], None] = print):
        self.tables = {False: real, True: {**real, **test}}
        self.log = log
        self.queue: list[tuple[Callable[[], object], str]] = []
        self.cache: dict[bool, dict[str, list[dict]]] = {False: {}, True: {}}

    def load(self) -> None:
        for key, t in self.tables[False].items():
            self.cache[False][key] = t.read()
        for key in LOGGED:
            self.cache[True][key] = self.tables[True][key].read()
        for key in ("program", "exercises"):          # shared, same list object
            self.cache[True][key] = self.cache[False][key]

    # -- reading
    def rows(self, key: str, test: bool = False) -> list[dict]:
        return self.cache[test][key]

    # -- the write queue
    @property
    def pending(self) -> int:
        return len(self.queue)

    def _enqueue(self, fn: Callable[[], object], desc: str) -> bool:
        self.queue.append((fn, desc))
        return self.flush()

    def flush(self) -> bool:
        """Push queued writes in order. Returns True when everything is saved."""
        while self.queue:
            fn, desc = self.queue[0]
            try:
                fn()
            except Exception as e:                  # noqa: BLE001 - any failure: keep it queued
                self.log(f"sheet write failed ({desc}), will retry: {e}")
                return False
            self.queue.pop(0)
        return True

    # -- writing (cache first, then queued sheet write)
    def append(self, key: str, row: dict, test: bool = False) -> bool:
        table = self.tables[test][key]
        row = {h: row.get(h, "") for h in HEADERS[key]}
        self.cache[test][key].append(row)
        return self._enqueue(lambda: table.append(row), f"add {key}")

    def update(self, key: str, match: dict, values: dict, test: bool = False) -> bool:
        table = self.tables[test][key]
        for r in self.cache[test][key]:
            if _match(r, match):
                r.update(values)
                break
        return self._enqueue(lambda: table.update(match, values), f"update {key}")

    def delete(self, key: str, match: dict, test: bool = False) -> bool:
        table = self.tables[test][key]
        rows = self.cache[test][key]
        for i, r in enumerate(rows):
            if _match(r, match):
                del rows[i]
                break
        return self._enqueue(lambda: table.delete(match), f"delete {key}")

    # -- test-mode helpers
    def reread(self, key: str, test: bool) -> list[dict]:
        """Read a tab fresh from the sheet, bypassing the cache (used by Check save)."""
        return self.tables[test][key].read()

    def clear_test(self) -> bool:
        ok = True
        for key in LOGGED:
            self.cache[True][key].clear()
            table = self.tables[True][key]
            ok = self._enqueue(table.clear, f"clear test {key}") and ok
        return ok
