"""Print the main screens with your real data, no Telegram or Google needed.

    python -m gymbot.demo tests/gym-log.xlsx
"""
import re
import sys
from datetime import datetime

from .app import App
from .clock import FakeClock
from .fakes import FakeTelegram, load_xlsx, memory_tables
from .store import Store


def show(title, app, tg):
    msg = tg.messages[app.screen]
    text = re.sub(r"</?(b|i|pre)>", "", msg["text"]).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    print(f"\n===== {title} " + "=" * (40 - len(title)))
    print(text)
    for row in msg["kb"]["inline_keyboard"]:
        print("  " + "  ".join(f"[ {b['text']} ]" for b in row))


def main(path: str) -> None:
    real, test = memory_tables(load_xlsx(path))
    tg = FakeTelegram()
    app = App(1, tg, Store(real, test), FakeClock(datetime(2026, 10, 26, 19, 0)))
    app.start()

    def say(t):
        app.handle({"update_id": 0, "message": {"message_id": 0, "chat": {"id": 1}, "text": t}})

    def tap(data):
        app.handle({"update_id": 0, "callback_query": {"id": "q", "from": {"id": 1}, "data": data,
                                                       "message": {"message_id": app.screen}}})

    say("/go"); show("Home", app, tg)
    tap("go:UB1"); show("Exercise card", app, tg)
    tap("log"); say("6 4"); tap("log"); show("After 3 sets", app, tg)
    tap("pn"); show("Pick next", app, tg)
    tap("ex:4"); tap("var"); show("Variant picker", app, tg)
    tap("card"); tap("nt"); show("Notes", app, tg)
    tap("card"); tap("pn"); tap("fin"); show("Finish", app, tg)
    say("/test"); show("Test session", app, tg)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/gym-log.xlsx")
