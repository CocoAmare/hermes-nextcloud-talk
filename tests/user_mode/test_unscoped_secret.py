"""v1.13.1: a multiplexed gateway builds the default profile's adapters with no
secret scope bound, so Hermes' get_secret raises UnscopedSecretError. _secret
must then read the profile's own .env (hermes_cli.config.load_env)."""

import importlib.util
import os
import sys
import types

import pytest

import user.adapter as user_adapter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Loaded by path under a unique name: tests/bot imports the same file as a flat
# ``adapter`` module, so a package import would depend on collection order.
if os.path.join(_ROOT, "bot") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "bot"))
_bspec = importlib.util.spec_from_file_location(
    "nctalk_bot_adapter_unscoped", os.path.join(_ROOT, "bot", "adapter.py")
)
bot_adapter = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(bot_adapter)


class UnscopedSecretError(RuntimeError):
    pass


@pytest.fixture(params=[user_adapter, bot_adapter], ids=["user", "bot"])
def mod(request):
    return request.param


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    """Default root holds 'default-root-value'; the launch home (HERMES_HOME, a named
    profile) holds a different password that must never be used."""
    default_root = tmp_path / "default"
    launch_home = tmp_path / "profiles" / "named"
    for home, pw in ((default_root, "default-root-value"), (launch_home, "launch-home-value")):
        home.mkdir(parents=True)
        (home / ".env").write_text("NEXTCLOUD_TALK_APP_PASSWORD" + "=" + pw + "\n")
    monkeypatch.setenv("HERMES_HOME", str(launch_home))
    monkeypatch.setenv("NEXTCLOUD_TALK_SECRET", "leak-canary")

    def build(home):
        out = {}
        for line in (home / ".env").read_text().splitlines():
            k, _, v = line.partition("=")
            out[k] = v
        return out

    scope = types.ModuleType("agent.secret_scope")
    scope.build_profile_secret_scope = build
    agent = types.ModuleType("agent")
    agent.secret_scope = scope
    const = types.ModuleType("hermes_constants")
    const.get_default_hermes_root = lambda: default_root
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", scope)
    monkeypatch.setitem(sys.modules, "hermes_constants", const)
    return scope


def _raiser(exc):
    def get(name, default=None):
        raise exc

    return get


def test_unscoped_reads_profile_env(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope")))
    assert mod._secret("NEXTCLOUD_TALK_APP_PASSWORD") == "default-root-value"


def test_unscoped_missing_key_returns_default(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope")))
    assert mod._secret("NEXTCLOUD_TALK_SECRET", "dflt") == "dflt"
    assert mod._secret("NEXTCLOUD_TALK_SECRET") == ""


def test_unscoped_never_reads_process_env(mod, env_file, monkeypatch):
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope")))
    assert mod._secret("NEXTCLOUD_TALK_SECRET", "dflt") == "dflt"


def test_catches_by_real_class_when_importable(mod, env_file, monkeypatch):
    class Real(Exception):
        pass

    monkeypatch.setattr(mod, "_UnscopedSecretError", Real)
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(Real("x")))
    assert mod._secret("NEXTCLOUD_TALK_APP_PASSWORD") == "default-root-value"
    # a same-named but unrelated class is not the real one
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("x")))
    with pytest.raises(UnscopedSecretError):
        mod._secret("NEXTCLOUD_TALK_APP_PASSWORD")


def test_helpers_missing_fails_closed(mod, env_file, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_constants", None)  # import raises ImportError
    monkeypatch.setattr(mod, "_hermes_get_secret", _raiser(UnscopedSecretError("no scope")))
    with pytest.raises(UnscopedSecretError):
        mod._secret("NEXTCLOUD_TALK_APP_PASSWORD")
    monkeypatch.setenv("NEXTCLOUD_TALK_APP_PASSWORD", "env-canary")
    with pytest.raises(UnscopedSecretError):
        mod._secret("NEXTCLOUD_TALK_APP_PASSWORD")


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
