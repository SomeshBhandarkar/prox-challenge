import re
from html import unescape

import pytest

from app.knowledge import POLARITY
from app.widgets.polarity import polarity_widget

PROCESSES = list(POLARITY["setups"])


def _drawn(html: str) -> dict:
    return {s: unescape(c) for s, c in re.findall(r'data-socket="(\w+)" data-cable="([^"]*)"', html)}


@pytest.mark.parametrize("key", PROCESSES)
def test_diagram_matches_the_verified_data_for_every_process(key):
    expected = {c["socket"]: c["cable"] for c in POLARITY["setups"][key]["cables"]}
    assert _drawn(polarity_widget(key)["html"]) == expected


def test_tig_ground_clamp_positive_torch_negative():
    drawn = _drawn(polarity_widget("tig")["html"])
    assert drawn == {"negative": "TIG Torch Cable", "positive": "Ground Clamp Cable"}


def test_mig_and_flux_cored_are_opposite():
    mig = _drawn(polarity_widget("mig")["html"])
    flux = _drawn(polarity_widget("flux-cored")["html"])
    assert mig["negative"] == "Ground Clamp Cable" and mig["positive"] == "Wire Feed Power Cable"
    assert flux["positive"] == "Ground Clamp Cable" and flux["negative"] == "Wire Feed Power Cable"


def test_aliases_work():
    for alias in ("gasless", "GTAW", " Stick ", "aluminum"):
        assert polarity_widget(alias)["ok"] is True


def test_unknown_process_gives_an_error_and_no_diagram():
    w = polarity_widget("plasma")
    assert w["ok"] is False and "html" not in w and "Known" in w["message"]


def test_output_is_self_contained_and_script_free():
    html = polarity_widget("mig")["html"]
    assert html.startswith("<!doctype html>") and "<script" not in html.lower()
    assert "http://" not in html and "https://" not in html  # no external resources


def test_every_socket_has_a_sign_and_a_label_not_just_color():
    html = polarity_widget("stick")["html"]
    assert "Negative (−) socket" in html and "Positive (+) socket" in html
    assert ">−<" in html and ">+<" in html


def test_sources_are_shown():
    assert "manual p14" in polarity_widget("mig")["html"]
