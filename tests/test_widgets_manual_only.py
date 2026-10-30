"""Everything the app shows WITHOUT the model (the widgets and tool messages) is manual-only too: no outside wording, no number the manual does not give."""
import html as _html
import json
import re

import pytest

from app import guard as G
from app.tools import troubleshooting as TR
from app.widgets.duty_cycle import duty_cycle_widget
from app.widgets.polarity import polarity_widget
from app.widgets.setup_guide import setup_guide_widget
from app.widgets.troubleshooting import troubleshooting_widget


def readable(page: str) -> str:
    """What a person can read in a widget: its visible text, every string VALUE in its JSON data (not the keys), and the string labels in its script."""
    strings = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            strings.append(node)

    for block in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', page, re.S):
        try:
            walk(json.loads(block))
        except ValueError:
            strings.append(block)
    js = " ".join(re.findall(r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", page, re.S))
    labels = " ".join(m.group(2) for m in G._LITERAL.finditer(js))
    visible = _html.unescape(re.sub(r"<[^>]+>", " ", G._NOT_VISIBLE.sub(" ", page)))
    return " ".join([visible, labels] + strings)


def pages():
    out = {}
    for proc in ("mig", "flux_cored", "tig", "stick", "spool_gun"):
        out[f"polarity {proc}"] = polarity_widget(proc)["html"]
    for proc in ("mig", "tig", "stick"):
        for volt in (120, 240):
            for amps in (60, 100, 150, 200, 215):
                out[f"duty {proc} {volt} {amps}"] = duty_cycle_widget(proc, volt, amps)["html"]
    for section in TR.TROUBLESHOOTING["sections"]:
        for problem in section["problems"]:
            out[f"flowchart {problem['id']}"] = troubleshooting_widget(problem["id"])["html"]
    for kw in ({"process": "mig", "voltage": 240, "material": "steel", "thickness": "1/8 inch", "wire_diameter": "0.030"},
               {"process": "tig", "voltage": 120, "material": "stainless steel", "thickness": "22 gauge"},
               {"material": "aluminum", "thickness": "3/16 inch", "outdoors": True}, {"process": "stick", "voltage": 240, "material": "steel", "thickness": "1/2 inch"},
               {"process": "flux_cored", "material": "steel", "thickness": "5/16 inch", "outdoors": True, "gas_ok": False, "skill": "beginner"}):
        out[f"setup {kw}"] = setup_guide_widget(**kw)["html"]
    return out


PAGES = pages()


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_widget_says_nothing_beyond_the_manual(name):
    text = readable(PAGES[name])
    marker = G.OUTSIDE_MARKERS.search(G._QUOTED.sub(" ", text))
    assert marker is None, f"{name}: outside wording '{marker.group(0)}' in ...{text[max(0, marker.start() - 80): marker.end() + 60]}..."
    slider = {(float(a), "amp") for a in range(10, 221)} if name.startswith("duty") else set()   # the calculator echoes the current the person picks
    bad = sorted({f"{v:g} {u}" for v, u in G.number_unit_pairs(text) if (v, u) not in G.allowed_pairs() and (v, u) not in slider})
    assert not bad, f"{name}: numbers the manual does not give: {bad}"


def test_the_audit_itself_can_fail_it_notices_outside_wording_and_an_invented_number():
    page = "<html><body><p>General advice, not from the manual: use about 44% at 150A.</p></body></html>"
    text = readable(page)
    assert G.OUTSIDE_MARKERS.search(text) and (44.0, "percent") not in G.allowed_pairs()


def test_a_between_rated_points_calculator_shows_no_number_and_no_advice():
    text = readable(duty_cycle_widget("mig", 240, 150)["html"])
    assert "gives no duty cycle for 150A" in text and "plan" not in text.lower().replace("explanation", "") and "estimate" not in text.lower()
