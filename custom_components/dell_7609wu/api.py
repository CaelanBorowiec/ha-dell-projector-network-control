"""Async client for the Dell 7609WU projector web management interface.

The projector (2008-era firmware) exposes no JSON API. Everything goes through
its tiny HTTP/1.0 web server:

- ``GET /`` sets the ``ATOP`` session cookie (required by every other request).
- ``GET /home.htm`` and ``GET /status.htm`` carry the full device state inside
  fixed-format HTML forms.
- ``POST /tgi/status.tgi`` executes commands. The firmware expects the *entire*
  form state plus the clicked submit button, exactly as a browser would send it.
- When an admin password is enabled, ``POST /tgi/login.tgi`` authenticates the
  session cookie via an MD5 challenge-response:
  ``Response = md5("admin" + password + challenge)``.

See docs/PROTOCOL.md in the repository for the full reverse-engineered
reference. This module deliberately avoids Home Assistant imports so it can be
exercised standalone against a live projector.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlencode

import aiohttp

_LOGGER = logging.getLogger(__name__)

_LOGIN_FORM_MARKER = "/tgi/login.tgi"
_FRAMESET_MARKER = "<frameset"

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Submit buttons of the /status.htm form with their exact firmware values.
# Trailing spaces are significant: the firmware string-matches these.
BUTTON_VALUES: dict[str, str] = {
    "PowerOn": "Power ON ",
    "PowerOff": "Power OFF ",
    "btnPwSave": "Submit ",
    "btnECOMode": "Submit ",
    "btnPrjMode": "Submit ",
    "btnSource": "Submit ",
    "btnVideo": "Submit ",
    "btnHide": "Submit ",
    "btnAspect": "Submit ",
    "btnBright": "Submit ",
    "btnContrast": "Submit ",
    "btnAutoAdj": "Auto Adjust ",
    "btnReset": "Factory Reset ",
    "btnVol": "Submit",
}

# DOM order of the /status.htm form. Browsers serialize forms in this order and
# insert the clicked submit button at its own position; we mirror that exactly.
_FORM_ORDER: tuple[str, ...] = (
    "PJSTATE",
    "DSP_SOURCE",
    "ERRORSTA",
    "FREEZE0",
    "HIDE0",
    "PJSTATE2",
    "PowerOn",
    "PowerOff",
    "PwSave",
    "btnPwSave",
    "LAMPHR",
    "ERRORSTA2",
    "ecoMode",
    "btnECOMode",
    "PrjMode",
    "btnPrjMode",
    "PrjSRC",
    "btnSource",
    "VideoMode",
    "btnVideo",
    "hide",
    "btnHide",
    "Aspect",
    "btnAspect",
    "Bright",
    "btnBright",
    "Contrast",
    "btnContrast",
    "btnAutoAdj",
    "btnReset",
    "Volume",
    "btnVol",
)

# Non-button fields a browser always submits from /status.htm.
_STATE_FIELDS: tuple[str, ...] = tuple(
    name for name in _FORM_ORDER if name not in BUTTON_VALUES
)

ECO_MODE_ON = 27
ECO_MODE_OFF = 28
HIDE_ON = 85
HIDE_OFF = 170


class Dell7609Error(Exception):
    """Base error for the Dell 7609WU client."""


class Dell7609ConnectionError(Dell7609Error):
    """Could not reach the projector or got an unusable response."""


class Dell7609AuthError(Dell7609Error):
    """Login required or rejected."""


class Dell7609UnsupportedError(Dell7609Error):
    """The host is reachable but is not a Dell 7609WU web management UI."""


@dataclass
class ProjectorState:
    """Parsed snapshot of the projector's state."""

    # From /home.htm
    group_name: str | None = None
    projector_name: str | None = None
    location: str | None = None
    contact: str | None = None
    status_text: str | None = None
    lamp_hours: int | None = None
    firmware_version: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    password_enabled: bool | None = None

    # Raw /status.htm form values, used verbatim to rebuild command payloads.
    raw_form: dict[str, str] = dc_field(default_factory=dict)

    # ---- Typed views over raw_form -----------------------------------------

    def _raw_int(self, key: str) -> int | None:
        value = self.raw_form.get(key, "")
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None

    @property
    def power_status(self) -> str | None:
        """Human readable power status, e.g. 'Lamp ON', 'Standby'."""
        value = self.raw_form.get("PJSTATE2") or self.status_text
        return value.strip() if value else None

    @property
    def is_on(self) -> bool:
        """True when the lamp is on or warming up."""
        status = (self.power_status or "").lower()
        return "on" in status or "warm" in status

    @property
    def source_code(self) -> int | None:
        """Current input source code (113-120), None if no active source."""
        code = self._raw_int("DSP_SOURCE")
        return code if code is not None and 113 <= code <= 120 else None

    @property
    def error_status(self) -> str | None:
        value = self.raw_form.get("ERRORSTA2", "").strip()
        return value or None

    @property
    def eco_mode(self) -> bool | None:
        code = self._raw_int("ecoMode")
        return code == ECO_MODE_ON if code is not None else None

    @property
    def blank_screen(self) -> bool | None:
        code = self._raw_int("hide")
        if code is None:
            code = self._raw_int("HIDE0")
        return code == HIDE_ON if code is not None else None

    @property
    def projection_mode(self) -> int | None:
        return self._raw_int("PrjMode")

    @property
    def video_mode(self) -> int | None:
        return self._raw_int("VideoMode")

    @property
    def power_saving(self) -> int | None:
        return self._raw_int("PwSave")

    @property
    def aspect(self) -> int | None:
        return self._raw_int("Aspect")

    @property
    def brightness(self) -> int | None:
        return self._raw_int("Bright")

    @property
    def contrast(self) -> int | None:
        return self._raw_int("Contrast")

    @property
    def volume(self) -> int | None:
        return self._raw_int("Volume")


# ---------------------------------------------------------------------------
# HTML parsing helpers (the pages are tiny, machine-generated, fixed format)
# ---------------------------------------------------------------------------


def _input_value(html: str, name: str) -> str | None:
    """Return the VALUE of the <input> with the given NAME (any attr order)."""
    for tag in re.findall(r"<input\b[^>]*>", html, re.IGNORECASE):
        if re.search(rf'NAME\s*=\s*["\']{re.escape(name)}["\']', tag, re.IGNORECASE):
            match = re.search(r'VALUE\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
            return match.group(1) if match else ""
    return None


def _checked_radio_value(html: str, name: str) -> str | None:
    """Return the VALUE of the CHECKED radio in the given group."""
    fallback: str | None = None
    for tag in re.findall(r"<input\b[^>]*>", html, re.IGNORECASE):
        if not re.search(
            rf'NAME\s*=\s*["\']{re.escape(name)}["\']', tag, re.IGNORECASE
        ):
            continue
        match = re.search(r'VALUE\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
        if not match:
            continue
        if fallback is None:
            fallback = match.group(1)
        if re.search(r"\bCHECKED\b", tag, re.IGNORECASE):
            return match.group(1)
    return fallback


def _selected_option_value(html: str, name: str) -> str | None:
    """Return the SELECTED option VALUE of the named <select> (or the first)."""
    select_match = re.search(
        rf'<select\b[^>]*NAME\s*=\s*["\']{re.escape(name)}["\'].*?</select>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not select_match:
        return None
    block = select_match.group(0)
    options = re.findall(
        r'<option\b[^>]*VALUE\s*=\s*"([^"]*)"([^>]*)>', block, re.IGNORECASE
    )
    if not options:
        return None
    for value, attrs in options:
        if re.search(r"\bSELECTED\b", attrs, re.IGNORECASE):
            return value
    return options[0][0]


_HOME_FIELD_RE = r"{label}:</strong></font></td>.*?sans-serif\">\s*(.*?)\s*</font>"


def _home_value(html: str, label: str) -> str | None:
    match = re.search(
        _HOME_FIELD_RE.format(label=re.escape(label)),
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    # Collapse whitespace/newlines inside the cell.
    return re.sub(r"\s+", " ", match.group(1)).strip()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Dell7609Client:
    """Client for one projector, identified by host (IP), optional password."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        password: str | None = None,
    ) -> None:
        self._host = host
        self._session = session
        self._password = password or None
        self._cookie: str | None = None
        self._lock = asyncio.Lock()
        self.last_state: ProjectorState | None = None

    @property
    def host(self) -> str:
        return self._host

    def _url(self, path: str) -> str:
        return f"http://{self._host}{path}"

    # ---- low level HTTP ------------------------------------------------------

    async def _raw_request(
        self, method: str, path: str, data: dict[str, str] | None = None
    ) -> tuple[str, aiohttp.ClientResponse]:
        headers: dict[str, str] = {}
        if self._cookie:
            headers["Cookie"] = self._cookie
        body: str | None = None
        if data is not None:
            body = urlencode(data)  # quote_plus: spaces become '+', like a browser
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with self._session.request(
                method,
                self._url(path),
                data=body,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                text = await resp.text(errors="replace")
                self._store_cookie(resp)
                return text, resp
        except TimeoutError as err:
            raise Dell7609ConnectionError(
                f"Timeout talking to projector at {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise Dell7609ConnectionError(
                f"Error talking to projector at {self._host}: {err}"
            ) from err

    def _store_cookie(self, resp: aiohttp.ClientResponse) -> None:
        # aiohttp's cookie jar refuses bare-IP hosts, so track ATOP manually.
        for header in resp.headers.getall("Set-Cookie", []):
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(header)
            if "ATOP" in cookie:
                self._cookie = f"ATOP={cookie['ATOP'].value}"

    async def _bootstrap_session(self) -> str:
        """Fetch / to obtain the ATOP session cookie; returns the page."""
        self._cookie = None
        text, _ = await self._raw_request("GET", "/")
        if "Web Management" not in text:
            raise Dell7609UnsupportedError(
                f"Host {self._host} does not look like a supported Dell "
                "web management interface"
            )
        return text

    @staticmethod
    def _is_login_page(text: str) -> bool:
        return _LOGIN_FORM_MARKER in text

    @staticmethod
    def _is_frameset(text: str) -> bool:
        return _FRAMESET_MARKER in text.lower()

    async def _async_login(self) -> None:
        """Authenticate the session cookie via MD5 challenge-response."""
        if not self._password:
            raise Dell7609AuthError(
                f"Projector at {self._host} requires an admin password"
            )
        text, _ = await self._raw_request("GET", "/login.htm")
        match = re.search(
            r'NAME\s*=\s*"Challenge"\s+VALUE\s*=\s*"([^"]*)"', text, re.DOTALL
        )
        if not match:
            # Some firmware revisions wrap the attribute across lines.
            match = re.search(
                r'"Challenge"[^>]*VALUE\s*=\s*\n?"([^"]*)"', text, re.DOTALL
            )
        if not match:
            raise Dell7609ConnectionError(
                f"Could not find login challenge on projector at {self._host}"
            )
        challenge = match.group(1)
        response = hashlib.md5(f"admin{self._password}{challenge}".encode()).hexdigest()
        payload = {
            "user": "0",
            "Username": "1",
            "Password": "",
            "Challenge": "",
            "Response": response,
            "Submitbtn": "Login",
        }
        text, _ = await self._raw_request("POST", "/tgi/login.tgi", payload)
        if self._is_login_page(text):
            raise Dell7609AuthError(
                f"Projector at {self._host} rejected the admin password"
            )

    async def _request_page(
        self, method: str, path: str, data: dict[str, str] | None = None
    ) -> str:
        """Request a page, transparently (re)establishing session and login."""
        if self._cookie is None:
            await self._bootstrap_session()
        text, _ = await self._raw_request(method, path, data)
        needs_retry = self._is_login_page(text) or (
            path != "/" and self._is_frameset(text)
        )
        if not needs_retry:
            return text
        # Session cookie expired or login required: rebuild and retry once.
        landing = await self._bootstrap_session()
        if self._is_login_page(landing):
            await self._async_login()
        text, _ = await self._raw_request(method, path, data)
        if self._is_login_page(text):
            raise Dell7609AuthError(
                f"Projector at {self._host} requires a valid admin password"
            )
        if path != "/" and self._is_frameset(text):
            raise Dell7609ConnectionError(
                f"Projector at {self._host} keeps returning the frameset; "
                "session could not be established"
            )
        return text

    # ---- state ----------------------------------------------------------------

    async def async_get_state(self) -> ProjectorState:
        """Fetch and parse home.htm + status.htm into a ProjectorState."""
        async with self._lock:
            home = await self._request_page("GET", "/home.htm")
            status = await self._request_page("GET", "/status.htm")
            state = self._parse_state(home, status)
            self.last_state = state
            return state

    def _parse_state(self, home: str, status: str) -> ProjectorState:
        state = ProjectorState()

        # /home.htm
        state.group_name = _home_value(home, "Group Name")
        state.projector_name = _home_value(home, "Projector Name")
        state.location = _home_value(home, "Location")
        state.contact = _home_value(home, "Contact")
        state.status_text = _home_value(home, "Status")
        state.firmware_version = _home_value(home, "Firmware Version")
        state.ip_address = _home_value(home, "IP Address")
        state.mac_address = _home_value(home, "MAC Address")
        lamp = _home_value(home, "Lamp Hours")
        if lamp:
            digits = re.search(r"\d+", lamp)
            state.lamp_hours = int(digits.group(0)) if digits else None
        admin = _home_value(home, "Admin Password")
        if admin is not None:
            state.password_enabled = not admin.lower().startswith("not")

        # /status.htm form state
        raw: dict[str, str] = {}
        for name in (
            "PJSTATE",
            "DSP_SOURCE",
            "ERRORSTA",
            "FREEZE0",
            "HIDE0",
            "PJSTATE2",
            "LAMPHR",
            "ERRORSTA2",
            "Bright",
            "Contrast",
            "Volume",
        ):
            value = _input_value(status, name)
            if value is not None:
                raw[name] = value
        for name in ("ecoMode", "hide", "Aspect"):
            value = _checked_radio_value(status, name)
            if value is not None:
                raw[name] = value
        for name in ("PwSave", "PrjMode", "VideoMode", "PrjSRC"):
            value = _selected_option_value(status, name)
            if value is not None:
                raw[name] = value
        state.raw_form = raw
        return state

    # ---- commands ---------------------------------------------------------------

    def _build_payload(
        self, button: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Rebuild the full form payload the way a browser would submit it."""
        if button not in BUTTON_VALUES:
            raise ValueError(f"Unknown submit button: {button}")
        base = dict(self.last_state.raw_form if self.last_state else {})
        if overrides:
            base.update(overrides)
        payload: dict[str, str] = {}
        for name in _FORM_ORDER:
            if name == button:
                payload[name] = BUTTON_VALUES[name]
            elif name in _STATE_FIELDS:
                payload[name] = base.get(name, "")
        return payload

    async def _async_command(
        self, button: str, overrides: dict[str, str] | None = None
    ) -> None:
        async with self._lock:
            if self.last_state is None or not self.last_state.raw_form:
                # Need current form state to rebuild the payload faithfully.
                home = await self._request_page("GET", "/home.htm")
                status = await self._request_page("GET", "/status.htm")
                self.last_state = self._parse_state(home, status)
            payload = self._build_payload(button, overrides)
            _LOGGER.debug("Sending %s to %s: %s", button, self._host, payload)
            await self._request_page("POST", "/tgi/status.tgi", payload)

    async def async_power_on(self) -> None:
        await self._async_command("PowerOn")

    async def async_power_off(self) -> None:
        await self._async_command("PowerOff")

    async def async_set_power_saving(self, minutes: int) -> None:
        await self._async_command("btnPwSave", {"PwSave": str(minutes)})

    async def async_set_eco_mode(self, enabled: bool) -> None:
        code = ECO_MODE_ON if enabled else ECO_MODE_OFF
        await self._async_command("btnECOMode", {"ecoMode": str(code)})

    async def async_set_projection_mode(self, code: int) -> None:
        await self._async_command("btnPrjMode", {"PrjMode": str(code)})

    async def async_set_source(self, code: int) -> None:
        await self._async_command("btnSource", {"PrjSRC": str(code)})

    async def async_set_video_mode(self, code: int) -> None:
        await self._async_command("btnVideo", {"VideoMode": str(code)})

    async def async_set_blank_screen(self, enabled: bool) -> None:
        code = HIDE_ON if enabled else HIDE_OFF
        await self._async_command("btnHide", {"hide": str(code)})

    async def async_set_aspect(self, code: int) -> None:
        await self._async_command("btnAspect", {"Aspect": str(code)})

    async def async_set_brightness(self, value: int) -> None:
        await self._async_command("btnBright", {"Bright": str(value)})

    async def async_set_contrast(self, value: int) -> None:
        await self._async_command("btnContrast", {"Contrast": str(value)})

    async def async_set_volume(self, value: int) -> None:
        await self._async_command("btnVol", {"Volume": str(value)})

    async def async_auto_adjust(self) -> None:
        await self._async_command("btnAutoAdj")

    # ---- validation -------------------------------------------------------------

    async def async_validate(self) -> ProjectorState:
        """Validate connectivity, device type and credentials.

        Raises Dell7609UnsupportedError, Dell7609AuthError or
        Dell7609ConnectionError accordingly. Returns the current state.
        """
        landing = await self._bootstrap_session()
        if self._is_login_page(landing):
            await self._async_login()
        return await self.async_get_state()


def state_as_dict(state: ProjectorState) -> dict[str, Any]:
    """Serializable snapshot, used by diagnostics and the smoke test."""
    return {
        "group_name": state.group_name,
        "projector_name": state.projector_name,
        "location": state.location,
        "contact": state.contact,
        "status_text": state.status_text,
        "power_status": state.power_status,
        "is_on": state.is_on,
        "lamp_hours": state.lamp_hours,
        "firmware_version": state.firmware_version,
        "ip_address": state.ip_address,
        "mac_address": state.mac_address,
        "password_enabled": state.password_enabled,
        "source_code": state.source_code,
        "error_status": state.error_status,
        "eco_mode": state.eco_mode,
        "blank_screen": state.blank_screen,
        "projection_mode": state.projection_mode,
        "video_mode": state.video_mode,
        "power_saving": state.power_saving,
        "aspect": state.aspect,
        "brightness": state.brightness,
        "contrast": state.contrast,
        "volume": state.volume,
        "raw_form": dict(state.raw_form),
    }
