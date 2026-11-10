"""Keep developer/gateway credentials and identity out of isolated unit tests."""
import os

import pytest


@pytest.fixture(autouse=True)
def clean_nextcloud_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("NEXTCLOUD_TALK_"):
            monkeypatch.delenv(name)
