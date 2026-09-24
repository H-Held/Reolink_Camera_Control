#!/usr/bin/env python3
"""
reolink_camera.py  –  Python library for Reolink cameras (RLC-540A and compatible)

Hard requirement:
    pip install requests

Optional (only for non-WAV audio files):
    ffmpeg binary in PATH  →  needed for MP3 / AAC / M4A / OGG / FLAC.
    WAV files and generated tones work with zero extra dependencies.

Audio push uses the camera's built-in HTTP talkback (StartTalk / StopTalk).
No neolink, no Docker, no Baichuan binary protocol required.

Camera audio format:  PCM · 8 000 Hz · mono · 16-bit LE
    Automatically converted from any WAV using stdlib audioop + wave.

Quick-start:
    from reolink_camera import ReolinkCamera

    with ReolinkCamera("192.168.1.100", "admin", "password") as cam:
        print(cam.get_device_info().model)
        cam.set_ir_lights("Auto")
        jpeg = cam.snap()                        # raw JPEG bytes
        cam.play_tone(440, duration=2)           # A4 tone through speaker
        cam.play_audio_file("/path/to/alert.wav")
"""

from __future__ import annotations

import audioop
import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Iterator, Optional

import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ══════════════════════════════════════════════════════════════════════════════
#  Exceptions
# ══════════════════════════════════════════════════════════════════════════════

class ReolinkError(Exception):
    """Base exception for all Reolink errors."""

class ReolinkAuthError(ReolinkError):
    """Login / token failure."""

class ReolinkCommandError(ReolinkError):
    """Camera rejected a command."""

class ReolinkConnectionError(ReolinkError):
    """Network / transport error."""

class ReolinkAudioError(ReolinkError):
    """Audio push failure."""


# ══════════════════════════════════════════════════════════════════════════════
#  Data models
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeviceInfo:
    name: str = ""; model: str = ""; serial: str = ""
    firmware: str = ""; hardware: str = ""; build_day: str = ""
    raw: dict = field(default_factory=dict)

@dataclass
class ImageSettings:
    bright: int = 128; contrast: int = 128; saturation: int = 128
    sharpness: int = 128; hue: int = 128
    raw: dict = field(default_factory=dict)

@dataclass
class EncoderSettings:
    main_bitrate: int = 0; main_framerate: int = 0
    main_width: int = 0; main_height: int = 0
    sub_bitrate: int = 0; sub_framerate: int = 0
    raw: dict = field(default_factory=dict)

@dataclass
class NetworkPorts:
    http_port: int = 80; https_port: int = 443; rtsp_port: int = 554
    rtmp_port: int = 1935; onvif_port: int = 8000; rtsp_enabled: bool = True
    raw: dict = field(default_factory=dict)

@dataclass
class MotionAlarmConfig:
    enabled: bool = False; sensitivity: int = 50
    raw: dict = field(default_factory=dict)

@dataclass
class AiConfig:
    people: bool = False; vehicle: bool = False; animal: bool = False
    face: bool = False; ai_track: bool = False
    raw: dict = field(default_factory=dict)

@dataclass
class IrLightState:
    state: str = "Auto"
    raw: dict = field(default_factory=dict)

@dataclass
class WhiteLedState:
    state: int = 0; mode: int = 1; bright: int = 100
    raw: dict = field(default_factory=dict)

@dataclass
class AudioConfig:
    volume: int = 50; mute: int = 0
    raw: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
#  Audio helpers  (pure stdlib for WAV and tone generation)
# ══════════════════════════════════════════════════════════════════════════════

# Camera talkback format
_TALK_RATE     = 8000   # Hz
_TALK_CHANNELS = 1      # mono
_TALK_WIDTH    = 2      # bytes (16-bit)
_CHUNK_MS      = 20     # ms per chunk  (= 160 samples = 320 bytes)
_CHUNK_SAMPLES = int(_TALK_RATE * _CHUNK_MS / 1000)
_CHUNK_BYTES   = _CHUNK_SAMPLES * _TALK_WIDTH


def _wav_to_pcm8k(wav_path: str) -> bytes:
    """
    Read a WAV file and return raw PCM at 8 000 Hz · mono · 16-bit LE.
    Uses only Python stdlib (wave + audioop) — no external tools.
    Handles any combination of sample rate, bit depth, and channels.
    """
    with wave.open(wav_path, "rb") as wf:
        n_ch   = wf.getnchannels()
        width  = wf.getsampwidth()
        rate   = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    # ── Normalise bit depth to 16-bit signed ──────────────────────────────
    if width == 1:
        frames = audioop.bias(frames, 1, -128)   # unsigned 8-bit → signed
        frames = audioop.lin2lin(frames, 1, 2)
        width  = 2
    elif width == 3:
        frames = audioop.lin2lin(frames, 3, 2); width = 2
    elif width == 4:
        frames = audioop.lin2lin(frames, 4, 2); width = 2
    # width == 2 → already good

    # ── Stereo / multi-channel → mono ─────────────────────────────────────
    if n_ch == 2:
        frames = audioop.tomono(frames, width, 0.5, 0.5)
    elif n_ch > 2:
        # Extract only channel 0
        step   = width * n_ch
        frames = bytes(b for i in range(0, len(frames), step)
                         for b in frames[i: i + width])

    # ── Resample to 8 000 Hz ──────────────────────────────────────────────
    if rate != _TALK_RATE:
        frames, _ = audioop.ratecv(frames, width, 1, rate, _TALK_RATE, None)

    return frames


def _generate_tone_pcm(freq: float, duration: float,
                       amplitude: float = 0.7) -> bytes:
    """
    Generate a pure sine-wave tone as raw PCM bytes (8 kHz, 16-bit, mono).
    No external tools — pure Python math.
    """
    n       = int(_TALK_RATE * duration)
    buf     = bytearray(n * _TALK_WIDTH)
    twopi_f = 2.0 * math.pi * freq / _TALK_RATE
    for i in range(n):
        val = int(amplitude * 32767 * math.sin(twopi_f * i))
        struct.pack_into("<h", buf, i * 2, max(-32768, min(32767, val)))
    return bytes(buf)


def _ffmpeg_available() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"],
                              capture_output=True, timeout=5).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _convert_with_ffmpeg(src: str) -> str:
    """Convert any audio file to 8 kHz mono 16-bit WAV via ffmpeg."""
    if not _ffmpeg_available():
        raise ReolinkAudioError(
            "ffmpeg not found in PATH – required for MP3/AAC/M4A/OGG/FLAC.\n"
            "  Ubuntu/Debian : sudo apt install ffmpeg\n"
            "  macOS         : brew install ffmpeg\n"
            "  Windows       : https://ffmpeg.org/download.html\n"
            "WAV files work without ffmpeg."
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = ["ffmpeg", "-y", "-i", src,
           "-ar", str(_TALK_RATE), "-ac", "1", "-sample_fmt", "s16",
           "-f", "wav", tmp.name]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        os.unlink(tmp.name)
        raise ReolinkAudioError(
            f"ffmpeg conversion failed:\n{r.stderr.decode(errors='replace')[-400:]}")
    return tmp.name


# Extensions that cannot be read by stdlib wave and need ffmpeg first
_NEEDS_FFMPEG = {".mp3", ".aac", ".m4a", ".wma", ".opus",
                 ".amr", ".flac", ".ogg", ".mp4", ".mov"}


def _load_pcm(file_path: str) -> bytes:
    """
    Load an audio file → raw PCM (8 kHz, mono, 16-bit LE).

    .wav          → pure stdlib, no extra tools needed.
    everything else → ffmpeg conversion first (must be in PATH).
    """
    ext = Path(file_path).suffix.lower()
    if ext in _NEEDS_FFMPEG:
        tmp = _convert_with_ffmpeg(file_path)
        try:
            return _wav_to_pcm8k(tmp)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    elif ext == ".wav":
        return _wav_to_pcm8k(file_path)
    else:
        raise ReolinkAudioError(
            f"Unsupported audio format '{ext}'.\n"
            f"Native (no tools): .wav\n"
            f"Via ffmpeg: {', '.join(sorted(_NEEDS_FFMPEG))}"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP talkback session  (StartTalk → stream PCM → StopTalk)
# ══════════════════════════════════════════════════════════════════════════════

class _TalkSession:
    """
    Streams PCM audio to the camera speaker via HTTP talkback.

    Protocol:
        POST /api.cgi?cmd=StartTalk&token=...
            Content-Type: application/octet-stream
            Body: raw PCM chunks streamed at real-time rate (8 kHz, 16-bit, mono)

        POST /api.cgi?cmd=StopTalk&token=...   ← always called, even on error

    The StartTalk POST holds the TCP connection open while we feed PCM data
    through a generator.  A background thread runs the blocking POST while
    the main thread waits for completion.
    """

    def __init__(self, base_url: str, token: str):
        self._base  = base_url
        self._token = token
        self._pcm:  Optional[bytes] = None
        self._stop  = threading.Event()
        self._done  = threading.Event()
        self._error: Optional[Exception] = None

    # ── chunked body generator ─────────────────────────────────────────

    def _body(self) -> Iterator[bytes]:
        """Yield 20 ms PCM chunks at real-time speed."""
        if not self._pcm:
            return
        for offset in range(0, len(self._pcm), _CHUNK_BYTES):
            if self._stop.is_set():
                break
            yield self._pcm[offset: offset + _CHUNK_BYTES]
            time.sleep(_CHUNK_MS / 1000.0)   # pace to real-time

    # ── background streaming thread ────────────────────────────────────

    def _stream_thread(self):
        url = f"{self._base}?cmd=StartTalk&token={self._token}"
        try:
            requests.post(
                url,
                data    = self._body(),
                headers = {"Content-Type": "application/octet-stream"},
                verify  = False,
                # timeout > audio duration + safety margin
                timeout = (len(self._pcm) / (_TALK_RATE * _TALK_WIDTH)) + 10,
            )
        except Exception as exc:
            self._error = exc
        finally:
            self._done.set()

    # ── public ─────────────────────────────────────────────────────────

    def send(self, pcm: bytes) -> bool:
        """
        Stream *pcm* to the camera speaker.
        Blocks until the audio has been fully sent, then sends StopTalk.
        Returns True on success, raises ReolinkAudioError on hard failures.
        """
        self._pcm = pcm
        self._stop.clear()
        self._done.clear()
        self._error = None

        t = threading.Thread(target=self._stream_thread, daemon=True)
        t.start()

        # Wait for the stream to complete
        duration_s = len(pcm) / (_TALK_RATE * _TALK_WIDTH)
        t.join(timeout=duration_s + 15)

        # Always call StopTalk
        self._stop_talk()

        if self._error:
            # The camera often resets the connection when it's done receiving —
            # that's normal, not an error.
            msg = str(self._error).lower()
            if any(k in msg for k in ("connection", "reset", "closed",
                                      "eof", "broken pipe", "timeout")):
                return True
            raise ReolinkAudioError(f"StartTalk stream error: {self._error}")

        return True

    def _stop_talk(self):
        self._stop.set()
        try:
            requests.post(
                f"{self._base}?cmd=StopTalk&token={self._token}",
                json    = [{"cmd": "StopTalk", "action": 0, "param": {}}],
                verify  = False,
                timeout = 5,
            )
        except Exception:
            pass   # best-effort cleanup


# ══════════════════════════════════════════════════════════════════════════════
#  Low-level HTTP client
# ══════════════════════════════════════════════════════════════════════════════

class _ReolinkHTTP:
    """Handles authentication, retries, and raw API calls."""

    _THROTTLE   = 0.25   # s between requests (prevents camera overload)
    _SET_SETTLE = 1.5    # s after a Set command (let camera apply the change)

    def __init__(self, host: str, username: str, password: str,
                 port: int = 443, scheme: str = "https", timeout: int = 15):
        self.host     = host
        self.username = username
        self.password = password
        self.port     = port
        self.scheme   = scheme
        self.timeout  = timeout
        self._base    = f"{scheme}://{host}:{port}/api.cgi"
        self._token   = ""

    # ── Auth ──────────────────────────────────────────────────────────────

    def login(self) -> str:
        body = [{"cmd": "Login", "action": 0, "param": {
            "User": {"userName": self.username, "password": self.password}
        }}]
        for attempt in range(4):
            try:
                r = requests.post(f"{self._base}?cmd=Login",
                                  json=body, verify=False, timeout=self.timeout)
                if not r.text.strip():
                    time.sleep(5 * (attempt + 1)); continue
                data  = r.json()
                first = data[0] if isinstance(data, list) and data else {}
                token = first.get("value", {}).get("Token", {}).get("name", "")
                if token:
                    self._token = token; return token
                raise ReolinkAuthError(f"Login failed: {json.dumps(data)}")
            except ReolinkAuthError:
                raise
            except Exception as exc:
                if attempt == 3:
                    raise ReolinkConnectionError(f"Login error: {exc}") from exc
                time.sleep(5 * (attempt + 1))
        raise ReolinkAuthError("Login failed after 4 attempts")

    def logout(self):
        if not self._token: return
        try:
            requests.post(
                f"{self._base}?cmd=Logout&token={self._token}",
                json=[{"cmd": "Logout", "action": 0, "param": {}}],
                verify=False, timeout=5,
            )
        except Exception: pass
        self._token = ""

    def _refresh(self):
        self.logout(); time.sleep(3); self.login()

    # ── API call ──────────────────────────────────────────────────────────

    def call(self, cmd: str, param: Optional[dict] = None,
             action: int = 0, _retry: int = 0) -> dict:
        """Call the camera API. Returns the full response dict."""
        time.sleep(self._THROTTLE)
        body = [{"cmd": cmd, "action": action, "param": param or {}}]
        url  = f"{self._base}?cmd={cmd}&token={self._token}"
        try:
            r = requests.post(url, json=body, verify=False, timeout=self.timeout)
        except requests.RequestException as exc:
            if _retry < 2:
                self._refresh(); return self.call(cmd, param, action, _retry + 1)
            raise ReolinkConnectionError(str(exc)) from exc

        if not r.text.strip():
            if _retry == 0: time.sleep(3); return self.call(cmd, param, action, 1)
            if _retry == 1: self._refresh(); return self.call(cmd, param, action, 2)
            raise ReolinkCommandError(f"{cmd}: empty response")

        data = r.json()
        resp = data[0] if isinstance(data, list) and data else data

        if resp.get("code", -1) != 0:
            err = resp.get("error", {})
            if isinstance(err, dict):
                if err.get("rspCode") == -6 or "login" in str(err).lower():
                    if _retry < 2:
                        self._refresh(); return self.call(cmd, param, action, _retry + 1)
            raise ReolinkCommandError(f"{cmd} failed: {err or resp}")

        return resp

    def get(self, cmd: str, param: Optional[dict] = None) -> dict:
        return self.call(cmd, param, action=0)

    def set(self, cmd: str, param: dict, settle: bool = True) -> dict:
        resp = self.call(cmd, param, action=0)
        if settle: time.sleep(self._SET_SETTLE)
        return resp

    def value(self, resp: dict, key: str) -> Any:
        return resp.get("value", {}).get(key)


# ══════════════════════════════════════════════════════════════════════════════
#  Main camera class
# ══════════════════════════════════════════════════════════════════════════════

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
        self._http   = _ReolinkHTTP(host, username, password, port, scheme)

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
               f"/cgi-bin/api.cgi?cmd=Snap&channel={ch}&token={self._http._token}")
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
        pcm = _load_pcm(str(file_path))
        return _TalkSession(self._http._base, self._http._token).send(pcm)

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
        pcm = _generate_tone_pcm(freq, duration, amplitude)
        return _TalkSession(self._http._base, self._http._token).send(pcm)

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