"""Audio helpers for the camera talkback stream.

The camera speaker expects raw PCM: 8 000 Hz, mono, 16-bit little endian.
WAV files and generated tones are handled with the standard library only
(``audioop`` was removed in Python 3.13, so it is not used here).
Other formats (MP3, AAC, ...) are converted through an ``ffmpeg`` binary.
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

from .exceptions import ReolinkAudioError

TALK_RATE = 8000        # Hz
TALK_CHANNELS = 1       # mono
TALK_WIDTH = 2          # bytes per sample (16-bit)
CHUNK_MS = 20           # ms per streamed chunk
CHUNK_SAMPLES = int(TALK_RATE * CHUNK_MS / 1000)
CHUNK_BYTES = CHUNK_SAMPLES * TALK_WIDTH

# Extensions that the stdlib ``wave`` module cannot read.
NEEDS_FFMPEG = {".mp3", ".aac", ".m4a", ".wma", ".opus",
                ".amr", ".flac", ".ogg", ".mp4", ".mov"}


def _decode_samples(frames: bytes, width: int) -> list[int]:
    """Decode little-endian PCM frames into signed 16-bit range integers."""
    if width == 1:      # unsigned 8-bit
        return [(b - 128) << 8 for b in frames]
    if width == 2:
        samples = array("h")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()
        return list(samples)
    if width == 3:      # keep the upper 16 of 24 bits
        return [int.from_bytes(frames[i + 1:i + 3], "little", signed=True)
                for i in range(0, len(frames) - 2, 3)]
    if width == 4:      # keep the upper 16 of 32 bits
        samples = array("i")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()
        return [s >> 16 for s in samples]
    raise ReolinkAudioError(f"Unsupported WAV sample width: {width} bytes")


def _to_mono(samples: list[int], channels: int) -> list[int]:
    """Average all channels into one."""
    if channels == 1:
        return samples
    usable = len(samples) - len(samples) % channels
    return [sum(samples[i:i + channels]) // channels
            for i in range(0, usable, channels)]


def _resample(samples: list[int], src_rate: int, dst_rate: int) -> list[int]:
    """Linear-interpolation resampler (adequate for speech and alert tones)."""
    if src_rate == dst_rate or not samples:
        return samples
    n_out = max(1, int(len(samples) * dst_rate / src_rate))
    step = src_rate / dst_rate
    last = len(samples) - 1
    out = []
    for i in range(n_out):
        pos = i * step
        idx = int(pos)
        if idx >= last:
            out.append(samples[last])
            continue
        frac = pos - idx
        out.append(int(samples[idx] + (samples[idx + 1] - samples[idx]) * frac))
    return out


def _pack_pcm16(samples: list[int]) -> bytes:
    out = array("h", (max(-32768, min(32767, s)) for s in samples))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def wav_to_pcm8k(wav_path: str) -> bytes:
    """Read a WAV file and return PCM at 8 000 Hz, mono, 16-bit LE.

    Handles 8/16/24/32-bit integer WAVs with any channel count and rate.
    """
    try:
        with wave.open(str(wav_path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except FileNotFoundError as exc:
        raise ReolinkAudioError(f"Audio file not found: {wav_path}") from exc
    except (wave.Error, EOFError) as exc:
        raise ReolinkAudioError(f"Cannot read WAV file {wav_path}: {exc}") from exc

    samples = _decode_samples(frames, width)
    samples = _to_mono(samples, channels)
    samples = _resample(samples, rate, TALK_RATE)
    return _pack_pcm16(samples)


def generate_tone_pcm(freq: float, duration: float,
                      amplitude: float = 0.7) -> bytes:
    """Generate a sine tone as raw PCM (8 kHz, 16-bit, mono)."""
    if duration < 0 or freq < 0:
        raise ReolinkAudioError("freq and duration must not be negative")
    n = int(TALK_RATE * duration)
    buf = bytearray(n * TALK_WIDTH)
    twopi_f = 2.0 * math.pi * freq / TALK_RATE
    for i in range(n):
        val = int(amplitude * 32767 * math.sin(twopi_f * i))
        struct.pack_into("<h", buf, i * 2, max(-32768, min(32767, val)))
    return bytes(buf)


def ffmpeg_available() -> bool:
    """Return True if an ``ffmpeg`` binary is on the PATH."""
    try:
        return subprocess.run(["ffmpeg", "-version"],
                              capture_output=True, timeout=5).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def convert_with_ffmpeg(src: str) -> str:
    """Convert any audio file to an 8 kHz mono 16-bit temporary WAV file.

    The caller is responsible for deleting the returned file.
    """
    if not ffmpeg_available():
        raise ReolinkAudioError(
            "ffmpeg not found in PATH - required for MP3/AAC/M4A/OGG/FLAC.\n"
            "  Ubuntu/Debian : sudo apt install ffmpeg\n"
            "  macOS         : brew install ffmpeg\n"
            "  Windows       : https://ffmpeg.org/download.html\n"
            "WAV files work without ffmpeg."
        )
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = ["ffmpeg", "-y", "-i", src,
           "-ar", str(TALK_RATE), "-ac", "1", "-sample_fmt", "s16",
           "-f", "wav", tmp.name]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        os.unlink(tmp.name)
        raise ReolinkAudioError(
            f"ffmpeg conversion failed:\n{r.stderr.decode(errors='replace')[-400:]}")
    return tmp.name


def load_pcm(file_path: str) -> bytes:
    """Load an audio file as raw PCM (8 kHz, mono, 16-bit LE).

    ``.wav`` needs no extra tools; every other supported format goes
    through ffmpeg first.
    """
    ext = Path(file_path).suffix.lower()
    if ext in NEEDS_FFMPEG:
        tmp = convert_with_ffmpeg(file_path)
        try:
            return wav_to_pcm8k(tmp)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    if ext == ".wav":
        return wav_to_pcm8k(file_path)
    raise ReolinkAudioError(
        f"Unsupported audio format '{ext}'.\n"
        f"Native (no tools): .wav\n"
        f"Via ffmpeg: {', '.join(sorted(NEEDS_FFMPEG))}"
    )
