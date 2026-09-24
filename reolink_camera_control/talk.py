"""HTTP talkback session (StartTalk, stream PCM, StopTalk)."""

from __future__ import annotations

import threading
import time
from typing import Iterator, Optional

import requests

from .audio import CHUNK_BYTES, CHUNK_MS, TALK_RATE, TALK_WIDTH
from .exceptions import ReolinkAudioError


class TalkSession:
    """Stream PCM audio to the camera speaker via HTTP talkback.

    Protocol::

        POST /api.cgi?cmd=StartTalk&token=...
            Content-Type: application/octet-stream
            Body: raw PCM chunks at real-time rate (8 kHz, 16-bit, mono)

        POST /api.cgi?cmd=StopTalk&token=...   (always sent, even on error)

    The StartTalk POST holds the connection open while a generator feeds
    PCM data. A background thread runs the blocking POST.
    """

    def __init__(self, base_url: str, token: str):
        self._base = base_url
        self._token = token
        self._pcm: Optional[bytes] = None
        self._stop = threading.Event()
        self._error: Optional[Exception] = None

    def _body(self) -> Iterator[bytes]:
        """Yield 20 ms PCM chunks at real-time speed."""
        if not self._pcm:
            return
        for offset in range(0, len(self._pcm), CHUNK_BYTES):
            if self._stop.is_set():
                break
            yield self._pcm[offset: offset + CHUNK_BYTES]
            time.sleep(CHUNK_MS / 1000.0)

    def _stream_thread(self) -> None:
        url = f"{self._base}?cmd=StartTalk&token={self._token}"
        try:
            r = requests.post(
                url,
                data=self._body(),
                headers={"Content-Type": "application/octet-stream"},
                verify=False,
                timeout=(len(self._pcm) / (TALK_RATE * TALK_WIDTH)) + 10,
            )
            self._check_response(r)
        except Exception as exc:
            self._error = exc

    @staticmethod
    def _check_response(r) -> None:
        """Raise if the camera answered with a JSON error instead of accepting audio."""
        try:
            data = r.json()
        except ValueError:
            return  # not JSON: the camera consumed the stream
        first = data[0] if isinstance(data, list) and data else data
        if isinstance(first, dict) and first.get("code", 0) != 0:
            raise ReolinkAudioError(
                "Camera rejected HTTP talkback (StartTalk): "
                f"{first.get('error', first)}. This camera/firmware does not "
                "support audio push over HTTP; use siren_on()/siren_off() instead."
            )

    def send(self, pcm: bytes) -> bool:
        """Stream *pcm* to the speaker and block until it has been sent.

        Returns True on success. Raises ReolinkAudioError on hard failures.
        """
        self._pcm = pcm
        self._stop.clear()
        self._error = None

        t = threading.Thread(target=self._stream_thread, daemon=True)
        t.start()
        t.join(timeout=len(pcm) / (TALK_RATE * TALK_WIDTH) + 15)

        self._stop_talk()

        if isinstance(self._error, ReolinkAudioError):
            raise self._error
        if self._error:
            # The camera often resets the connection once it has received
            # everything - that is normal, not an error.
            msg = str(self._error).lower()
            if any(k in msg for k in ("connection", "reset", "closed",
                                      "eof", "broken pipe", "timeout")):
                return True
            raise ReolinkAudioError(f"StartTalk stream error: {self._error}")
        return True

    def _stop_talk(self) -> None:
        self._stop.set()
        try:
            requests.post(
                f"{self._base}?cmd=StopTalk&token={self._token}",
                json=[{"cmd": "StopTalk", "action": 0, "param": {}}],
                verify=False,
                timeout=5,
            )
        except Exception:
            pass  # best-effort cleanup
