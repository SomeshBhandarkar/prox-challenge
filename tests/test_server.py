import asyncio
import json
import socket

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from starlette.testclient import TestClient

from app import server as S
from app.knowledge import FIGURES
from app.show import PREFIX
from scripts.dev_server import DemoClient, scenario


class Recorder(DemoClient):
    """The pretend agent, remembering every instance so tests can see which conversation got which question."""
    made: list = []

    def __init__(self, options=None):
        super().__init__(options)
        Recorder.made.append(self)


class Gated(Recorder):
    """Waits at a gate before answering, so a test can look at a conversation while a question is still being answered."""
    gate = None

    async def receive_response(self):
        await Gated.gate.wait()
        async for m in super().receive_response():
            yield m


class Refuses:
    def __init__(self, options=None):
        pass

    async def __aenter__(self):
        raise RuntimeError("401 authentication_failed")

    async def __aexit__(self, *exc):
        return False


def events(response):
    out = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def kinds(evs):
    return [name for name, _ in evs]


@pytest.fixture
def client():
    Recorder.made = []
    app = S.create_app(client_factory=Recorder, options_factory=lambda: None, model="haiku")
    with TestClient(app) as c:
        yield c


def ask(c, message, session_id=None):
    return events(c.post("/api/chat", json={"message": message, "session_id": session_id}))


# ---------- the chat stream ----------
def test_a_question_streams_session_status_show_text_and_done_in_order(client):
    r = client.post("/api/chat", json={"message": "duty cycle please"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream") and r.headers["cache-control"] == "no-store"
    evs = events(r)
    assert kinds(evs) == ["session", "status", "status", "show", "text", "done"]
    assert evs[0][1]["resumed"] is False and evs[0][1]["session_id"]
    assert evs[-1][1] == {"ok": True, "cost_usd": 0.0}


def test_widgets_and_drawings_never_travel_in_the_stream_only_a_link_to_a_sandboxed_frame(client):
    r = client.post("/api/chat", json={"message": "everything"})
    assert "<!doctype" not in r.text.lower() and "<script" not in r.text.lower()
    shows = [d for n, d in events(r) if n == "show"]
    assert [s["kind"] for s in shows] == ["widget", "figure", "widget"]
    widget = shows[0]
    assert widget["embed"].startswith("/embed/") and "html" not in widget and widget["title"]
    page = client.get(widget["embed"])
    assert page.status_code == 200 and page.text.startswith("<!doctype html>") and "source:'widget'" in page.text
    csp = page.headers["content-security-policy"]
    assert csp.startswith("sandbox allow-scripts;") and "connect-src 'none'" in csp and "default-src 'none'" in csp
    assert "allow-same-origin" not in csp and page.headers["cache-control"] == "no-store"


def test_a_figure_comes_with_its_caption_source_picture_and_manual_page(client):
    (fig,) = [d for n, d in ask(client, "figure") if n == "show"]
    assert fig["kind"] == "figure" and fig["id"] == "rating-label" and fig["url"] == "/figures/rating-label.png"
    assert fig["source"] == "Manual p.16" and fig["manual_page"] == 16 and fig["caption"]
    image = client.get(fig["url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png" and image.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_pictures_from_other_pdfs_have_no_manual_page_to_link():
    embeds = S.Embeds()
    chart = S.public({"kind": "figure", "id": "selection-chart", "caption": "c", "source": "Selection chart", "url": "/figures/selection-chart.png"}, embeds)
    quick = S.public({"kind": "figure", "id": "quick-start-all-cable-setups", "caption": "c", "source": "Quick-start guide p.2", "url": "/x"}, embeds)
    assert chart["manual_page"] is None and quick["manual_page"] is None


def test_a_drawing_is_framed_with_its_identifier_and_carries_its_own_csp(client):
    (art,) = [d for n, d in ask(client, "draw me something") if n == "show"]
    assert art["kind"] == "artifact" and art["identifier"] == "cable-cheat-sheet" and art["title"]
    body = client.get(art["embed"]).text
    assert "Content-Security-Policy" in body and "window.MANUAL" in body


def test_a_picture_that_cannot_be_shown_becomes_a_short_error_and_the_answer_continues(client):
    evs = ask(client, "badfigure")
    (err,) = [d for n, d in evs if n == "show"]
    assert err["kind"] == "error" and err["message"] == "I couldn't show a picture there."
    assert "no-such-figure" in err["detail"] and len(err["detail"]) <= 200 and "Valid ids" not in err["message"]
    assert kinds(evs)[-2:] == ["text", "done"]


def test_the_same_conversation_keeps_one_agent_and_an_unknown_one_starts_fresh(client):
    first = ask(client, "hello")
    sid = first[0][1]["session_id"]
    second = ask(client, "hello again", sid)
    assert second[0][1] == {"session_id": sid, "resumed": True}
    assert len(Recorder.made) == 1 and Recorder.made[0].queries == ["hello", "hello again"]
    stranger = ask(client, "hello", "not-a-real-session")
    assert stranger[0][1]["resumed"] is False and stranger[0][1]["session_id"] != "not-a-real-session" and len(Recorder.made) == 2


def test_reset_ends_a_conversation(client):
    sid = ask(client, "hello")[0][1]["session_id"]
    assert client.post("/api/reset", json={"session_id": sid}).json() == {"ok": True, "closed": True}
    assert client.post("/api/reset", json={"session_id": sid}).json() == {"ok": True, "closed": False}
    assert client.post("/api/reset", json={}).json() == {"ok": True, "closed": False}
    assert ask(client, "hello", sid)[0][1]["resumed"] is False


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "   \n "}, {"message": "x" * 2001}, {}, {"message": 5}, {"message": None},
                                  {"message": "hi", "session_id": "s" * 65}])
def test_bad_questions_are_refused_before_any_agent_is_started(client, body):
    r = client.post("/api/chat", json=body)
    assert r.status_code == 422 and "1 to 2000" in r.json()["error"] and Recorder.made == []


def test_garbage_bodies_are_refused_too(client):
    assert client.post("/api/chat", content=b"not json", headers={"content-type": "application/json"}).status_code == 422
    assert client.post("/api/chat", content=b"[]", headers={"content-type": "application/json"}).status_code == 422
    assert client.post("/api/chat").status_code == 422
    assert client.get("/api/chat").status_code == 405 and Recorder.made == []


def test_the_longest_allowed_question_is_accepted_and_the_limit_matches_the_terminal_runner(client):
    from scripts.ask import MAX_QUESTION_CHARS
    assert S.MAX_QUESTION_CHARS == MAX_QUESTION_CHARS
    assert kinds(ask(client, "a" * S.MAX_QUESTION_CHARS))[-1] == "done"


def test_text_is_passed_through_untouched_so_the_page_alone_is_responsible_for_escaping(client):
    texts = [d["text"] for n, d in ask(client, "unsafe") if n == "text"]
    assert "<script>alert(1)</script>" in texts[0] and "javascript:alert(3)" in texts[0]


# ---------- when things go wrong ----------
def test_a_soft_limit_is_explained_and_the_conversation_goes_on(client):
    sid = ask(client, "hello")[0][1]["session_id"]
    evs = ask(client, "limit", sid)
    (err,) = [d for n, d in evs if n == "error"]
    assert err["code"] == "error_max_turns" and err["fatal"] is False and "smaller pieces" in err["message"]
    assert ask(client, "hello", sid)[0][1]["resumed"] is True


def test_the_spending_limit_ends_the_conversation_and_the_next_question_starts_a_new_one(client):
    sid = ask(client, "hello")[0][1]["session_id"]
    evs = ask(client, "budget", sid)
    (err,) = [d for n, d in evs if n == "error"]
    assert err["fatal"] is True and "spending limit" in err["message"] and evs[-1][1]["ok"] is False
    assert ask(client, "hello", sid)[0][1]["resumed"] is False


def test_a_crash_inside_the_agent_is_reported_without_details_and_the_next_question_starts_clean(client):
    sid = ask(client, "hello")[0][1]["session_id"]
    evs = ask(client, "crash", sid)
    (err,) = [d for n, d in evs if n == "error"]
    assert err["fatal"] is True and "RuntimeError" in err["message"] and "demo crash" not in err["message"]
    assert kinds(evs)[-1] == "done"
    assert ask(client, "hello", sid)[0][1]["resumed"] is False


def test_an_agent_that_cannot_start_gives_a_clear_message_instead_of_hanging():
    app = S.create_app(client_factory=Refuses, options_factory=lambda: None, model="haiku")
    with TestClient(app) as c:
        evs = ask(c, "hello")
        (err,) = [d for n, d in evs if n == "error"]
        assert "API key was refused" in err["message"] and err["fatal"] is True and kinds(evs)[-1] == "done"


def test_one_explanation_per_answer_even_when_the_sdk_sends_two():
    embeds = S.Embeds()
    err = AssistantMessage(content=[TextBlock("hmm")], model="m", error="rate_limit")
    res = ResultMessage(subtype="error_during_execution", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s", total_cost_usd=0.0)

    class Twice(DemoClient):
        async def receive_response(self):
            yield err
            yield res

    async def go():
        sessions = S.Sessions(Twice, lambda: None, embeds)
        out = sessions.get_or_create(None).submit("hi")
        got = []
        while (item := await asyncio.wait_for(out.get(), 5)) is not None:
            got.append(item[0])
        await sessions.close_all()
        return got

    assert asyncio.run(go()) == ["error", "text", "done"]


# ---------- turning SDK messages into events ----------
def test_events_for_maps_text_tools_and_results():
    embeds = S.Embeds()
    msg = AssistantMessage(content=[TextBlock("  hi  "), TextBlock("   "), ToolUseBlock(id="1", name=PREFIX + "duty_cycle", input={}),
                                    ToolUseBlock(id="2", name="Bash", input={}), ToolUseBlock(id="3", name=PREFIX + "show_unicorn", input={})], model="m")
    evs = S.events_for(msg, embeds)
    assert evs[0] == ("text", {"text": "hi"}) and evs[1] == ("status", {"text": S.STATUS["duty_cycle"]})
    assert evs[2] == ("status", {"text": "Working on it"}) and evs[3][0] == "show" and evs[3][1]["kind"] == "error"
    assert len(evs) == 4  # blank text and the foreign tool are ignored
    ok = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", total_cost_usd=0.5)
    assert S.events_for(ok, embeds) == [("done", {"ok": True, "cost_usd": 0.5})]
    assert S.events_for("not a message", embeds) == [] and S.events_for(None, embeds) == []


def test_every_status_label_belongs_to_a_registered_tool_and_every_show_tool_has_one():
    from app.agent_tools import TOOL_NAMES
    assert set(S.STATUS) == {n[len(PREFIX):] for n in TOOL_NAMES}


def test_known_api_errors_get_a_plain_explanation():
    embeds = S.Embeds()
    for code in S.HINTS:
        (ev,) = S.events_for(AssistantMessage(content=[], model="m", error=code), embeds)
        assert ev[0] == "error" and ev[1]["message"] == S.HINTS[code]


# ---------- conversations: one question at a time, idle expiry, a cap ----------
def test_a_second_question_is_refused_while_the_first_is_still_being_answered():
    async def go():
        Gated.gate = asyncio.Event()
        sessions = S.Sessions(Gated, lambda: None, S.Embeds())
        s = sessions.get_or_create(None)
        out = s.submit("figure")
        assert out is not None and s.busy and s.submit("figure") is None and s.pending == 1
        Gated.gate.set()
        names = []
        while (item := await asyncio.wait_for(out.get(), 5)) is not None:
            names.append(item[0])
        assert names[-1] == "done" and not s.busy
        assert s.submit("figure") is not None  # free again
        await sessions.close_all()

    asyncio.run(go())


def test_idle_conversations_expire_but_one_that_is_answering_never_does():
    async def go():
        now = [0.0]
        Gated.gate = asyncio.Event()
        sessions = S.Sessions(Gated, lambda: None, S.Embeds(), limit=5, idle=60, clock=lambda: now[0])
        idle, busy = sessions.get_or_create(None), sessions.get_or_create(None)
        out = busy.submit("figure")
        now[0] = 61
        sessions.sweep()
        assert idle.id not in sessions.items and idle.closing and busy.id in sessions.items
        await asyncio.wait_for(idle.task, 5)
        now[0] = 10_000
        sessions.sweep()
        assert busy.id in sessions.items  # still answering
        Gated.gate.set()
        while await asyncio.wait_for(out.get(), 5) is not None:
            pass
        await sessions.close_all()

    asyncio.run(go())


def test_the_cap_drops_the_oldest_idle_conversation_and_says_busy_when_all_are_answering():
    async def go():
        Gated.gate = asyncio.Event()
        sessions = S.Sessions(Gated, lambda: None, S.Embeds(), limit=2)
        a, b = sessions.get_or_create(None), sessions.get_or_create(None)
        c = sessions.get_or_create(None)  # a and b are idle: the oldest (a) makes room
        assert a.id not in sessions.items and {b.id, c.id} == set(sessions.items) and a.closing
        b.submit("x"), c.submit("x")
        assert sessions.get_or_create(None) is None
        Gated.gate.set()
        await sessions.close_all()

    asyncio.run(go())


def test_using_a_conversation_makes_it_the_newest_so_the_other_one_is_dropped_first():
    async def go():
        sessions = S.Sessions(Recorder, lambda: None, S.Embeds(), limit=2)
        a, b = sessions.get_or_create(None), sessions.get_or_create(None)
        assert sessions.get_or_create(a.id) is a
        sessions.get_or_create(None)
        assert a.id in sessions.items and b.id not in sessions.items
        await sessions.close_all()

    asyncio.run(go())


def test_a_dead_or_closing_conversation_is_replaced_not_reused():
    async def go():
        sessions = S.Sessions(Recorder, lambda: None, S.Embeds())
        a = sessions.get_or_create(None)
        a.close()
        b = sessions.get_or_create(a.id)
        assert b is not a and b.id != a.id and a.id not in sessions.items
        await sessions.close_all()

    asyncio.run(go())


def test_a_start_failure_answers_every_waiting_question():
    async def go():
        sessions = S.Sessions(Refuses, lambda: None, S.Embeds())
        s = sessions.get_or_create(None)
        out = s.submit("hi")
        names = []
        while (item := await asyncio.wait_for(out.get(), 5)) is not None:
            names.append(item[0])
        await asyncio.wait_for(s.task, 5)
        assert names == ["error", "done"] and s.dead and s.pending == 0
        assert s.submit("again") is None

    asyncio.run(go())


def test_shutting_the_server_down_closes_every_conversation():
    Recorder.made = []
    app = S.create_app(client_factory=Recorder, options_factory=lambda: None, model="haiku")
    with TestClient(app) as c:
        ask(c, "hello")
        ask(c, "hello")
        sessions = list(app.state.sessions.items.values())
        assert len(sessions) == 2
    assert app.state.sessions.items == {} and all(s.task.done() for s in sessions)


# ---------- embeds ----------
def test_embeds_keep_the_newest_and_forget_the_oldest():
    e = S.Embeds(limit=3)
    tokens = [e.add(f"<p>{i}</p>") for i in range(3)]
    assert e.get(tokens[0]) == "<p>0</p>"          # reading refreshes it
    tokens.append(e.add("<p>3</p>"))
    assert e.get(tokens[1]) is None and e.get(tokens[0]) and e.get(tokens[3])
    assert len(set(tokens)) == 4 and all(len(t) >= 16 for t in tokens)


@pytest.mark.parametrize("token", ["nope", "../../etc/passwd", "a" * 100, "short", "x y z w q r s t", "%00" * 10])
def test_unknown_or_malformed_embed_links_are_not_found(client, token):
    assert client.get(f"/embed/{token}").status_code == 404


# ---------- pictures and manual pages ----------
def test_every_catalog_figure_is_served_as_a_png(client):
    for f in FIGURES:
        r = client.get(f"/figures/{f['id']}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png", f["id"]


@pytest.mark.parametrize("name", ["nope", "Rating-Label", "rating_label", "..%2F..%2F.env", "rating-label.png", "a" * 300, "%2e%2e"])
def test_unknown_or_tricky_picture_names_are_not_found(client, name):
    assert client.get(f"/figures/{name}.png").status_code == 404


def test_all_48_manual_pages_are_served_and_nothing_else(client):
    for n in range(1, 49):
        r = client.get(f"/pages/{n}.jpg")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg", n
    for bad in ("0", "49", "100", "-1", "abc", "1.5", "007", "%2e%2e"):
        assert client.get(f"/pages/{bad}.jpg").status_code == 404, bad


# ---------- the page, headers, health ----------
def test_the_page_is_served_with_a_strict_policy_and_a_missing_page_is_a_clear_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(S, "WEB", tmp_path)
    r = client.get("/")
    assert r.status_code == 404 and "web/index.html" in r.json()["error"]
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert r.headers["x-frame-options"] == "DENY"


def test_static_files_are_served_from_web_static_and_nothing_outside_it(monkeypatch, tmp_path):
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text("1", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(S, "WEB", tmp_path)
    with TestClient(S.create_app(client_factory=Recorder, options_factory=lambda: None, model="haiku")) as c:
        assert c.get("/static/app.js").status_code == 200
        assert c.get("/static/../secret.txt").status_code == 404 and c.get("/static/%2e%2e/secret.txt").status_code == 404
    monkeypatch.setattr(S, "WEB", tmp_path / "missing")
    with TestClient(S.create_app(client_factory=Recorder, options_factory=lambda: None, model="haiku")) as c:
        assert c.get("/static/app.js").status_code == 404  # no crash when the folder is missing


def test_every_response_gets_the_safe_headers_and_the_docs_pages_are_off(client):
    for path in ("/api/health", "/nope", "/figures/nope.png"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer", path
    assert all(client.get(p).status_code == 404 for p in ("/docs", "/redoc", "/openapi.json"))


def test_health_says_whether_a_key_is_set_but_never_shows_it(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-very-secret")
    r = client.get("/api/health")
    assert r.json() == {"ok": True, "model": "claude-haiku-5-5", "key": True} and "very-secret" not in r.text
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your-api-key-here")
    assert client.get("/api/health").json()["key"] is False
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/api/health").json()["key"] is False


# ---------- starting it ----------
def test_the_spending_limit_setting_is_checked():
    assert S.session_budget({}) == S.DEFAULT_SESSION_BUDGET_USD == 1.0
    assert S.session_budget({"SESSION_BUDGET_USD": " 2.5 "}) == 2.5
    for bad in ("abc", "0", "-1", "nan", "inf", "1,5"):
        with pytest.raises(SystemExit) as e:
            S.session_budget({"SESSION_BUDGET_USD": bad})
        assert "SESSION_BUDGET_USD" in str(e.value), bad


def test_a_busy_port_is_skipped_so_the_app_still_starts():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert S.find_free_port("127.0.0.1", port) != port
        with pytest.raises(SystemExit) as e:
            S.find_free_port("127.0.0.1", port, tries=1)
        assert "APP_PORT" in str(e.value)


@pytest.mark.parametrize("argv", [["--model", "hiaku"], ["--port", "0"], ["--port", "70000"], ["--port", "abc"]])
def test_bad_options_stop_before_anything_starts(argv):
    with pytest.raises(SystemExit) as e:
        S.parse_args(argv)
    assert e.value.code == 2


def test_the_port_can_come_from_the_environment_and_a_typo_there_is_explained(monkeypatch):
    monkeypatch.setenv("APP_PORT", "8123")
    assert S.parse_args([]).port == 8123 and S.parse_args(["--port", "9000"]).port == 9000
    monkeypatch.setenv("APP_PORT", "eight thousand")
    with pytest.raises(SystemExit):
        S.parse_args([])
    monkeypatch.delenv("APP_PORT")
    monkeypatch.delenv("APP_HOST", raising=False)
    a = S.parse_args([])
    assert a.port == 8000 and a.host == "127.0.0.1" and a.model_id


def test_main_warns_when_the_page_is_open_to_the_network_and_needs_a_key(monkeypatch, capsys):
    import uvicorn
    started = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.update(kw))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    S.main(["--no-open", "--model", "haiku"])
    out = capsys.readouterr().out
    assert started["host"] == "127.0.0.1" and "WARNING" not in out and "claude-haiku-5-5" in out and "http://localhost:" in out
    S.main(["--no-open", "--host", "0.0.0.0"])
    assert "WARNING" in capsys.readouterr().out and started["host"] == "0.0.0.0"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your-api-key-here")
    started.clear()
    with pytest.raises(SystemExit) as e:
        S.main(["--no-open"])
    assert "ANTHROPIC_API_KEY" in str(e.value) and started == {}


# ---------- the pretend agent used to build the page ----------
@pytest.mark.parametrize("word", ["figure", "polarity", "duty", "flowchart", "setup", "draw", "broken", "reported this error", "everything"])
def test_every_demo_scenario_only_shows_things_the_real_tools_can_build(word):
    from app.show import render_show
    shown = [render_show(PREFIX + step[1], step[2]) for step in scenario(word) if step[0] == "tool"]
    assert shown and all(s is None or s["kind"] in ("figure", "widget", "artifact") for s in shown), word
    assert any(s is not None for s in shown)


def test_the_demo_covers_every_page_behaviour():
    steps = {w: [s[0] for s in scenario(w)] for w in ("slow", "limit", "budget", "crash", "unsafe", "long", "badfigure", "nothing special")}
    assert "sleep" in steps["slow"] and "result" in steps["limit"] and "result" in steps["budget"] and "raise" in steps["crash"]
    assert scenario("broken")[1][2]["identifier"] == scenario("reported this error")[1][2]["identifier"]  # the retry replaces the same drawing


# ---------- found by the full Haiku run ----------
def test_a_placeholder_drawing_never_reaches_the_page_not_even_as_a_status_line(client):
    evs = ask(client, "placeholder please")
    assert kinds(evs) == ["session", "text", "done"]  # no status, no show, no error card


def test_the_same_picture_or_widget_is_shown_once_per_answer_but_again_in_a_later_answer(client):
    sid_events = ask(client, "twice please")
    shows = [d for n, d in sid_events if n == "show"]
    assert [s["kind"] for s in shows] == ["figure", "widget", "widget"]  # rating label once; two DIFFERENT polarity diagrams both kept
    assert [s["id"] for s in shows if s["kind"] == "figure"] == ["rating-label"]
    sid = sid_events[0][1]["session_id"]
    again = ask(client, "twice again", sid)
    assert [d["kind"] for n, d in again if n == "show"] == ["figure", "widget", "widget"]  # a new answer may show them again


def test_events_for_remembers_what_it_showed_only_when_given_a_seen_set():
    embeds = S.Embeds()
    use = ToolUseBlock(id="1", name=PREFIX + "show_figure", input={"figure_id": "rating-label"})
    msg = AssistantMessage(content=[use, use], model="m")
    assert [n for n, _ in S.events_for(msg, embeds)].count("show") == 1          # within one message
    seen: set = set()
    assert [n for n, _ in S.events_for(AssistantMessage(content=[use], model="m"), embeds, seen)].count("show") == 1
    assert [n for n, _ in S.events_for(AssistantMessage(content=[use], model="m"), embeds, seen)].count("show") == 0  # a later message of the same answer
