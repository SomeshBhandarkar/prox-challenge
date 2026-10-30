"""How one answer goes from the model's draft to the person (app/answering.py): check, rewrite once, remove, or fall back."""
import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from app import answering as A
from app import guard as G
from app import server as S
from app.guard import Finding
from app.show import PREFIX

GOOD = ("At 200A on 240V the MIG duty cycle is 25% (manual p.7). That means 2.5 minutes of welding and 7.5 minutes of rest in every 10 minutes (manual p.19). "
        "Leave the Power Switch ON so the fan can cool it (manual p.23).")
BAD = GOOD + " General advice, not from the manual: 240V gives you more current range."
SHOW = ("tool", "show_figure", {"figure_id": "rating-label"})


class Scripted:
    """A pretend model: question number n is answered with plan[n] (a list of steps)."""

    def __init__(self, plan, cost=0.25):
        self.plan, self.cost, self.asked = plan, cost, []

    async def query(self, text):
        self.asked.append(text)

    async def receive_response(self):
        steps = self.plan[min(len(self.asked) - 1, len(self.plan) - 1)]
        for kind, *rest in steps:
            if kind == "text":
                yield AssistantMessage(content=[TextBlock(rest[0])], model="m")
            elif kind == "tool":
                yield AssistantMessage(content=[ToolUseBlock(id="t", name=PREFIX + rest[0], input=rest[1])], model="m")
            elif kind == "error":
                yield AssistantMessage(content=[], model="m", error=rest[0])
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", total_cost_usd=self.cost)


def run(plan, question="what is the duty cycle?", judge=None, guard_text=True):
    client, events, outcome = Scripted(plan), [], A.Outcome()
    asyncio.run(A.answer(client, question, S.Embeds(), lambda e, d: events.append((e, d)), S.events_for, judge=judge, guard_text=guard_text, outcome=outcome))
    return client, events, outcome


def texts(events):
    return [d["text"] for e, d in events if e == "text"]


def kinds(events):
    return [e for e, _ in events]


class Judge:
    """A pretend fact-checker: flags any sentence containing one of `flag`, and records what it was asked."""

    def __init__(self, flag=(), result="ok"):
        self.flag, self.result, self.asked = flag, result, []

    async def __call__(self, answer, question):
        self.asked.append(answer)
        if self.result == "boom":
            raise RuntimeError("judge down")
        if self.result is None:
            return None
        return [Finding("checker", s, "not in the manual") for s in G.split_sentences(answer) if any(f in s for f in self.flag)]


def test_a_clean_answer_is_shown_once_after_both_checks_with_one_done():
    judge = Judge()
    client, events, out = run([[("text", GOOD)]], judge=judge)
    assert texts(events) == [GOOD] and kinds(events) == ["text", "done"] and len(client.asked) == 1
    assert judge.asked == [GOOD] and out.violated is False and out.judge_used is True


def test_pictures_stream_at_once_but_the_text_waits_for_the_checks_and_done_comes_last():
    _, events, _ = run([[("text", GOOD), SHOW]])
    assert kinds(events) == ["status", "show", "text", "done"]


def test_a_draft_with_outside_wording_is_never_shown_the_model_is_asked_once_to_rewrite_and_only_the_rewrite_is_shown():
    judge = Judge()
    client, events, out = run([[("text", BAD)], [("text", GOOD)]], judge=judge)
    assert texts(events) == [GOOD] and len(client.asked) == 2
    assert "General advice, not from the manual" in client.asked[1] and G.FALLBACK in client.asked[1]   # it is told exactly what was wrong
    assert out.rewritten and out.violated and out.removed == [] and out.fallback is False
    assert judge.asked == [GOOD]   # the word-level guard objected first, so the checker only judged the rewrite


def test_a_rewrite_is_not_thrown_away_as_a_repeat_of_the_draft_it_replaces():
    near = GOOD + " General advice, not from the manual: use less current on thin sheet."
    _, events, _ = run([[("text", near)], [("text", GOOD)]])
    assert texts(events) == [GOOD]


def test_if_the_rewrite_still_goes_beyond_the_manual_the_offending_sentence_is_removed_not_shown():
    client, events, out = run([[("text", BAD)], [("text", BAD)]])
    (shown,) = texts(events)
    assert "General advice" not in shown and "25%" in shown and "fan can cool it" in shown
    assert len(client.asked) == 2 and out.removed and out.fallback is False   # never a third question


def test_when_nothing_trustworthy_is_left_the_person_gets_the_no_information_message_with_the_support_number():
    junk = "Typically you would use 15 CFH. Most welders find 18 volts works. I'd recommend checking reviews online."
    _, events, out = run([[("text", junk)], [("text", junk)]])
    assert texts(events) == [f"{G.FALLBACK} {G.SUPPORT}"] and out.fallback is True


def test_the_fact_checker_can_object_to_a_draft_the_word_level_guard_passed():
    sneaky = GOOD + " Buy a small spool first and test it on scrap."
    judge = Judge(flag=["small spool"])
    client, events, out = run([[("text", sneaky)], [("text", GOOD)]], judge=judge)
    assert texts(events) == [GOOD] and out.rewritten and "Buy a small spool" in client.asked[1]
    assert len(judge.asked) == 2   # once on the draft, once on the rewrite (a second opinion on what will be shown)


def test_if_the_checker_still_objects_after_the_rewrite_that_sentence_is_removed():
    sneaky = GOOD + " Buy a small spool first and test it on scrap."
    judge = Judge(flag=["small spool"])
    _, events, out = run([[("text", sneaky)], [("text", sneaky)]], judge=judge)
    (shown,) = texts(events)
    assert "spool" not in shown and "25%" in shown and out.removed


@pytest.mark.parametrize("judge", [None, Judge(result=None), Judge(result="boom")])
def test_if_the_fact_checker_is_off_or_fails_the_answer_still_goes_through_the_word_level_guard(judge):
    client, events, out = run([[("text", GOOD)]], judge=judge)
    assert texts(events) == [GOOD] and len(client.asked) == 1 and out.rewritten is False
    client, events, _ = run([[("text", BAD)], [("text", GOOD)]], judge=judge)
    assert texts(events) == [GOOD]


def test_the_demo_switch_skips_the_manual_only_checks_but_not_the_picture_follow_up():
    client, events, _ = run([[("text", BAD)]], guard_text=False)
    assert texts(events) == [BAD] and len(client.asked) == 1
    client, events, _ = run([[("text", "See the picture below.")], [SHOW, ("text", "Here it is.")]], guard_text=False)
    assert len(client.asked) == 2 and "show" in kinds(events)


def test_an_answer_that_ended_in_an_error_is_passed_through_unchecked():
    client, events, _ = run([[("text", BAD), ("error", "rate_limit")]], judge=Judge())
    assert len(client.asked) == 1 and any(e == "error" for e, _ in events) and "done" in kinds(events)


def test_a_draft_that_points_at_a_picture_and_breaks_the_rules_gets_ONE_follow_up_covering_both():
    bad_pointer = BAD + " See the picture below."
    client, events, _ = run([[("text", bad_pointer)], [SHOW, ("text", GOOD + " See the picture below.")]])
    assert len(client.asked) == 2 and "show tool" in client.asked[1] and "General advice" in client.asked[1]
    assert kinds(events).count("show") == 1 and "General advice" not in texts(events)[0]


def test_a_rewrite_that_writes_nothing_falls_back_to_cleaning_the_first_draft():
    _, events, out = run([[("text", BAD)], [SHOW]])
    (shown,) = texts(events)
    assert "General advice" not in shown and "25%" in shown and out.removed


def test_the_no_information_answer_itself_is_never_rewritten():
    judge = Judge()
    client, events, _ = run([[("text", G.FALLBACK)]], judge=judge)
    assert texts(events) == [G.FALLBACK] and len(client.asked) == 1


def test_the_cost_reported_is_the_last_one_so_it_includes_the_rewrite():
    client = Scripted([[("text", BAD)], [("text", GOOD)]])
    events = []
    client.cost = 0.31
    asyncio.run(A.answer(client, "q", S.Embeds(), lambda e, d: events.append((e, d)), S.events_for))
    assert [d for e, d in events if e == "done"] == [{"ok": True, "cost_usd": 0.31}]
