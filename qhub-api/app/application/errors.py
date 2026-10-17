from dataclasses import dataclass
from typing import Literal


class ApplicationError(Exception):
    """Base class for errors crossing an application boundary."""


@dataclass(frozen=True, slots=True)
class BadRequest(ApplicationError):
    detail: str
    source_code: str | None = None
    kind: Literal["bad_request"] = "bad_request"


@dataclass(frozen=True, slots=True)
class UnprocessableInput(ApplicationError):
    detail: str
    source_code: str | None = None
    kind: Literal["unprocessable_input"] = "unprocessable_input"


@dataclass(frozen=True, slots=True)
class Conflict(ApplicationError):
    detail: str
    source_code: str | None = None
    kind: Literal["conflict"] = "conflict"


@dataclass(frozen=True, slots=True)
class NotFound(ApplicationError):
    detail: str
    resource: str
    kind: Literal["not_found"] = "not_found"


@dataclass(frozen=True, slots=True)
class Unauthorized(ApplicationError):
    detail: str
    reason: Literal["missing", "invalid", "expired", "inactive"]
    kind: Literal["unauthorized"] = "unauthorized"


@dataclass(frozen=True, slots=True)
class Forbidden(ApplicationError):
    detail: str
    required_role: str | None = None
    kind: Literal["forbidden"] = "forbidden"


@dataclass(frozen=True, slots=True)
class TooManyRequests(ApplicationError):
    detail: str
    retry_after_seconds: int
    kind: Literal["too_many_requests"] = "too_many_requests"


@dataclass(frozen=True, slots=True)
class PersistenceUnavailable(ApplicationError):
    operation: str
    detail: str = "Servicio de persistencia no disponible"
    kind: Literal["persistence_unavailable"] = "persistence_unavailable"


@dataclass(frozen=True, slots=True)
class PersistenceFailure(ApplicationError):
    operation: str
    detail: str = "Error interno de persistencia"
    kind: Literal["persistence_failure"] = "persistence_failure"


@dataclass(frozen=True, slots=True)
class BrokerUnavailable(ApplicationError):
    operation: str
    detail: str = "Broker no disponible"
    kind: Literal["broker_unavailable"] = "broker_unavailable"


@dataclass(frozen=True, slots=True)
class CryptoFailure(ApplicationError):
    operation: Literal["password_hash", "password_verify", "token_issue", "token_verify"]
    detail: str = "Error interno de seguridad"
    kind: Literal["crypto_failure"] = "crypto_failure"


@dataclass(frozen=True, slots=True)
class PermanentMessageError(ApplicationError):
    detail: str
    reason: Literal[
        "decode",
        "shape",
        "missing",
        "type",
        "empty",
        "uuid",
        "enum",
        "queue_mismatch",
        "idempotency_collision",
    ]
    message_kind: Literal["queue_event", "notification_job", "fanout"]
    kind: Literal["permanent_message"] = "permanent_message"


@dataclass(frozen=True, slots=True)
class PermanentDeliveryError(ApplicationError):
    detail: str
    channel: str
    reason: Literal["invalid_destination", "rejected", "unsupported"]
    kind: Literal["permanent_delivery"] = "permanent_delivery"


