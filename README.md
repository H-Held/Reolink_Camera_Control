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

The firmware was current at the time of testing: the camera reported no newer
version (`CheckFirmware` returned `newFirmware: 0`) on 2026-09-24.

Test results with this camera and firmware:

| Test suite | Result |
|------------|--------|
| Offline tests (`pytest`, no camera) | 65 passed |
| Live tests (`tests/live/run_live_tests.py`, all set/restore checks, LEDs, siren and audio) | 63 passed, 0 failed, 0 skipped |
| Speaker audio | Verified with a microphone: tones at 500 Hz and 1000 Hz and a four-note melody arrived at the expected frequencies |

All features in the function reference were run against this camera and
firmware, including playing sound through the camera speaker (checked with a
microphone). Other Reolink cameras that use the same `api.cgi` interface will
likely work, but only the model above has been verified. Features that a model
does not support (for example PTZ on a fixed camera) raise
`ReolinkCommandError` or return empty results. Some firmware versions return
list-shaped answers for motion detection and webhooks; both layouts are handled.

## Requirements

- Python 3.11 or newer (tested on 3.14)
- `requests` and `reolink-aio` (installed automatically)
- Optional: `ffmpeg` in `PATH` to play MP3, AAC, M4A, OGG or FLAC files.
  WAV files and generated tones need no extra tools.
- Network access to the camera on the API port (443 or 80) and, for audio
  playback, on the Baichuan port 9000.

## Installation

```bash
git clone https://github.com/H-Held/Reolink_Camera_Control.git
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
| `siren_times(times=1, channel=None)` | Plays the built-in alarm sound N times |
| `play_tone(freq=440.0, duration=3.0, amplitude=0.7, volume=1.0, channel=None)` | Plays a sine tone through the camera speaker |
| `play_audio_file(file_path, volume=1.0, channel=None)` | Plays a local audio file through the camera speaker |
| `ffmpeg_available()` | True if `ffmpeg` was found in `PATH` |

Audio is sent through the camera's Baichuan protocol (TCP port 9000): the
library reads the camera's talk format, converts your audio to 16 kHz mono
PCM (WAV natively, other formats through `ffmpeg`), encodes it to IMA ADPCM
in pure Python and streams it in real time. No Docker and no external
program is needed for WAV files. The call blocks for the length of the
audio. `volume` is a gain factor (1.0 = unchanged, up to about 2.0, clipped
at full scale). If the camera does not support talk, or another talk session
blocks the speaker, `ReolinkAudioError` is raised.

```python
cam.play_audio_file("alert.wav")
cam.play_audio_file("song.mp3", volume=0.8)   # needs ffmpeg
cam.play_tone(880, duration=2)
```

The audio port can be changed with `ReolinkCamera(..., baichuan_port=9000)`.

### Command line

Stored audio files can be played at any time without writing code. Connection
settings are read from `.env` in the current directory (see below).

```bash
python -m reolink_camera_control play alert.wav
python -m reolink_camera_control play song.mp3 --volume 0.8
python -m reolink_camera_control tone --freq 880 --duration 2
python -m reolink_camera_control siren --times 2
python -m reolink_camera_control snap picture.jpg
python -m reolink_camera_control info
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
| `ReolinkAudioError` | Audio file missing or unsupported, conversion failed, or the camera refused the audio |

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
audio conversion, ADPCM encoding (verified against a reference decoder), the
talk message flow, login and retry logic, response parsing, the command line
and the public API.

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

The full run also switches the white LED on for 2 seconds, plays the siren for
2 seconds and plays two tones and a short melody through the speaker.

Names set by the tests must not contain underscores; the camera rejects them
(`SetDevName` / `SetOsd` fail). Without `--skip-set`, the script temporarily changes settings (device name,
image brightness, LEDs, volume and others), checks the result and restores the
original value. Run the read-only variant first. The reboot command is only probed, never
executed.

## Project layout

```
reolink_camera_control/
    camera.py       ReolinkCamera, the public API
    http.py         login, token refresh, retries
    audio.py        WAV/tone to PCM conversion, ffmpeg fallback
    adpcm.py        ADPCM encoder and talk packet format
    talk.py         audio push to the speaker (Baichuan protocol)
    __main__.py     command line interface
    models.py       data classes returned by the API
    exceptions.py   exception hierarchy
tests/
    unit/           offline tests
    live/           script for testing against a real camera
```

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). The dependencies (requests: Apache-2.0,
reolink-aio: MIT, urllib3: MIT, pytest: MIT) are compatible with the GPL-3.0; details are in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

The speaker audio packet format follows the documented behaviour of the
open source [neolink](https://github.com/QuantumEntangledAndy/neolink)
project; the implementation here is independent Python code.

This project is not affiliated with Reolink.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).
