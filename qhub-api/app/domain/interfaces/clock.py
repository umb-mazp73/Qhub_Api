from datetime import datetime
from typing import Protocol
from uuid import UUID


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_uuid(self) -> UUID: ...
