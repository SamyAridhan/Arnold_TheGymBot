"""Run the bot:  python -m gymbot"""
import html
import os
import sys
import traceback

from .app import App
from .clock import Clock
from .config import Config
from .store import Store, open_google_sheet
from .telegram import Telegram

HINTS = {
    "Missing environment variables": "A GitHub secret is missing or misnamed (Settings → Secrets → Actions).",
    "SpreadsheetNotFound": "SHEET_ID looks wrong, or the sheet isn't shared with the service account.",
    "has not been used in project": "Enable the Google Sheets API in the same Google Cloud project as the key.",
    "PERMISSION_DENIED": "Share the sheet with the service account email as Editor.",
    "JSONDecodeError": "GOOGLE_CREDENTIALS isn't the whole JSON file: paste everything from { to }.",
    "invalid literal for int": "CHAT_ID must be just the number from @userinfobot.",
    "is missing columns": "A tab's header row doesn't match; check the first row of that tab.",
    "WorksheetNotFound": "A tab is missing or renamed.",
    "404": "SHEET_ID looks wrong: copy the part between /d/ and /edit in the sheet URL.",
}


def report(err: BaseException) -> None:
    """Make a startup failure visible: a GitHub annotation and a Telegram message."""
    text = f"{type(err).__name__}: {err}"[:600]
    hint = next((h for k, h in HINTS.items() if k in text), "")
    print(f"::error title=Arnold failed to start::{text} {hint}".replace("\n", " "))
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("CHAT_ID", "").strip()
    if token and chat.lstrip("-").isdigit():
        try:
            Telegram(token).send(int(chat), html.escape(f"⚠️ Arnold failed to start\n{text}\n\n{hint}".strip(), quote=False))
        except Exception as e:  # noqa: BLE001
            print(f"could not send the error to Telegram: {e}")


def main() -> None:
    try:
        cfg = Config.from_env()
        real, test = open_google_sheet(cfg.sheet_id, cfg.google_credentials)
        app = App(cfg.chat_id, Telegram(cfg.token), Store(real, test), Clock(cfg.tz),
                  idle_close_min=cfg.idle_close_min)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        traceback.print_exc()
        report(e)
        sys.exit(1)
    print("gym bot running")
    app.run(cfg.max_runtime, announce=cfg.announce)


if __name__ == "__main__":
    main()
