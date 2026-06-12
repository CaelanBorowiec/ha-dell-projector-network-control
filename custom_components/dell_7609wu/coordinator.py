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
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN, HOME_REFRESH_EVERY_N_POLLS

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
        self._poll_count = 0

    async def _async_update_data(self) -> ProjectorState:
        self._poll_count += 1
        refresh_home = (
            self._poll_count == 1 or self._poll_count % HOME_REFRESH_EVERY_N_POLLS == 0
        )
        try:
            return await self.client.async_get_state(refresh_home=refresh_home)
        except Dell7609AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Dell7609Error as err:
            if self.client.last_state is not None:
                _LOGGER.debug(
                    "Poll failed for %s, keeping last state: %s",
                    self.client.host,
                    err,
                )
                return self.client.last_state
            raise UpdateFailed(str(err)) from err

    async def async_send_command(self, coro, *, skip_refresh: bool = False) -> None:
        """Run a client command coroutine, then refresh state."""
        try:
            await coro
        except Dell7609AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        if skip_refresh and self.client.last_state is not None:
            state = self.client.apply_power_hold_overlay(self.client.last_state)
            self.client.last_state = state
            self.async_set_updated_data(state)
            return
        await self.async_request_refresh()
