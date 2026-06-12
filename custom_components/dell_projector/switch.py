"""Switch entities for the Dell 7609WU integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Dell7609Client, ProjectorState
from .coordinator import Dell7609ConfigEntry, Dell7609Coordinator
from .entity import Dell7609Entity


@dataclass(frozen=True, kw_only=True)
class Dell7609SwitchDescription(SwitchEntityDescription):
    """Describes a Dell 7609WU switch."""

    is_on_fn: Callable[[ProjectorState], bool | None]
    turn_on_fn: Callable[[Dell7609Client], Awaitable[None]]
    turn_off_fn: Callable[[Dell7609Client], Awaitable[None]]
    skip_refresh: bool = False


SWITCHES: tuple[Dell7609SwitchDescription, ...] = (
    Dell7609SwitchDescription(
        key="power",
        translation_key="power",
        device_class=SwitchDeviceClass.SWITCH,
        is_on_fn=lambda state: state.is_on,
        turn_on_fn=lambda client: client.async_power_on(),
        turn_off_fn=lambda client: client.async_power_off(),
        skip_refresh=True,
    ),
    Dell7609SwitchDescription(
        key="blank_screen",
        translation_key="blank_screen",
        device_class=SwitchDeviceClass.SWITCH,
        is_on_fn=lambda state: state.blank_screen,
        turn_on_fn=lambda client: client.async_set_blank_screen(True),
        turn_off_fn=lambda client: client.async_set_blank_screen(False),
        skip_refresh=True,
    ),
    Dell7609SwitchDescription(
        key="eco_mode",
        translation_key="eco_mode",
        device_class=SwitchDeviceClass.SWITCH,
        is_on_fn=lambda state: state.eco_mode,
        turn_on_fn=lambda client: client.async_set_eco_mode(True),
        turn_off_fn=lambda client: client.async_set_eco_mode(False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Dell7609ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        Dell7609Switch(coordinator, description) for description in SWITCHES
    )


class Dell7609Switch(Dell7609Entity, SwitchEntity):
    """A projector switch."""

    entity_description: Dell7609SwitchDescription

    def __init__(
        self,
        coordinator: Dell7609Coordinator,
        description: Dell7609SwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_send_command(
            self.entity_description.turn_on_fn(self.coordinator.client),
            skip_refresh=self.entity_description.skip_refresh,
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send_command(
            self.entity_description.turn_off_fn(self.coordinator.client),
            skip_refresh=self.entity_description.skip_refresh,
        )
