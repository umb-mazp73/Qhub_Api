from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DomainError(Exception):
    detail: str


@dataclass(frozen=True, slots=True)
class InvalidSchedule(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class InvalidTurnTransition(DomainError):
    pass
