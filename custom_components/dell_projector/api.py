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
import time
from dataclasses import dataclass, replace
from dataclasses import field as dc_field
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlencode

import aiohttp

_LOGGER = logging.getLogger(__name__)


_LOGIN_FORM_MARKER = "/tgi/login.tgi"
_FRAMESET_MARKER = "<frameset"

# The firmware web server is single-threaded; allow headroom but fail before
# blocking the coordinator (and user commands) for minutes.
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
_OPTIONAL_STATUS_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)

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

# After power on/off the firmware may still report the previous PJSTATE2 for minutes.
_POWER_HOLD_SECONDS = 120

# Standby /status.htm uses a smaller form than lamp-on (browser-captured).
_STANDBY_FORM_ORDER: tuple[str, ...] = (
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
    "Contrast",
    "Volume",
    "btnVol",
)
_STANDBY_ALWAYS: frozenset[str] = frozenset(
    {
        "PJSTATE",
        "DSP_SOURCE",
        "ERRORSTA",
        "FREEZE0",
        "HIDE0",
        "PJSTATE2",
        "PwSave",
        "LAMPHR",
        "ERRORSTA2",
        "PrjMode",
        "PrjSRC",
        "VideoMode",
        "Bright",
        "Contrast",
        "Volume",
    }
)
_STANDBY_DEFAULTS: dict[str, str] = {
    "PJSTATE": "0",
    "DSP_SOURCE": "0",
    "ERRORSTA": "Standby ",
    "FREEZE0": "",
    "HIDE0": "0",
    "PJSTATE2": "Standby ",
    "PwSave": "99",
    "LAMPHR": "0 hr.",
    "ERRORSTA2": "",
    "PrjMode": "99",
    "PrjSRC": "0",
    "VideoMode": "99",
    "Bright": "0",
    "Contrast": "0",
    "Volume": "0",
}


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
        status = (self.power_status or "").strip().lower()
        if not status:
            return False
        # Explicit strings — avoid `"on" in status` which falsely matches "Cooling".
        if status.startswith("standby") or "cooling" in status:
            return False
        if "power saving" in status:
            return False
        if "warm" in status or "lamp on" in status:
            return True
        code = self._raw_int("PJSTATE")
        return code == 1 if code is not None else False

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
        self._state_lock = asyncio.Lock()
        self._http_lock = asyncio.Lock()
        self.last_state: ProjectorState | None = None
        self._power_hold_is_on: bool | None = None
        self._power_hold_until: float = 0.0
        # Accumulated standby form values (mirrors browser session state).
        self._standby_form: dict[str, str] = {}

    @property
    def host(self) -> str:
        return self._host

    def set_power_hold(self, is_on: bool) -> None:
        """Keep switch state stable while the lamp warms up or cools down."""
        self._power_hold_is_on = is_on
        self._power_hold_until = time.monotonic() + _POWER_HOLD_SECONDS

    def apply_power_hold_overlay(self, state: ProjectorState) -> ProjectorState:
        """Mask stale PJSTATE2 reads during a power transition."""
        if self._power_hold_is_on is None or time.monotonic() >= self._power_hold_until:
            self._power_hold_is_on = None
            return state
        pj = (state.power_status or "").strip().lower()
        if self._power_hold_is_on and "lamp on" in pj:
            self._power_hold_is_on = None
            return state
        if not self._power_hold_is_on and pj.startswith("standby"):
            self._power_hold_is_on = None
            return state
        raw = dict(state.raw_form)
        if self._power_hold_is_on:
            raw["PJSTATE2"] = "Warm up "
            raw["PJSTATE"] = "1"
        else:
            raw["PJSTATE2"] = "Cooling "
            raw["PJSTATE"] = "0"
        return replace(state, raw_form=raw)

    def _url(self, path: str) -> str:
        return f"http://{self._host}{path}"

    # ---- low level HTTP ------------------------------------------------------

    async def _raw_request(
        self,
        method: str,
        path: str,
        data: dict[str, str] | None = None,
        *,
        timeout: aiohttp.ClientTimeout | None = None,
        max_attempts: int = 2,
    ) -> tuple[str, aiohttp.ClientResponse]:
        headers: dict[str, str] = {}
        if self._cookie:
            headers["Cookie"] = self._cookie
        body: str | None = None
        if data is not None:
            body = urlencode(data)  # quote_plus: spaces become '+', like a browser
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        effective_timeout = timeout or _REQUEST_TIMEOUT
        last_timeout: TimeoutError | None = None
        referer = {
            "/tgi/status.tgi": "/status.htm",
            "/tgi/password.tgi": "/password.htm",
        }.get(path)
        for attempt in range(max_attempts):
            try:
                async with self._http_lock:
                    if referer:
                        headers["Referer"] = self._url(referer)
                    async with self._session.request(
                        method,
                        self._url(path),
                        data=body,
                        headers=headers,
                        timeout=effective_timeout,
                    ) as resp:
                        text = await resp.text(errors="replace")
                        self._store_cookie(resp)
                        return text, resp
            except TimeoutError as err:
                last_timeout = err
                if attempt + 1 < max_attempts:
                    continue
            except aiohttp.ClientError as err:
                raise Dell7609ConnectionError(
                    f"Error talking to projector at {self._host}: {err}"
                ) from err
        assert last_timeout is not None
        raise Dell7609ConnectionError(
            f"Timeout talking to projector at {self._host}"
        ) from last_timeout

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

    async def _try_status_page(self) -> str | None:
        """Best-effort /status.htm for startup; never blocks for a full retry cycle."""
        if self._cookie is None:
            await self._bootstrap_session()
        try:
            text, _ = await self._raw_request(
                "GET",
                "/status.htm",
                timeout=_OPTIONAL_STATUS_TIMEOUT,
                max_attempts=1,
            )
        except Dell7609ConnectionError:
            return None
        if self._is_login_page(text) or self._is_frameset(text):
            return None
        return text

    def _state_from_home(
        self, home: str, status: str | None, *, preserve_form: bool
    ) -> ProjectorState:
        """Build state from /home.htm, optionally merging /status.htm."""
        if status:
            return self._parse_state(home, status)
        state = self._parse_state(home, "")
        if preserve_form and self.last_state:
            raw = dict(self.last_state.raw_form)
            # /home.htm status_text is authoritative when /status.htm is missing.
            raw.pop("PJSTATE2", None)
            raw.pop("PJSTATE", None)
            return replace(state, raw_form=raw)
        return state

    async def _fetch_status_page(self, *, single_attempt: bool = False) -> str | None:
        """Fetch /status.htm; return None instead of raising when the server is busy."""
        if self._cookie is None:
            await self._bootstrap_session()
        timeout = _OPTIONAL_STATUS_TIMEOUT if single_attempt else _REQUEST_TIMEOUT
        max_attempts = 1 if single_attempt else 2
        try:
            text, _ = await self._raw_request(
                "GET",
                "/status.htm",
                timeout=timeout,
                max_attempts=max_attempts,
            )
        except Dell7609ConnectionError:
            return None
        if self._is_login_page(text) or self._is_frameset(text):
            await self._bootstrap_session()
            try:
                text, _ = await self._raw_request(
                    "GET",
                    "/status.htm",
                    timeout=_OPTIONAL_STATUS_TIMEOUT,
                    max_attempts=1,
                )
            except Dell7609ConnectionError:
                return None
            if self._is_login_page(text) or self._is_frameset(text):
                return None
        return text

    async def async_get_state(self, *, refresh_home: bool = True) -> ProjectorState:
        """Fetch projector state.

        Routine polls should pass ``refresh_home=False`` to hit only /status.htm;
        the firmware's single-threaded web server cannot sustain two page fetches
        every 30 seconds without frequent 30-90s timeouts.
        """
        status_partial = False
        async with self._state_lock:
            need_home = refresh_home or self.last_state is None
            base = self.last_state

        if need_home:
            home = await self._request_page("GET", "/home.htm")
            status = await self._try_status_page()
            status_partial = status is None
            async with self._state_lock:
                state = self._state_from_home(
                    home, status, preserve_form=status is None
                )
                if not status_partial:
                    state = self.apply_power_hold_overlay(state)
                self.last_state = state
        else:
            status = await self._fetch_status_page(single_attempt=True)
            async with self._state_lock:
                if status is None:
                    if base is not None:
                        status_partial = True
                        state = self.apply_power_hold_overlay(base)
                    else:
                        raise Dell7609ConnectionError(
                            f"Timeout talking to projector at {self._host}"
                        )
                else:
                    state = self.apply_power_hold_overlay(
                        self._apply_status(base, status)
                    )
                self.last_state = state
        return state

    @staticmethod
    def _lamp_hours_from_text(text: str | None) -> int | None:
        if not text:
            return None
        digits = re.search(r"\d+", text)
        return int(digits.group(0)) if digits else None

    def _parse_status_form(self, status: str) -> dict[str, str]:
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
        return raw

    def _apply_status(self, base: ProjectorState, status: str) -> ProjectorState:
        raw = self._parse_status_form(status)
        lamp_hours = self._lamp_hours_from_text(raw.get("LAMPHR")) or base.lamp_hours
        return replace(base, raw_form=raw, lamp_hours=lamp_hours)

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
        state.lamp_hours = self._lamp_hours_from_text(_home_value(home, "Lamp Hours"))
        admin = _home_value(home, "Admin Password")
        if admin is not None:
            state.password_enabled = not admin.lower().startswith("not")

        state.raw_form = self._parse_status_form(status)
        if state.lamp_hours is None:
            state.lamp_hours = self._lamp_hours_from_text(state.raw_form.get("LAMPHR"))
        return state

    # ---- commands ---------------------------------------------------------------

    @staticmethod
    def _is_standby_state(state: ProjectorState | None) -> bool:
        if state is None:
            return True
        pj = (state.power_status or state.status_text or "").strip().lower()
        if pj.startswith("standby"):
            return True
        code = state._raw_int("PJSTATE")
        return code == 0 if code is not None else not state.raw_form

    def _standby_form_values(self) -> dict[str, str]:
        """Merged standby defaults, cached session fields, and polled state."""
        values = dict(_STANDBY_DEFAULTS)
        if self.last_state:
            lamphr = self.last_state.raw_form.get("LAMPHR")
            if not lamphr and self.last_state.lamp_hours is not None:
                lamphr = f"{self.last_state.lamp_hours} hr."
            if lamphr:
                values["LAMPHR"] = lamphr
            for key in _STANDBY_ALWAYS | {"ecoMode", "hide", "Aspect"}:
                if key in self.last_state.raw_form:
                    values[key] = self.last_state.raw_form[key]
        values.update(self._standby_form)
        return values

    def _persist_standby_fields(
        self, overrides: dict[str, str] | None, parsed: dict[str, str]
    ) -> None:
        """Keep standby session fields aligned with the browser form."""
        for key, value in (overrides or {}).items():
            if key not in BUTTON_VALUES:
                self._standby_form[key] = value
        for key in (
            "ecoMode",
            "hide",
            "Aspect",
            "Bright",
            "Contrast",
            "Volume",
            "PwSave",
            "PrjMode",
            "PrjSRC",
            "VideoMode",
        ):
            if key in parsed:
                self._standby_form[key] = parsed[key]

    def _build_standby_payload(
        self, button: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Minimal standby POST matching browser field order and inclusion rules."""
        if button not in BUTTON_VALUES:
            raise ValueError(f"Unknown submit button: {button}")
        values = self._standby_form_values()
        if overrides:
            values.update(overrides)
        optional = set(self._standby_form) | set(overrides or {})
        payload: dict[str, str] = {}
        for name in _STANDBY_FORM_ORDER:
            if name in ("PowerOn", "PowerOff"):
                if name == button:
                    payload[name] = BUTTON_VALUES[name]
                continue
            if name in BUTTON_VALUES:
                if name == button:
                    payload[name] = BUTTON_VALUES[name]
                continue
            if name in _STANDBY_ALWAYS or name in optional:
                payload[name] = values.get(name, _STANDBY_DEFAULTS.get(name, ""))
        return payload

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

    def _apply_command_response(
        self,
        response: str,
        *,
        optimistic_pjstate2: str | None = None,
    ) -> None:
        """Update cached state from a command POST body or transitional guess."""
        if self.last_state is None:
            return
        parsed = self._parse_status_form(response)
        if parsed.get("PJSTATE2"):
            self.last_state = self._apply_status(self.last_state, response)
            if not self._is_standby_state(self.last_state):
                self._standby_form.clear()
            else:
                self._persist_standby_fields(None, parsed)
        elif optimistic_pjstate2:
            raw = dict(self.last_state.raw_form)
            raw["PJSTATE2"] = optimistic_pjstate2
            transitional = optimistic_pjstate2.strip().lower()
            if transitional.startswith(("lamp", "warm")):
                raw["PJSTATE"] = "1"
                self._standby_form.clear()
            elif transitional.startswith(("standby", "cooling")):
                raw["PJSTATE"] = "0"
            self.last_state = replace(self.last_state, raw_form=raw)

    async def _async_command(
        self,
        button: str,
        overrides: dict[str, str] | None = None,
        *,
        optimistic_pjstate2: str | None = None,
    ) -> None:
        payload_mode = "full"
        use_standby = False
        async with self._state_lock:
            use_standby = self._is_standby_state(self.last_state)
            needs_prefetch = not use_standby and (
                self.last_state is None or not self.last_state.raw_form
            )
            if use_standby:
                payload = self._build_standby_payload(button, overrides)
                payload_mode = "standby"
            elif not needs_prefetch:
                payload = self._build_payload(button, overrides)

        if not use_standby and needs_prefetch:
            status = await self._fetch_status_page(single_attempt=False)
            if status is None:
                status = await self._request_page("GET", "/status.htm")
            async with self._state_lock:
                if self.last_state is None:
                    home = await self._request_page("GET", "/home.htm")
                    self.last_state = self._parse_state(home, status)
                else:
                    self.last_state = self._apply_status(self.last_state, status)
                use_standby = self._is_standby_state(self.last_state)
                if use_standby:
                    payload = self._build_standby_payload(button, overrides)
                    payload_mode = "standby"
                else:
                    payload = self._build_payload(button, overrides)

        _LOGGER.debug(
            "Sending %s to %s (%s): %s", button, self._host, payload_mode, payload
        )
        response = await self._request_page("POST", "/tgi/status.tgi", payload)
        async with self._state_lock:
            if use_standby:
                self._persist_standby_fields(
                    overrides, self._parse_status_form(response)
                )
            self._apply_command_response(
                response, optimistic_pjstate2=optimistic_pjstate2
            )

    async def async_power_on(self) -> None:
        await self._async_command("PowerOn", optimistic_pjstate2="Warm up ")
        self.set_power_hold(True)

    async def async_power_off(self) -> None:
        await self._async_command("PowerOff", optimistic_pjstate2="Cooling ")
        self.set_power_hold(False)

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

    # ---- admin password (password.htm / password.tgi) -------------------------

    async def async_set_admin_password(
        self, password: str, *, snmp_write_community: str = "private"
    ) -> None:
        """Enable the web admin password and set SNMP write community.

        Not exposed as a Home Assistant entity (security-sensitive). For tooling
        and protocol reference see docs/PROTOCOL.md.
        """
        payload = {
            "stateadm": "1",
            "new_admin": password,
            "verify_admin": password,
            "Submit_admin": "Submit",
            "snmp_pwdtable": snmp_write_community,
        }
        await self._request_page("POST", "/tgi/password.tgi", payload)
        self._password = password or None

    async def async_disable_admin_password(self) -> None:
        """Turn off the web admin password requirement."""
        payload = {"stateadm": "0", "btn_secuadm": "Submit"}
        await self._request_page("POST", "/tgi/password.tgi", payload)
        self._password = None

    # ---- validation -------------------------------------------------------------

    async def async_validate(self) -> ProjectorState:
        """Validate connectivity, device type and credentials.

        Raises Dell7609UnsupportedError, Dell7609AuthError or
        Dell7609ConnectionError accordingly. Returns the current state.
        """
        try:
            landing = await self._bootstrap_session()
            if self._is_login_page(landing):
                await self._async_login()
            home = await self._request_page("GET", "/home.htm")
            status = await self._try_status_page()
            async with self._state_lock:
                state = self._state_from_home(
                    home, status, preserve_form=status is None
                )
                self.last_state = state
        except Dell7609Error:
            raise
        return state


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
