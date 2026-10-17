from app.domain.interfaces.delivery import NotificationDeliveryChannel
from app.domain.entities import Notificacion


class DeliveryDispatcher:
    def __init__(
        self, channels: tuple[NotificationDeliveryChannel, ...]
    ) -> None:
        self._channels = channels

    @property
    def channels(self) -> tuple[NotificationDeliveryChannel, ...]:
        return self._channels

    async def deliver(
        self, notification: Notificacion, notice_type: str
    ) -> None:
        for channel in self._channels:
            await channel.deliver(notification, notice_type)
