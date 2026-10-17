from uuid import UUID

from app.application.errors import PermanentMessageError, PersistenceFailure
from app.domain.models import NotificationDraft, Page, PersistNotification
from app.domain.interfaces.notifications import (
    NotificationPersistence,
    NotificationRepository,
)
from app.domain.entities import Notificacion
from app.domain.value_objects import PersonIdentity
from app.infrastructure.persistence.supabase.error_mapping import provider_code
from app.infrastructure.persistence.supabase.mappers import notificacion_from_row


class SupabaseNotificationPersistence(NotificationPersistence):
    def __init__(self, client) -> None:
        self._client = client

    @property
    def client(self):
        return self._client

    async def persist(self, command: PersistNotification) -> Notificacion:
        identity = command.identity
        row = {
            "propietario_tipo": identity.owner.tipo.value,
            "propietario_id": str(identity.owner.id),
            "usuario_id": identity.usuario_id,
            "turno_id": str(command.turn_id) if command.turn_id else None,
            "mensaje": command.message,
            "clave_idempotencia": (
                str(command.idempotency_key)
                if command.idempotency_key is not None
                else None
            ),
        }
        try:
            result = (
                await self._client.table("notificaciones")
                .insert(row)
                .execute()
            )
        except Exception as exc:
            if (
                provider_code(exc) == "23505"
                and command.idempotency_key is not None
            ):
                existing = await self._find_by_key(
                    identity, command.idempotency_key
                )
                if existing is not None:
                    return existing
                raise PermanentMessageError(
                    detail="Colisión de idempotencia de notificación",
                    reason="idempotency_collision",
                    message_kind="notification_job",
                ) from exc
            if provider_code(exc) is not None:
                raise PersistenceFailure(
                    operation="persist_notification"
                ) from exc
            raise
        return notificacion_from_row(result.data[0])

    async def _find_by_key(
        self, identity: PersonIdentity, key: UUID
    ) -> Notificacion | None:
        result = (
            await self._client.table("notificaciones")
            .select("*")
            .eq("clave_idempotencia", str(key))
            .eq("propietario_tipo", identity.owner.tipo.value)
            .eq("propietario_id", str(identity.owner.id))
            .eq("usuario_id", identity.usuario_id)
            .limit(1)
            .execute()
        )
        return notificacion_from_row(result.data[0]) if result.data else None


class SupabaseNotificationRepository(NotificationRepository):
    def __init__(self, client) -> None:
        self._client = client
        self._persistence = SupabaseNotificationPersistence(client)

    @property
    def client(self):
        return self._client

    def _owned(self, identity: PersonIdentity):
        return (
            self._client.table("notificaciones")
            .select("*")
            .eq("usuario_id", identity.usuario_id)
            .eq("propietario_tipo", identity.owner.tipo.value)
            .eq("propietario_id", str(identity.owner.id))
        )

    async def create_idempotent(
        self, identity: PersonIdentity, draft: NotificationDraft
    ) -> Notificacion:
        return await self._persistence.persist(
            PersistNotification(
                identity=identity,
                message=draft.mensaje,
                turn_id=draft.turno_id,
                idempotency_key=draft.clave_idempotencia,
            )
        )

    async def get_by_key(
        self, identity: PersonIdentity, key: UUID
    ) -> Notificacion | None:
        return await self._persistence._find_by_key(identity, key)

    async def list(
        self, identity: PersonIdentity, page: Page
    ) -> tuple[Notificacion, ...]:
        result = await (
            self._owned(identity)
            .order("creada_en", desc=True)
            .order("id")
            .range(page.offset, page.offset + page.limit - 1)
            .execute()
        )
        return tuple(notificacion_from_row(row) for row in result.data)

    async def count_unread(self, identity: PersonIdentity) -> int:
        result = (
            await self._client.table("notificaciones")
            .select("id", count="exact")
            .eq("usuario_id", identity.usuario_id)
            .eq("propietario_tipo", identity.owner.tipo.value)
            .eq("propietario_id", str(identity.owner.id))
            .eq("leida", False)
            .limit(1)
            .execute()
        )
        return result.count or 0

    async def get(
        self, identity: PersonIdentity, notification_id: UUID
    ) -> Notificacion | None:
        result = await self._owned(identity).eq(
            "id", str(notification_id)
        ).limit(1).execute()
        return notificacion_from_row(result.data[0]) if result.data else None

    async def mark_read(
        self, identity: PersonIdentity, notification_id: UUID
    ) -> Notificacion:
        result = (
            await self._client.table("notificaciones")
            .update({"leida": True})
            .eq("usuario_id", identity.usuario_id)
            .eq("propietario_tipo", identity.owner.tipo.value)
            .eq("propietario_id", str(identity.owner.id))
            .eq("id", str(notification_id))
            .execute()
        )
        return notificacion_from_row(result.data[0])

    async def delete(
        self, identity: PersonIdentity, notification_id: UUID
    ) -> None:
        await self._client.table("notificaciones").delete().eq(
            "usuario_id", identity.usuario_id
        ).eq("propietario_tipo", identity.owner.tipo.value).eq(
            "propietario_id", str(identity.owner.id)
        ).eq("id", str(notification_id)).execute()
