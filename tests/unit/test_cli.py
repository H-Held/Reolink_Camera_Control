import pytest

from reolink_camera_control import __main__ as cli


class FakeCamera:
    calls = []

    def __init__(self, host, user, password, port=443, scheme="https"):
        FakeCamera.calls = [("init", host, user, password, port, scheme)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def play_audio_file(self, path, volume=1.0):
        FakeCamera.calls.append(("play", path, volume))

    def play_tone(self, freq, duration, volume=1.0):
        FakeCamera.calls.append(("tone", freq, duration, volume))

    def siren_times(self, n):
        FakeCamera.calls.append(("siren_times", n))

    def siren_on(self):
        FakeCamera.calls.append(("siren_on",))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for key in ("REOLINK_HOST", "REOLINK_USER", "REOLINK_PASSWORD",
                "REOLINK_PORT", "REOLINK_SCHEME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)          # no stray .env from the repository
    monkeypatch.setattr(cli, "ReolinkCamera", FakeCamera)


def test_missing_settings_exit_code_2(capsys):
    assert cli.main(["tone"]) == 2
    assert ".env.example" in capsys.readouterr().err


def test_play_uses_arguments(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    code = cli.main(["--host", "h", "--user", "u", "--password", "p",
                     "play", str(wav), "--volume", "0.5"])
    assert code == 0
    assert FakeCamera.calls[0] == ("init", "h", "u", "p", 443, "https")
    assert FakeCamera.calls[1] == ("play", str(wav), 0.5)


def test_play_missing_file_is_reported(tmp_path, capsys):
    code = cli.main(["--host", "h", "--user", "u", "--password", "p",
                     "play", str(tmp_path / "missing.wav")])
    assert code == 1
    assert "File not found" in capsys.readouterr().err


def test_settings_from_dotenv_file(tmp_path):
    (tmp_path / ".env").write_text(
        "# comment\nREOLINK_HOST=1.2.3.4\nREOLINK_USER='admin'\n"
        "REOLINK_PASSWORD=secret\nREOLINK_PORT=80\nREOLINK_SCHEME=http\n",
        encoding="utf-8")
    assert cli.main(["tone", "--freq", "880", "--duration", "1"]) == 0
    assert FakeCamera.calls[0] == ("init", "1.2.3.4", "admin", "secret", 80, "http")
    assert FakeCamera.calls[1] == ("tone", 880.0, 1.0, 1.0)


def test_siren_times(tmp_path):
    cli.main(["--host", "h", "--user", "u", "--password", "p", "siren", "--times", "3"])
    assert FakeCamera.calls[1] == ("siren_times", 3)


def test_camera_errors_give_exit_code_1(monkeypatch, capsys):
    from reolink_camera_control import ReolinkAudioError

    class Broken(FakeCamera):
        def play_tone(self, *a, **k):
            raise ReolinkAudioError("speaker busy")

    monkeypatch.setattr(cli, "ReolinkCamera", Broken)
    code = cli.main(["--host", "h", "--user", "u", "--password", "p", "tone"])
    assert code == 1
    assert "speaker busy" in capsys.readouterr().err
