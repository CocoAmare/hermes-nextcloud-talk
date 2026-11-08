"""v1.13.1: a multiplexed gateway builds the default profile's adapters with no
secret scope bound, so Hermes' get_secret raises UnscopedSecretError. _secret
must then read the profile's own .env (hermes_cli.config.load_env)."""

import importlib.util
import os
import sys
import types

import pytest

import bot.adapter as bot_adapter
import user.adapter as user_adapter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class UnscopedSecretError(RuntimeError):
    pass


@pytest.fixture(params=[user_adapter, bot_adapter], ids=["user", "bot"])
def mod(request):
    return request.param


@pytest.fixture
def env_file(monkeypatch):
    """Stub hermes_cli.config.load_env returning a profile .env."""
    values = {"NEXTCLOUD_TALK_APP_PASSWORD": "from-dotenv"}
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_env = lambda: dict(values)
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    return values


def _raiser(exc):
    def get(name, default=None):
        raise exc

    return get


def test_unscoped_reads_profile_env(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope")))
    assert mod._secret("NEXTCLOUD_TALK_APP_PASSWORD") == "from-dotenv"


def test_unscoped_missing_key_returns_default(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope")))
    assert mod._secret("NEXTCLOUD_TALK_SECRET", "dflt") == "dflt"
    assert mod._secret("NEXTCLOUD_TALK_SECRET") == ""


def test_other_errors_propagate(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(ValueError("boom")))
    with pytest.raises(ValueError):
        mod._secret("NEXTCLOUD_TALK_APP_PASSWORD")


def test_bound_scope_unchanged(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", lambda n, d=None: "scoped-val")
    assert mod._secret("NEXTCLOUD_TALK_APP_PASSWORD") == "scoped-val"
    monkeypatch.setattr(mod, "_hermes_get_secret", lambda n, d=None: None)
    assert mod._secret("NEXTCLOUD_TALK_APP_PASSWORD", "d") == "d"


def test_mode_user_when_unscoped(env_file, monkeypatch):
    monkeypatch.delenv("NEXTCLOUD_TALK_MODE", raising=False)
    spec = importlib.util.spec_from_file_location(
        "nctalk_root_under_test",
        os.path.join(_ROOT, "__init__.py"),
        submodule_search_locations=[_ROOT],
    )
    root = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "nctalk_root_under_test", root)
    spec.loader.exec_module(root)
    monkeypatch.setattr(
        root._user, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope"))
    )
    assert root._mode(None) == "user"
