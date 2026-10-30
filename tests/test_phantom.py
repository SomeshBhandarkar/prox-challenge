"""An answer that says 'see the picture below' when nothing was shown (app/phantom.py), and what the server does about it."""
import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from starlette.testclient import TestClient

from app import phantom as P
from app import server as S
from app.show import PREFIX
from scripts.dev_server import DemoClient


@pytest.mark.parametrize("text", [
    "See the picture below.", "The picture below shows it.", "The calculator and the label are below.", "see the diagram above",
    "The flowchart below has the full list.", "The rating label picture is below.", "Both screens are shown in the pictures below.",
])
def test_it_notices_an_answer_that_points_at_a_picture(text):
    assert P.points_at_a_picture(text) is True


@pytest.mark.parametrize("text", [
    "Check the list below.", "Which process are you using? Choose one of these:", "A chart of everything is on p.14.",
    "The screen shows 24 V at 200 A.", "Look below the nozzle for spatter.", "", None, "Turn the knob below the screen.",
])
def test_it_leaves_ordinary_sentences_alone(text):
    assert P.points_at_a_picture(text) is False


class Scripted(DemoClient):
    """Answers each question from a plan: a list of steps per question, like the demo agent's scenarios."""
    plan: list = []
    asked: list = []

    async def receive_response(self):
        steps = Scripted.plan[min(len(self.queries) - 1, len(Scripted.plan) - 1)]
        Scripted.asked.append(self.queries[-1])
        for kind, *rest in steps:
            if kind == "text":
                yield AssistantMessage(content=[TextBlock(rest[0])], model="m")
            elif kind == "tool":
                yield AssistantMessage(content=[ToolUseBlock(id="t", name=PREFIX + rest[0], input=rest[1])], model="m")
            elif kind == "error":
                yield AssistantMessage(content=[], model="m", error=rest[0])
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s", total_cost_usd=0.25)


def run(plan):
    Scripted.plan, Scripted.asked = plan, []
    with TestClient(S.create_app(client_factory=Scripted, options_factory=lambda: None, model="haiku", guard_text=False)) as c:
        r = c.post("/api/chat", json={"message": "what voltage is on the label?"})
    import json
    evs = []
    for block in r.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        evs.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return [n for n, _ in evs], evs, list(Scripted.asked)


SHOW = ("tool", "show_figure", {"figure_id": "rating-label"})
POINTS = ("text", "The label gives 24 V at 200 A on 240V MIG. See the picture below.")


def test_a_pointer_to_a_picture_that_was_never_shown_makes_the_server_ask_once_and_the_picture_arrives_in_the_same_answer():
    kinds, evs, asked = run([[POINTS], [SHOW, ("text", "Here is the rating label.")]])
    assert len(asked) == 2 and asked[1].startswith("Automatic note from the app"), asked
    assert kinds == ["session", "status", "show", "text", "done"], kinds   # pictures stream at once; the text is checked, then sent ONCE; ONE done at the end
    assert "Here is the rating label." in dict(evs)["text"]["text"] and "See the picture below" in dict(evs)["text"]["text"]
    assert dict(evs)["done"]["cost_usd"] == 0.25


def test_no_second_question_when_a_picture_was_shown_or_nothing_points_at_one():
    kinds, _, asked = run([[SHOW, POINTS]])
    assert len(asked) == 1 and kinds.count("show") == 1
    _, _, asked = run([[("text", "The label gives 24 V at 200 A on 240V MIG (manual p.14).")]])
    assert len(asked) == 1


def test_the_server_asks_only_once_even_if_the_model_still_shows_nothing():
    kinds, _, asked = run([[POINTS], [POINTS]])
    assert len(asked) == 2 and kinds.count("done") == 1


def test_no_second_question_after_an_error():
    kinds, _, asked = run([[POINTS, ("error", "billing_error")]])
    assert len(asked) == 1 and "error" in kinds and kinds.count("done") == 1


def test_if_the_model_repeats_itself_while_showing_the_picture_the_repeat_is_dropped():
    long_answer = ("text", "The label gives 24 V at 200 A, 20.5 V at 130 A and 19.75 V at 115 A for MIG on 240V, and the open circuit voltage is 86 V, "
                           "all of which you can check in the rating label picture below.")
    kinds, evs, _ = run([[long_answer], [SHOW, long_answer, ("text", "Anything else?")]])
    texts = [d["text"] for n, d in evs if n == "text"]
    assert texts == [long_answer[1] + "\n\n" + "Anything else?"], texts   # the long repeat is gone; the short closing line stays
