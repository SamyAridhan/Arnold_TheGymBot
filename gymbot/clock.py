"""Time in Malaysia (UTC+8). Injectable so tests can move time forward."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class Clock:
    def __init__(self, tz: str = "Asia/Kuala_Lumpur"):
        self.tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(self.tz).replace(microsecond=0)


class FakeClock(Clock):
    def __init__(self, start: datetime, tz: str = "Asia/Kuala_Lumpur"):
        super().__init__(tz)
        self.t = start.replace(tzinfo=self.tz)

    def now(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_stamp(s: str, tz) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    except ValueError:
        return None
