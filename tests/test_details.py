"""Tap-to-answer questions (app/tools/details.py, the ask_for_details tool): the buttons come from verified data, never from the model."""
import asyncio

import pytest

from app import agent_tools as T
from app.knowledge import TROUBLESHOOTING
from app.show import render_show
from app.tools import details as D
from app.tools.data import get_polarity


def labels(group):
    return [o["label"] for o in group["options"]]


def test_each_topic_builds_a_group_with_buttons_taken_from_the_data():
    r = D.build_choices(list(D.TOPICS))
    assert r["ok"] is False                      # six topics is more than the limit of five
    r = D.build_choices(["process", "voltage", "material", "thickness", "wire_size"])
    assert r["ok"] and [g["id"] for g in r["groups"]] == ["process", "voltage", "material", "thickness", "wire_size"]
    by = {g["id"]: g for g in r["groups"]}
    assert labels(by["voltage"]) == ["120V", "240V"]                                   # read from the specifications
    assert [o["value"] for o in by["wire_size"]["options"]] == ["0.025 inch", "0.030 inch", "0.035 inch", "0.045 inch"]   # the p.7 wire sizes
    assert [o["value"] for o in by["process"]["options"]] == ["MIG", "flux-cored", "TIG", "Stick"]
    assert by["material"]["free_text"] and by["thickness"]["free_text"] and not by["process"]["free_text"]


def test_the_symptom_buttons_are_exactly_the_manuals_troubleshooting_problems():
    (group,) = D.build_choices(["symptom"])["groups"]
    problems = [p["problem"] for s in TROUBLESHOOTING["sections"] for p in s["problems"]]
    assert len(group["options"]) == len(problems) == 13
    for option, problem in zip(group["options"], problems):
        assert option["value"].startswith(problem) and option["value"].endswith(("(MIG or flux-cored)", "(TIG or Stick)"))
    assert len({o["value"] for o in group["options"]}) == 13   # names two sections share ("Weak Arc Strength") stay distinguishable


def test_every_process_button_is_a_process_the_polarity_lookup_understands():
    (group,) = D.build_choices(["process"])["groups"]
    assert all(get_polarity(o["value"])["found"] for o in group["options"])


@pytest.mark.parametrize("topics", [None, [], "process", ["colour"], ["process", 5], [None], {"process": 1}, ["process", "voltage", "material", "thickness", "wire_size", "symptom"]])
def test_odd_requests_are_refused_with_a_message_not_a_crash(topics):
    r = D.build_choices(topics)
    assert r["ok"] is False and r["message"]


def test_topics_are_case_insensitive_and_repeats_are_dropped():
    r = D.build_choices(["Process", " VOLTAGE ", "process"])
    assert r["ok"] and [g["id"] for g in r["groups"]] == ["process", "voltage"]


def test_the_model_cannot_add_an_option_it_only_picks_topics():
    r = D.build_choices(["process"])
    again = D.build_choices(["process", "voltage"])
    assert r["groups"][0] == again["groups"][0]
    assert "<" not in str(r) and "script" not in str(r).lower()   # nothing but plain names


def test_the_show_contract_turns_the_call_into_a_choices_card_and_a_bad_call_into_an_error():
    ok = render_show("mcp__welder__ask_for_details", {"topics": ["process", "voltage"]})
    assert ok["kind"] == "choices" and ok["tool"] == "ask_for_details" and len(ok["groups"]) == 2 and ok["title"]
    bad = render_show("mcp__welder__ask_for_details", {"topics": ["nonsense"]})
    assert bad["kind"] == "error" and "not a topic" in bad["message"]
    assert render_show("mcp__welder__ask_for_details", None)["kind"] == "error"


def test_through_the_mcp_layer_the_tool_lists_a_topic_enum_and_answers_both_good_and_bad_calls():
    handlers = T.server["instance"]._request_handlers
    lst, call = handlers["tools/list"], handlers["tools/call"]

    async def go():
        tools = (await lst.handler(None, lst.params_type())).tools
        schema = next(t for t in tools if t.name == "ask_for_details").input_schema
        ask = lambda args: call.handler(None, call.params_type(name="ask_for_details", arguments=args))  # noqa: E731
        return schema, await ask({"topics": ["process"]}), await ask({"topics": ["bogus"]}), await ask({})
    schema, good, bad, empty = asyncio.run(go())
    text = lambda r: r.content[0].text  # noqa: E731
    assert schema["properties"]["topics"]["items"]["enum"] == list(D.TOPICS) and schema["required"] == ["topics"]
    assert "now shown" in text(good) and not good.is_error
    # the MCP layer checks the schema before our code runs: a made-up topic and a missing list never reach the builder
    assert bad.is_error and "is not one of" in text(bad) and empty.is_error and "required" in text(empty)


@pytest.mark.parametrize("sentence", ["I need a few details first: tap your answers below.", "To set this up I need a few details. Tap your answers below.",
                                      "I need to know a little more first: tap what it is doing.", "Tap the buttons below to tell me about your job."])
@pytest.mark.parametrize("question", ["What settings should I use?", "It's not working right."])
def test_the_one_sentence_that_goes_with_the_buttons_is_never_flagged_by_the_guard(sentence, question):
    from app import guard as G
    assert G.check(sentence, question).ok   # otherwise every clarifying question would trigger a pointless rewrite


def test_the_checkers_rules_accept_a_request_for_details_and_a_pointer_to_the_buttons():
    from app.judge import JUDGE_RULES
    assert "a request for details" in JUDGE_RULES and "tap your answers below" in JUDGE_RULES and "buttons" in JUDGE_RULES
