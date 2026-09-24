import struct
import sys
import types

import pytest

from reolink_camera_control import ReolinkAudioError
from reolink_camera_control import talk as talk_mod
from reolink_camera_control.talk import TalkSession, build_talk_message, parse_talk_ability

ABILITY_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<body>
<TalkAbility version="1.1">
<audioConfigList>
<audioConfig>
<priority>0</priority>
<audioType>adpcm</audioType>
<sampleRate>16000</sampleRate>
<samplePrecision>16</samplePrecision>
<lengthPerEncoder>1024</lengthPerEncoder>
<soundTrack>mono</soundTrack>
</audioConfig>
</audioConfigList>
</TalkAbility>
</body>
"""


class FakeConnection:
    def __init__(self):
        self.sent = []

    async def send_without_wait(self, data):
        self.sent.append(data)


class FakeBaichuan:
    def __init__(self, ability=ABILITY_XML, fail_first_config=False):
        self.ability = ability
        self.fail_first_config = fail_first_config
        self.commands = []
        self._mess_id = 5
        self._connection = FakeConnection()

    async def send(self, cmd_id, channel=None, body=""):
        self.commands.append(cmd_id)
        if cmd_id == 10:
            return self.ability
        if cmd_id == 201 and self.fail_first_config and self.commands.count(201) == 1:
            raise RuntimeError("422")
        return ""

    def _aes_encrypt(self, data):
        return data          # identity: keeps the test readable


@pytest.fixture
def fake_host(monkeypatch):
    """Replace reolink_aio.api.Host with an in-memory fake."""
    state = types.SimpleNamespace(baichuan=FakeBaichuan(), logged_out=False)

    class FakeHost:
        def __init__(self, *args, **kwargs):
            self.baichuan = state.baichuan

        async def get_host_data(self):
            pass

        async def logout(self):
            state.logged_out = True

    module = types.ModuleType("reolink_aio.api")
    module.Host = FakeHost
    monkeypatch.setitem(sys.modules, "reolink_aio.api", module)
    monkeypatch.setattr(talk_mod.asyncio, "sleep", _instant_sleep)
    return state


async def _instant_sleep(_seconds):
    return None


def test_parse_talk_ability():
    assert parse_talk_ability(ABILITY_XML) == {"type": "adpcm", "rate": 16000, "length": 1024}


def test_parse_talk_ability_rejects_garbage():
    with pytest.raises(ReolinkAudioError):
        parse_talk_ability("not xml")
    with pytest.raises(ReolinkAudioError):
        parse_talk_ability("<body></body>")


def test_talk_message_header_and_payload():
    bc = FakeBaichuan()
    payload = b"PAYLOAD"
    msg = build_talk_message(bc, channel=0, payload=payload, mess_id=77)
    assert int.from_bytes(msg[4:8], "little") == 202               # Talk message id
    body_len = int.from_bytes(msg[8:12], "little")
    assert msg[12] == 1                                             # channel + 1
    assert int.from_bytes(msg[13:16], "little") == 77               # message number
    assert msg[18:20] == bytes.fromhex("1464")                      # message class
    ext_len = int.from_bytes(msg[20:24], "little")
    assert body_len == ext_len + len(payload)
    assert b"<binaryData>1</binaryData>" in msg[24:24 + ext_len]
    assert msg.endswith(payload)                                    # payload not encrypted


def test_send_runs_the_talk_sequence(fake_host):
    pcm = struct.pack("<3000h", *([1000] * 3000))                   # 3 blocks
    session = TalkSession("cam", "admin", "pw")
    assert session.send(pcm) is True
    assert fake_host.baichuan.commands == [10, 201, 11]              # ability, config, reset
    assert len(fake_host.baichuan._connection.sent) == 1             # 3 blocks -> 1 message
    assert fake_host.logged_out


def test_send_splits_into_messages_of_four_blocks(fake_host):
    pcm = bytes(2 * 1025 * 9)                                        # 9 blocks
    TalkSession("cam", "admin", "pw").send(pcm)
    assert len(fake_host.baichuan._connection.sent) == 3             # 4 + 4 + 1


def test_config_failure_triggers_reset_and_retry(fake_host):
    fake_host.baichuan.fail_first_config = True
    TalkSession("cam", "admin", "pw").send(bytes(2 * 1025))
    assert fake_host.baichuan.commands == [10, 201, 11, 201, 11]


def test_unsupported_talk_format_is_reported(fake_host):
    fake_host.baichuan.ability = ABILITY_XML.replace("16000", "8000")
    with pytest.raises(ReolinkAudioError, match="Unsupported camera talk format"):
        TalkSession("cam", "admin", "pw").send(bytes(2 * 1025))
    assert fake_host.logged_out


def test_empty_audio_is_a_no_op():
    assert TalkSession("cam", "admin", "pw").send(b"") is True


def test_connection_errors_become_audio_errors(fake_host, monkeypatch):
    async def boom(*_a, **_k):
        raise ConnectionError("no route")
    monkeypatch.setattr(fake_host.baichuan, "send", boom)
    with pytest.raises(ReolinkAudioError, match="no route"):
        TalkSession("cam", "admin", "pw").send(bytes(2 * 1025))
