"""Python library for controlling Reolink cameras over their HTTP API.

Quick start::

    from reolink_camera_control import ReolinkCamera

    with ReolinkCamera("192.168.1.100", "admin", "password") as cam:
        print(cam.get_device_info().model)
"""

from .camera import ReolinkCamera
from .exceptions import (ReolinkAudioError, ReolinkAuthError,
                         ReolinkCommandError, ReolinkConnectionError,
                         ReolinkError)
from .models import (AiConfig, AudioConfig, DeviceInfo, EncoderSettings,
                     ImageSettings, IrLightState, MotionAlarmConfig,
                     NetworkPorts, WhiteLedState)

__version__ = "0.1.0"

__all__ = [
    "ReolinkCamera",
    "ReolinkError", "ReolinkAuthError", "ReolinkCommandError",
    "ReolinkConnectionError", "ReolinkAudioError",
    "AiConfig", "AudioConfig", "DeviceInfo", "EncoderSettings",
    "ImageSettings", "IrLightState", "MotionAlarmConfig", "NetworkPorts",
    "WhiteLedState",
    "__version__",
]
