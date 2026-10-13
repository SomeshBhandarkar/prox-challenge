"""Stress tests found during the checkpoint pass: odd inputs must never crash a tool, and the numbers must stay sane."""
import asyncio
import re

import pytest

from app import agent_tools as T
from app.prompt import INSTRUCTIONS
from app.tools.data import get_duty_cycle, get_polarity, normalize_process, normalize_voltage
from app.tools.figures import show_figure
from app.tools.manual import view_manual_page
from app.tools.troubleshooting import get_troubleshooting
from app.widgets.duty_cycle import duty_cycle_widget
from app.widgets.polarity import polarity_widget

ODD = [None, 5, 5.5, True, [], ["tig"], {}, {"a": 1}, "", "  ", "\n", "x" * 10_000, "<script>alert(1)</script>", float("nan"), float("inf")]
TOOLS = [T.duty_cycle, T.polarity, T.view_page, T.show_figure, T.show_polarity_diagram, T.show_duty_cycle_calculator,
         T.show_troubleshooting_flowchart, T.show_setup_guide, T.create_artifact]


@pytest.mark.parametrize("value", ODD, ids=repr)
def test_lookups_never_crash_on_odd_input(value):
    normalize_process(value)
    normalize_voltage(value)
    assert get_polarity(value)["found"] in (True, False)
    assert show_figure(value)["ok"] is False or isinstance(value, str)
    assert view_manual_page(value)["ok"] in (True, False)
    assert get_troubleshooting(value)["found"] is False
    assert get_duty_cycle(value, 240, 100)["status"] == "invalid"
    assert get_duty_cycle("MIG", value, 100)["status"] == "invalid"
    assert polarity_widget(value)["ok"] in (True, False)
    assert duty_cycle_widget(value, 240, 100)["ok"] is False


@pytest.mark.parametrize("amps", [float("nan"), float("inf"), float("-inf"), True, False, 0, -1, "200", [], {}], ids=repr)
def test_bad_amps_are_rejected_not_classified_and_never_crash(amps):
    r = get_duty_cycle("MIG", 240, amps)
    assert r["status"] == "invalid" and "duty_percent" not in r
    assert duty_cycle_widget("MIG", 240, amps)["ok"] is False


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
@pytest.mark.parametrize("args", [
    {},
    {"process": None, "voltage": None, "amps": None, "page": None, "figure_id": None},
    {"process": ["x"], "voltage": "abc", "amps": float("nan"), "page": True, "figure_id": {"a": 1}},
    {"process": "x" * 10_000, "voltage": 10**12, "amps": 1e308, "page": -10**12, "figure_id": "../../.env"},
], ids=["empty", "nones", "wrong-types", "huge"])
def test_every_tool_survives_garbage_arguments(tool, args):
    r = asyncio.run(tool.handler(args))
    assert isinstance(r["content"], list) and r["content"]
    assert all(block["type"] in ("text", "image") for block in r["content"])


def test_tool_list_and_names_stay_in_sync():
    assert T.TOOL_NAMES == ["mcp__welder__" + t.name for t in TOOLS]


def test_the_prompt_mentions_every_tool_and_only_real_ones():
    short = [n.removeprefix("mcp__welder__") for n in T.TOOL_NAMES]
    for name in short:
        assert name in INSTRUCTIONS, f"{name} is registered but the prompt never tells Claude about it"
    for token in set(re.findall(r"\b(?:show_[a-z_]+|view_manual_page)\b", INSTRUCTIONS)):
        assert token in short, f"the prompt mentions {token}, which is not a registered tool"


def test_duty_cycle_sweep_is_sane_across_every_process_voltage_and_half_amp():
    allowed = {"continuous", "rated_point", "between_rated_points", "above_highest_rated_point",
               "exceeds_machine_range", "below_machine_range"}
    for proc in ("MIG", "TIG", "Stick"):
        for volt in (120, 240):
            last_percent = 100
            for tenth in range(1, 3001):  # 0.1 A .. 300 A
                amps = tenth / 10
                r = get_duty_cycle(proc, volt, amps)
                assert r["status"] in allowed, (proc, volt, amps, r["status"])
                if "duty_percent" in r:
                    assert r["duty_percent"] <= last_percent, f"duty cycle rose at {proc} {volt}V {amps}A"
                    last_percent = r["duty_percent"]
                    assert r["weld_minutes_per_10"] + r["rest_minutes_per_10"] == 10
                if r["status"] == "between_rated_points":
                    assert "NOT in the manual" in r["estimate"]["note"]
                    assert r["duty_percent"] == r["bracketing_points"][1]["percent"]  # plan with the safer, higher-amp point
                if r["status"] in ("exceeds_machine_range", "below_machine_range"):
                    assert "duty_percent" not in r
