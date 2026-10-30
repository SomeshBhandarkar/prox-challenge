"""The model-based fact-checker (app/judge.py), tested with pretend models: no network, no cost."""
import asyncio
import json
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from app import judge as J

ANSWER = "Set the flow to 20-30 SCFH (manual p.20). Buy a small spool first. Which process are you using? Use 100% argon for TIG (manual p.25)."


def test_the_answer_is_sent_as_numbered_sentences_and_questions_are_left_out():
    listing, sentences = J.numbered(ANSWER)
    assert sentences == ["Set the flow to 20-30 SCFH (manual p.20).", "Buy a small spool first.", "Use 100% argon for TIG (manual p.25)."]
    assert listing.splitlines()[1] == "2. Buy a small spool first."


@pytest.mark.parametrize("reply, expected", [
    ('{"unsupported": [{"n": 2, "why": "advice"}]}', ["Buy a small spool first."]),
    ('Here is my verdict:\n```json\n{"unsupported": [{"n": 2, "why": "advice"}, {"n": 3, "why": "x"}]}\n```', ["Buy a small spool first.", "Use 100% argon for TIG (manual p.25)."]),
    ('{"unsupported": []}', []),
    ('{"unsupported": [{"n": 99, "why": "out of range"}]}', []),       # a number that is not a sentence is ignored
])
def test_the_checkers_reply_becomes_findings(reply, expected):
    _, sentences = J.numbered(ANSWER)
    assert [f.sentence for f in J.parse(reply, sentences)] == expected


@pytest.mark.parametrize("reply", ["", "I think it is fine.", "{not json}", '{"unsupported": "all of it"}', '{"other": []}', None])
def test_a_reply_that_cannot_be_understood_means_no_second_opinion_not_a_verdict(reply):
    assert J.parse(reply, ["a sentence"]) is None


class Pretend:
    """Stands in for the SDK client: answers whatever it is asked with a fixed reply (or fails)."""
    queries: list = []

    def __init__(self, reply=None, boom=False, hang=False):
        self.reply, self.boom, self.hang = reply, boom, hang

    def __call__(self, options=None):
        Pretend.options = options
        return self

    async def __aenter__(self):
        if self.boom:
            raise RuntimeError("network down")
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, text):
        Pretend.queries.append(text)

    async def receive_response(self):
        if self.hang:
            await asyncio.sleep(10)
        yield AssistantMessage(content=[TextBlock(self.reply)], model="m")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", total_cost_usd=0.001)


def run(reply=None, **kw):
    Pretend.queries = []
    return asyncio.run(J.check_with_model(ANSWER, "how do I set up gas?", factory=Pretend(reply, **kw), options=object()))


def test_the_checker_sends_the_question_and_the_numbered_answer_and_returns_what_it_finds():
    found = run('{"unsupported": [{"n": 2, "why": "advice"}]}')
    assert [f.sentence for f in found] == ["Buy a small spool first."] and found[0].kind == "checker" and found[0].detail == "advice"
    sent = Pretend.queries[0]
    assert "how do I set up gas?" in sent and "2. Buy a small spool first." in sent and "Which process" not in sent


def test_any_failure_of_the_checker_is_no_opinion_never_a_crash():
    assert run(boom=True) is None
    assert run("garbage") is None
    J.TIMEOUT_SECONDS, old = 0.05, J.TIMEOUT_SECONDS
    try:
        assert run('{"unsupported": []}', hang=True) is None
    finally:
        J.TIMEOUT_SECONDS = old


def test_an_answer_with_nothing_to_judge_is_not_sent_to_the_model_at_all():
    Pretend.queries = []
    assert asyncio.run(J.check_with_model("Which process are you using?", "q", factory=Pretend("{}"), options=object())) == []
    assert Pretend.queries == []


def test_the_checker_is_locked_down_has_only_the_manual_as_its_source_and_runs_on_the_small_model():
    o = J.build_judge_options()
    assert o.tools == [] and o.allowed_tools == [] and o.setting_sources == [] and o.max_turns == 1 and o.mcp_servers in ({}, None)
    assert o.model == "claude-haiku-5-5"
    prompt = Path(o.system_prompt["path"]).read_text(encoding="utf-8")  # handed to the engine as a file (see app/agent.py prompt_file)
    assert "ONLY what the owner's manual says" in prompt and "OWNER'S MANUAL (full text" in prompt
    assert "Rewording is fine; adding is not" in prompt and '{"unsupported"' in prompt
    assert "show_figure" not in prompt.split("SOURCES")[0]   # it is a judge, not the assistant: none of the assistant's tool rules


def test_bare_pointers_and_support_referrals_are_not_sent_to_the_fact_checker_but_real_claims_are():
    from app.judge import numbered
    answer = ("The manual gives 25% at 200A on 240V (manual p.7).\n"
              "The specification table is shown below.\n"
              "For anything beyond the manual, call Harbor Freight support at 1-800-444-3353.\n"
              "Flux-cored welds cleaner than MIG, see the chart below.\n"
              "Is that clear?")
    listing, sentences = numbered(answer)
    assert sentences == ["The manual gives 25% at 200A on 240V (manual p.7).", "Flux-cored welds cleaner than MIG, see the chart below."]
    assert listing.startswith("1. The manual gives")


def test_the_checkers_rules_say_pointers_and_the_manuals_own_support_line_are_supported():
    from app.judge import JUDGE_RULES
    assert "shown below" in JUDGE_RULES and "1-800-444-3353" in JUDGE_RULES and "never the pointer" in JUDGE_RULES


def test_the_required_fallback_sentence_is_never_sent_to_the_fact_checker():
    # found in the first real strict-mode run: the checker objected to "There is no specific information in the manual..." itself
    from app.guard import FALLBACK
    from app.judge import numbered
    _, sentences = numbered(f"{FALLBACK} The manual gives 25% at 200A on 240V (manual p.7).")
    assert sentences == ["The manual gives 25% at 200A on 240V (manual p.7)."]
    assert numbered(FALLBACK) == ("", [])
