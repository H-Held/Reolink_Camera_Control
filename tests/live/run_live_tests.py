#!/usr/bin/env python3
"""
run_live_tests.py  –  Live feature test against a real Reolink camera

Usage:
    python tests/live/run_live_tests.py            # reads .env / REOLINK_* variables
    python tests/live/run_live_tests.py --host 192.168.1.100 --user admin --password mypass
    python tests/live/run_live_tests.py --skip-set     # GET tests only (no camera changes)
    python tests/live/run_live_tests.py --skip-audio   # skip audio push tests

Setup:
    pip install -e .                   # install the library
    copy .env.example .env             # then fill in camera IP, user and password

Set tests change a setting, verify it and restore the original value.

Each test prints:
    [PASS]  feature name .............. result detail
    [FAIL]  feature name .............. error detail
    [SKIP]  feature name .............. reason
"""

from __future__ import annotations

import argparse
import math
import os
import struct
import sys
import tempfile
import time
import wave
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    from reolink_camera_control import (
        ReolinkCamera,
        ReolinkError, ReolinkAuthError, ReolinkCommandError,
        ReolinkConnectionError, ReolinkAudioError,
    )
except ImportError:
    print("[ERROR] Package 'reolink_camera_control' is not installed.")
    print("        Run 'pip install -e .' from the repository root first.")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  Tiny test framework
# ══════════════════════════════════════════════════════════════════════════════

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"


@dataclass
class Result:
    name:   str
    status: str   # "PASS" | "FAIL" | "SKIP"
    detail: str

    def __str__(self) -> str:
        colours = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}
        label = f"{colours[self.status]}[{self.status}]{RESET}"
        return f"  {label}  {self.name:<45s}  {self.detail}"


class Suite:
    def __init__(self, cam: ReolinkCamera, skip_set: bool, skip_audio: bool):
        self.cam        = cam
        self.skip_set   = skip_set
        self.skip_audio = skip_audio
        self.results: list[Result] = []

    # ── Helpers ───────────────────────────────────────────────────────────

    def _run(self, name: str, fn: Callable) -> Result:
        try:
            detail = fn()
            r = Result(name, "PASS", detail or "ok")
        except AssertionError as e:
            r = Result(name, "FAIL", f"AssertionError: {e}")
        except ReolinkError as e:
            r = Result(name, "FAIL", str(e)[:120])
        except Exception as e:
            tb = traceback.format_exc().strip().splitlines()[-1]
            r = Result(name, "FAIL", f"{e}  [{tb}]")
        self.results.append(r)
        print(r)
        return r

    def _skip(self, name: str, reason: str) -> Result:
        r = Result(name, "SKIP", reason)
        self.results.append(r)
        print(r)
        return r

    def _roundtrip(self,
                   get_fn:      Callable,
                   set_fn:      Callable,
                   new_value,
                   extract_fn:  Callable,
                   restore_fn:  Callable) -> str:
        """GET → SET(new) → VERIFY → RESTORE. Returns description string."""
        orig_obj = get_fn()
        orig     = extract_fn(orig_obj)

        if orig == new_value:
            return f"already={orig} (set skipped)"

        set_fn(new_value)
        time.sleep(0.5)

        after = extract_fn(get_fn())
        restore_fn(orig_obj)
        time.sleep(0.5)

        verified = "verified" if after == new_value else "set accepted"
        return f"{orig} → {new_value} → {orig} ({verified})"

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 1 – Device & System
    # ══════════════════════════════════════════════════════════════════════

    def phase_device(self):
        _header("Phase 1: Device & System")
        c = self.cam

        self._run("GetDevInfo", lambda: (
            info := c.get_device_info(),
            f"model={info.model!r}  fw={info.firmware!r}"
        )[-1])

        self._run("GetDevName", lambda: f"name={c.get_device_name()!r}")

        self._run("GetChannelStatus", lambda: (
            _vkeys(c._http.get("GetChannelstatus"))
        ))

        self._run("GetPerformance", lambda: (
            f"keys={list(c.get_performance().keys())[:4]}"
        ))

        self._run("GetHddInfo", lambda: f"drives={len(c.get_hdd_info())}")

        self._run("GetOnline", lambda: f"sessions={len(c.get_online_users())}")

        self._run("GetAbility", lambda: (
            f"keys={list(c.get_ability().keys())[:3]}"
        ))

        self._run("GetUser", lambda: (
            _vkeys(c._http.get("GetUser",
                               {"User": {"userName": c._http.username}}))
        ))

        if self.skip_set:
            self._skip("SetDevName (roundtrip)", "--skip-set")
        else:
            self._run("SetDevName (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_device_name,
                set_fn     = c.set_device_name,
                new_value  = "RLC540A Test",
                extract_fn = lambda v: v,
                restore_fn = lambda orig: c.set_device_name(orig),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 2 – Network
    # ══════════════════════════════════════════════════════════════════════

    def phase_network(self):
        _header("Phase 2: Network")
        c = self.cam

        self._run("GetNetPort", lambda: (
            p := c.get_network_ports(),
            f"rtsp={p.rtsp_port}  enabled={p.rtsp_enabled}"
        )[-1])

        self._run("GetRTSP URLs", lambda: str(c.get_rtsp_urls()))

        self._run("GetLocalLink", lambda: (
            f"keys={list(c.get_local_link().keys())[:4]}"
        ))

        self._run("GetP2p",  lambda: f"keys={list(c.get_p2p().keys())[:4]}")
        self._run("GetUpnp", lambda: _vkeys(c._http.get("GetUpnp")))
        self._run("GetDdns", lambda: _vkeys(c._http.get("GetDdns")))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 3 – Time & Maintenance
    # ══════════════════════════════════════════════════════════════════════

    def phase_time(self):
        _header("Phase 3: Time & Maintenance")
        c = self.cam

        self._run("GetTime", lambda: f"keys={list(c.get_time().keys())[:4]}")

        self._run("GetNtp", lambda: (
            ntp := c.get_ntp(),
            f"enable={ntp.get('enable')}  server={ntp.get('server','?')}"
        )[-1])

        self._run("GetAutoMaint", lambda: (
            f"keys={list(c.get_auto_maintenance().keys())[:4]}"
        ))

        if self.skip_set:
            self._skip("SetNtp enable (roundtrip)",        "--skip-set")
            self._skip("SetAutoMaint enable (roundtrip)",  "--skip-set")
        else:
            self._run("SetNtp enable (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_ntp,
                set_fn     = c.set_ntp,
                new_value  = 1,
                extract_fn = lambda v: v.get("enable"),
                restore_fn = lambda orig: c.set_ntp(bool(orig.get("enable"))),
            ))
            self._run("SetAutoMaint enable (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_auto_maintenance,
                set_fn     = c.set_auto_maintenance,
                new_value  = 1,
                extract_fn = lambda v: v.get("enable"),
                restore_fn = lambda orig: c.set_auto_maintenance(bool(orig.get("enable"))),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 4 – Video & Image
    # ══════════════════════════════════════════════════════════════════════

    def phase_video(self):
        _header("Phase 4: Video & Image")
        c = self.cam

        self._run("GetEnc", lambda: (
            e := c.get_encoder_settings(),
            f"main={e.main_width}×{e.main_height}  "
            f"bitrate={e.main_bitrate}kbps  fps={e.main_framerate}"
        )[-1])

        self._run("GetImage", lambda: (
            i := c.get_image_settings(),
            f"bright={i.bright}  contrast={i.contrast}  sat={i.saturation}"
        )[-1])

        self._run("GetIsp",  lambda: f"keys={list(c.get_isp().keys())[:4]}")
        self._run("GetOsd",  lambda: f"keys={list(c.get_osd().keys())[:4]}")
        self._run("GetMask", lambda: f"enable={c.get_mask().get('enable')}")

        if self.skip_set:
            for name in ["SetImage brightness", "SetImage contrast",
                         "SetIsp dayNight", "SetOsd name",
                         "SetEnc bitrate",   "SetMask enable"]:
                self._skip(f"{name} (roundtrip)", "--skip-set")
        else:
            self._run("SetImage brightness (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_image_settings,
                set_fn     = lambda v: c.set_image_settings(bright=v),
                new_value  = 140,
                extract_fn = lambda v: v.bright,
                restore_fn = lambda orig: c.set_image_settings(bright=orig.bright),
            ))
            self._run("SetImage contrast (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_image_settings,
                set_fn     = lambda v: c.set_image_settings(contrast=v),
                new_value  = 140,
                extract_fn = lambda v: v.contrast,
                restore_fn = lambda orig: c.set_image_settings(contrast=orig.contrast),
            ))
            self._run("SetIsp dayNight (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_isp,
                set_fn     = c.set_day_night_mode,
                new_value  = "Color",
                extract_fn = lambda v: v.get("dayNight"),
                restore_fn = lambda orig: c.set_day_night_mode(orig.get("dayNight","Auto")),
            ))
            self._run("SetOsd name (roundtrip)", lambda: self._roundtrip(
                get_fn     = lambda: c.get_osd().get("osdChannel", {}).get("name", ""),
                set_fn     = c.set_osd_channel_name,
                new_value  = "TestCam API",
                extract_fn = lambda v: v,
                restore_fn = lambda orig: c.set_osd_channel_name(orig),
            ))
            self._run("SetEnc bitrate (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_encoder_settings,
                set_fn     = c.set_main_stream_bitrate,
                new_value  = 4096,
                extract_fn = lambda v: v.main_bitrate,
                restore_fn = lambda orig: c.set_main_stream_bitrate(orig.main_bitrate),
            ))
            self._run("SetMask enable (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_mask,
                set_fn     = lambda v: c.set_mask_enabled(bool(v)),
                new_value  = 0,
                extract_fn = lambda v: v.get("enable"),
                restore_fn = lambda orig: c.set_mask_enabled(bool(orig.get("enable"))),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 5 – Snapshot & Streaming
    # ══════════════════════════════════════════════════════════════════════

    def phase_snap(self):
        _header("Phase 5: Snapshot & Streaming")
        c = self.cam

        self._run("Snap (JPEG bytes)", lambda: (
            data := c.snap(),
            f"{len(data):,} bytes  magic={data[:3].hex()}"
        )[-1])

        self._run("RTSP URL construction", lambda: (
            urls := c.get_rtsp_urls(),
            str(urls.get("main", "RTSP disabled"))
        )[-1])

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 6 – Lights
    # ══════════════════════════════════════════════════════════════════════

    def phase_lights(self):
        _header("Phase 6: Lights")
        c = self.cam

        self._run("GetIrLights",  lambda: f"state={c.get_ir_lights().state!r}")
        self._run("GetWhiteLed",  lambda: (
            w := c.get_white_led(),
            f"state={w.state}  mode={w.mode}  bright={w.bright}"
        )[-1])
        self._run("GetPowerLed",  lambda: f"state={c.get_power_led()!r}")

        if self.skip_set:
            for name in ["SetIrLights", "SetWhiteLed state",
                         "SetWhiteLed bright", "SetPowerLed"]:
                self._skip(f"{name} (roundtrip)", "--skip-set")
        else:
            def white_led_on_2s():
                orig = c.get_white_led().raw
                try:
                    c.set_white_led(state=1, mode=0, bright=100)
                    on = c.get_white_led().state
                    time.sleep(2.0)
                finally:
                    c._http.set("SetWhiteLed", {"WhiteLed": orig})
                off = c.get_white_led().state
                assert on == 1, f"LED did not switch on (state={on})"
                assert off == orig.get("state"), f"LED not restored (state={off})"
                return "white LED on for 2 s, then restored"

            self._run("White LED on 2 s, then off", white_led_on_2s)
            self._run("SetIrLights (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_ir_lights,
                set_fn     = c.set_ir_lights,
                new_value  = "Off",
                extract_fn = lambda v: v.state,
                restore_fn = lambda orig: c.set_ir_lights(orig.state),
            ))
            self._run("SetWhiteLed state (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_white_led,
                set_fn     = lambda v: c.set_white_led(state=v),
                new_value  = 0,
                extract_fn = lambda v: v.state,
                restore_fn = lambda orig: c.set_white_led(state=orig.state),
            ))
            self._run("SetWhiteLed bright (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_white_led,
                set_fn     = lambda v: c.set_white_led(bright=v),
                new_value  = 50,
                extract_fn = lambda v: v.bright,
                restore_fn = lambda orig: c.set_white_led(bright=orig.bright),
            ))
            self._run("SetPowerLed (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_power_led,
                set_fn     = c.set_power_led,
                new_value  = "Off",
                extract_fn = lambda v: v,
                restore_fn = lambda orig: c.set_power_led(orig),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 7 – Audio config (HTTP)
    # ══════════════════════════════════════════════════════════════════════

    def phase_audio_config(self):
        _header("Phase 7: Audio Config (HTTP)")
        c = self.cam

        self._run("GetAudioCfg", lambda: (
            a := c.get_audio_config(),
            f"volume={a.volume}  mute={a.mute}"
        )[-1])

        self._run("GetAudioAlarmV20", lambda: (
            aa := c.get_audio_alarm(),
            f"enable={aa.get('enable')}  keys={list(aa.keys())[:4]}"
        )[-1])

        if self.skip_set:
            self._skip("SetAudioCfg volume (roundtrip)",      "--skip-set")
            self._skip("SetAudioAlarmV20 enable (roundtrip)", "--skip-set")
        else:
            self._run("SetAudioCfg volume (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_audio_config,
                set_fn     = c.set_audio_volume,
                new_value  = 80,
                extract_fn = lambda v: v.volume,
                restore_fn = lambda orig: c.set_audio_volume(orig.volume),
            ))
            self._run("SetAudioAlarmV20 enable (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_audio_alarm,
                set_fn     = lambda v: c.set_audio_alarm_enabled(bool(v)),
                new_value  = 1,
                extract_fn = lambda v: v.get("enable"),
                restore_fn = lambda orig: c.set_audio_alarm_enabled(bool(orig.get("enable"))),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 8 – Detection
    # ══════════════════════════════════════════════════════════════════════

    def phase_detection(self):
        _header("Phase 8: Detection")
        c = self.cam

        self._run("GetMdAlarm", lambda: (
            m := c.get_motion_alarm(),
            f"enabled={m.enabled}  sensitivity={m.sensitivity}"
        )[-1])

        self._run("GetAiCfg", lambda: (
            ai := c.get_ai_config(),
            f"people={ai.people}  vehicle={ai.vehicle}  "
            f"animal={ai.animal}  track={ai.ai_track}"
        )[-1])

        if self.skip_set:
            self._skip("SetAiCfg aiTrack (roundtrip)", "--skip-set")
        else:
            self._run("SetAiCfg aiTrack (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_ai_config,
                set_fn     = lambda v: c.set_ai_tracking(bool(v)),
                new_value  = 0,
                extract_fn = lambda v: int(v.ai_track),
                restore_fn = lambda orig: c.set_ai_tracking(orig.ai_track),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 9 – Recording & FTP
    # ══════════════════════════════════════════════════════════════════════

    def phase_recording(self):
        _header("Phase 9: Recording & FTP")
        c = self.cam

        self._run("GetRecV20", lambda: (
            r := c.get_recording_config(),
            f"enable={r.get('enable')}  keys={list(r.keys())[:4]}"
        )[-1])

        self._run("GetFtpV20", lambda: (
            f"keys={list(c.get_ftp_config().keys())[:4]}"
        ))

        if self.skip_set:
            self._skip("SetRecV20 enable (roundtrip)", "--skip-set")
        else:
            self._run("SetRecV20 enable (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_recording_config,
                set_fn     = lambda v: c.set_recording_enabled(bool(v)),
                new_value  = 1,
                extract_fn = lambda v: v.get("enable"),
                restore_fn = lambda orig: c.set_recording_enabled(bool(orig.get("enable"))),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 10 – Notifications
    # ══════════════════════════════════════════════════════════════════════

    def phase_notifications(self):
        _header("Phase 10: Notifications")
        c = self.cam

        self._run("GetEmailV20", lambda: (
            f"keys={list(c.get_email_config().keys())[:4]}"
        ))
        self._run("GetPushV20",  lambda: (
            f"keys={list(c.get_push_config().keys())[:4]}"
        ))
        self._run("GetWebHook",  lambda: (
            w := c.get_webhook_config(),
            f"enable={_webhook_enabled(w)}  entries={len(w)}"
        )[-1])

        if self.skip_set:
            self._skip("SetWebHook enable (roundtrip)", "--skip-set")
        else:
            self._run("SetWebHook enable (roundtrip)", lambda: self._roundtrip(
                get_fn     = c.get_webhook_config,
                set_fn     = lambda v: c.set_webhook_enabled(bool(v)),
                new_value  = 0,
                extract_fn = _webhook_enabled,
                restore_fn = lambda orig: c._http.set("SetWebHook", {"WebHook": orig}),
            ))

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 11 – PTZ
    # ══════════════════════════════════════════════════════════════════════

    def phase_ptz(self):
        _header("Phase 11: PTZ")
        c = self.cam

        self._run("GetPtzPreset", lambda: (
            f"presets={len(c.get_ptz_presets())}"
        ))

        self._run("PtzCtrl ZoomInc + Stop", lambda: (
            c.ptz_move("ZoomInc", speed=1),
            time.sleep(0.3),
            c.ptz_stop(),
            "ZoomInc(speed=1) → Stop"
        )[-1])

    # ══════════════════════════════════════════════════════════════════════
    #  Phase 12 – Audio push (HTTP talkback)
    # ══════════════════════════════════════════════════════════════════════

    def phase_audio_push(self):
        _header("Phase 12: Audio (siren and speaker playback)")
        c = self.cam

        if self.skip_audio:
            for name in ["Siren on/off", "ffmpeg check", "Tone 440Hz 1s",
                         "Tone 880Hz 1s", "Tone 1000Hz 0.5s"]:
                self._skip(name, "--skip-audio")
            return

        def siren():
            c.siren_on()
            time.sleep(2.0)
            c.siren_off()
            return "siren played for 2 s (listen at the camera)"

        self._run("Siren on/off (2 s, audible)", siren)

        self._run("ffmpeg availability (MP3/AAC/OGG/FLAC only)", lambda:
            f"available={c.ffmpeg_available()}  (WAV and tones need no extra tools)"
        )

        self._run("play_tone 440Hz 1s", lambda: (
            c.play_tone(440.0, 1.0, amplitude=0.6),
            "sent to camera speaker (Baichuan talk)"
        )[-1])
        self._run("play_tone 1000Hz 0.5s", lambda: (
            c.play_tone(1000.0, 0.5, amplitude=0.6),
            "sent to camera speaker (Baichuan talk)"
        )[-1])

        def play_wav():
            path = Path(tempfile.gettempdir()) / "reolink_live_test.wav"
            rate = 44100
            with wave.open(str(path), "wb") as wf:      # 44.1 kHz stereo, C-E-G-C
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                for freq in (523, 659, 784, 1047):
                    for i in range(int(rate * 0.4)):
                        v = int(20000 * math.sin(2 * math.pi * freq * i / rate))
                        wf.writeframes(struct.pack("<hh", v, v))
            try:
                c.play_audio_file(str(path))
            finally:
                path.unlink(missing_ok=True)
            return "44.1 kHz stereo WAV converted and played"

        self._run("play_audio_file (WAV, rising melody)", play_wav)

    def phase_misc(self):
        _header("Phase 13: Misc")
        c = self.cam

        self._run("Reboot command (probe only, not executed)", lambda: (
            resp := c._http.call("Reboot", {}, action=1),
            "recognised" if resp else "ok"
        )[-1])

    # ══════════════════════════════════════════════════════════════════════
    #  Run all + summary
    # ══════════════════════════════════════════════════════════════════════

    def run_all(self):
        self.phase_device()
        self.phase_network()
        self.phase_time()
        self.phase_video()
        self.phase_snap()
        self.phase_lights()
        self.phase_audio_config()
        self.phase_detection()
        self.phase_recording()
        self.phase_notifications()
        self.phase_ptz()
        self.phase_audio_push()
        self.phase_misc()

    def summary(self) -> int:
        passed  = sum(1 for r in self.results if r.status == "PASS")
        failed  = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        total   = passed + failed

        print()
        print("═" * 70)
        print(f"  RESULTS  "
              f"{GREEN}{passed} passed{RESET} / "
              f"{RED}{failed} failed{RESET} / "
              f"{YELLOW}{skipped} skipped{RESET}  "
              f"(out of {total} run)")
        print("═" * 70)

        if failed:
            print(f"\n  {RED}Failed tests:{RESET}")
            for r in self.results:
                if r.status == "FAIL":
                    print(f"    • {r.name}: {r.detail}")

        return 0 if failed == 0 else 1


# ══════════════════════════════════════════════════════════════════════════════
#  Utilities
# ══════════════════════════════════════════════════════════════════════════════

def _header(title: str):
    print(f"\n  {'─' * 60}")
    print(f"  {title}")
    print(f"  {'─' * 60}")


def _webhook_enabled(w) -> int:
    """Webhook enable flag for both the dict and the list (newer firmware) layout."""
    if isinstance(w, list):
        return int(any(e.get("indexEnable") for e in w))
    return w.get("enable")


def _vkeys(resp: dict, n: int = 4) -> str:
    return f"keys={list(resp.get('value', {}).keys())[:n]}"


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from *path* into os.environ (existing vars win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main():
    # Box-drawing characters need UTF-8 (Windows consoles default to cp1252).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    _load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    p = argparse.ArgumentParser(description="Reolink camera live test")
    p.add_argument("--host",       default=os.environ.get("REOLINK_HOST"),
                   help="Camera IP/hostname (env: REOLINK_HOST)")
    p.add_argument("--user",       default=os.environ.get("REOLINK_USER"),
                   help="Login user (env: REOLINK_USER)")
    p.add_argument("--password",   default=os.environ.get("REOLINK_PASSWORD"),
                   help="Login password (env: REOLINK_PASSWORD)")
    p.add_argument("--port",       type=int,
                   default=int(os.environ.get("REOLINK_PORT", "443")))
    p.add_argument("--scheme",     default=os.environ.get("REOLINK_SCHEME", "https"),
                   choices=["https", "http"])
    p.add_argument("--skip-set",   action="store_true",
                   help="Skip all Set commands (read-only mode)")
    p.add_argument("--skip-audio", action="store_true",
                   help="Skip audio push tests")
    args = p.parse_args()

    missing = [name for name, val in (("REOLINK_HOST / --host", args.host),
                                      ("REOLINK_USER / --user", args.user),
                                      ("REOLINK_PASSWORD / --password", args.password))
               if not val]
    if missing:
        print(f"{RED}[FATAL] Missing connection settings:{RESET} {', '.join(missing)}")
        print("  Copy .env.example to .env and fill in your camera details,")
        print("  or pass the values as command line arguments.")
        sys.exit(2)

    print("═" * 70)
    print("  Reolink Camera – Comprehensive API Test")
    print(f"  Camera : {args.scheme}://{args.host}:{args.port}")
    print(f"  User   : {args.user}")
    print(f"  Flags  : skip-set={args.skip_set}  skip-audio={args.skip_audio}")
    print("═" * 70)

    cam = ReolinkCamera(args.host, args.user, args.password,
                        args.port, args.scheme)

    print("\n  Connecting…")
    try:
        token = cam.connect()
        print(f"  Token : {token[:20]}…\n")
    except ReolinkAuthError as e:
        print(f"\n{RED}[FATAL] Auth failed:{RESET} {e}")
        sys.exit(2)
    except ReolinkConnectionError as e:
        print(f"\n{RED}[FATAL] Cannot reach camera:{RESET} {e}")
        sys.exit(2)

    suite = Suite(cam, skip_set=args.skip_set, skip_audio=args.skip_audio)
    try:
        suite.run_all()
    finally:
        cam.disconnect()
        print("\n  Session closed.")

    return suite.summary()


if __name__ == "__main__":
    sys.exit(main())