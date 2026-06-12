"""Number entities for the Dell projector integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DellProjectorClient, ProjectorState
from .const import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CONTRAST_MAX,
    CONTRAST_MIN,
    VOLUME_MAX,
    VOLUME_MIN,
)
from .coordinator import DellProjectorConfigEntry, DellProjectorCoordinator
from .entity import DellProjectorEntity


@dataclass(frozen=True, kw_only=True)
class DellProjectorNumberDescription(NumberEntityDescription):
    """Describes a Dell projector number."""

    value_fn: Callable[[ProjectorState], int | None]
    set_fn: Callable[[DellProjectorClient, int], Awaitable[None]]


NUMBERS: tuple[DellProjectorNumberDescription, ...] = (
    DellProjectorNumberDescription(
        key="brightness",
        translation_key="brightness",
        native_min_value=BRIGHTNESS_MIN,
        native_max_value=BRIGHTNESS_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda state: state.brightness,
        set_fn=lambda client, value: client.async_set_brightness(value),
    ),
    DellProjectorNumberDescription(
        key="contrast",
        translation_key="contrast",
        native_min_value=CONTRAST_MIN,
        native_max_value=CONTRAST_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda state: state.contrast,
        set_fn=lambda client, value: client.async_set_contrast(value),
    ),
    DellProjectorNumberDescription(
        key="volume",
        translation_key="volume",
        native_min_value=VOLUME_MIN,
        native_max_value=VOLUME_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda state: state.volume,
        set_fn=lambda client, value: client.async_set_volume(value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DellProjectorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        DellProjectorNumber(coordinator, description) for description in NUMBERS
    )


class DellProjectorNumber(DellProjectorEntity, NumberEntity):
    """A projector number control."""

    entity_description: DellProjectorNumberDescription

    def __init__(
        self,
        coordinator: DellProjectorCoordinator,
        description: DellProjectorNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send_command(
            self.entity_description.set_fn(self.coordinator.client, int(value))
        )
