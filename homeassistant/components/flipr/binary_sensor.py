"""Support for Flipr binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FliprConfigEntry
from .entity import FliprEntity

BINARY_SENSORS_TYPES: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="ph_status",
        translation_key="ph_status",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    BinarySensorEntityDescription(
        key="chlorine_status",
        translation_key="chlorine_status",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FliprConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Defer sensor setup of flipr binary sensors."""

    coordinators = config_entry.runtime_data.flipr_coordinators

    async_add_entities(
        FliprBinarySensor(coordinator, description)
        for description in BINARY_SENSORS_TYPES
        for coordinator in coordinators
    )


class FliprBinarySensor(FliprEntity, BinarySensorEntity):
    """Representation of Flipr binary sensors."""

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on in case of a Problem is detected."""
        return self.coordinator.data[self.entity_description.key] in (
            "TooLow",
            "TooHigh",
        )
