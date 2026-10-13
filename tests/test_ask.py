import asyncio
import re
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from app.show import PREFIX
from scripts import ask as A

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"


def assistant(*blocks, error=None):
    return AssistantMessage(content=list(blocks), model="claude-haiku-5-5", error=error)


def use(name, **args):
    return ToolUseBlock(id="t1", name=PREFIX + name, input=args)


def result(cost=0.001, subtype="success", is_error=False, errors=None):
    return ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=is_error, num_turns=1, session_id="s",
                         total_cost_usd=cost, errors=errors)


class FakeClient:
    """Stands in for ClaudeSDKClient: no network, no key, no cost."""

    def __init__(self, turns):
        self.turns, self.queries, self.options = list(turns), [], None

    def factory(self, options):
        self.options = options
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, question):
        self.queries.append(question)

    async def receive_response(self):
        for message in self.turns.pop(0):
            yield message


def runner(tmp_path, open_pages=False):
    out, opened = [], []
    return A.Runner(tmp_path / "previews", open_pages, out.append, opened.append), out, opened


def feed(r, *messages):
    for m in messages:
        r.handle(m)


# ---------- what the person sees ----------
def test_text_and_lookup_calls_are_printed_and_show_nothing(tmp_path):
    r, out, opened = runner(tmp_path)
    feed(r, assistant(use("duty_cycle", process="MIG", voltage=240, amps=200), TextBlock("It is 25%.")), result())
    text = "\n".join(out)
    assert "[tool] duty_cycle" in text and '"amps": 200' in text and "agent> It is 25%." in text
    assert "SHOWN" not in text and not opened and not (tmp_path / "previews").exists()


def test_a_figure_prints_its_caption_source_and_file_and_opens_only_with_the_flag(tmp_path):
    r, out, opened = runner(tmp_path)
    feed(r, assistant(use("show_figure", figure_id="selection-chart")))
    text = "\n".join(out)
    assert "[FIGURE SHOWN]" in text and "Selection chart" in text and "selection-chart.png" in text and not opened
    r, out, opened = runner(tmp_path, open_pages=True)
    feed(r, assistant(use("show_figure", figure_id="selection-chart")))
    assert len(opened) == 1 and opened[0].startswith("file://") and opened[0].endswith("selection-chart.png")


def test_a_widget_is_saved_and_opened_only_with_the_flag(tmp_path):
    r, out, opened = runner(tmp_path)
    feed(r, assistant(use("show_polarity_diagram", process="tig")))
    files = list((tmp_path / "previews").glob("*.html"))
    assert len(files) == 1 and files[0].read_text().startswith("<!doctype html>") and "add --open" in "\n".join(out) and not opened
    r, out, opened = runner(tmp_path / "b", open_pages=True)
    feed(r, assistant(use("show_polarity_diagram", process="tig")))
    assert len(opened) == 1 and opened[0].endswith(".html") and "add --open" not in "\n".join(out)


def test_an_artifact_is_saved_inside_the_same_sandbox_frame_the_website_uses(tmp_path):
    r, out, _ = runner(tmp_path)
    code = (FIXTURES / "cheat_sheet.html").read_text(encoding="utf-8")
    feed(r, assistant(use("create_artifact", identifier="Cheat Sheet!", type="html", title="Cables", code=code)))
    (page,) = list((tmp_path / "previews").glob("*.html"))
    html = page.read_text()
    assert "[ARTIFACT SHOWN]" in "\n".join(out)
    assert re.findall(r'<iframe[^>]*sandbox="([^"]*)"', html) == ["allow-scripts"]  # the real attribute, nothing more
    assert "cheat-sheet" in page.name


def test_a_failed_show_is_reported_not_raised_and_writes_no_file(tmp_path):
    r, out, _ = runner(tmp_path)
    feed(r, assistant(use("show_figure", figure_id="nope"), use("create_artifact", identifier="x", type="html", title="x", code="<iframe></iframe>")))
    assert "\n".join(out).count("[SHOW FAILED]") == 2 and not (tmp_path / "previews").exists()


def test_page_names_never_collide_across_answers(tmp_path):
    r, _, _ = runner(tmp_path)
    for turn in (1, 2):
        r.turn = turn
        feed(r, assistant(use("show_polarity_diagram", process="tig"), use("show_polarity_diagram", process="tig")))
    assert len(list((tmp_path / "previews").glob("*.html"))) == 4


def test_a_hostile_identifier_cannot_escape_the_previews_folder(tmp_path):
    r, _, _ = runner(tmp_path)
    feed(r, assistant(use("create_artifact", identifier="../../etc/x", type="html", title="t", code="<p>hi</p>" + "<!-- " + "x" * 120 + " -->")))
    (page,) = list((tmp_path / "previews").glob("*.html"))
    assert page.parent == tmp_path / "previews" and "/" not in page.name


# ---------- cost and stopping ----------
def test_the_cost_line_says_what_the_sdk_reports_and_whether_it_is_cumulative(tmp_path):
    r, out, _ = runner(tmp_path)
    feed(r, result(0.0040), result(0.0061), result(0.0020), result(None))
    assert out[0] == "  [cost] SDK reports $0.0040"
    assert "(+$0.0021 since the last answer)" in out[1]
    assert "per-answer figure" in out[2]
    assert "not reported" in out[3]


@pytest.mark.parametrize("subtype, phrase", [("error_max_budget_usd", "spending cap"), ("error_max_turns", "turn limit")])
def test_stopping_early_is_explained(tmp_path, subtype, phrase):
    r, out, _ = runner(tmp_path)
    feed(r, result(0.5, subtype=subtype, is_error=False))
    assert phrase in "\n".join(out) and "[stopped]" in "\n".join(out)


def test_an_api_error_gets_a_hint_that_never_contains_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-123")
    r, out, _ = runner(tmp_path)
    feed(r, assistant(error="authentication_failed"), result(0.0, subtype="error_during_execution", is_error=True, errors=["bad key"]))
    text = "\n".join(out)
    assert "Check ANTHROPIC_API_KEY in .env" in text and "bad key" in text and "sk-ant-secret" not in text


# ---------- asking ----------
def test_ask_sends_the_question_and_prints_the_whole_answer(tmp_path):
    client = FakeClient([[assistant(use("show_figure", figure_id="lcd-optional-settings"), TextBlock("See the picture.")), result()]])
    r, out, _ = runner(tmp_path)
    asyncio.run(A.ask(client, "What are the optional settings?", r))
    assert client.queries == ["What are the optional settings?"] and r.turn == 1
    assert any("agent> See the picture." in line for line in out) and any("FIGURE SHOWN" in line for line in out)


def test_a_huge_question_is_refused_before_anything_is_sent(tmp_path):
    client = FakeClient([])
    r, out, _ = runner(tmp_path)
    asyncio.run(A.ask(client, "x" * 5000, r))
    assert client.queries == [] and r.turn == 0 and "Nothing was sent" in out[0]


# ---------- the command line ----------
def test_defaults_are_the_cheapest_model_and_a_small_cap():
    a = A.parse_args(["hello"])
    assert a.model_id == "claude-haiku-5-5" and a.cap == 0.10 and a.question == ["hello"] and a.open is False
    assert A.parse_args(["--model", "sonnet"]).cap == 0.30
    assert A.parse_args(["--model", "opus"]).cap == 0.50
    assert A.parse_args(["--model", "opus", "--cap", "1.25"]).cap == 1.25 and A.parse_args(["--open"]).open is True


@pytest.mark.parametrize("argv", [["--model", "hiaku"], ["--cap", "0"], ["--cap", "-1"], ["--cap", "nan"], ["--cap", "abc"]])
def test_bad_options_stop_before_any_key_or_client_is_touched(argv):
    with pytest.raises(SystemExit) as e:
        A.parse_args(argv)
    assert e.value.code == 2


def test_run_checks_the_key_before_it_builds_a_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def explode(**kw):
        raise AssertionError("a client was created without a key")
    with pytest.raises(SystemExit) as e:
        asyncio.run(A.run(A.parse_args(["hi"]), client_factory=explode))
    assert "cp .env.example .env" in str(e.value)


def test_one_shot_run_uses_the_locked_down_options_and_the_chosen_model(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000000000")
    client = FakeClient([[assistant(TextBlock("Hi")), result()]])
    out = []
    asyncio.run(A.run(A.parse_args(["hello", "there", "--model", "haiku"]), client.factory, out=out.append, previews=tmp_path))
    assert client.queries == ["hello there"]
    assert client.options.model == "claude-haiku-5-5" and client.options.tools == [] and client.options.max_budget_usd == 0.10


def test_chat_mode_keeps_one_conversation_until_an_empty_line(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000000000")
    client = FakeClient([[assistant(TextBlock("one")), result(0.001)], [assistant(TextBlock("two")), result(0.002)]])
    typed = iter(["first question", "  second question  ", "", "never reached"])
    out = []
    asyncio.run(A.run(A.parse_args([]), client.factory, read=lambda prompt: next(typed), out=out.append, previews=tmp_path))
    assert client.queries == ["first question", "second question"]
    text = "\n".join(out)
    assert "agent> one" in text and "agent> two" in text and "(+$0.0010 since the last answer)" in text


def test_chat_mode_survives_ctrl_d_and_exit_words(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000000000")
    for typed in (iter(["exit"]), iter(["QUIT"])):
        client = FakeClient([])
        asyncio.run(A.run(A.parse_args([]), client.factory, read=lambda p, t=typed: next(t), out=lambda s: None, previews=tmp_path))
        assert client.queries == []

    def eof(prompt):
        raise EOFError
    client = FakeClient([])
    asyncio.run(A.run(A.parse_args([]), client.factory, read=eof, out=lambda s: None, previews=tmp_path))
    assert client.queries == []
