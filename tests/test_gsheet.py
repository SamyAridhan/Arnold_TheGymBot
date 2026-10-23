"""GSheetTable against a stand-in that mimics gspread's worksheet calls:
values come back as display strings, records come back numericised."""
from gspread.utils import a1_to_rowcol, numericise_all

from gymbot.store import GSheetTable, HEADERS


class FakeWorksheet:
    def __init__(self, headers):
        self.grid = [list(headers)]

    def row_values(self, i):
        return list(self.grid[i - 1])

    def get_all_values(self):
        w = len(self.grid[0])
        return [[str(c) for c in r] + [""] * (w - len(r)) for r in self.grid]

    def get_all_records(self, default_blank=""):
        hdr, *rows = self.get_all_values()
        return [dict(zip(hdr, numericise_all(r, default_blank=default_blank))) for r in rows if any(r)]

    def append_row(self, values, value_input_option, insert_data_option, table_range):
        assert value_input_option == "RAW"
        while len(self.grid) > 1 and not any(self.grid[-1]):   # table ends at last non-empty row
            self.grid.pop()
        self.grid.append(["" if v is None else str(v) for v in values])

    def batch_update(self, data, value_input_option):
        for d in data:
            r, c = a1_to_rowcol(d["range"])
            self.grid[r - 1][c - 1] = str(d["values"][0][0])

    def delete_rows(self, i):
        del self.grid[i - 1]

    def batch_clear(self, ranges):
        assert ranges == ["A2:Z"]
        for r in self.grid[1:]:
            r[:] = [""] * len(r)


def test_round_trip():
    ws = FakeWorksheet(HEADERS["sets"])
    t = GSheetTable(ws)
    row = {"set_time": "2026-10-26 19:00:00", "session_id": "2026-10-26-UB1", "date": "2026-10-26",
           "session": "UB1", "exercise": "Chest press", "variant": "Usual", "slot": "W1",
           "load": 3, "unit": "plates", "reps": 5, "tag": ""}
    t.append(row)
    t.append({**row, "slot": "W2", "load": 6, "reps": 3})
    got = t.read()
    assert got[0]["load"] == 3 and got[0]["date"] == "2026-10-26" and got[0]["tag"] == ""
    key = {"session_id": "2026-10-26-UB1", "exercise": "Chest press", "variant": "Usual", "slot": "W2"}
    assert t.update(key, {"reps": 4})
    assert t.read()[1]["reps"] == 4 and t.read()[1]["load"] == 6     # other cells untouched
    assert t.delete({**key, "slot": "W1"})
    assert [r["slot"] for r in t.read()] == ["W2"]
    assert not t.update({**key, "slot": "S9"}, {"reps": 1})
    t.clear()
    assert t.read() == []
    t.append(row)                                                    # appends right after header
    assert len(t.read()) == 1 and ws.grid[1][0] == "2026-10-26 19:00:00"
