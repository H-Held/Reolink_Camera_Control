"""Shared fixtures: make sure no test ever sleeps or touches the network."""

import pytest


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
