"""Support for IKEA Tradfri."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pytradfri import Gateway, RequestError
from pytradfri.api.aiocoap_api import APIFactory
from pytradfri.command import Command
from pytradfri.device import Device

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_GATEWAY_ID,
    CONF_IDENTITY,
    CONF_KEY,
    COORDINATOR,
    COORDINATOR_LIST,
    DOMAIN,
    FACTORY,
    KEY_API,
    LOGGER,
)
from .coordinator import TradfriDeviceDataUpdateCoordinator

PLATFORMS = [
    Platform.COVER,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]
SIGNAL_GW = "tradfri.gw_status"
TIMEOUT_API = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Create a gateway."""
    tradfri_data: dict[str, Any] = {}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = tradfri_data

    factory = await APIFactory.init(
        entry.data[CONF_HOST],
        psk_id=entry.data[CONF_IDENTITY],
        psk=entry.data[CONF_KEY],
    )
    tradfri_data[FACTORY] = factory  # Used for async_unload_entry

    async def on_hass_stop(event: Event) -> None:
        """Close connection when hass stops."""
        await factory.shutdown()

    # Setup listeners
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )

    api = factory.request
    gateway = Gateway()

    try:
        gateway_info = await api(gateway.get_gateway_info(), timeout=TIMEOUT_API)
        devices_commands: Command = await api(
            gateway.get_devices(), timeout=TIMEOUT_API
        )
        devices: list[Device] = await api(devices_commands, timeout=TIMEOUT_API)

    except RequestError as exc:
        await factory.shutdown()
        raise ConfigEntryNotReady from exc

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections=set(),
        identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])},
        manufacturer="IKEA of Sweden",
        name="Gateway",
        # They just have 1 gateway model. Type is not exposed yet.
        model="E1526",
        sw_version=gateway_info.firmware_version,
    )

    remove_stale_devices(hass, entry, devices)

    # Setup the device coordinators
    coordinator_data = {
        CONF_GATEWAY_ID: gateway,
        KEY_API: api,
        COORDINATOR_LIST: [],
    }

    for device in devices:
        coordinator = TradfriDeviceDataUpdateCoordinator(
            hass=hass, config_entry=entry, api=api, device=device
        )
        await coordinator.async_config_entry_first_refresh()

        entry.async_on_unload(
            async_dispatcher_connect(hass, SIGNAL_GW, coordinator.set_hub_available)
        )
        coordinator_data[COORDINATOR_LIST].append(coordinator)

    tradfri_data[COORDINATOR] = coordinator_data

    async def async_keep_alive(now: datetime) -> None:
        if hass.is_stopping:
            return

        gw_status = True
        try:
            await api(gateway.get_gateway_info())
        except RequestError:
            LOGGER.error("Keep-alive failed")
            gw_status = False

        async_dispatcher_send(hass, SIGNAL_GW, gw_status)

    entry.async_on_unload(
        async_track_time_interval(hass, async_keep_alive, timedelta(seconds=60))
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        tradfri_data = hass.data[DOMAIN].pop(entry.entry_id)
        factory = tradfri_data[FACTORY]
        await factory.shutdown()

    return unload_ok


@callback
def remove_stale_devices(
    hass: HomeAssistant, config_entry: ConfigEntry, devices: list[Device]
) -> None:
    """Remove stale devices from device registry."""
    device_registry = dr.async_get(hass)
    device_entries = dr.async_entries_for_config_entry(
        device_registry, config_entry.entry_id
    )
    all_device_ids = {str(device.id) for device in devices}

    for device_entry in device_entries:
        device_id: str | None = None
        gateway_id: str | None = None

        for identifier in device_entry.identifiers:
            if identifier[0] != DOMAIN:
                continue

            _id = identifier[1]

            # Identify gateway device.
            if _id == config_entry.data[CONF_GATEWAY_ID]:
                gateway_id = _id
                break

            device_id = _id.replace(f"{config_entry.data[CONF_GATEWAY_ID]}-", "")
            break

        if gateway_id is not None:
            # Do not remove gateway device entry.
            continue

        if device_id is None or device_id not in all_device_ids:
            # If device_id is None an invalid device entry was found for this config entry.
            # If the device_id is not in existing device ids it's a stale device entry.
            # Remove config entry from this device entry in either case.
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=config_entry.entry_id
            )


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    LOGGER.debug(
        "Migrating Tradfri configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version > 1:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 1:
        # Migrate to version 2
        migrate_config_entry_and_identifiers(hass, config_entry)

        hass.config_entries.async_update_entry(config_entry, version=2)

    LOGGER.debug(
        "Migration to Tradfri configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )

    return True


def migrate_config_entry_and_identifiers(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Migrate old non-unique identifiers to new unique identifiers."""

    related_device_flag: bool
    device_id: str

    device_reg = dr.async_get(hass)
    # Get all devices associated to contextual gateway config_entry
    # and loop through list of devices.
    for device in dr.async_entries_for_config_entry(device_reg, config_entry.entry_id):
        related_device_flag = False
        for identifier in device.identifiers:
            if identifier[0] != DOMAIN:
                continue

            related_device_flag = True

            _id = identifier[1]

            # Identify gateway device.
            if _id == config_entry.data[CONF_GATEWAY_ID]:
                # Using this to avoid updating gateway's own device registry entry
                related_device_flag = False
                break

            device_id = str(_id)
            break

        # Check that device is related to tradfri domain (and is not the gateway itself)
        if not related_device_flag:
            continue

        # Loop through list of config_entry_ids for device
        config_entry_ids = device.config_entries
        for config_entry_id in config_entry_ids:
            # Check that the config entry in list is not the device's primary config entry
            if config_entry_id == device.primary_config_entry:
                continue

            # Check that the 'other' config entry is also a tradfri config entry
            other_entry = hass.config_entries.async_get_entry(config_entry_id)

            if other_entry is None or other_entry.domain != DOMAIN:
                continue

            # Remove non-primary 'tradfri' config entry from device's config_entry_ids
            device_reg.async_update_device(
                device.id, remove_config_entry_id=config_entry_id
            )

        if config_entry.data[CONF_GATEWAY_ID] in device_id:
            continue

        device_reg.async_update_device(
            device.id,
            new_identifiers={
                (DOMAIN, f"{config_entry.data[CONF_GATEWAY_ID]}-{device_id}")
            },
        )
