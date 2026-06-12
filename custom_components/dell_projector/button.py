"""Button entities for the Dell projector integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DellProjectorConfigEntry, DellProjectorCoordinator
from .entity import DellProjectorEntity

AUTO_ADJUST = ButtonEntityDescription(
    key="auto_adjust",
    translation_key="auto_adjust",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DellProjectorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data
    async_add_entities([DellProjectorAutoAdjustButton(coordinator)])


class DellProjectorAutoAdjustButton(DellProjectorEntity, ButtonEntity):
    """Triggers the projector's auto adjust."""

    entity_description = AUTO_ADJUST

    def __init__(self, coordinator: DellProjectorCoordinator) -> None:
        super().__init__(coordinator, AUTO_ADJUST.key)

    async def async_press(self) -> None:
        await self.coordinator.async_send_command(
            self.coordinator.client.async_auto_adjust()
        )
