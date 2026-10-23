"""Run the bot:  python -m gymbot"""
from .app import App
from .clock import Clock
from .config import Config
from .store import Store, open_google_sheet
from .telegram import Telegram


def main() -> None:
    cfg = Config.from_env()
    real, test = open_google_sheet(cfg.sheet_id, cfg.google_credentials)
    app = App(cfg.chat_id, Telegram(cfg.token), Store(real, test), Clock(cfg.tz),
              idle_close_min=cfg.idle_close_min)
    print("gym bot running")
    app.run(cfg.max_runtime, announce=cfg.announce)


if __name__ == "__main__":
    main()
