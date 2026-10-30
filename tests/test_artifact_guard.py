"""Drawings the model writes itself may show only what the manual says: no invented numbers, and always a source page (app/guard.artifact_findings)."""
import pytest

from app.artifacts import build_artifact
from app.guard import artifact_findings

pytestmark = pytest.mark.content_guard

BAR_CHART = """<svg viewBox="0 0 400 260" role="img" aria-label="Highest continuous amps on 240V">
<text x="200" y="24" text-anchor="middle">Highest continuous amps, 240V (100% duty cycle)</text>
<rect x="60" y="60" width="70" height="140" fill="#c2410c"/><text x="95" y="52" text-anchor="middle">115 A</text><text x="95" y="220" text-anchor="middle">MIG</text>
<rect x="165" y="76" width="70" height="124" fill="#1d6f42"/><text x="200" y="68" text-anchor="middle">105 A</text><text x="200" y="220" text-anchor="middle">TIG</text>
<rect x="270" y="84" width="70" height="116" fill="#a65e00"/><text x="305" y="76" text-anchor="middle">100 A</text><text x="305" y="220" text-anchor="middle">Stick</text>
<text x="200" y="248" text-anchor="middle">Source: manual p.7</text></svg>"""

DATA_DRIVEN = """<h1>Cable cheat sheet</h1><div id="out"></div><p>Source: manual p.14</p>
<script>var s = window.MANUAL.polarity.setups, out = document.getElementById('out');
Object.keys(s).forEach(function (k) { var d = document.createElement('div'); d.textContent = k + ': ' + s[k].cables.map(function (c) { return c.cable + ' -> ' + c.socket; }).join('; '); out.appendChild(d); });</script>"""


def kinds(code):
    return [f.kind for f in artifact_findings(code)]


def test_the_bar_chart_sonnet_really_drew_from_the_manuals_numbers_is_accepted():
    assert artifact_findings(BAR_CHART) == []
    assert build_artifact("bar-chart", "svg", "Highest continuous amps", BAR_CHART)["ok"] is True


def test_a_drawing_that_reads_window_manual_and_names_its_page_is_accepted():
    assert artifact_findings(DATA_DRIVEN) == []
    assert build_artifact("cable-cheat-sheet", "html", "Cable cheat sheet", DATA_DRIVEN)["ok"] is True


@pytest.mark.parametrize("label", ["about 44%", "0.0299 inch", "15 CFH", "18 volts", "34% duty", "120 IPM"])
def test_a_number_with_a_unit_that_the_manual_does_not_give_is_refused_in_text_and_in_script_labels(label):
    in_text = f"<h1>Settings</h1><p>{label}</p><p>Source: manual p.7</p>" + "<!--" + "x" * 80 + "-->"
    in_script = "<div id='o'></div><p>Source: manual p.7</p><script>document.getElementById('o').textContent = 'Use " + label + " here';</script>" + "<!--" + "x" * 60 + "-->"
    assert kinds(in_text) == ["artifact_number"], label
    assert "artifact_number" in kinds(in_script), label


def test_a_bare_number_that_appears_nowhere_in_the_manual_is_refused():
    assert kinds("<svg viewBox='0 0 100 100'><text>Magic number 7777</text><text>Source: manual p.7</text></svg>") == ["artifact_number"]


def test_a_drawing_with_no_source_page_is_refused_and_a_hidden_comment_does_not_count():
    plain = "<svg viewBox='0 0 100 100'><text>MIG: Positive</text><text>TIG: Negative</text></svg>"
    assert kinds(plain) == ["artifact_source"]
    assert kinds(plain.replace("</svg>", "<!-- Source: manual p.7 --></svg>")) == ["artifact_source"]   # not visible, so not a source
    assert kinds(plain.replace("</svg>", "<text>Source: manual p.7</text></svg>")) == []


def test_coordinates_and_styling_are_not_judged_only_what_a_person_reads():
    art = ("<svg viewBox='0 0 900 700'><rect x='123' y='456' width='789' height='33' style='stroke-width:11px' fill='#123456'/>"
           "<text x='321' y='654'>Positive socket</text><text>Source: manual p.14</text></svg>")
    assert artifact_findings(art) == []


def test_a_refused_drawing_tells_the_model_exactly_why_and_how_to_fix_it():
    result = build_artifact("tips", "html", "Tips", "<h1>Tips</h1><p>Use about 18 volts for thin sheet.</p>" + "<!--" + "x" * 80 + "-->")
    assert result["ok"] is False and result["guard"] is True
    assert "18 volt" in result["message"] and "source" in result["message"] and "window.MANUAL" in result["message"]


def test_the_standard_gauge_numbers_cannot_be_smuggled_into_a_drawing():
    assert "artifact_number" in kinds("<svg viewBox='0 0 100 100'><text>22 gauge = 0.0299 inch</text><text>Source: manual p.20</text></svg>")


def test_a_refused_drawing_is_silent_on_the_page_and_does_not_reach_the_person():
    from app.show import render_show
    shown = render_show("mcp__welder__create_artifact", {"identifier": "tips", "type": "html", "title": "Tips",
                                                           "code": "<h1>Tips</h1><p>Use about 18 volts.</p>" + "<!--" + "x" * 80 + "-->"})
    assert shown["kind"] == "error" and shown["silent"] is True
