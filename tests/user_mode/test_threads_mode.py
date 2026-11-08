"""v1.14.0: per-room threads mode (/threads on|off), main-timeline replies open threads."""

import asyncio
import json

import httpx

from gateway.config import PlatformConfig
from user import threadsmode
from user.adapter import (ROOM_TYPE_GROUP, ROOM_TYPE_ONE_TO_ONE, NextcloudTalkUserAdapter,
                          _fallback_title)


def _run(coro):
    return asyncio.run(coro)


def _adapter(tmp_path, monkeypatch, **extra):
    monkeypatch.setenv("NEXTCLOUD_TALK_STATE_DIR", str(tmp_path))
    extra.setdefault("allowed_users", "chef")
    a = NextcloudTalkUserAdapter(PlatformConfig(extra=dict(extra)))
    a._threads_enabled = True
    a._capabilities_checked = True
    a._room_meta["dm1"] = {"token": "dm1", "type": ROOM_TYPE_ONE_TO_ONE, "displayName": "chef"}
    return a


class Talk:
    def __init__(self, host_features=("threads",), fail_thread=False):
        self.posts = []
        self.host_features = list(host_features)
        self.fail_thread = fail_thread

    def __call__(self, request):
        path = request.url.path
        if request.method == "POST":
            body = json.loads(request.content)
            self.posts.append(body)
            if self.fail_thread and "threadTitle" in body:
                return httpx.Response(500, json={})
            return httpx.Response(201, json={"ocs": {"data": {"id": 500 + len(self.posts)}}})
        if path.endswith("/capabilities"):
            return httpx.Response(200, json={"ocs": {"data": {"features": self.host_features}}})
        if "/threads/" in path:
            tid = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"ocs": {"data": {
                "thread": {"id": tid, "title": "T"}, "attendee": {"notificationLevel": 0},
                "first": {"id": tid, "actorId": "hermes-bot", "actorType": "users", "message": "ans",
                          "messageType": "comment", "timestamp": 1, "isThread": True, "threadId": tid}}}})
        return httpx.Response(200, json={"ocs": {"data": []}})


def _wire(a, talk):
    a._http_client = httpx.AsyncClient(base_url="https://cloud.example.com",
                                       transport=httpx.MockTransport(talk))


def _msg(msg_id, actor, text, thread=None, actor_type="users"):
    m = {"id": msg_id, "actorId": actor, "actorType": actor_type, "actorDisplayName": actor,
         "message": text, "messageType": "comment", "messageParameters": {}, "timestamp": 1700000000,
         "threadId": msg_id}
    if thread:
        m.update(isThread=True, threadId=thread, threadTitle="T")
    return m


def _on(a, talk, token="dm1"):
    _wire(a, talk)
    _run(a._on_message(token, _msg(1, "chef", "/threads on")))


# -- toggle -------------------------------------------------------------------


def test_default_off_and_status(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _wire(a, talk)
    _run(a._on_message("dm1", _msg(1, "chef", "/threads")))
    assert "off" in talk.posts[0]["message"] and a.handled_events == []


def test_toggle_persists_across_restart(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    assert "is on" in talk.posts[0]["message"]
    b = _adapter(tmp_path, monkeypatch)
    assert b._threads_mode_stored("dm1") and not b._threads_mode_stored("other")
    _wire(b, talk)
    _run(b._on_message("dm1", _msg(2, "chef", "/threads off")))
    assert not _adapter(tmp_path, monkeypatch)._threads_mode_stored("dm1")


def test_env_seed_and_stored_off_beats_it(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_TALK_THREADS_MODE_ROOMS", "dm1, g2")
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    assert a._threads_mode_stored("dm1") and a._threads_mode_stored("g2")
    _wire(a, talk)
    _run(a._on_message("dm1", _msg(1, "chef", "/threads off")))
    assert not a._threads_mode_stored("dm1") and a._threads_mode_stored("g2")


def test_state_file_is_per_account(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_TALK_STATE_DIR", str(tmp_path))
    assert (threadsmode.state_path("https://a", "x") != threadsmode.state_path("https://a", "y"))


def test_non_allowed_human_cannot_toggle(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _wire(a, talk)
    _run(a._on_message("dm1", _msg(1, "mallory", "/threads on")))
    assert not a._threads_mode_stored("dm1") and a.handled_events == []
    assert "Only people allowed" in talk.posts[0]["message"]


def test_agent_cannot_toggle(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch, allowed_users="chef,jarvis", agent_users="jarvis"), Talk()
    _wire(a, talk)
    _run(a._on_message("dm1", _msg(1, "jarvis", "/threads on")))
    assert not a._threads_mode_stored("dm1") and a.handled_events == [] and talk.posts == []


def test_threads_command_not_forwarded_to_core(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    assert a.handled_events == []
    _run(a._on_message("dm1", _msg(3, "chef", "/status")))
    assert len(a.handled_events) == 1


# -- behaviour ----------------------------------------------------------------


def _ask(a, text="Plan my taxes for this year please", msg_id=10):
    _run(a._on_message("dm1", _msg(msg_id, "chef", text)))
    return a.handled_events[-1]


def test_on_reply_opens_thread_with_model_title(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    ev = _ask(a)
    assert "Thread title:" in ev.text
    n = len(talk.posts)
    res = _run(a.send("dm1", "Thread title: Tax plan 2026\nHere is the plan.", reply_to="10"))
    assert res.success and res.message_id == str(500 + n + 1)
    body = talk.posts[n]
    assert body["threadTitle"] == "Tax plan 2026" and body["message"] == "Here is the plan."
    assert "replyTo" not in body
    # later message of the same turn follows into the thread
    _run(a.send("dm1", "more", reply_to="10"))
    assert talk.posts[-1]["threadId"] == int(res.message_id) and "replyTo" not in talk.posts[-1]


def test_on_reply_fallback_title(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    _ask(a, "**Hey** @hermes-bot can you plan my taxes — for this year and next one please")
    _run(a.send("dm1", "Sure.", reply_to="10"))
    title = talk.posts[-1]["threadTitle"]
    assert title == "Hey can you plan my taxes, for this"
    assert "—" not in title and "@" not in title
    assert _fallback_title("   ") == "New thread"


def test_followup_in_new_thread_routes_to_thread_session_with_seed(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    _ask(a, "taxes please")
    res = _run(a.send("dm1", "On it.", reply_to="10"))
    tid = int(res.message_id)
    _run(a._on_message("dm1", _msg(tid + 1, "chef", "and the car?", thread=tid)))
    ev = a.handled_events[-1]
    assert ev.source.thread_id == str(tid) and "chef: taxes please" in ev.text


def test_on_in_thread_reply_stays_in_thread(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    _run(a._on_message("dm1", _msg(21, "chef", "in thread", thread=20)))
    ev = a.handled_events[-1]
    assert "Threads mode" not in ev.text
    n = len(talk.posts)
    _run(a.send("dm1", "reply", reply_to="21", metadata={"thread_id": "20"}))
    assert "threadTitle" not in talk.posts[n] and talk.posts[n]["threadId"] == 20


def test_on_unrelated_sends_unchanged(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    n = len(talk.posts)
    _run(a.send("dm1", "cron result"))
    assert talk.posts[n] == {"message": "cron result"}
    _ask(a, "/status")
    assert "Threads mode" not in a.handled_events[-1].text


def test_off_is_unchanged(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _wire(a, talk)
    ev = _ask(a)
    assert "Threads mode" not in ev.text and a._thread_turns == {}
    _run(a.send("dm1", "Thread title: x\nhi", reply_to="10"))
    assert talk.posts[-1] == {"message": "Thread title: x\nhi", "replyTo": 10}


def test_thread_refused_falls_back_to_main_timeline(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch), Talk()
    _on(a, talk)
    _ask(a)
    talk.fail_thread = True
    res = _run(a.send("dm1", "hi", reply_to="10"))
    assert res.success and talk.posts[-1] == {"message": "hi", "replyTo": 10}


def test_federated_host_without_threads_behaves_off(tmp_path, monkeypatch):
    a, talk = _adapter(tmp_path, monkeypatch, room_modes="fed1=free"), Talk(host_features=["chat-v2"])
    a._room_meta["fed1"] = {"token": "fed1", "type": ROOM_TYPE_GROUP, "displayName": "r",
                            "remoteServer": "https://other.example.com"}
    _wire(a, talk)
    _run(a._on_message("fed1", _msg(1, "chef", "/threads on")))
    assert "does not support threads" in talk.posts[-1]["message"]
    _run(a._on_message("fed1", _msg(2, "chef", "hello there")))
    assert "Threads mode" not in a.handled_events[-1].text and a._thread_turns == {}
