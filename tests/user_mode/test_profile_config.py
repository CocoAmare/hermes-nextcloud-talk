"""Regression tests for the config env pass (which updates explicit extras)."""
from gateway.config import PlatformConfig
import user.adapter as adapter


def test_env_seed_does_not_replace_explicit_identity_with_defaults(monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_TALK_SERVER_URL", "https://cloud.example.com")
    monkeypatch.setenv("NEXTCLOUD_TALK_APP_PASSWORD", "test-password")
    monkeypatch.delenv("NEXTCLOUD_TALK_USERNAME", raising=False)
    monkeypatch.delenv("NEXTCLOUD_TALK_DISPLAY_NAME", raising=False)
    config = PlatformConfig(extra={"username": "jocasta", "display_name": "Jocasta"})
    config.extra.update(adapter._env_enablement() or {})
    instance = adapter.NextcloudTalkUserAdapter(config)
    assert instance._username == "jocasta"
    assert instance._display_name == "Jocasta"
