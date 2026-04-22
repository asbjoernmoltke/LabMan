from enum import StrEnum


class DeviceRole(StrEnum):
    LASER = "laser"
    POWER_METER = "power_meter"
    CAMERA = "camera"
    SPECTROMETER = "spectrometer"
    STAGE = "stage"
