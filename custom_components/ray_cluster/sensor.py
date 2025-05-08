# cover.py
import logging
from collections import defaultdict
from datetime import timedelta

import aiohttp
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.constants import Endian
from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_SLAVE_ID, CONF_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES = [
    ("CPU Usage", "cpu_usage", PERCENTAGE, SensorStateClass.MEASUREMENT, "mdi:chip"),
    ("Memory Usage", "memory_usage", PERCENTAGE, SensorStateClass.MEASUREMENT, "mdi:memory"),

]


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = RayClusterCoordinator(hass, config_entry)

    # 确保协调器已初始化
    await coordinator.async_config_entry_first_refresh()

    # 确保update_interval类型正确
    if not isinstance(coordinator.update_interval, timedelta):
        raise ValueError("Invalid update interval type")

    sensors = []
    for hostname, dev in coordinator.device_infos.items():
        for name, key, unit, state_class, icon in SENSOR_TYPES:
            sensors.append(
                RayClusterSensor(coordinator, name, key, unit, state_class, icon,
                                 hostname=hostname, device_info=dev)
            )
        for gpu in coordinator.data.get(hostname, {}).get('gpus'):
            dev['model'] = gpu['name']
            sensors.append(RayClusterSensor(coordinator, f"GPU {gpu['index']} Util",
                                 f"gpu_usage_{gpu['index']}",
                                 unit=PERCENTAGE,
                                 state_class=SensorStateClass.MEASUREMENT,
                                 icon="mdi:chip",
                                 hostname=hostname,
                                 device_info=dev)
            )
            sensors.append(RayClusterSensor(coordinator, f"GPU {gpu['index']} Mem",
                                 f"gpu_memusage_{gpu['index']}",
                                 unit=PERCENTAGE,
                                 state_class=SensorStateClass.MEASUREMENT,
                                 icon="mdi:memory",
                                 hostname=hostname,
                                 device_info=dev)
            )
            sensors.append(RayClusterSensor(coordinator, f"GPU {gpu['index']} Memory Used",
                                 f"gpu_memused_{gpu['index']}",
                                 unit=UnitOfInformation.MEGABYTES,
                                 state_class=SensorStateClass.MEASUREMENT,
                                 icon="mdi:memory",
                                 hostname=hostname,
                                 device_info=dev)
            )

    async_add_entities(sensors)


class RayClusterSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, name, key, unit, state_class, icon, hostname, device_info):
        super().__init__(coordinator, key)
        self._attr_device_info = device_info
        self._attr_translation_key = key
        self.hostname = hostname
        self.entity_description = SensorEntityDescription(
            key=key,
            name=name,
            state_class=state_class,
            icon=icon,
            native_unit_of_measurement=unit,
            has_entity_name=True,
            suggested_display_precision=2
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """处理来自协调器的更新数据。"""
        self.async_write_ha_state()

    @property
    def native_value(self):
        state = self.coordinator.data.get(self.hostname, {})
        if self.entity_description.key == "cpu_usage":
            return state.get("cpu")
        elif self.entity_description.key == "memory_usage":
            return state.get("mem")[2]
        elif self.entity_description.key.startswith("gpu_usage_"):
            gpu_id = int(self.entity_description.key[10:])
            for gpu in state.get("gpus"):
                if gpu.get("index") == gpu_id:
                    return gpu.get("utilizationGpu")
            return None
        elif self.entity_description.key.startswith("gpu_memusage_"):
            gpu_id = int(self.entity_description.key[13:])
            for gpu in state.get("gpus"):
                if gpu.get("index") == gpu_id:
                    return gpu.get("memoryUsed") / gpu.get("memoryTotal") * 100.0
            return None
        elif self.entity_description.key.startswith("gpu_memused_"):
            gpu_id = int(self.entity_description.key[12:])
            for gpu in state.get("gpus"):
                if gpu.get("index") == gpu_id:
                    return gpu.get("memoryUsed")
            return None
        return state.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        return self.coordinator.data.get(self.hostname, None) is not None

    @property
    def unique_id(self):
        return f"{self.hostname}_{self.entity_description.key.lower()}"


class RayClusterCoordinator(DataUpdateCoordinator):
    """异步数据协调器"""

    def __init__(self, hass, config_entry):
        host, port = config_entry.data[CONF_HOST], config_entry.data[CONF_PORT]
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Ray Cluster",
            update_interval=timedelta(seconds=config_entry.data[CONF_SCAN_INTERVAL]),
        )
        self.config_entry = config_entry
        self.device_infos = {}
        self.data = defaultdict(dict)

    async def _async_update_data(self):
        """异步获取所有数据"""
        try:
            http_session = aiohttp.ClientSession()
            async with (http_session.get(
                    f"http://{self.config_entry.data[CONF_HOST]}:{self.config_entry.data[CONF_PORT]}/nodes?view=summary"
            ) as response):
                if response.status != 200:
                    error = await response.text()
                    raise ConnectionError(f"请求失败，状态码: {response.status}，{error}")

                data = await response.json()
                for device in data['data']['summary']:
                    if device.get("hostname") is None:
                        continue
                    self.device_infos[device['hostname']] = DeviceInfo(
                        identifiers={(DOMAIN, self.config_entry.entry_id+"-"+device['hostname'])},
                        name=f"Ray Cluster Node {device['hostname']}",
                        manufacturer=None,
                        model=None
                    )
                    self.data[device['hostname']] = device

            await http_session.close()
            return self.data
        except Exception as e:
            self.logger.error("Update failed: %s", str(e))
            await http_session.close()
            raise

