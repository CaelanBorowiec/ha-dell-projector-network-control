"""Number entities for the Dell 7609WU integration."""

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

from .api import Dell7609Client, ProjectorState
from .const import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CONTRAST_MAX,
    CONTRAST_MIN,
    VOLUME_MAX,
    VOLUME_MIN,
)
from .coordinator import Dell7609ConfigEntry, Dell7609Coordinator
from .entity import Dell7609Entity


@dataclass(frozen=True, kw_only=True)
class Dell7609NumberDescription(NumberEntityDescription):
    """Describes a Dell 7609WU number."""

    value_fn: Callable[[ProjectorState], int | None]
    set_fn: Callable[[Dell7609Client, int], Awaitable[None]]


NUMBERS: tuple[Dell7609NumberDescription, ...] = (
    Dell7609NumberDescription(
        key="brightness",
        translation_key="brightness",
        native_min_value=BRIGHTNESS_MIN,
        native_max_value=BRIGHTNESS_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda state: state.brightness,
        set_fn=lambda client, value: client.async_set_brightness(value),
    ),
    Dell7609NumberDescription(
        key="contrast",
        translation_key="contrast",
        native_min_value=CONTRAST_MIN,
        native_max_value=CONTRAST_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda state: state.contrast,
        set_fn=lambda client, value: client.async_set_contrast(value),
    ),
    Dell7609NumberDescription(
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
    entry: Dell7609ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        Dell7609Number(coordinator, description) for description in NUMBERS
    )


class Dell7609Number(Dell7609Entity, NumberEntity):
    """A projector number control."""

    entity_description: Dell7609NumberDescription

    def __init__(
        self,
        coordinator: Dell7609Coordinator,
        description: Dell7609NumberDescription,
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
