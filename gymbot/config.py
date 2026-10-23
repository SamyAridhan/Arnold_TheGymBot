"""Secrets and constants. Nothing user-facing lives here."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    token: str
    chat_id: int
    sheet_id: str
    google_credentials: str      # service-account JSON, as a string
    tz: str = "Asia/Kuala_Lumpur"
    max_runtime: int = 0         # seconds; 0 = run forever (GitHub Actions sets ~5h40m)
    idle_close_min: int = 90     # auto-close a session after this long with no sets
    announce: bool = False       # send an "online" message at startup (new version, manual run)

    @classmethod
    def from_env(cls) -> "Config":
        missing = [k for k in ("TELEGRAM_TOKEN", "CHAT_ID", "SHEET_ID", "GOOGLE_CREDENTIALS")
                   if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Missing environment variables: {', '.join(missing)}")
        return cls(
            token=os.environ["TELEGRAM_TOKEN"],
            chat_id=int(os.environ["CHAT_ID"]),
            sheet_id=os.environ["SHEET_ID"],
            google_credentials=os.environ["GOOGLE_CREDENTIALS"],
            tz=os.environ.get("TZ_NAME", "Asia/Kuala_Lumpur"),
            max_runtime=int(os.environ.get("MAX_RUNTIME", "0")),
            idle_close_min=int(os.environ.get("IDLE_CLOSE_MIN", "90")),
            announce=os.environ.get("ANNOUNCE", "").lower() == "true",
        )
