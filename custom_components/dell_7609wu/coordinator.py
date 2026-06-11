"""Data update coordinator for the Dell 7609WU integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    Dell7609AuthError,
    Dell7609Client,
    Dell7609Error,
    ProjectorState,
)
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)

type Dell7609ConfigEntry = ConfigEntry[Dell7609Coordinator]


class Dell7609Coordinator(DataUpdateCoordinator[ProjectorState]):
    """Polls home.htm + status.htm and exposes the parsed state."""

    config_entry: Dell7609ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: Dell7609ConfigEntry,
        client: Dell7609Client,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self) -> ProjectorState:
        try:
            return await self.client.async_get_state()
        except Dell7609AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Dell7609Error as err:
            raise UpdateFailed(str(err)) from err

    async def async_send_command(self, coro) -> None:
        """Run a client command coroutine, then refresh state."""
        try:
            await coro
        except Dell7609AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        await self.async_request_refresh()
