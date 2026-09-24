import pytest

from reolink_camera_control import (ReolinkAuthError, ReolinkCommandError,
                                    ReolinkConnectionError)
from reolink_camera_control import http as http_mod
from reolink_camera_control.http import ReolinkHTTP


class FakeResponse:
    def __init__(self, payload=None, text=None):
        self._payload = payload
        self.text = text if text is not None else ("x" if payload is not None else "")

    def json(self):
        return self._payload


@pytest.fixture
def client():
    return ReolinkHTTP("cam", "admin", "pw")


def _patch_post(monkeypatch, responses):
    calls = []
    it = iter(responses)

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http_mod.requests, "post", fake_post)
    return calls


LOGIN_OK = [{"code": 0, "value": {"Token": {"name": "TOK"}}}]


def test_login_stores_token(client, monkeypatch):
    _patch_post(monkeypatch, [FakeResponse(LOGIN_OK)])
    assert client.login() == "TOK"
    assert client.token == "TOK"


def test_login_with_wrong_password_raises_auth_error(client, monkeypatch):
    _patch_post(monkeypatch, [FakeResponse([{"code": 1, "error": {"rspCode": -7}}])])
    with pytest.raises(ReolinkAuthError):
        client.login()


def test_login_unreachable_raises_connection_error(client, monkeypatch):
    _patch_post(monkeypatch, [OSError("down")] * 4)
    with pytest.raises(ReolinkConnectionError):
        client.login()


def test_call_returns_first_response(client, monkeypatch):
    client.token = "TOK"
    calls = _patch_post(monkeypatch, [FakeResponse([{"code": 0, "value": {"a": 1}}])])
    resp = client.get("GetDevInfo")
    assert resp["value"] == {"a": 1}
    assert "cmd=GetDevInfo&token=TOK" in calls[0][0]


def test_command_error_is_raised(client, monkeypatch):
    _patch_post(monkeypatch, [FakeResponse([{"code": 1, "error": {"rspCode": -9}}])])
    with pytest.raises(ReolinkCommandError):
        client.get("GetFoo")


def test_expired_token_triggers_relogin_and_retry(client, monkeypatch):
    calls = _patch_post(monkeypatch, [
        FakeResponse([{"code": 1, "error": {"rspCode": -6}}]),  # token expired
        FakeResponse([{"code": 0}]),                             # logout
        FakeResponse(LOGIN_OK),                                  # login
        FakeResponse([{"code": 0, "value": {"ok": True}}]),      # retry
    ])
    client.token = "OLD"
    assert client.get("GetFoo")["value"] == {"ok": True}
    assert client.token == "TOK"
    assert len(calls) == 4


def test_empty_responses_end_in_command_error(client, monkeypatch):
    _patch_post(monkeypatch, [
        FakeResponse(text=""),          # first try
        FakeResponse(text=""),          # second try
        FakeResponse(LOGIN_OK),         # login during refresh (no token, so no logout)
        FakeResponse(text=""),          # third try
    ])
    with pytest.raises(ReolinkCommandError, match="empty"):
        client.get("GetFoo")


def test_value_helper():
    assert ReolinkHTTP.value({"value": {"k": 5}}, "k") == 5
    assert ReolinkHTTP.value({}, "k") is None
