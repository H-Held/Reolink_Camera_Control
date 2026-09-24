"""Data models returned by :class:`~reolink_camera_control.ReolinkCamera`.

Every model keeps the unparsed camera response in ``raw``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    name: str = ""
    model: str = ""
    serial: str = ""
    firmware: str = ""
    hardware: str = ""
    build_day: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ImageSettings:
    bright: int = 128
    contrast: int = 128
    saturation: int = 128
    sharpness: int = 128
    hue: int = 128
    raw: dict = field(default_factory=dict)


@dataclass
class EncoderSettings:
    main_bitrate: int = 0
    main_framerate: int = 0
    main_width: int = 0
    main_height: int = 0
    sub_bitrate: int = 0
    sub_framerate: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class NetworkPorts:
    http_port: int = 80
    https_port: int = 443
    rtsp_port: int = 554
    rtmp_port: int = 1935
    onvif_port: int = 8000
    rtsp_enabled: bool = True
    raw: dict = field(default_factory=dict)


@dataclass
class MotionAlarmConfig:
    enabled: bool = False
    sensitivity: int = 50
    raw: dict = field(default_factory=dict)


@dataclass
class AiConfig:
    people: bool = False
    vehicle: bool = False
    animal: bool = False
    face: bool = False
    ai_track: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class IrLightState:
    state: str = "Auto"
    raw: dict = field(default_factory=dict)


@dataclass
class WhiteLedState:
    state: int = 0
    mode: int = 1
    bright: int = 100
    raw: dict = field(default_factory=dict)


@dataclass
class AudioConfig:
    volume: int = 50
    mute: int = 0
    raw: dict = field(default_factory=dict)
