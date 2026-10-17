from uuid import UUID

from app.domain.models import MAX_PAGE_SIZE
from app.domain.interfaces.queues import ActiveQueueSubscriptionSource
from app.domain.value_objects import QueueSubscription


class SupabaseActiveQueueSubscriptionSource(ActiveQueueSubscriptionSource):
    def __init__(self, client) -> None:
        self._client = client

    async def list_active(self) -> tuple[QueueSubscription, ...]:
        subscriptions: list[QueueSubscription] = []
        offset = 0
        while True:
            result = await (
                self._client.table("colas")
                .select("id, rabbitmq_queue_name")
                .eq("activa", True)
                .order("id")
                .range(offset, offset + MAX_PAGE_SIZE - 1)
                .execute()
            )
            subscriptions.extend(
                QueueSubscription(UUID(str(row["id"])), str(row["rabbitmq_queue_name"]))
                for row in result.data
            )
            if len(result.data) < MAX_PAGE_SIZE:
                return tuple(subscriptions)
            offset += MAX_PAGE_SIZE
