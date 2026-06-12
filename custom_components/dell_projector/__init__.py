"""The Dell Projector Network Interface integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    DellProjectorAuthError,
    DellProjectorClient,
    DellProjectorError,
)
from .coordinator import DellProjectorConfigEntry, DellProjectorCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: DellProjectorConfigEntry
) -> bool:
    """Set up Dell Projector Network Interface from a config entry."""
    client = DellProjectorClient(
        entry.data[CONF_HOST],
        async_create_clientsession(hass),
        password=entry.data.get(CONF_PASSWORD),
    )
    coordinator = DellProjectorCoordinator(hass, entry, client)

    try:
        await client.async_validate()
    except DellProjectorAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except DellProjectorError as err:
        raise ConfigEntryNotReady(str(err)) from err

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DellProjectorConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
