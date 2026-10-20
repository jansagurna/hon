import logging
import re
from .device import HonDevice
from .const import DOMAIN, APPLIANCE_DEFAULT_NAME
from .parameter import HonParameterFixed, HonParameterEnum, HonParameterRange, HonParameterProgram

from homeassistant.core import callback
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import translation
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

default_values = {
    "delayTime": {
        "icon": "mdi:timer-plus",
        "native_unit_of_measurement": UnitOfTime.MINUTES,
    },
    "rinseIterations": {
        "icon": "mdi:rotate-right",
    },
    "mainWashTime": {
        "icon": "mdi:clock-start",
        "native_unit_of_measurement": UnitOfTime.MINUTES,
    },
    "dryLevel": {
        "icon": "mdi:hair-dryer",
    },
    "tempLevel": {
        "icon": "mdi:thermometer",
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
    },
    "antiCreaseTime": {
        "icon": "mdi:timer",
        "native_unit_of_measurement": UnitOfTime.MINUTES,
    },
    "sterilizationStatus": {
        "icon": "mdi:clock-start",
    },
}


GENERIC_SETTING_NUMBERS = False

WINE_COOLER_ZONES = {
    "tempSel": "zone 1",
    "tempSelZ2": "zone 2",
}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hon = hass.data[DOMAIN][entry.unique_id]
    translations = await translation.async_get_translations(
        hass, hass.config.language, "entity"
    )

    appliances = []
    for appliance in hon.appliances:
        coordinator = await hon.async_get_coordinator(appliance)
        device = coordinator.device

        if device.appliance_type == "WC":
            for key, zone_name in WINE_COOLER_ZONES.items():
                if HonWineCoolerTemperature.program_ranges(device, key):
                    appliances.append(HonWineCoolerTemperature(coordinator, appliance, key, zone_name))

        # Generic numbers built from the device settings are not enabled yet
        if not GENERIC_SETTING_NUMBERS:
            continue

        #command = device.settings_command()

        for key in coordinator.device.settings:
            parameter = coordinator.device.settings[key]
            if(isinstance(parameter, HonParameterRange)
            and key.startswith("startProgram.")):

                default_value = default_values.get(parameter.key, {})
                translation_key = coordinator.device.appliance_type.lower() + '_' + parameter.key.lower()
                
                #name=translations.get(f"component.hon.entity.number.{translation_key}.name", parameter.key),

                description = NumberEntityDescription(
                    key=key,
                    name=f"{parameter.key}",
                    entity_category=EntityCategory.CONFIG,
                    #entity_category=None,
                    translation_key = translation_key,
                    icon=default_value.get("icon", None),
                    unit_of_measurement=default_value.get("unit_of_measurement", None),
                )
                appliances.extend([HonNumber(hon, coordinator, appliance, description)])

        for key, parameter in coordinator.device.settings.items():
            if not isinstance(parameter, HonParameterRange):
                continue

            default_value = default_values.get(parameter.key, {})
            translation_key = (
                coordinator.device.appliance_type.lower() + "_" + parameter.key.lower()
            )

            description = NumberEntityDescription(
                key=key,
                name=translations.get(
                    f"component.hon.entity.number.{translation_key}.name", parameter.key
                ),
                entity_category=EntityCategory.CONFIG,
                translation_key=translation_key,
                icon=default_value.get("icon"),
                native_unit_of_measurement=default_value.get(
                    "native_unit_of_measurement"
                ),
            )
            appliances.append(HonNumber(hon, coordinator, appliance, description))

    async_add_entities(appliances)


class HonBaseNumberEntity(CoordinatorEntity, NumberEntity):
    def __init__(self, coordinator, appliance, key, sensor_name) -> None:
        super().__init__(coordinator)
        self._coordinator   = coordinator
        self._mac           = appliance["macAddress"]
        self._type_id       = appliance["applianceTypeId"]
        self._name          = appliance.get("nickName", APPLIANCE_DEFAULT_NAME.get(str(self._type_id), "Device ID: " + str(self._type_id)))
        self._brand         = appliance["brand"]
        self._model         = appliance["modelName"]
        self._fw_version    = appliance["fwVersion"]
        self._type_name     = appliance["applianceTypeName"]
        self._key           = key
        self._device        = coordinator.device


        #Generate unique ID from key
        key_formatted = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()
        if( len(key_formatted) <= 0 ): 
            key_formatted = re.sub(r'(?<!^)(?=[A-Z])', '_', sensor_name).lower()
        self._attr_unique_id = self._mac + "_" + key_formatted
        
        self._attr_name = self._name + " " + sensor_name
        self.coordinator_update()

    @property
    def device_info(self):
        return {
            "identifiers": {
                (DOMAIN, self._mac, self._type_name)
            },
            "name": self._name,
            "manufacturer": self._brand,
            "model": self._model,
            "sw_version": self._fw_version,
        }

    @callback
    def _handle_coordinator_update(self):
        if self._coordinator.data is False:
            return
        self.coordinator_update()
        self.async_write_ha_state()

    def coordinator_update(self):
        self._attr_native_value = self._device.get(self._key)


class HonNumber(HonBaseNumberEntity):
    _attr_has_entity_name = False  

    def __init__(self, hon, coordinator, appliance, description) -> None:
        super().__init__(coordinator, appliance, description.key, description.name)

        self._coordinator = coordinator
        self._device = coordinator.device
        self.entity_description = description
        
        #param_display = description.key.replace("startProgram.", "").replace("tempSelZ", "Zone ")
        #self._attr_name = f"{self._name} {param_display}"
        #_LOGGER.error(self._attr_name)
        self._attr_unique_id = f"{self._mac}-number-{description.key}"

    def _get_setting(self):
        return self._device.get_setting(self.entity_description.key)

    def _refresh_bounds(self):
        setting = self._get_setting()
        if isinstance(setting, HonParameterRange):
            self._attr_native_max_value = setting.max
            self._attr_native_min_value = setting.min
            self._attr_native_step = setting.step

    @property
    def native_value(self) -> float | None:
        setting = self._get_setting()
        return None if setting is None else setting.value

    async def async_set_native_value(self, value: float) -> None:
        command_name, parameter_name = self.entity_description.key.split(".", 1)
        if command_name == "settings":
            command = self._device.settings_command({parameter_name: value})
            await command.send()
            await self.coordinator.async_request_refresh()
            return

        self._device.start_command(parameters={parameter_name: value})
        self.coordinator.async_set_updated_data({})

    @callback
    def _handle_coordinator_update(self):
        setting = self._get_setting()
        self._refresh_bounds()
        self._attr_native_value = None if setting is None else setting.value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return super().available and self._device.has_current_setting(
            self.entity_description.key
        )


class HonWineCoolerTemperature(HonBaseNumberEntity):
    """Target temperature of a wine cooler zone.

    Wine coolers set the temperature through programs (e.g. sparkling, white, red),
    each one allowing a different range. The matching program is selected from the value.
    """

    def __init__(self, coordinator, appliance, key, zone_name) -> None:
        super().__init__(coordinator, appliance, key, f"Target temperature {zone_name}")
        self._attr_unique_id = f"{self._mac}-wine-cooler-{key}"
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer"
        self._attr_mode = NumberMode.BOX

        ranges = self.program_ranges(self._device, key)
        self._attr_native_min_value = min(parameter.min for parameter in ranges.values())
        self._attr_native_max_value = max(parameter.max for parameter in ranges.values())
        self._attr_native_step = min(parameter.step for parameter in ranges.values())

    @staticmethod
    def program_ranges(device, key):
        command = device.commands.get("startProgram")
        if command is None:
            return {}
        result = {}
        for program, program_command in command.get_programs().items():
            parameter = program_command.parameters.get(key)
            if isinstance(parameter, HonParameterRange):
                result[program] = parameter
        return result

    def coordinator_update(self):
        try:
            self._attr_native_value = float(str(self._device.get(self._key)).replace(",", "."))
        except (TypeError, ValueError):
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        value = int(value) if float(value).is_integer() else value
        program = next(
            (name for name, parameter in self.program_ranges(self._device, self._key).items()
             if parameter.min <= value <= parameter.max),
            None,
        )
        if program is None:
            raise HomeAssistantError(f"No program allows {value}°C for {self._key}")

        # The other zone keeps its current value if the program allows it, otherwise the program default is used
        await self._device.start_command(program, {self._key: value}).send()
        self._device.set(self._key, str(value))
        self._attr_native_value = float(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
