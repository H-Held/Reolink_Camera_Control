import struct
import wave
from array import array

import pytest

from reolink_camera_control import ReolinkAudioError
from reolink_camera_control import audio


def _write_wav(path, samples, rate=8000, width=2, channels=1):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(samples)


def _pcm(data: bytes):  # noqa: D401
    a = array("h")
    a.frombytes(data)
    return list(a)


def test_tone_length_and_amplitude():
    pcm = audio.generate_tone_pcm(440, 0.5, amplitude=0.5)
    assert len(pcm) == audio.TALK_RATE * 0.5 * 2
    peak = max(abs(s) for s in _pcm(pcm))
    assert 0.45 * 32767 < peak <= 0.5 * 32767


def test_tone_zero_duration_is_empty():
    assert audio.generate_tone_pcm(440, 0) == b""


def test_tone_rejects_negative_values():
    with pytest.raises(ReolinkAudioError):
        audio.generate_tone_pcm(440, -1)


def test_wav_16k_mono_passthrough(tmp_path):
    data = struct.pack("<4h", 0, 1000, -1000, 32767)
    _write_wav(tmp_path / "a.wav", data, rate=16000)
    assert audio.wav_to_pcm(str(tmp_path / "a.wav")) == data


def test_wav_stereo_is_downmixed(tmp_path):
    data = struct.pack("<4h", 1000, 3000, -2000, 0)  # two stereo frames
    _write_wav(tmp_path / "s.wav", data, rate=16000, channels=2)
    assert _pcm(audio.wav_to_pcm(str(tmp_path / "s.wav"))) == [2000, -1000]


def test_wav_44k_is_resampled_to_16k(tmp_path):
    n = 44100
    data = struct.pack(f"<{n}h", *([500] * n))
    _write_wav(tmp_path / "hi.wav", data, rate=44100)
    out = _pcm(audio.wav_to_pcm(str(tmp_path / "hi.wav")))
    assert abs(len(out) - 16000) <= 1
    assert set(out) == {500}


def test_wav_8bit_is_converted_to_16bit(tmp_path):
    _write_wav(tmp_path / "u8.wav", bytes([128, 255, 0]), rate=16000, width=1)
    assert _pcm(audio.wav_to_pcm(str(tmp_path / "u8.wav"))) == [0, 127 << 8, -128 << 8]


def test_wav_24bit_keeps_upper_bits(tmp_path):
    sample = (0x123456).to_bytes(3, "little")
    _write_wav(tmp_path / "w24.wav", sample, rate=16000, width=3)
    assert _pcm(audio.wav_to_pcm(str(tmp_path / "w24.wav"))) == [0x1234]


def test_missing_wav_raises_audio_error(tmp_path):
    with pytest.raises(ReolinkAudioError, match="not found"):
        audio.load_pcm(str(tmp_path / "missing.wav"))


def test_invalid_wav_raises_audio_error(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"this is not a wav file")
    with pytest.raises(ReolinkAudioError):
        audio.load_pcm(str(bad))


def test_unsupported_extension_raises(tmp_path):
    with pytest.raises(ReolinkAudioError, match="Unsupported"):
        audio.load_pcm(str(tmp_path / "song.xyz"))


def test_ffmpeg_formats_fail_cleanly_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(audio, "ffmpeg_available", lambda: False)
    with pytest.raises(ReolinkAudioError, match="ffmpeg not found"):
        audio.load_pcm(str(tmp_path / "song.mp3"))


def test_scale_pcm_applies_gain_and_clips():
    pcm = struct.pack("<3h", 1000, -1000, 30000)
    assert _pcm(audio.scale_pcm(pcm, 0.5)) == [500, -500, 15000]
    assert _pcm(audio.scale_pcm(pcm, 2.0)) == [2000, -2000, 32767]
    assert audio.scale_pcm(pcm, 1.0) == pcm


def test_scale_pcm_rejects_negative_volume():
    with pytest.raises(ReolinkAudioError):
        audio.scale_pcm(b"\x00\x00", -1)
