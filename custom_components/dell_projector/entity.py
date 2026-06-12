"""Base entity for the Dell projector integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import DellProjectorCoordinator


class DellProjectorEntity(CoordinatorEntity[DellProjectorCoordinator]):
    """Base entity tied to one projector."""

    _attr_has_entity_name = True
    _requires_lamp_on: bool = False

    def __init__(self, coordinator: DellProjectorCoordinator, key: str) -> None:
        super().__init__(coordinator)
        state = coordinator.data
        mac = format_mac(state.mac_address or coordinator.client.host)
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections=(
                {(CONNECTION_NETWORK_MAC, mac)} if state.mac_address else set()
            ),
            manufacturer=MANUFACTURER,
            model=state.group_name or DEFAULT_MODEL,
            name=state.projector_name
            or (
                f"Dell {state.group_name}"
                if state.group_name
                else "Dell Projector Network Interface"
            ),
            sw_version=state.firmware_version,
            configuration_url=f"http://{coordinator.client.host}/",
        )

    @property
    def available(self) -> bool:
        """Runtime controls are inactive while the lamp is off."""
        if self._requires_lamp_on and not self.coordinator.data.is_on:
            return False
        return super().available
