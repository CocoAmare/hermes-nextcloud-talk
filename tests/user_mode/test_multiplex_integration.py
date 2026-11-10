"""Run against real Hermes helpers when HERMES_SOURCE points to its checkout.

Example: HERMES_SOURCE=~/.hermes/hermes-agent python -m pytest tests/ -q
The subprocess keeps Hermes' global multiplex state out of the unit-test stubs.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("scenario", ["default", "secondary", "missing", "mode", "standalone"])
def test_real_hermes_profile_isolation(scenario):
    source = os.environ.get("HERMES_SOURCE")
    if not source:
        pytest.skip("Set HERMES_SOURCE to also test real Hermes multiplex helpers")
    repo = Path(__file__).resolve().parents[2]
    script = r'''
import asyncio
import importlib.util
import os
from pathlib import Path
import sys

repo, source, scenario = sys.argv[1:]
sys.path[:0] = [str(Path(repo) / "tests/stubs"), repo, source]
# Use lightweight gateway/base stubs but REAL Hermes scope and platform helpers.
import gateway.platforms
spec = importlib.util.spec_from_file_location(
    "gateway.platforms._shared", Path(source) / "gateway/platforms/_shared.py")
shared = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shared
spec.loader.exec_module(shared)
from agent.secret_scope import set_multiplex_active, set_secret_scope
from gateway.config import PlatformConfig
import user.adapter as adapter

for key in list(os.environ):
    if key.startswith("NEXTCLOUD_TALK_"):
        del os.environ[key]
os.environ.update({
    "NEXTCLOUD_TALK_SERVER_URL": "https://default.example.com",
    "NEXTCLOUD_TALK_APP_PASSWORD": "default-test-password",
    "NEXTCLOUD_TALK_USERNAME": "default-user",
    "NEXTCLOUD_TALK_DISPLAY_NAME": "Default",
    "NEXTCLOUD_TALK_MODE": "bot",
    "NEXTCLOUD_TALK_SECRET": "default-bot-secret",
    "NEXTCLOUD_TALK_ALLOW_ALL_USERS": "true",
    "NEXTCLOUD_TALK_ALLOWED_USERS": "default-owner",
    "NEXTCLOUD_TALK_AGENT_USERS": "default-agent",
    "NEXTCLOUD_TALK_ROOM_MODES": "default-room=free",
})
set_multiplex_active(True)
if scenario == "default":
    config = PlatformConfig(extra={"username": "default-user"})
    assert adapter.validate_config(config)
    assert adapter.check_requirements()
    instance = adapter.NextcloudTalkUserAdapter(config)
    assert instance._app_password == "default-test-password"
    assert instance._username == "default-user"
else:
    scope = {
        "NEXTCLOUD_TALK_SERVER_URL": "https://secondary.example.com",
        "NEXTCLOUD_TALK_APP_PASSWORD": "secondary-test-password",
    }
    if scenario == "missing":
        scope.pop("NEXTCLOUD_TALK_APP_PASSWORD")
    set_secret_scope(scope)
    config = PlatformConfig(extra={"username": "secondary-user", "display_name": "Secondary"})
    if scenario == "missing":
        assert not adapter.validate_config(config)
        assert not adapter.check_requirements()
        assert adapter._env_enablement() is None
        assert adapter.NextcloudTalkUserAdapter(config)._app_password == ""
    elif scenario == "mode":
        spec = importlib.util.spec_from_file_location("nctalk_plugin", Path(repo) / "__init__.py",
            submodule_search_locations=[repo])
        plugin = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        assert plugin._mode(config) == "user"
        assert plugin.validate_config(config)
        assert plugin.env_enablement()["server_url"] == "https://secondary.example.com"
    elif scenario == "standalone":
        class Client:
            def __init__(self, **kwargs):
                assert kwargs["base_url"] == "https://secondary.example.com"
                assert kwargs["headers"]["Authorization"] == adapter._build_auth_header(
                    "secondary-user", "secondary-test-password")["Authorization"]
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs):
                class Response:
                    status_code = 201
                    def json(self): return {"ocs": {"data": {"id": 123}}}
                return Response()
        adapter.httpx.AsyncClient = Client
        assert asyncio.run(adapter._standalone_send(config, "secondary-room", "hello"))["success"]
    else:
        config.extra.update(adapter._env_enablement() or {})
        instance = adapter.NextcloudTalkUserAdapter(config)
        assert instance._server == "https://secondary.example.com"
        assert instance._username == "secondary-user"
        assert instance._display_name == "Secondary"
        assert instance._app_password == "secondary-test-password"
        assert instance._allowed_users == frozenset()
        assert instance._allow_all_users is False
        assert instance._agent_users == frozenset()
        assert instance._room_modes == {}
'''
    result = subprocess.run([sys.executable, "-c", script, str(repo), source, scenario],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
