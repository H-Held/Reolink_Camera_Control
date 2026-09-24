# Reolink Camera Control

A small Python library to control Reolink cameras through their local HTTP API.
It covers device information, network and time settings, image and video
configuration, snapshots, lights, audio (including playing sound through the
camera speaker), detection, recording, notifications and PTZ.

## Tested hardware

| Item | Value |
|------|-------|
| Camera | Reolink RLC-540A |
| Firmware | v3.0.0.4348_2411261180 |

Other Reolink cameras that use the same `api.cgi` interface will likely work,
but only the model above has been verified. Features that a model does not
support (for example PTZ on a fixed camera) raise `ReolinkCommandError` or
return empty results.

## Requirements

- Python 3.9 or newer (tested on 3.14)
- `requests` (installed automatically)
- Optional: `ffmpeg` in `PATH` to play MP3, AAC, M4A, OGG or FLAC files.
  WAV files and generated tones need no extra tools.

## Installation

```bash
git clone https://github.com/<your-user>/Reolink_Camera_Control.git
cd Reolink_Camera_Control
pip install -e .          # library only
pip install -e ".[dev]"   # library plus pytest
```

## Quick start

```python
from reolink_camera_control import ReolinkCamera

with ReolinkCamera("192.168.1.100", "admin", "password") as cam:
    info = cam.get_device_info()
    print(info.model, info.firmware)

    cam.set_ir_lights("Auto")
    cam.snap_to_file("snapshot.jpg")
    cam.play_tone(440, duration=2)
```

`ReolinkCamera` is a context manager: it logs in on entry and logs out on
exit. Without `with`, call `cam.connect()` and `cam.disconnect()` yourself.

### Constructor

```python
ReolinkCamera(host, username="admin", password="", port=443,
              scheme="https", channel=0)
```

| Parameter | Description |
|-----------|-------------|
| `host` | Camera IP address or hostname |
| `username`, `password` | Camera login |
| `port` | API port. 443 for HTTPS (default), 80 for HTTP |
| `scheme` | `"https"` (default) or `"http"`. Self-signed certificates are accepted |
| `channel` | Default channel used when a method is called without `channel` |

Most methods accept an optional `channel` argument that overrides the default.

## Function reference

Methods named `get_*` only read from the camera. Methods named `set_*` read the
current configuration first and write it back with only your change applied,
so other settings stay untouched. Every `set_*` call waits about 1.5 seconds
for the camera to apply the change.

### Connection

| Method | Description |
|--------|-------------|
| `connect()` | Log in and return the session token |
| `disconnect()` | Log out |

### Device and system

| Method | Returns / effect |
|--------|------------------|
| `get_device_info()` | `DeviceInfo` with name, model, serial, firmware, hardware, build_day |
| `get_device_name()` / `set_device_name(name)` | Display name |
| `get_performance()` | CPU and memory statistics (dict) |
| `get_hdd_info()` | List of storage devices |
| `get_online_users()` | Currently logged-in sessions |
| `get_ability()` | Capability map of the camera |
| `reboot()` | Reboots the camera; it is back after about 30 seconds |

### Network

| Method | Returns / effect |
|--------|------------------|
| `get_network_ports()` | `NetworkPorts` (http, https, rtsp, rtmp, onvif, rtsp_enabled) |
| `get_rtsp_urls()` | `{"main": "rtsp://...", "sub": "rtsp://..."}`, or `{}` if RTSP is disabled |
| `get_local_link()`, `get_p2p()`, `get_upnp()`, `get_ddns()` | Raw configuration dicts |

### Time and maintenance

| Method | Returns / effect |
|--------|------------------|
| `get_time()` | Camera time settings |
| `get_ntp()` / `set_ntp(enabled)` | NTP time synchronisation |
| `get_auto_maintenance()` / `set_auto_maintenance(enabled)` | Scheduled automatic reboot |

### Video and image

| Method | Returns / effect |
|--------|------------------|
| `get_encoder_settings(channel=None)` | `EncoderSettings` (resolution, bitrate, frame rate) |
| `set_main_stream_bitrate(bitrate, channel=None)` | Main stream bitrate in kbps |
| `get_image_settings(channel=None)` | `ImageSettings` (bright, contrast, saturation, sharpness, hue) |
| `set_image_settings(channel=None, **kwargs)` | Any of `bright`, `contrast`, `saturation`, `sharpness`, `hue` (0-255) |
| `get_isp(channel=None)` | ISP settings such as day/night mode |
| `set_day_night_mode(mode, channel=None)` | `"Auto"`, `"Color"` or `"Black&White"` |
| `get_osd(channel=None)` / `set_osd_channel_name(name, channel=None)` | On-screen display and channel name |
| `get_mask(channel=None)` / `set_mask_enabled(enabled, channel=None)` | Privacy mask |

```python
cam.set_image_settings(bright=140, contrast=130)
cam.set_day_night_mode("Auto")
```

### Snapshot

| Method | Returns / effect |
|--------|------------------|
| `snap(channel=None)` | JPEG image as `bytes` |
| `snap_to_file(path, channel=None)` | Saves the JPEG and returns the `Path` |

### Lights

| Method | Returns / effect |
|--------|------------------|
| `get_ir_lights(channel=None)` | `IrLightState` |
| `set_ir_lights(state)` | `"Auto"` or `"Off"` |
| `get_white_led(channel=None)` | `WhiteLedState` (state, mode, bright) |
| `set_white_led(state=None, mode=None, bright=None, channel=None)` | `state` 0/1, `mode` 0 = off, 1 = auto, 3 = schedule, `bright` 0-100. Only the given values change |
| `get_power_led(channel=None)` / `set_power_led(state, channel=None)` | Status LED, `"On"` or `"Off"` |

### Audio

| Method | Returns / effect |
|--------|------------------|
| `get_audio_config(channel=None)` | `AudioConfig` (volume, mute) |
| `set_audio_volume(volume, channel=None)` | Speaker volume 0-100 |
| `get_audio_alarm(channel=None)` | Siren-on-event configuration |
| `set_audio_alarm_enabled(enabled, channel=None)` | Enable or disable the event siren |
| `siren_on()` / `siren_off()` | Manual siren (firmware support varies) |
| `play_tone(freq=440.0, duration=3.0, amplitude=0.7, channel=None)` | Plays a sine tone through the camera speaker |
| `play_audio_file(file_path, channel=None)` | Plays an audio file through the camera speaker |
| `ffmpeg_available()` | True if `ffmpeg` was found in `PATH` |

**Compatibility note:** On the tested RLC-540A with firmware
v3.0.0.4348_2411261180 the camera rejects HTTP talkback (`TalkAbility: not
support`), so `play_tone` and `play_audio_file` raise `ReolinkAudioError`
there. The manual siren (`siren_on()` / `siren_off()`) works on that firmware.
Other models or firmware versions may support talkback.

Audio is sent through the camera's HTTP talkback endpoint (`StartTalk` and
`StopTalk`). The camera expects PCM, 8 000 Hz, mono, 16-bit; the library
converts WAV input automatically (any sample rate, channel count, and 8, 16,
24 or 32 bit). Other formats are converted with `ffmpeg` first. Playback runs
in real time, so the call blocks for the length of the audio.

```python
cam.play_audio_file("alert.wav")
```

### Detection

| Method | Returns / effect |
|--------|------------------|
| `get_motion_alarm(channel=None)` | `MotionAlarmConfig` (enabled, sensitivity) |
| `get_ai_config(channel=None)` | `AiConfig` (people, vehicle, animal, face, ai_track) |
| `set_ai_tracking(enabled, channel=None)` | Enable or disable AI auto-tracking |

### Recording and FTP

| Method | Returns / effect |
|--------|------------------|
| `get_recording_config(channel=None)` | Recording configuration |
| `set_recording_enabled(enabled, channel=None)` | Enable or disable recording |
| `get_ftp_config()` | FTP upload configuration |

### Notifications

| Method | Returns / effect |
|--------|------------------|
| `get_email_config(channel=None)` | Email alert configuration |
| `get_push_config(channel=None)` | Push notification configuration |
| `get_webhook_config()` / `set_webhook_enabled(enabled)` | Webhook configuration |

### PTZ

| Method | Returns / effect |
|--------|------------------|
| `get_ptz_presets(channel=None)` | List of presets, empty list if unsupported |
| `ptz_move(operation, speed=20, channel=None)` | `"Up"`, `"Down"`, `"Left"`, `"Right"`, `"ZoomInc"`, `"ZoomDec"` or `"Stop"` |
| `ptz_stop(channel=None)` | Stops any movement |
| `ptz_goto_preset(preset_id, channel=None)` | Moves to a preset position |

## Error handling

All exceptions derive from `ReolinkError`:

| Exception | Raised when |
|-----------|-------------|
| `ReolinkAuthError` | Login failed (wrong user or password) |
| `ReolinkConnectionError` | The camera cannot be reached |
| `ReolinkCommandError` | The camera rejected a command or returned an error |
| `ReolinkAudioError` | Audio file missing, unsupported, or conversion failed |

```python
from reolink_camera_control import ReolinkCamera, ReolinkAuthError, ReolinkConnectionError

try:
    with ReolinkCamera("192.168.1.100", "admin", "wrong") as cam:
        cam.snap_to_file("a.jpg")
except ReolinkAuthError:
    print("Check username and password")
except ReolinkConnectionError:
    print("Camera not reachable")
```

Expired sessions are renewed automatically, and empty or failed requests are
retried a limited number of times.

## Configuration for the live tests

Camera credentials are never stored in the code. Copy the template and edit it:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

```
REOLINK_HOST=192.168.1.100
REOLINK_USER=admin
REOLINK_PASSWORD=change-me
REOLINK_PORT=443
REOLINK_SCHEME=https
```

`.env` is listed in `.gitignore` and must not be committed. Values can also be
given as environment variables or command line arguments.

## Tests

The tests are split into two groups.

### Offline tests (no camera needed)

These use mocked network calls and check that the code runs without errors:
audio conversion, tone generation, login and retry logic, response parsing,
the talkback session and the public API.

```bash
pip install -e ".[dev]"
pytest
```

### Live tests (real camera required)

```bash
python tests/live/run_live_tests.py --skip-set    # read-only, changes nothing
python tests/live/run_live_tests.py               # also runs set/restore checks
python tests/live/run_live_tests.py --skip-audio  # no sound from the speaker
```

Names set by the tests must not contain underscores; the camera rejects them
(`SetDevName` / `SetOsd` fail). Without `--skip-set`, the script temporarily changes settings (device name,
image brightness, LEDs, volume and others), checks the result and restores the
original value. Run the read-only variant first. The audio phase plays short
tones through the camera speaker. The reboot command is only probed, never
executed.

## Project layout

```
reolink_camera_control/
    camera.py       ReolinkCamera, the public API
    http.py         login, token refresh, retries
    audio.py        WAV/tone to PCM conversion, ffmpeg fallback
    talk.py         talkback streaming to the speaker
    models.py       data classes returned by the API
    exceptions.py   exception hierarchy
tests/
    unit/           offline tests
    live/           script for testing against a real camera
```

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). The dependencies (requests: Apache-2.0,
urllib3: MIT, pytest: MIT) are compatible with the GPL-3.0; details are in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

This project is not affiliated with Reolink.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).
