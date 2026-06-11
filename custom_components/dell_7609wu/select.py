"""Select entities for the Dell 7609WU integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Dell7609Client, ProjectorState
from .const import (
    ASPECT_CODES,
    ASPECT_NAMES_TO_CODES,
    POWER_SAVING_CODES,
    POWER_SAVING_NAMES_TO_CODES,
    PROJECTION_MODE_CODES,
    PROJECTION_MODE_NAMES_TO_CODES,
    SOURCE_CODES,
    SOURCE_NAMES_TO_CODES,
    VIDEO_MODE_CODES,
    VIDEO_MODE_NAMES_TO_CODES,
)
from .coordinator import Dell7609ConfigEntry, Dell7609Coordinator
from .entity import Dell7609Entity


@dataclass(frozen=True, kw_only=True)
class Dell7609SelectDescription(SelectEntityDescription):
    """Describes a Dell 7609WU select."""

    current_fn: Callable[[ProjectorState], int | None]
    code_map: dict[int, str]
    name_map: dict[str, int]
    select_fn: Callable[[Dell7609Client, int], Awaitable[None]]


SELECTS: tuple[Dell7609SelectDescription, ...] = (
    Dell7609SelectDescription(
        key="source",
        translation_key="source",
        current_fn=lambda state: state.source_code,
        code_map=SOURCE_CODES,
        name_map=SOURCE_NAMES_TO_CODES,
        select_fn=lambda client, code: client.async_set_source(code),
    ),
    Dell7609SelectDescription(
        key="video_mode",
        translation_key="video_mode",
        current_fn=lambda state: state.video_mode,
        code_map=VIDEO_MODE_CODES,
        name_map=VIDEO_MODE_NAMES_TO_CODES,
        select_fn=lambda client, code: client.async_set_video_mode(code),
    ),
    Dell7609SelectDescription(
        key="aspect_ratio",
        translation_key="aspect_ratio",
        current_fn=lambda state: state.aspect,
        code_map=ASPECT_CODES,
        name_map=ASPECT_NAMES_TO_CODES,
        select_fn=lambda client, code: client.async_set_aspect(code),
    ),
    Dell7609SelectDescription(
        key="projection_mode",
        translation_key="projection_mode",
        entity_category=EntityCategory.CONFIG,
        current_fn=lambda state: state.projection_mode,
        code_map=PROJECTION_MODE_CODES,
        name_map=PROJECTION_MODE_NAMES_TO_CODES,
        select_fn=lambda client, code: client.async_set_projection_mode(code),
    ),
    Dell7609SelectDescription(
        key="power_saving",
        translation_key="power_saving",
        entity_category=EntityCategory.CONFIG,
        current_fn=lambda state: state.power_saving,
        code_map=POWER_SAVING_CODES,
        name_map=POWER_SAVING_NAMES_TO_CODES,
        select_fn=lambda client, code: client.async_set_power_saving(code),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Dell7609ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        Dell7609Select(coordinator, description) for description in SELECTS
    )


class Dell7609Select(Dell7609Entity, SelectEntity):
    """A projector select."""

    entity_description: Dell7609SelectDescription

    def __init__(
        self,
        coordinator: Dell7609Coordinator,
        description: Dell7609SelectDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.code_map.values())

    @property
    def current_option(self) -> str | None:
        code = self.entity_description.current_fn(self.coordinator.data)
        if code is None:
            return None
        return self.entity_description.code_map.get(code)

    async def async_select_option(self, option: str) -> None:
        code = self.entity_description.name_map[option]
        await self.coordinator.async_send_command(
            self.entity_description.select_fn(self.coordinator.client, code)
        )
