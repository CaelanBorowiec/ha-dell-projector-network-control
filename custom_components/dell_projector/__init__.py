"""The Dell Projector Network Interface integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    Dell7609AuthError,
    Dell7609Client,
    Dell7609Error,
)
from .coordinator import Dell7609ConfigEntry, Dell7609Coordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: Dell7609ConfigEntry) -> bool:
    """Set up Dell Projector Network Interface from a config entry."""
    client = Dell7609Client(
        entry.data[CONF_HOST],
        async_create_clientsession(hass),
        password=entry.data.get(CONF_PASSWORD),
    )
    coordinator = Dell7609Coordinator(hass, entry, client)

    try:
        await client.async_validate()
    except Dell7609AuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except Dell7609Error as err:
        raise ConfigEntryNotReady(str(err)) from err

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Dell7609ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
