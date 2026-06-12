"""Constants for the Dell Projector Network Interface integration."""

from __future__ import annotations

DOMAIN = "dell_projector"

MANUFACTURER = "Dell"
DEFAULT_MODEL = "Projector"

# The projector web server is single-threaded; polling too aggressively causes
# multi-second (or minute-long) timeouts that make the UI feel laggy.
DEFAULT_SCAN_INTERVAL_SECONDS = 60

# Re-fetch /home.htm (static identity fields) every N coordinator polls.
HOME_REFRESH_EVERY_N_POLLS = 15

CONF_NOTE_USERNAME = "administrator"  # firmware-fixed, informational only

# --- Source codes (PrjSRC command values / DSP_SOURCE status values) ---------
SOURCE_CODES: dict[int, str] = {
    113: "VGA-A",
    114: "VGA-B",
    115: "S-Video",
    116: "Composite Video",
    117: "Component",
    118: "DisplayPort",
    119: "HDMI-A",
    120: "HDMI-B",
}
SOURCE_NAMES_TO_CODES: dict[str, int] = {v: k for k, v in SOURCE_CODES.items()}

# --- Video modes (VideoMode) --------------------------------------------------
VIDEO_MODE_CODES: dict[int, str] = {
    0: "Presentation",
    1: "Bright",
    2: "Movie",
    3: "sRGB",
    4: "Custom",
}
VIDEO_MODE_NAMES_TO_CODES: dict[str, int] = {v: k for k, v in VIDEO_MODE_CODES.items()}

# --- Projection modes (PrjMode) ----------------------------------------------
PROJECTION_MODE_CODES: dict[int, str] = {
    0: "Front Projection - Desktop",
    1: "Front Projection - Ceiling Mount",
    2: "Rear Projection - Desktop",
    3: "Rear Projection - Ceiling Mount",
}
PROJECTION_MODE_NAMES_TO_CODES: dict[str, int] = {
    v: k for k, v in PROJECTION_MODE_CODES.items()
}

# --- Aspect ratios (Aspect) ---------------------------------------------------
ASPECT_CODES: dict[int, str] = {
    1: "1:1",
    2: "4:3",
    3: "16:9",
}
ASPECT_NAMES_TO_CODES: dict[str, int] = {v: k for k, v in ASPECT_CODES.items()}

# --- Power saving timeout (PwSave, minutes; 0 = off) --------------------------
POWER_SAVING_CODES: dict[int, str] = {
    0: "Off",
    5: "5 min",
    15: "15 min",
    30: "30 min",
    45: "45 min",
    60: "60 min",
    120: "120 min",
}
POWER_SAVING_NAMES_TO_CODES: dict[str, int] = {
    v: k for k, v in POWER_SAVING_CODES.items()
}

# --- ECO mode (ecoMode radio) -------------------------------------------------
ECO_MODE_ON = 27  # "ECO Mode"
ECO_MODE_OFF = 28  # "Full Power"

# --- Blank screen (hide radio / HIDE0 hidden field) ---------------------------
HIDE_ON = 85
HIDE_OFF = 170

# Brightness / contrast 0-100, volume 0-20
BRIGHTNESS_MIN, BRIGHTNESS_MAX = 0, 100
CONTRAST_MIN, CONTRAST_MAX = 0, 100
VOLUME_MIN, VOLUME_MAX = 0, 20
