"""The Roborock component."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RoborockClient, RoborockMqttClient
from .const import CONF_ENTRY_USERNAME, CONF_USER_DATA, CONF_HOME_DATA, CONF_BASE_URL
from .const import DOMAIN, PLATFORMS

SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up roborock from a config entry."""
    _LOGGER.debug(f"integration async setup entry: {entry.as_dict()}")
    hass.data.setdefault(DOMAIN, {})

    # Find ble device here so that we can raise device not found on startup
    user_data = entry.data.get(CONF_USER_DATA)

    # Newer version will have this None so new roborock devices show up on reload
    home_data = entry.data.get(CONF_HOME_DATA)
    if not home_data:
        base_url = entry.data.get(CONF_BASE_URL)
        username = entry.data.get(CONF_ENTRY_USERNAME)
        device_identifier = entry.unique_id
        api_client = RoborockClient(username, device_identifier, base_url)
        loop = asyncio.get_running_loop()
        _LOGGER.debug("Connecting to roborock mqtt")
        home_data = await loop.run_in_executor(
            None,
            api_client.get_home_data,
            user_data
        )

    client = RoborockMqttClient(user_data, home_data)
    coordinator = RoborockDataUpdateCoordinator(hass, client)

    _LOGGER.debug("Searching for Roborock sensors...")
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    for platform in PLATFORMS:
        if entry.options.get(platform, True):
            coordinator.platforms.append(platform)
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


class RoborockDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, client: RoborockMqttClient) -> None:
        """Initialize."""
        self.api = client
        self.platforms = []
        self._connected = False

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    async def _async_update_data(self):
        """Update data via library."""
        if not self._connected:
            try:
                loop = asyncio.get_running_loop()
                _LOGGER.debug("Connecting to roborock mqtt")
                await loop.run_in_executor(
                    None,
                    self.api.connect
                )
                self._connected = True
            except Exception as exception:
                raise UpdateFailed(exception) from exception


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
                if platform in coordinator.platforms
            ]
        )
    )
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
