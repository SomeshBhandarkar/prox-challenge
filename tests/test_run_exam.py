import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from app.show import PREFIX
from scripts import run_exam as E

QS = E.load_questions()
BY_ID = {q["id"]: q for q in QS}


# ---------- choosing questions ----------
def test_the_exam_file_has_85_questions_and_10_holdouts():
    assert len(QS) == 85 and sum(q["holdout"] for q in QS) == 10


def test_per_category_takes_one_of_each_and_never_a_holdout():
    chosen = E.pick(QS, per_category=1)
    cats = [q["category"] for q in chosen]
    assert len(cats) == len(set(cats)) == len({q["category"] for q in QS if not q["holdout"]})
    assert not any(q["holdout"] for q in chosen)
    assert [q["id"] for q in chosen] == sorted(q["id"] for q in chosen)  # deterministic order


def test_tier_filter_and_holdouts_need_asking_for():
    tier1 = E.pick(QS, tier=1)
    assert tier1 and all(q["tier"] == 1 and not q["holdout"] for q in tier1)
    assert len(E.pick(QS, tier=1, include_holdouts=True)) == 55 > len(tier1)


def test_ids_are_case_insensitive_and_a_named_holdout_is_allowed():
    assert [q["id"] for q in E.pick(QS, ids=["q01", " Q03 "])] == ["Q01", "Q03"]
    assert E.pick(QS, ids=["Q999"]) == []


# ---------- the automatic hints ----------
@pytest.mark.parametrize("answer, item, found", [
    ("The duty cycle is **25%** at 200A.", "25%", True),
    ("Weld for 2.5 minutes, rest 7.5.", "2.5 or 2-1/2 min welding", True),
    ("Weld 2-1/2 min welding then rest", "2.5 or 2-1/2 min welding", True),
    ("Rest for 7.5 minutes", "7.5 or 7-1/2 min rest", True),
    ("The duty cycle is 40%.", "25%", False),
    ("Put the ground clamp in the positive socket", "Positive socket for the ground clamp", True),
    ("I do not know", "Positive socket for the ground clamp", False),
])
def test_must_include_matching_is_lenient_about_wording_but_not_about_numbers(answer, item, found):
    assert E.item_found(answer, item) is found


def test_forbidden_words_and_clarifying_questions_are_flagged():
    q = BY_ID["Q01"]
    ok = E.check_answer("It is 25%: 2.5 minutes welding, 7.5 minutes rest.", q)
    assert ok == {"missing": [], "forbidden": [], "asked_question": False, "should_clarify": False}
    bad = E.check_answer("It is 40% at 200A. Anything else?", q)
    assert bad["forbidden"] == ["40%"] and bad["missing"] and bad["asked_question"] is True


# ---------- running with a fake client (no key, no cost) ----------
class FakeClient:
    def __init__(self, replies, cost=0.002, boom=False):
        self.replies, self.cost, self.boom, self.queries = list(replies), cost, boom, []

    async def __aenter__(self):
        if self.boom:
            raise RuntimeError("network down")
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, text):
        self.queries.append(text)

    async def receive_response(self):
        text, tool = self.replies.pop(0)
        content = ([ToolUseBlock(id="t", name=PREFIX + tool[0], input=tool[1])] if tool else []) + [TextBlock(text)]
        yield AssistantMessage(content=content, model="m")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s",
                            total_cost_usd=self.cost)


def test_a_question_records_tools_shown_pictures_answer_cost_and_checks():
    client = FakeClient([("It is 25%: 2.5 minutes welding and 7.5 minutes rest.", ("show_figure", {"figure_id": "selection-chart"}))])
    r = asyncio.run(E.run_question(BY_ID["Q01"], lambda: client))
    assert client.queries == [BY_ID["Q01"]["question"]] and r["error"] is None and E.flags(r) == []
    (turn,) = r["turns"]
    assert turn["tools"][0]["tool"] == "show_figure" and turn["shown"] == [
        {"kind": "figure", "tool": "show_figure", "id": "selection-chart", "source": "Selection chart"}]
    assert r["cost"] == 0.002 and r["checks"]["missing"] == []


def test_follow_up_questions_are_asked_in_order_as_text_in_the_same_conversation():
    for qid in ("Q70", "Q71"):
        q = BY_ID[qid]
        assert q["follow_ups"] and all(isinstance(f, dict) and isinstance(f["question"], str) for f in q["follow_ups"])  # the real shape
        client = FakeClient([("first", None)] + [("again", None) for _ in q["follow_ups"]])
        r = asyncio.run(E.run_question(q, lambda: client))
        assert client.queries == [q["question"]] + [f["question"] for f in q["follow_ups"]], qid
        assert all(isinstance(t, str) for t in client.queries) and len(r["turns"]) == 1 + len(q["follow_ups"])


def test_each_answer_is_checked_against_its_own_questions_expectations():
    q = BY_ID["Q71"]
    client = FakeClient([("anything", None), ("On 240V that is 60%: 6 minutes welding, 4 minutes rest, from the rating label.", None)])
    r = asyncio.run(E.run_question(q, lambda: client))
    assert r["checks"]["missing"] == [m for m in r["checks"]["missing"] if not m.startswith("turn 2")]  # turn 2 satisfied all its items
    client = FakeClient([("anything", None), ("I do not know.", None)])
    r = asyncio.run(E.run_question(q, lambda: client))
    assert any(m.startswith("turn 2: ") for m in r["checks"]["missing"])


def test_one_failing_question_is_recorded_and_the_run_continues():
    ok = FakeClient([("25% 2.5 minutes welding 7.5 minutes rest", None)])
    clients = iter([FakeClient([], boom=True), ok])
    out = []
    results = asyncio.run(E.run_all([BY_ID["Q01"], BY_ID["Q02"]], lambda: next(clients), 1.0, out.append))
    assert [r["error"] is not None for r in results] == [True, False] and "ERROR" in E.flags(results[0])
    assert "network down" in results[0]["error"] and len(out) == 2


def test_the_run_stops_when_the_total_cap_is_used_up():
    clients = iter([FakeClient([("a", None)], cost=0.2) for _ in range(5)])
    out = []
    results = asyncio.run(E.run_all(E.pick(QS, per_category=1)[:5], lambda: next(clients), 0.25, out.append))
    assert len(results) == 2 and "total cap" in out[-1]  # 0.2 + 0.2 reaches 0.25, so a third question is never started


def test_the_summary_table_lists_every_question_and_the_flags():
    r1 = {"id": "Q01", "category": "duty_cycle_specs", "cost": 0.002, "error": None,
          "turns": [{"tools": [{"tool": "duty_cycle", "input": {}}], "shown": [{"kind": "widget", "title": "Duty cycle calculator"}]}],
          "checks": {"missing": [], "forbidden": [], "asked_question": False, "should_clarify": False}}
    r2 = {**r1, "id": "Q02", "checks": {"missing": ["x"], "forbidden": ["y"], "asked_question": False, "should_clarify": True}}
    md = E.summary_markdown([r1, r2], "claude-haiku-5-5")
    assert "2 questions, 1 flagged" in md and "| Q01 | duty_cycle_specs | duty_cycle | Duty cycle calculator | ok |" in md
    assert "MISSING 1; FORBIDDEN 1; NO-QUESTION" in md


# ---------- the command line ----------
@pytest.mark.parametrize("argv", [[], ["--per-category", "1", "--model", "hiaku"], ["--tier", "3"], ["--ids", "Q01", "--cap", "0"],
                                  ["--ids", "Q01", "--total-cap", "-1"]])
def test_bad_options_stop_before_the_key_is_touched(argv):
    with pytest.raises(SystemExit) as e:
        E.parse_args(argv)
    assert e.value.code == 2


def test_defaults_are_cheap():
    a = E.parse_args(["--per-category", "1"])
    assert a.model_id == "claude-haiku-5-5" and a.cap == 0.05 and a.total_cap == 0.30 and a.include_holdouts is False


# ---------- hints added after the full Haiku run ----------
def test_repeated_text_is_flagged_but_two_different_blocks_are_not():
    block = "Turn the Power Switch off and unplug the welder first. Then move the Ground Clamp Cable to the Positive socket and twist it clockwise to lock it."
    assert E.repeats([block, "Here it is again. " + block]) is True
    assert E.repeats([block, "The manual says the flux-cored wire needs a drag angle of up to fifteen degrees while welding along the joint."]) is False
    assert E.repeats([block]) is False and E.repeats([]) is False and E.repeats(["short", "short"]) is False  # too little text to judge


@pytest.mark.parametrize("answer, narrates", [
    ("I made a stray call that opened a blank card. Please ignore it.", True),
    ("I accidentally loaded the same picture twice, so ignore the duplicate.", True),
    ("I also just opened the flux-cored diagram, which I didn't need.", True),
    ("Use the knurled groove for flux-cored wire (manual p.12).", False),
])
def test_commentary_about_the_agents_own_mistakes_is_flagged(answer, narrates):
    r = {"checks": {"missing": [], "forbidden": [], "asked_question": False, "should_clarify": False}, "error": None,
         "turns": [{"answer": answer, "texts": [answer]}]}
    assert ("NARRATES" in E.flags(r)) is narrates


def test_the_runner_records_what_the_website_would_show_and_each_text_block():
    use = lambda name, **kw: ToolUseBlock(id="t", name=PREFIX + name, input=kw)  # noqa: E731

    class Client(FakeClient):
        async def receive_response(self):
            yield AssistantMessage(content=[TextBlock("first"), use("show_figure", figure_id="rating-label"), use("show_figure", figure_id="rating-label"),
                                            use("create_artifact", identifier="x", type="html", title="noop", code="<p>unused</p>")], model="m")
            yield AssistantMessage(content=[TextBlock("second")], model="m")
            yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", total_cost_usd=0.001)

    r = asyncio.run(E.run_question(BY_ID["Q01"], lambda: Client([])))
    (turn,) = r["turns"]
    assert [s["id"] for s in turn["shown"]] == ["rating-label"]  # the repeat and the silent placeholder are not counted as shown
    assert turn["texts"] == ["first", "second"] and turn["answer"] == "first\nsecond"


@pytest.mark.parametrize("answer, shown, phantom", [
    ("See the MIG setting on the LCD screen below and the TIG gas hookup below that.", [], True),
    ("See the picture below.", [], True),
    ("See the picture below.", [{"kind": "figure"}], False),   # something was shown: fine
    ("Set the flow to 20 to 30 SCFH (manual p.20).", [], False),
])
def test_pointing_at_a_picture_that_was_never_shown_is_flagged(answer, shown, phantom):
    r = {"checks": {"missing": [], "forbidden": [], "asked_question": False, "should_clarify": False}, "error": None,
         "turns": [{"answer": answer, "texts": [answer], "shown": shown}]}
    assert ("PHANTOM" in E.flags(r)) is phantom
