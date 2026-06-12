"""Switch entities for the Dell projector integration."""

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

from .api import DellProjectorClient, ProjectorState
from .coordinator import DellProjectorConfigEntry, DellProjectorCoordinator
from .entity import DellProjectorEntity


@dataclass(frozen=True, kw_only=True)
class DellProjectorSwitchDescription(SwitchEntityDescription):
    """Describes a Dell projector switch."""

    is_on_fn: Callable[[ProjectorState], bool | None]
    turn_on_fn: Callable[[DellProjectorClient], Awaitable[None]]
    turn_off_fn: Callable[[DellProjectorClient], Awaitable[None]]
    skip_refresh: bool = False


SWITCHES: tuple[DellProjectorSwitchDescription, ...] = (
    DellProjectorSwitchDescription(
        key="power",
        translation_key="power",
        device_class=SwitchDeviceClass.SWITCH,
        is_on_fn=lambda state: state.is_on,
        turn_on_fn=lambda client: client.async_power_on(),
        turn_off_fn=lambda client: client.async_power_off(),
        skip_refresh=True,
    ),
    DellProjectorSwitchDescription(
        key="blank_screen",
        translation_key="blank_screen",
        device_class=SwitchDeviceClass.SWITCH,
        is_on_fn=lambda state: state.blank_screen,
        turn_on_fn=lambda client: client.async_set_blank_screen(True),
        turn_off_fn=lambda client: client.async_set_blank_screen(False),
        skip_refresh=True,
    ),
    DellProjectorSwitchDescription(
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
    entry: DellProjectorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        DellProjectorSwitch(coordinator, description) for description in SWITCHES
    )


class DellProjectorSwitch(DellProjectorEntity, SwitchEntity):
    """A projector switch."""

    entity_description: DellProjectorSwitchDescription

    def __init__(
        self,
        coordinator: DellProjectorCoordinator,
        description: DellProjectorSwitchDescription,
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
