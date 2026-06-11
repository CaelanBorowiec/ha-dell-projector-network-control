"""Base entity for the Dell 7609WU integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import Dell7609Coordinator


class Dell7609Entity(CoordinatorEntity[Dell7609Coordinator]):
    """Base entity tied to one projector."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Dell7609Coordinator, key: str) -> None:
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
            model=MODEL,
            name=state.projector_name or f"Dell {MODEL}",
            sw_version=state.firmware_version,
            configuration_url=f"http://{coordinator.client.host}/",
        )
