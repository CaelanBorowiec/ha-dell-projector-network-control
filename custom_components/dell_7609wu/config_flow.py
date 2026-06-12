"""Config flow for the Dell Projector Network Interface integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import (
    Dell7609AuthError,
    Dell7609Client,
    Dell7609Error,
    Dell7609UnsupportedError,
    ProjectorState,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PASSWORD): str,
    }
)
PASSWORD_SCHEMA = vol.Schema({vol.Optional(CONF_PASSWORD): str})


class Dell7609ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dell Projector Network Interface."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None

    async def _async_validate(self, host: str, password: str | None) -> ProjectorState:
        client = Dell7609Client(
            host, async_create_clientsession(self.hass), password=password
        )
        return await client.async_validate()

    @staticmethod
    def _title(state: ProjectorState) -> str:
        if state.projector_name:
            return state.projector_name
        if state.group_name:
            return f"Dell {state.group_name}"
        return "Dell Projector Network Interface"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: ask for host (+ optional admin password)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            password = user_input.get(CONF_PASSWORD) or None
            try:
                state = await self._async_validate(host, password)
            except Dell7609AuthError as err:
                _LOGGER.warning("Auth failed for %s: %s", host, err)
                errors["base"] = "invalid_auth"
            except Dell7609UnsupportedError as err:
                _LOGGER.warning("Unsupported device at %s: %s", host, err)
                errors["base"] = "not_supported"
            except Dell7609Error as err:
                _LOGGER.error(
                    "Connection failed for %s (%s): %s",
                    host,
                    type(err).__name__,
                    err,
                )
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating %s", host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    format_mac(state.mac_address or host),
                    raise_on_progress=False,
                )
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=self._title(state),
                    data={CONF_HOST: host, CONF_PASSWORD: password},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """DHCP discovery: probe the host, abort quietly if not a Dell projector."""
        host = discovery_info.ip
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        try:
            state = await self._async_validate(host, None)
        except Dell7609AuthError:
            # Projector needs a password; continue and ask for it.
            self._discovered_host = host
            return await self.async_step_discovery_confirm()
        except Dell7609Error:
            # Most Dell OUI matches are not projectors; bail out silently.
            return self.async_abort(reason="not_supported")
        self._discovered_host = host
        self.context["title_placeholders"] = {"name": self._title(state)}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered projector and collect a password if needed."""
        assert self._discovered_host is not None
        host = self._discovered_host
        errors: dict[str, str] = {}
        if user_input is not None:
            password = user_input.get(CONF_PASSWORD) or None
            try:
                state = await self._async_validate(host, password)
            except Dell7609AuthError:
                errors["base"] = "invalid_auth"
            except Dell7609Error:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=self._title(state),
                    data={CONF_HOST: host, CONF_PASSWORD: password},
                )
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=PASSWORD_SCHEMA,
            description_placeholders={"host": host},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The stored password stopped working; ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            password = user_input.get(CONF_PASSWORD) or None
            try:
                await self._async_validate(entry.data[CONF_HOST], password)
            except Dell7609AuthError:
                errors["base"] = "invalid_auth"
            except Dell7609Error:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PASSWORD_SCHEMA,
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing host and/or password without re-adding."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            password = user_input.get(CONF_PASSWORD) or None
            try:
                state = await self._async_validate(host, password)
            except Dell7609AuthError:
                errors["base"] = "invalid_auth"
            except Dell7609UnsupportedError:
                errors["base"] = "not_supported"
            except Dell7609Error:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(format_mac(state.mac_address or host))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_HOST: host, CONF_PASSWORD: password},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
        )
