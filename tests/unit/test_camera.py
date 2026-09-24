import pytest

from reolink_camera_control import ReolinkCamera, ReolinkCommandError


class FakeHTTP:
    """Records calls and serves canned responses keyed by command."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.sets = []
        self.calls = []
        self.username = "admin"
        self.scheme, self.port = "https", 443
        self.base, self.token = "https://cam:443/api.cgi", "TOK"

    def get(self, cmd, param=None):
        self.calls.append((cmd, param))
        return {"code": 0, "value": self.responses.get(cmd, {})}

    def call(self, cmd, param=None, action=0):
        self.calls.append((cmd, param))
        return {"code": 0}

    def set(self, cmd, param, settle=True):
        self.sets.append((cmd, param))
        return {"code": 0}

    @staticmethod
    def value(resp, key):
        return resp.get("value", {}).get(key)


@pytest.fixture
def cam():
    c = ReolinkCamera("cam", "admin", "pw")
    c._http = FakeHTTP()
    return c


def test_device_info_mapping(cam):
    cam._http.responses["GetDevInfo"] = {"DevInfo": {
        "name": "Garden", "model": "RLC-540A", "serial": "S1",
        "firmVer": "v1", "hardVer": "H1", "buildDay": "b"}}
    info = cam.get_device_info()
    assert (info.name, info.model, info.firmware) == ("Garden", "RLC-540A", "v1")


def test_missing_data_falls_back_to_defaults(cam):
    assert cam.get_device_info().model == ""
    assert cam.get_image_settings().bright == 128
    assert cam.get_hdd_info() == []


def test_default_channel_is_used_and_overridable(cam):
    cam.get_image_settings()
    cam.get_image_settings(channel=2)
    assert cam._http.calls[0][1] == {"channel": 0}
    assert cam._http.calls[1][1] == {"channel": 2}


def test_set_image_settings_merges_existing_values(cam):
    cam._http.responses["GetImage"] = {"Image": {"bright": 100, "hue": 5}}
    cam.set_image_settings(bright=140)
    cmd, param = cam._http.sets[0]
    assert cmd == "SetImage"
    assert param == {"Image": {"bright": 140, "hue": 5}}


def test_set_ntp_converts_bool_to_int(cam):
    cam._http.responses["GetNtp"] = {"Ntp": {"server": "pool"}}
    cam.set_ntp(True)
    assert cam._http.sets[0][1] == {"Ntp": {"server": "pool", "enable": 1}}


def test_set_white_led_only_changes_given_fields(cam):
    cam._http.responses["GetWhiteLed"] = {"WhiteLed": {"state": 1, "mode": 1, "bright": 100}}
    cam.set_white_led(bright=40)
    assert cam._http.sets[0][1]["WhiteLed"] == {"state": 1, "mode": 1, "bright": 40}


def test_rtsp_urls(cam):
    cam._http.responses["GetNetPort"] = {"NetPort": {"rtspPort": 8554, "rtspEnable": 1}}
    urls = cam.get_rtsp_urls()
    assert urls["main"] == "rtsp://cam:8554//h264Preview_01_main"
    assert urls["sub"].endswith("_sub")


def test_rtsp_urls_empty_when_disabled(cam):
    cam._http.responses["GetNetPort"] = {"NetPort": {"rtspEnable": 0}}
    assert cam.get_rtsp_urls() == {}


def test_ai_config_mapping(cam):
    cam._http.responses["GetAiCfg"] = {"people": {"enable": 1}, "aiTrack": 1}
    ai = cam.get_ai_config()
    assert ai.people and ai.ai_track and not ai.vehicle


def test_motion_alarm_mapping(cam):
    cam._http.responses["GetMdAlarm"] = {"MdAlarm": {"enable": 1, "sens": {"sens": 70}}}
    m = cam.get_motion_alarm()
    assert m.enabled and m.sensitivity == 70


def test_ptz_presets_swallow_unsupported_cameras(cam):
    def boom(*a, **k):
        raise ReolinkCommandError("no ptz")
    cam._http.get = boom
    assert cam.get_ptz_presets() == []


def test_ptz_goto_preset_command(cam):
    cam.ptz_goto_preset(3)
    assert cam._http.calls[-1] == ("PtzCtrl", {"channel": 0, "op": "ToPos", "id": 3})


def test_snap_returns_bytes(cam, monkeypatch):
    class R:
        status_code = 200
        content = b"\xff\xd8\xff" + b"0" * 600
    monkeypatch.setattr("reolink_camera_control.camera.requests.get", lambda *a, **k: R())
    assert cam.snap().startswith(b"\xff\xd8\xff")


def test_snap_failure_raises(cam, monkeypatch):
    class R:
        status_code = 500
        content = b""
    monkeypatch.setattr("reolink_camera_control.camera.requests.get", lambda *a, **k: R())
    with pytest.raises(ReolinkCommandError):
        cam.snap()


def test_snap_to_file(cam, tmp_path, monkeypatch):
    monkeypatch.setattr(cam, "snap", lambda channel=None: b"jpeg")
    assert cam.snap_to_file(str(tmp_path / "a.jpg")).read_bytes() == b"jpeg"


def test_play_tone_streams_generated_pcm(cam, monkeypatch):
    sent = {}

    class FakeSession:
        def __init__(self, base, token):
            sent["args"] = (base, token)

        def send(self, pcm):
            sent["len"] = len(pcm)
            return True

    monkeypatch.setattr("reolink_camera_control.camera.TalkSession", FakeSession)
    assert cam.play_tone(440, 0.25) is True
    assert sent["len"] == 8000 * 0.25 * 2
    assert sent["args"] == ("https://cam:443/api.cgi", "TOK")


def test_motion_alarm_newer_firmware_list_layout(cam):
    """Firmware v3.0.0.4348 reports lists of time slots instead of a dict."""
    cam._http.responses["GetMdAlarm"] = {"MdAlarm": {
        "useNewSens": 1,
        "newSens": {"sens": [{"enable": 0, "sensitivity": 0}]},
        "sens": [{"id": 0, "sensitivity": 10}, {"id": 1, "sensitivity": 20}]}}
    m = cam.get_motion_alarm()
    assert not m.enabled
    assert m.sensitivity == 20


def test_motion_alarm_new_slots_enabled(cam):
    cam._http.responses["GetMdAlarm"] = {"MdAlarm": {
        "newSens": {"sens": [{"enable": 1, "sensitivity": 30}, {"enable": 0, "sensitivity": 90}]},
        "sens": []}}
    m = cam.get_motion_alarm()
    assert m.enabled and m.sensitivity == 30


def test_webhook_list_layout_sets_every_entry(cam):
    cam._http.responses["GetWebHook"] = {"WebHook": [
        {"index": 0, "indexEnable": 0}, {"index": 1, "indexEnable": 0}]}
    cam.set_webhook_enabled(True)
    assert cam._http.sets[0][1] == {"WebHook": [
        {"index": 0, "indexEnable": 1}, {"index": 1, "indexEnable": 1}]}


def test_webhook_dict_layout_still_supported(cam):
    cam._http.responses["GetWebHook"] = {"WebHook": {"url": "x"}}
    cam.set_webhook_enabled(False)
    assert cam._http.sets[0][1] == {"WebHook": {"url": "x", "enable": 0}}
