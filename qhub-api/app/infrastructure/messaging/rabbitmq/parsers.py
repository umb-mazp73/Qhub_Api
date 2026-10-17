import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.application.errors import PermanentMessageError
from app.domain.models import (
    FanoutNotification,
    NotificationJob,
    PersonalNotificationWire,
    QueueEventEnvelope,
    freeze_json,
)
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import OwnerId, PersonIdentity, QueueSubscription


def _error(
    message_kind: str, reason: str, detail: str
) -> PermanentMessageError:
    return PermanentMessageError(
        detail=detail,
        reason=reason,
        message_kind=message_kind,
    )


def _decode(body: bytes, message_kind: str) -> Mapping[str, object]:
    if not isinstance(body, bytes):
        raise _error(message_kind, "type", "El cuerpo debe ser bytes")
    try:
        value = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise _error(message_kind, "decode", "UTF-8 inválido") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise _error(message_kind, "decode", "JSON inválido") from exc
    if not isinstance(value, dict):
        raise _error(message_kind, "shape", "La raíz debe ser un objeto")
    return value


def _required_string(
    value: Mapping[str, object], name: str, message_kind: str
) -> str:
    if name not in value:
        raise _error(message_kind, "missing", f"Falta {name}")
    item = value[name]
    if not isinstance(item, str):
        raise _error(message_kind, "type", f"{name} debe ser string")
    if item == "":
        raise _error(message_kind, "empty", f"{name} no puede estar vacío")
    return item


def _uuid(value: str, name: str, message_kind: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise _error(message_kind, "uuid", f"{name} debe ser UUID") from exc


class NotificationJobParser:
    def parse(self, body: bytes) -> NotificationJob:
        return self.parse_mapping(_decode(body, "notification_job"))

    def parse_mapping(self, data: Mapping[str, object]) -> NotificationJob:
        if not isinstance(data, Mapping):
            raise _error(
                "notification_job", "shape", "La raíz debe ser un objeto"
            )
        key = _uuid(
            _required_string(data, "clave", "notification_job"),
            "clave",
            "notification_job",
        )
        owner_type_value = _required_string(
            data, "propietario_tipo", "notification_job"
        )
        try:
            owner_type = PropietarioTipo(owner_type_value)
        except ValueError as exc:
            raise _error(
                "notification_job", "enum", "propietario_tipo inválido"
            ) from exc
        owner_id = _uuid(
            _required_string(data, "propietario_id", "notification_job"),
            "propietario_id",
            "notification_job",
        )
        user_id = _required_string(data, "usuario_id", "notification_job")
        message = _required_string(data, "mensaje", "notification_job")
        turn_value = data.get("turno_id")
        if turn_value is not None and not isinstance(turn_value, str):
            raise _error(
                "notification_job", "type", "turno_id debe ser string o null"
            )
        turn_id = (
            None
            if turn_value is None
            else _uuid(turn_value, "turno_id", "notification_job")
        )
        type_value = data.get("tipo", "generica")
        if not isinstance(type_value, str):
            raise _error(
                "notification_job", "type", "tipo debe ser string"
            )
        if type_value == "":
            raise _error(
                "notification_job", "empty", "tipo no puede estar vacío"
            )
        return NotificationJob(
            key=key,
            identity=PersonIdentity(OwnerId(owner_type, owner_id), user_id),
            message=message,
            turn_id=turn_id,
            notice_type=type_value,
        )


def parse_queue_event(body: bytes) -> QueueEventEnvelope:
    data = _decode(body, "queue_event")
    event_type = _required_string(data, "tipo", "queue_event")
    queue_id = _uuid(
        _required_string(data, "cola_id", "queue_event"),
        "cola_id",
        "queue_event",
    )
    if "payload" not in data:
        raise _error("queue_event", "missing", "Falta payload")
    if not isinstance(data["payload"], dict):
        raise _error("queue_event", "shape", "payload debe ser un objeto")
    frozen = freeze_json(dict(data))
    if not isinstance(frozen, Mapping):
        raise _error("queue_event", "shape", "La raíz debe ser un objeto")
    payload = frozen["payload"]
    if not isinstance(payload, Mapping):
        raise _error("queue_event", "shape", "payload debe ser un objeto")
    return QueueEventEnvelope(queue_id, event_type, payload, frozen)


class RabbitQueueEventParser:
    """Mensaje de una cola dedicada: además de ser válido, tiene que ser de ESA cola."""

    def parse(
        self, body: bytes, subscription: QueueSubscription
    ) -> QueueEventEnvelope:
        event = parse_queue_event(body)
        if event.queue_id != subscription.queue_id:
            raise _error("queue_event", "queue_mismatch", "cola_id no coincide")
        return event


class FanoutQueueEventParser:
    """Mensaje del exchange de difusión: llega el evento de cualquier cola."""

    def parse(self, body: bytes) -> QueueEventEnvelope:
        return parse_queue_event(body)


class FanoutNotificationParser:
    def parse(self, body: bytes) -> FanoutNotification:
        data = _decode(body, "fanout")
        owner_type_value = _required_string(data, "propietario_tipo", "fanout")
        try:
            owner_type = PropietarioTipo(owner_type_value)
        except ValueError as exc:
            raise _error("fanout", "enum", "propietario_tipo inválido") from exc
        owner_id = _uuid(
            _required_string(data, "propietario_id", "fanout"),
            "propietario_id",
            "fanout",
        )
        user_id = _required_string(data, "usuario_id", "fanout")
        frame = data.get("mensaje")
        if not isinstance(frame, dict):
            raise _error("fanout", "shape", "mensaje debe ser un objeto")
        if frame.get("tipo") != "notificacion":
            raise _error("fanout", "enum", "tipo de frame inválido")
        notification = frame.get("notificacion")
        if not isinstance(notification, dict):
            raise _error(
                "fanout", "shape", "notificacion debe ser un objeto"
            )
        notification_id = _required_string(notification, "id", "fanout")
        _uuid(notification_id, "id", "fanout")
        message = _required_string(notification, "mensaje", "fanout")
        notice_type = _required_string(
            notification, "tipo_aviso", "fanout"
        )
        turn_value = notification.get("turno_id")
        if turn_value is not None:
            if not isinstance(turn_value, str):
                raise _error(
                    "fanout", "type", "turno_id debe ser string o null"
                )
            _uuid(turn_value, "turno_id", "fanout")
        read = notification.get("leida")
        if type(read) is not bool:
            raise _error("fanout", "type", "leida debe ser bool")
        created_at = _required_string(
            notification, "creada_en", "fanout"
        )
        try:
            parsed_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _error("fanout", "type", "creada_en inválida") from exc
        if parsed_at.tzinfo is None:
            raise _error("fanout", "type", "creada_en debe incluir zona")
        return FanoutNotification(
            identity=PersonIdentity(OwnerId(owner_type, owner_id), user_id),
            message=PersonalNotificationWire(
                notification_id=notification_id,
                message=message,
                turn_id=turn_value,
                notice_type=notice_type,
                read=read,
                created_at=created_at,
            ),
        )

