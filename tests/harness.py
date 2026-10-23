import os
from datetime import datetime

from gymbot.app import App
from gymbot.clock import FakeClock
from gymbot.fakes import FakeTelegram, load_xlsx, memory_tables
from gymbot.store import Store

CHAT = 42
import pytest

XLSX = os.path.join(os.path.dirname(__file__), "gym-log.xlsx")
if not os.path.exists(XLSX):
    pytest.skip("tests/gym-log.xlsx not present (it holds your own data and is git-ignored)", allow_module_level=True)


class Bot:
    def __init__(self, seed=None, tables=None, start=datetime(2026, 10, 26, 19, 0)):
        self.real, self.test = tables or memory_tables(load_xlsx(XLSX) if seed is None else seed)
        self.tg = FakeTelegram()
        self.clock = FakeClock(start)
        self.logs = []
        self.app = App(CHAT, self.tg, Store(self.real, self.test, log=self.logs.append), self.clock)
        self.app.start()
        self.uid = 0

    # what's on screen
    @property
    def screen(self):
        return self.tg.messages[self.app.screen]

    @property
    def text(self):
        return self.screen["text"]

    def buttons(self):
        return [b for row in self.screen["kb"]["inline_keyboard"] for b in row]

    # actions
    def say(self, text):
        self.uid += 1
        self.app.handle({"update_id": self.uid, "message": {"message_id": 1000 + self.uid,
                         "chat": {"id": CHAT}, "from": {"id": CHAT}, "text": text}})

    def tap(self, label, nth=0):
        btn = [b for b in self.buttons() if label in b["text"]][nth:]
        assert btn, f"no button {label!r} in {[b['text'] for b in self.buttons()]}"
        self.uid += 1
        self.app.handle({"update_id": self.uid, "callback_query": {
            "id": str(self.uid), "from": {"id": CHAT}, "data": btn[0]["callback_data"],
            "message": {"message_id": self.app.screen}}})

    def sets(self, test=False):
        return (self.test if test else self.real)["sets"].rows
