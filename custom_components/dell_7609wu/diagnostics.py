"""Diagnostics support for the Dell 7609WU integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .api import state_as_dict
from .coordinator import Dell7609ConfigEntry

TO_REDACT = {CONF_PASSWORD, "mac_address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Dell7609ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "state": async_redact_data(state_as_dict(coordinator.data), TO_REDACT),
    }
