from pathlib import Path

import pytest

from app import show
from app.agent_tools import TOOL_NAMES
from app.show import LOOKUPS, PREFIX, render_show

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"
ODD = [None, 5, True, [], {}, "", "x" * 10_000, "<script>alert(1)</script>", float("nan")]


def test_a_figure_call_gives_the_caption_the_source_label_and_a_real_file():
    r = render_show(PREFIX + "show_figure", {"figure_id": "selection-chart-processes"})
    assert r["kind"] == "figure" and r["source"] == "Selection chart" and r["url"] == "/figures/selection-chart-processes.png"
    assert Path(r["path"]).is_file() and r["caption"]
    assert render_show(PREFIX + "show_figure", {"figure_id": "feed-mechanism"})["source"] == "Manual p.12"


@pytest.mark.parametrize("tool, args, title_part", [
    ("show_polarity_diagram", {"process": "tig"}, "Polarity"),
    ("show_duty_cycle_calculator", {"process": "mig", "voltage": 240, "amps": 200}, ""),
    ("show_troubleshooting_flowchart", {"problem_id": "mig-porosity"}, ""),
    ("show_setup_guide", {"process": "mig", "voltage": 240, "material": "steel", "thickness": "22 gauge", "wire_diameter": "0.030"}, "Setup sheet"),
])
def test_every_widget_call_gives_a_self_contained_page(tool, args, title_part):
    r = render_show(PREFIX + tool, args)
    assert r["kind"] == "widget" and r["tool"] == tool and title_part in r["title"]
    assert r["html"].startswith("<!doctype html>") and "</html>" in r["html"]


def test_an_artifact_call_gives_the_wrapped_document_and_refuses_forbidden_tags():
    code = (FIXTURES / "cheat_sheet.html").read_text(encoding="utf-8")
    r = render_show(PREFIX + "create_artifact", {"identifier": "Cable Cheat Sheet", "type": "html", "title": "Cables", "code": code})
    assert r["kind"] == "artifact" and r["identifier"] == "cable-cheat-sheet" and "Content-Security-Policy" in r["html"]
    bad = render_show(PREFIX + "create_artifact", {"identifier": "x", "type": "html", "title": "x", "code": "<iframe src=x></iframe>"})
    assert bad["kind"] == "error" and "html" not in bad


def test_lookups_and_foreign_tools_show_nothing():
    for name in LOOKUPS:
        assert render_show(PREFIX + name, {"process": "mig"}) is None
    for name in (None, 5, [], "", "Bash", "mcp__other__show_figure", "show_figure"):
        assert render_show(name, {}) is None


def test_unknown_welder_tool_is_an_error_not_a_crash():
    assert render_show(PREFIX + "show_unicorn", {})["kind"] == "error"


def test_every_registered_tool_is_either_a_lookup_or_something_that_can_be_shown():
    for full in TOOL_NAMES:
        short = full[len(PREFIX):]
        r = render_show(full, {})
        if short in LOOKUPS:
            assert r is None, short
        else:
            assert r is not None and r["kind"] in ("figure", "widget", "artifact", "error"), short
            assert not (r["kind"] == "error" and "No way to show" in r["message"]), f"{short} is registered but cannot be shown"


@pytest.mark.parametrize("value", ODD, ids=repr)
def test_garbage_input_never_raises(value):
    for full in TOOL_NAMES:
        r = render_show(full, value)
        assert r is None or r["kind"] in ("figure", "widget", "artifact", "error")
        r = render_show(full, {"process": value, "voltage": value, "amps": value, "figure_id": value, "problem_id": value,
                               "identifier": value, "type": value, "title": value, "code": value})
        assert r is None or r["kind"] in ("figure", "widget", "artifact", "error")


def test_a_broken_builder_becomes_an_error_instead_of_stopping_the_answer(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(show, "polarity_widget", boom)
    r = render_show(PREFIX + "show_polarity_diagram", {"process": "tig"})
    assert r["kind"] == "error" and "RuntimeError" in r["message"] and "boom" not in r["message"]


def test_every_catalog_figure_flows_through_the_show_contract_with_a_real_file():
    from app.knowledge import FIGURES
    from app.tools.figures import source_label
    for f in FIGURES:
        r = render_show(PREFIX + "show_figure", {"figure_id": f["id"]})
        assert r["kind"] == "figure" and r["id"] == f["id"], f["id"]
        assert Path(r["path"]).is_file() and r["url"] == f"/figures/{f['id']}.png", f["id"]
        assert r["source"] == source_label(f) and r["caption"] == f["caption"], f["id"]


def test_figure_images_are_a_sensible_size_for_a_web_page():
    from app.tools.figures import FIGURES_DIR
    from app.knowledge import FIGURES
    sizes = {f["id"]: (FIGURES_DIR / f"{f['id']}.png").stat().st_size for f in FIGURES}
    too_big = {k: round(v / 1_000_000, 1) for k, v in sizes.items() if v > 4_000_000}
    assert not too_big, f"figures over 4 MB (lower their dpi): {too_big}"
    assert sum(sizes.values()) < 60_000_000  # the whole library stays clone-friendly


def test_a_refused_placeholder_is_marked_silent_so_the_person_never_hears_about_it():
    r = render_show(PREFIX + "create_artifact", {"identifier": "never-used", "type": "html", "title": "noop", "code": "<p>unused</p>"})
    assert r["kind"] == "error" and r["silent"] is True and "real drawing" in r["message"]
    other = render_show(PREFIX + "create_artifact", {"identifier": "x", "type": "html", "title": "x", "code": "<iframe src=x></iframe>" + "x" * 120})
    assert other["kind"] == "error" and other["silent"] is False  # a real failure is still reported
    assert render_show(PREFIX + "show_figure", {"figure_id": "nope"})["silent"] is False
