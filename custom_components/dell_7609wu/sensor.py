"""Sensor entities for the Dell 7609WU integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .api import ProjectorState
from .coordinator import Dell7609ConfigEntry, Dell7609Coordinator
from .entity import Dell7609Entity


@dataclass(frozen=True, kw_only=True)
class Dell7609SensorDescription(SensorEntityDescription):
    """Describes a Dell 7609WU sensor."""

    value_fn: Callable[[ProjectorState], StateType]


SENSORS: tuple[Dell7609SensorDescription, ...] = (
    Dell7609SensorDescription(
        key="status",
        translation_key="status",
        value_fn=lambda state: state.power_status,
    ),
    Dell7609SensorDescription(
        key="lamp_hours",
        translation_key="lamp_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda state: state.lamp_hours,
    ),
    Dell7609SensorDescription(
        key="error_status",
        translation_key="error_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.error_status or "OK",
    ),
    Dell7609SensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.firmware_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Dell7609ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        Dell7609Sensor(coordinator, description) for description in SENSORS
    )


class Dell7609Sensor(Dell7609Entity, SensorEntity):
    """A projector sensor."""

    entity_description: Dell7609SensorDescription

    def __init__(
        self,
        coordinator: Dell7609Coordinator,
        description: Dell7609SensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)
