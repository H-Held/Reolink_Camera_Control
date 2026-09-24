import pytest

from reolink_camera_control import ReolinkAudioError
from reolink_camera_control import talk as talk_mod
from reolink_camera_control.audio import CHUNK_BYTES
from reolink_camera_control.talk import TalkSession


def _patch(monkeypatch, start_error=None):
    posts = []

    def fake_post(url, **kwargs):
        posts.append(url)
        if "StartTalk" in url:
            list(kwargs["data"])  # drain the generator like a real upload
            if start_error:
                raise start_error

    monkeypatch.setattr(talk_mod.requests, "post", fake_post)
    return posts


def test_body_yields_20ms_chunks():
    s = TalkSession("b", "t")
    s._pcm = b"\x00" * (CHUNK_BYTES * 2 + 10)
    chunks = list(s._body())
    assert [len(c) for c in chunks] == [CHUNK_BYTES, CHUNK_BYTES, 10]


def test_send_calls_start_then_stop(monkeypatch):
    posts = _patch(monkeypatch)
    assert TalkSession("http://c/api.cgi", "T").send(b"\x00" * CHUNK_BYTES)
    assert "StartTalk" in posts[0] and "StopTalk" in posts[-1]


def test_connection_reset_is_not_an_error(monkeypatch):
    posts = _patch(monkeypatch, start_error=ConnectionResetError("Connection reset"))
    assert TalkSession("http://c/api.cgi", "T").send(b"\x00" * CHUNK_BYTES)
    assert "StopTalk" in posts[-1]


def test_other_errors_raise_but_still_stop(monkeypatch):
    posts = _patch(monkeypatch, start_error=ValueError("bad payload"))
    with pytest.raises(ReolinkAudioError):
        TalkSession("http://c/api.cgi", "T").send(b"\x00" * CHUNK_BYTES)
    assert "StopTalk" in posts[-1]
