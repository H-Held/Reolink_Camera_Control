"""High-level Reolink camera API."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests

from .audio import (ffmpeg_available as _ffmpeg_available, generate_tone_pcm,
                    load_pcm)
from .exceptions import ReolinkCommandError
from .http import ReolinkHTTP
from .models import (AiConfig, AudioConfig, DeviceInfo, EncoderSettings,
                     ImageSettings, IrLightState, MotionAlarmConfig,
                     NetworkPorts, WhiteLedState)
from .talk import TalkSession


class ReolinkCamera:
    """
    High-level Reolink camera API.

    Raises ReolinkError subclasses on failure.

    Context manager:
        with ReolinkCamera("192.168.1.100", "admin", "pass") as cam:
            print(cam.get_device_info().model)
    """

    def __init__(self, host: str, username: str = "admin", password: str = "",
                 port: int = 443, scheme: str = "https", channel: int = 0):
        """
        Args:
            host:     Camera IP or hostname.
            username: Login username (default "admin").
            password: Login password.
            port:     API port (default 443 for HTTPS, 80 for HTTP).
            scheme:   "https" (default) or "http".
            channel:  Default channel index (default 0).
        """
        self.host    = host
        self._ch_def = channel
        self._http   = ReolinkHTTP(host, username, password, port, scheme)

    def _ch(self, ch: Optional[int]) -> int:
        return self._ch_def if ch is None else ch

    # ── Connection ────────────────────────────────────────────────────────

    def connect(self) -> str:
        """Log in and return the session token."""
        return self._http.login()

    def disconnect(self):
        """Log out and release the session."""
        self._http.logout()

    def __enter__(self): self.connect(); return self
    def __exit__(self, *_): self.disconnect()

    # ══════════════════════════════════════════════════════════════════════
    #  Device / System
    # ══════════════════════════════════════════════════════════════════════

    def get_device_info(self) -> DeviceInfo:
        """Model, firmware version, serial number, hardware version."""
        v = self._http.value(self._http.get("GetDevInfo"), "DevInfo") or {}
        return DeviceInfo(
            name=v.get("name",""), model=v.get("model",""),
            serial=v.get("serial",""), firmware=v.get("firmVer",""),
            hardware=v.get("hardVer",""), build_day=v.get("buildDay",""), raw=v,
        )

    def get_device_name(self) -> str:
        """Current display name of the device."""
        return (self._http.value(self._http.get("GetDevName"), "DevName") or {}).get("name","")

    def set_device_name(self, name: str) -> None:
        cur = self._http.value(self._http.get("GetDevName"), "DevName") or {}
        self._http.set("SetDevName", {"DevName": {**cur, "name": name}})

    def get_performance(self) -> dict:
        """CPU / memory performance stats."""
        return self._http.value(self._http.get("GetPerformance"), "Performance") or {}

    def get_hdd_info(self) -> list:
        """List of storage device info dicts."""
        return self._http.value(self._http.get("GetHddInfo"), "HddInfo") or []

    def get_online_users(self) -> list:
        """Currently logged-in sessions."""
        return self._http.value(self._http.get("GetOnline"), "OnlineList") or []

    def get_ability(self) -> dict:
        """Camera capability map."""
        return self._http.value(
            self._http.get("GetAbility", {"User": {"userName": self._http.username}}),
            "Ability") or {}

    def reboot(self) -> None:
        """Reboot the camera (takes ~30 s to come back online)."""
        self._http.call("Reboot", {})

    # ══════════════════════════════════════════════════════════════════════
    #  Network
    # ══════════════════════════════════════════════════════════════════════

    def get_network_ports(self) -> NetworkPorts:
        v = self._http.value(self._http.get("GetNetPort"), "NetPort") or {}
        return NetworkPorts(
            http_port    = v.get("httpPort", 80),
            https_port   = v.get("httpsPort", 443),
            rtsp_port    = v.get("rtspPort", 554),
            rtmp_port    = v.get("rtmpPort", 1935),
            onvif_port   = v.get("onvifPort", 8000),
            rtsp_enabled = bool(v.get("rtspEnable", 0)),
            raw          = v,
        )

    def get_rtsp_urls(self) -> dict[str, str]:
        """Return {"main": "rtsp://...", "sub": "rtsp://..."} or {} if disabled."""
        p = self.get_network_ports()
        if not p.rtsp_enabled: return {}
        b = f"rtsp://{self.host}:{p.rtsp_port}"
        return {"main": f"{b}//h264Preview_01_main", "sub": f"{b}//h264Preview_01_sub"}

    def get_local_link(self) -> dict:
        return self._http.value(self._http.get("GetLocalLink"), "LocalLink") or {}

    def get_p2p(self) -> dict:
        return self._http.value(self._http.get("GetP2p"), "P2p") or {}

    def get_upnp(self) -> dict:
        return self._http.value(self._http.get("GetUpnp"), "Upnp") or {}

    def get_ddns(self) -> dict:
        return self._http.value(self._http.get("GetDdns"), "Ddns") or {}

    # ══════════════════════════════════════════════════════════════════════
    #  Time
    # ══════════════════════════════════════════════════════════════════════

    def get_time(self) -> dict:
        return self._http.value(self._http.get("GetTime"), "Time") or {}

    def get_ntp(self) -> dict:
        return self._http.value(self._http.get("GetNtp"), "Ntp") or {}

    def set_ntp(self, enabled: bool) -> None:
        cur = self.get_ntp()
        self._http.set("SetNtp", {"Ntp": {**cur, "enable": int(enabled)}})

    def get_auto_maintenance(self) -> dict:
        return self._http.value(self._http.get("GetAutoMaint"), "AutoMaint") or {}

    def set_auto_maintenance(self, enabled: bool) -> None:
        cur = self.get_auto_maintenance()
        self._http.set("SetAutoMaint", {"AutoMaint": {**cur, "enable": int(enabled)}})

    # ══════════════════════════════════════════════════════════════════════
    #  Video & Image
    # ══════════════════════════════════════════════════════════════════════

    def get_encoder_settings(self, channel: Optional[int] = None) -> EncoderSettings:
        v  = self._http.value(
            self._http.get("GetEnc", {"channel": self._ch(channel)}), "Enc") or {}
        ms = v.get("mainStream", {}); ss = v.get("subStream", {})
        return EncoderSettings(
            main_bitrate=ms.get("bitRate",0),   main_framerate=ms.get("frameRate",0),
            main_width=ms.get("width",0),       main_height=ms.get("height",0),
            sub_bitrate=ss.get("bitRate",0),    sub_framerate=ss.get("frameRate",0),
            raw=v,
        )

    def set_main_stream_bitrate(self, bitrate: int, channel: Optional[int] = None) -> None:
        ch  = self._ch(channel)
        enc = self._http.value(self._http.get("GetEnc", {"channel": ch}), "Enc") or {}
        ms  = enc.get("mainStream", {})
        self._http.set("SetEnc", {"Enc": {**enc, "mainStream": {**ms, "bitRate": bitrate}}})

    def get_image_settings(self, channel: Optional[int] = None) -> ImageSettings:
        v = self._http.value(
            self._http.get("GetImage", {"channel": self._ch(channel)}), "Image") or {}
        return ImageSettings(
            bright=v.get("bright",128), contrast=v.get("contrast",128),
            saturation=v.get("saturation",128), sharpness=v.get("sharpness",128),
            hue=v.get("hue",128), raw=v,
        )

    def set_image_settings(self, channel: Optional[int] = None, **kwargs) -> None:
        """kwargs: bright, contrast, saturation, sharpness, hue (0–255)."""
        ch  = self._ch(channel)
        cur = self._http.value(self._http.get("GetImage", {"channel": ch}), "Image") or {}
        self._http.set("SetImage", {"Image": {**cur, **kwargs}})

    def get_isp(self, channel: Optional[int] = None) -> dict:
        """ISP settings: day/night mode, flip, mirroring."""
        return self._http.value(
            self._http.get("GetIsp", {"channel": self._ch(channel)}), "Isp") or {}

    def set_day_night_mode(self, mode: str, channel: Optional[int] = None) -> None:
        """mode: "Auto" | "Color" | "Black&White" """
        ch = self._ch(channel)
        self._http.set("SetIsp", {"Isp": {**self.get_isp(ch), "dayNight": mode}})

    def get_osd(self, channel: Optional[int] = None) -> dict:
        """On-screen display settings (channel name, time overlay, etc.)."""
        return self._http.value(
            self._http.get("GetOsd", {"channel": self._ch(channel)}), "Osd") or {}

    def set_osd_channel_name(self, name: str, channel: Optional[int] = None) -> None:
        ch     = self._ch(channel)
        osd    = self.get_osd(ch)
        osd_ch = osd.get("osdChannel", {})
        self._http.set("SetOsd", {"Osd": {**osd, "osdChannel": {**osd_ch, "name": name}}})

    def get_mask(self, channel: Optional[int] = None) -> dict:
        return self._http.value(
            self._http.get("GetMask", {"channel": self._ch(channel)}), "Mask") or {}

    def set_mask_enabled(self, enabled: bool, channel: Optional[int] = None) -> None:
        ch = self._ch(channel)
        self._http.set("SetMask", {"Mask": {**self.get_mask(ch), "enable": int(enabled)}})

    # ══════════════════════════════════════════════════════════════════════
    #  Snapshot
    # ══════════════════════════════════════════════════════════════════════

    def snap(self, channel: Optional[int] = None) -> bytes:
        """Take a snapshot. Returns raw JPEG bytes."""
        ch  = self._ch(channel)
        url = (f"{self._http.scheme}://{self.host}:{self._http.port}"
               f"/cgi-bin/api.cgi?cmd=Snap&channel={ch}&token={self._http.token}")
        r = requests.get(url, verify=False, timeout=15)
        if r.status_code == 200 and len(r.content) > 500:
            return r.content
        raise ReolinkCommandError(
            f"Snap failed: HTTP {r.status_code}, {len(r.content)} bytes")

    def snap_to_file(self, path: str, channel: Optional[int] = None) -> Path:
        """Take a snapshot and save to *path*. Returns the Path."""
        p = Path(path); p.write_bytes(self.snap(channel)); return p

    # ══════════════════════════════════════════════════════════════════════
    #  Lights
    # ══════════════════════════════════════════════════════════════════════

    def get_ir_lights(self, channel: Optional[int] = None) -> IrLightState:
        v = self._http.value(
            self._http.get("GetIrLights", {"channel": self._ch(channel)}), "IrLights") or {}
        return IrLightState(state=v.get("state","Auto"), raw=v)

    def set_ir_lights(self, state: str) -> None:
        """state: "Auto" | "Off" """
        self._http.set("SetIrLights", {"IrLights": {"state": state}})

    def get_white_led(self, channel: Optional[int] = None) -> WhiteLedState:
        v = self._http.value(
            self._http.get("GetWhiteLed", {"channel": self._ch(channel)}), "WhiteLed") or {}
        return WhiteLedState(state=v.get("state",0), mode=v.get("mode",1),
                             bright=v.get("bright",100), raw=v)

    def set_white_led(self, state: Optional[int] = None, mode: Optional[int] = None,
                      bright: Optional[int] = None, channel: Optional[int] = None) -> None:
        """state: 0/1 | mode: 0=Off, 1=Auto, 3=Schedule | bright: 0-100"""
        ch = self._ch(channel)
        v  = self.get_white_led(ch).raw
        if state  is not None: v = {**v, "state":  state}
        if mode   is not None: v = {**v, "mode":   mode}
        if bright is not None: v = {**v, "bright": bright}
        self._http.set("SetWhiteLed", {"WhiteLed": v})

    def get_power_led(self, channel: Optional[int] = None) -> str:
        """Return "On" or "Off"."""
        v = self._http.value(
            self._http.get("GetPowerLed", {"channel": self._ch(channel)}), "PowerLed") or {}
        return v.get("state","On")

    def set_power_led(self, state: str, channel: Optional[int] = None) -> None:
        """state: "On" | "Off" """
        ch = self._ch(channel)
        self._http.set("SetPowerLed", {"PowerLed": {"channel": ch, "state": state}})

    # ══════════════════════════════════════════════════════════════════════
    #  Audio — HTTP config  (volume, event siren)
    # ══════════════════════════════════════════════════════════════════════

    def get_audio_config(self, channel: Optional[int] = None) -> AudioConfig:
        """Microphone / speaker volume and mute settings."""
        v = self._http.value(
            self._http.get("GetAudioCfg", {"channel": self._ch(channel)}), "AudioCfg") or {}
        return AudioConfig(volume=v.get("volume",50), mute=v.get("mute",0), raw=v)

    def set_audio_volume(self, volume: int, channel: Optional[int] = None) -> None:
        """Set speaker volume 0–100."""
        ch = self._ch(channel)
        v  = self.get_audio_config(ch).raw
        self._http.set("SetAudioCfg", {"AudioCfg": {**v, "volume": volume}})

    def get_audio_alarm(self, channel: Optional[int] = None) -> dict:
        """Siren-on-event configuration."""
        return self._http.value(
            self._http.get("GetAudioAlarmV20", {"channel": self._ch(channel)}), "Audio") or {}

    def set_audio_alarm_enabled(self, enabled: bool,
                                channel: Optional[int] = None) -> None:
        """Enable / disable the siren that fires on AI/motion events."""
        ch    = self._ch(channel)
        audio = self.get_audio_alarm(ch)
        self._http.set("SetAudioAlarmV20", {"Audio": {**audio, "enable": int(enabled)}})

    def siren_on(self) -> None:
        """Manual HTTP siren trigger (firmware support varies)."""
        self._http.set("AudioAlarmPlay",
                       {"alarm_mode": "manul", "manual_switch": 1, "channel": 0},
                       settle=False)

    def siren_off(self) -> None:
        """Stop manual HTTP siren."""
        self._http.set("AudioAlarmPlay",
                       {"alarm_mode": "manul", "manual_switch": 0, "channel": 0},
                       settle=False)

    # ══════════════════════════════════════════════════════════════════════
    #  Audio PUSH  –  StartTalk / StopTalk  (pure HTTP, no extra binaries)
    # ══════════════════════════════════════════════════════════════════════

    def play_audio_file(self, file_path: str,
                        channel: Optional[int] = None) -> bool:
        """
        Play an audio file through the camera speaker.

        Uses the camera's built-in HTTP talkback endpoint (StartTalk/StopTalk).
        No neolink, no Docker, no Baichuan protocol — just HTTP + Python.

        Supported formats (no extra tools):
            .wav

        Supported formats (requires ffmpeg in PATH):
            .mp3  .aac  .m4a  .ogg  .flac  .wma  .opus

        All audio is automatically resampled to 8 kHz mono 16-bit PCM
        before streaming to the camera.

        Args:
            file_path:  Path to the audio file.
            channel:    Camera channel index (default: instance channel).

        Returns:
            True on success.

        Raises:
            ReolinkAudioError: Conversion failed or stream error.
        """
        pcm = load_pcm(str(file_path))
        return TalkSession(self._http.base, self._http.token).send(pcm)

    def play_tone(self, freq: float = 440.0, duration: float = 3.0,
                  amplitude: float = 0.7,
                  channel: Optional[int] = None) -> bool:
        """
        Generate and play a sine-wave tone through the camera speaker.

        Zero external dependencies — pure Python math.

        Args:
            freq:      Frequency in Hz (440=A4, 1000=alert, 2000=hi-alert).
            duration:  Length in seconds.
            amplitude: Volume 0.0–1.0 (default 0.7).
            channel:   Camera channel index.

        Returns:
            True on success.
        """
        pcm = generate_tone_pcm(freq, duration, amplitude)
        return TalkSession(self._http.base, self._http.token).send(pcm)

    def ffmpeg_available(self) -> bool:
        """Return True if ffmpeg is installed (needed for MP3/AAC/OGG/FLAC)."""
        return _ffmpeg_available()

    # ══════════════════════════════════════════════════════════════════════
    #  Detection
    # ══════════════════════════════════════════════════════════════════════

    def get_motion_alarm(self, channel: Optional[int] = None) -> MotionAlarmConfig:
        v = self._http.value(
            self._http.get("GetMdAlarm", {"channel": self._ch(channel)}), "MdAlarm") or {}
        return MotionAlarmConfig(
            enabled     = bool(v.get("enable",0)),
            sensitivity = v.get("sens",{}).get("sens",50),
            raw         = v,
        )

    def get_ai_config(self, channel: Optional[int] = None) -> AiConfig:
        v = self._http.get("GetAiCfg", {"channel": self._ch(channel)}).get("value",{})
        return AiConfig(
            people   = bool(v.get("people",  {}).get("enable",0)),
            vehicle  = bool(v.get("vehicle", {}).get("enable",0)),
            animal   = bool(v.get("animal",  {}).get("enable",0)),
            face     = bool(v.get("face",    {}).get("enable",0)),
            ai_track = bool(v.get("aiTrack", 0)),
            raw      = v,
        )

    def set_ai_tracking(self, enabled: bool, channel: Optional[int] = None) -> None:
        ch = self._ch(channel)
        v  = self._http.get("GetAiCfg", {"channel": ch}).get("value",{})
        self._http.set("SetAiCfg", {**v, "aiTrack": int(enabled)})

    # ══════════════════════════════════════════════════════════════════════
    #  Recording / FTP
    # ══════════════════════════════════════════════════════════════════════

    def get_recording_config(self, channel: Optional[int] = None) -> dict:
        return self._http.value(
            self._http.get("GetRecV20", {"channel": self._ch(channel)}), "Rec") or {}

    def set_recording_enabled(self, enabled: bool,
                               channel: Optional[int] = None) -> None:
        ch  = self._ch(channel)
        rec = self.get_recording_config(ch)
        self._http.set("SetRecV20", {"Rec": {**rec, "enable": int(enabled)}})

    def get_ftp_config(self) -> dict:
        return self._http.value(self._http.get("GetFtpV20"), "Ftp") or {}

    # ══════════════════════════════════════════════════════════════════════
    #  Notifications
    # ══════════════════════════════════════════════════════════════════════

    def get_email_config(self, channel: Optional[int] = None) -> dict:
        return self._http.value(
            self._http.get("GetEmailV20", {"channel": self._ch(channel)}), "Email") or {}

    def get_push_config(self, channel: Optional[int] = None) -> dict:
        return self._http.value(
            self._http.get("GetPushV20", {"channel": self._ch(channel)}), "Push") or {}

    def get_webhook_config(self) -> dict:
        return self._http.value(self._http.get("GetWebHook"), "WebHook") or {}

    def set_webhook_enabled(self, enabled: bool) -> None:
        wh = self.get_webhook_config()
        self._http.set("SetWebHook", {"WebHook": {**wh, "enable": int(enabled)}})

    # ══════════════════════════════════════════════════════════════════════
    #  PTZ
    # ══════════════════════════════════════════════════════════════════════

    def get_ptz_presets(self, channel: Optional[int] = None) -> list:
        try:
            return self._http.value(
                self._http.get("GetPtzPreset", {"channel": self._ch(channel)}),
                "PtzPreset") or []
        except ReolinkCommandError:
            return []

    def ptz_move(self, operation: str, speed: int = 20,
                 channel: Optional[int] = None) -> None:
        """operation: "Up"|"Down"|"Left"|"Right"|"ZoomInc"|"ZoomDec"|"Stop" """
        ch = self._ch(channel)
        self._http.call("PtzCtrl", {"channel": ch, "op": operation, "speed": speed})

    def ptz_stop(self, channel: Optional[int] = None) -> None:
        self._http.call("PtzCtrl", {"channel": self._ch(channel), "op": "Stop"})

    def ptz_goto_preset(self, preset_id: int, channel: Optional[int] = None) -> None:
        self._http.call("PtzCtrl",
                        {"channel": self._ch(channel), "op": "ToPos", "id": preset_id})
