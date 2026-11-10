"""Small stand-ins for Hermes' public platform helpers; no Hermes required.

The optional HERMES_SOURCE tests also exercise the real helpers and secret scope.
"""
import os


def get_scoped_secret(name, default=None):
    return os.getenv(name, default)


def seed_extra_from_env(spec, *, home_env=None, home_default=""):
    seed = {}
    for env, key, convert in spec:
        raw = str(get_scoped_secret(env, "") or "").strip()
        if raw:
            try:
                seed[key] = convert(raw) if convert else raw
            except ValueError:
                pass
    if home_env:
        home = str(get_scoped_secret(home_env, "") or "").strip() or home_default
        if home:
            seed["home_channel"] = {
                "chat_id": home,
                "name": get_scoped_secret(f"{home_env}_NAME", "Home"),
            }
    return seed
