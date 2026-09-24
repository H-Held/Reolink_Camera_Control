"""Audio push to the camera speaker over the Baichuan protocol.

The camera does not accept audio over its HTTP API. Speaker audio is sent
through the proprietary Baichuan protocol (TCP port 9000) using the same
message flow as the open source neolink project:

    10   TalkAbility  read the accepted audio format
    201  TalkConfig   announce the format (ADPCM, 16 kHz, mono)
    202  Talk         stream ADPCM blocks, four blocks per message
    11   TalkReset    finish the talk session

Login, key exchange and message encryption are handled by ``reolink-aio``.
"""

from __future__ import annotations

import asyncio
import threading
import xml.etree.ElementTree as ET
from typing import Any, List, Optional

from .adpcm import encode_pcm, frame_block
from .audio import TALK_RATE
from .exceptions import ReolinkAudioError

BLOCKS_PER_MESSAGE = 4

MSG_TALK_ABILITY = 10
MSG_TALK_RESET = 11
MSG_TALK_CONFIG = 201
MSG_TALK = 202

_EXTENSION = "\n".join([
    '<?xml version="1.0" encoding="UTF-8" ?>',
    '<Extension version="1.1">',
    "<binaryData>1</binaryData>",
    "<channelId>{channel}</channelId>",
    "</Extension>",
    "",
])

_TALK_CONFIG = "\n".join([
    '<?xml version="1.0" encoding="UTF-8" ?>',
    "<body>",
    '<TalkConfig version="1.1">',
    "<channelId>{channel}</channelId>",
    "<duplex>FDX</duplex>",
    "<audioStreamMode>followVideoStream</audioStreamMode>",
    "<audioConfig>",
    "<audioType>adpcm</audioType>",
    "<sampleRate>{rate}</sampleRate>",
    "<samplePrecision>16</samplePrecision>",
    "<lengthPerEncoder>{length}</lengthPerEncoder>",
    "<soundTrack>mono</soundTrack>",
    "</audioConfig>",
    "</TalkConfig>",
    "</body>",
    "",
])


def parse_talk_ability(xml_text: str) -> dict:
    """Extract the first audio configuration from a TalkAbility reply."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ReolinkAudioError(f"Invalid TalkAbility reply: {exc}") from exc
    cfg = root.find(".//audioConfigList/audioConfig")
    if cfg is None:
        raise ReolinkAudioError("Camera reported no talk audio configuration")
    return {
        "type": (cfg.findtext("audioType") or "").strip(),
        "rate": int(cfg.findtext("sampleRate") or 0),
        "length": int(cfg.findtext("lengthPerEncoder") or 0),
    }


def build_talk_message(baichuan: Any, channel: int, payload: bytes,
                       mess_id: int) -> bytes:
    """Build one raw Talk (202) message.

    The extension is encrypted like every other message, the binary
    payload is sent unencrypted (as neolink does).
    """
    from reolink_aio.baichuan.baichuan import HEADER_MAGIC

    ext = _EXTENSION.format(channel=channel).encode("utf-8")
    header = (
        bytes.fromhex(HEADER_MAGIC)
        + MSG_TALK.to_bytes(4, "little")
        + (len(ext) + len(payload)).to_bytes(4, "little")
        + (channel + 1).to_bytes(1, "little")
        + mess_id.to_bytes(3, "little")
        + bytes.fromhex("0000" + "1464")
        + len(ext).to_bytes(4, "little")
    )
    return header + baichuan._aes_encrypt(ext) + payload


class TalkSession:
    """Send PCM audio (16 kHz, mono, 16-bit LE) to the camera speaker."""

    def __init__(self, host: str, username: str, password: str,
                 channel: int = 0, port: int = 443, use_https: bool = True,
                 baichuan_port: int = 9000):
        self._host = host
        self._username = username
        self._password = password
        self._channel = channel
        self._port = port
        self._use_https = use_https
        self._bc_port = baichuan_port

    def send(self, pcm: bytes) -> bool:
        """Play *pcm* on the camera speaker; blocks until it was sent.

        Raises ReolinkAudioError on any failure.
        """
        if not pcm:
            return True
        result: List[Optional[BaseException]] = [None]

        def runner() -> None:
            try:
                asyncio.run(self._send(pcm))
            except BaseException as exc:  # reported in the calling thread
                result[0] = exc

        # A dedicated thread also works when the caller already has a running loop.
        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        exc = result[0]
        if exc is None:
            return True
        if isinstance(exc, ReolinkAudioError):
            raise exc
        raise ReolinkAudioError(f"Audio push failed: {exc}") from exc

    async def _send(self, pcm: bytes) -> None:
        try:
            from reolink_aio.api import Host
        except ImportError as exc:
            raise ReolinkAudioError(
                "Audio push needs the 'reolink-aio' package: pip install reolink-aio"
            ) from exc

        host = Host(self._host, self._username, self._password,
                    port=self._port, use_https=self._use_https,
                    bc_port=self._bc_port)
        talking = False
        try:
            await host.get_host_data()
            bc = host.baichuan
            ability = parse_talk_ability(
                await bc.send(cmd_id=MSG_TALK_ABILITY, channel=self._channel))
            if ability["type"] != "adpcm" or ability["rate"] != TALK_RATE:
                raise ReolinkAudioError(
                    f"Unsupported camera talk format: {ability} "
                    f"(expected adpcm at {TALK_RATE} Hz)")

            config = _TALK_CONFIG.format(channel=self._channel,
                                         rate=ability["rate"],
                                         length=ability["length"])
            talking = True
            try:
                await bc.send(cmd_id=MSG_TALK_CONFIG, channel=self._channel,
                              body=config)
            except Exception:
                # Another talk session (or a crashed one) blocks the speaker:
                # reset it and retry once, like the official client.
                await bc.send(cmd_id=MSG_TALK_RESET, channel=self._channel)
                await bc.send(cmd_id=MSG_TALK_CONFIG, channel=self._channel,
                              body=config)

            blocks = encode_pcm(pcm, ability["length"])
            bc._mess_id = (bc._mess_id + 1) % 16777216
            mess_id = bc._mess_id
            samples_per_block = ability["length"] + 1

            for i in range(0, len(blocks), BLOCKS_PER_MESSAGE):
                chunk = blocks[i:i + BLOCKS_PER_MESSAGE]
                payload = b"".join(frame_block(b) for b in chunk)
                message = build_talk_message(bc, self._channel, payload, mess_id)
                await bc._connection.send_without_wait(message)
                await asyncio.sleep(len(chunk) * samples_per_block / ability["rate"])
        except ReolinkAudioError:
            raise
        except Exception as exc:
            raise ReolinkAudioError(f"Audio push failed: {exc}") from exc
        finally:
            try:
                if talking:
                    await host.baichuan.send(cmd_id=MSG_TALK_RESET,
                                             channel=self._channel)
            except Exception:
                pass
            try:
                await host.logout()
            except Exception:
                pass
