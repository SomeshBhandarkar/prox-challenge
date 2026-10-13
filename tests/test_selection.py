import re

import pytest

from app.knowledge import PROCESS_SELECTION, ROOT, SETTINGS
from app.tools.selection import GAUGE_IN, chart_key, chart_limits_in, check_thickness, get_process_info, parse_thickness

CHART = PROCESS_SELECTION["processes"]
MANUAL = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")


def flat(page: int) -> str:
    text = re.split(r"=====PAGE (\d+)=====", MANUAL)
    pages = {int(text[i]): text[i + 1] for i in range(1, len(text), 2)}
    return re.sub(r"\s+", " ", pages[page].replace("|", " ")).lower()


# ---------- the chart data, cross-checked against facts the manual states in TEXT ----------
def test_the_chart_has_the_four_processes_with_every_row():
    assert set(CHART) == {"flux_cored", "mig", "stick", "tig"}
    for key, p in CHART.items():
        for field in ("label", "skill_level", "shielding_gas", "materials", "thickness", "applications", "weld_cleanliness",
                      "use_this_process_because", "material_tags"):
            assert p[field], (key, field)
        assert isinstance(p["gas_required"], bool), key  # False is a real answer here (flux-cored needs no gas)
        assert len(p["applications"]) == 4 and len(p["use_this_process_because"]) == 4


def test_the_skill_levels_and_gas_flags_match_the_chart_as_read():
    assert {k: p["skill_level"] for k, p in CHART.items()} == {"flux_cored": "low", "mig": "low", "stick": "moderate", "tig": "high"}
    assert {k: p["gas_required"] for k, p in CHART.items()} == {"flux_cored": False, "mig": True, "stick": False, "tig": True}


def test_the_chart_agrees_with_what_the_manual_says_in_text():
    assert "flux-cored wire welding is used to weld mild steel and stainless steel without shielding gas" in flat(18)
    assert "mig welding uses solid wire and shielding gas" in flat(18)
    assert "mig welding can also be used to weld thinner workpieces than flux-cored welding can" in flat(18)  # chart: MIG goes thinner
    assert CHART["mig"]["thickness"]["min_gauge"] < CHART["flux_cored"]["thickness"]["min_gauge"] + 99  # sanity
    assert GAUGE_IN[CHART["mig"]["thickness"]["min_gauge"]] < GAUGE_IN[CHART["flux_cored"]["thickness"]["min_gauge"]]
    assert "aluminum welding can be performed with an optional spool gun" in flat(18) and "aluminum" in CHART["mig"]["material_tags"]
    assert "100% argon" in flat(25) and CHART["tig"]["gas_required"] is True
    assert "dc tig welding is used to weld mild steel and stainless steel" in flat(28)
    assert "ac tig welding is used to weld aluminum" in flat(28)
    assert "stick welding is used to weld mild steel and stainless steel using a stick electrode without shielding gas" in flat(28)


def test_the_mig_vs_flux_table_is_consistent_with_the_process_rows():
    rows = {r["feature"]: r for r in PROCESS_SELECTION["mig_or_flux_cored_table"]["rows"]}
    assert len(rows) == 9
    assert rows["Uses shielding gas"]["mig"] is True and CHART["mig"]["gas_required"] is True
    assert rows["Uses shielding gas"]["flux_cored"] is False and CHART["flux_cored"]["gas_required"] is False
    assert rows["Thin materials like sheet metal"]["mig"] is True  # and MIG's chart minimum is the thinner one
    for r in rows.values():  # each row is a check mark in exactly one column
        assert r["mig"] != r["flux_cored"]


def test_the_chart_text_blocks_and_the_duty_cycle_example_are_exact():
    assert PROCESS_SELECTION["duty_cycle_box"]["example"].startswith("165A @ 30% Duty Cycle")
    assert "3 Minutes Welding" in PROCESS_SELECTION["duty_cycle_box"]["example"]
    assert "120 VOLT OR 240 VOLT" in PROCESS_SELECTION["important"]


def test_the_gauge_table_is_in_the_right_order_and_has_the_chart_values():
    ordered = [GAUGE_IN[g] for g in sorted(GAUGE_IN)]
    assert ordered == sorted(ordered, reverse=True)  # higher gauge number = thinner steel
    assert GAUGE_IN[10] == pytest.approx(0.1345, abs=1e-4) and GAUGE_IN[24] == pytest.approx(0.0239, abs=1e-4)
    for key in CHART:
        lo, hi = chart_limits_in(key)
        assert 0 < lo < hi <= 0.5


# ---------- thickness parsing: forgiving about spelling, never guessing a unit ----------
@pytest.mark.parametrize("given, inches", [
    ("22 ga", 0.0299), ("22ga", 0.0299), ("22 GA", 0.0299), ("22 gauge", 0.0299), ("22-gauge", 0.0299), ("22 gage", 0.0299),
    ("22 g", 0.0299), ("10 Gauge", 0.1345),
    ('3/8"', 0.375), ("3/8 in", 0.375), ("3/8 inch", 0.375), ("3 / 8 inch", 0.375), ("3/8", 0.375),
    ("1/4 inches", 0.25), ("0.25 in", 0.25), (".375", 0.375), ("0.5\"", 0.5), ("1\"", 1.0), ("1 in", 1.0),
    ("1-1/2 in", 1.5), ("1 1/2 inch", 1.5), ("3 mm", 3 / 25.4), ("6.5mm", 6.5 / 25.4), ("5/16”", 0.3125),
    (0.25, 0.25), (1, 1.0), (0.0299, 0.0299),
])
def test_thicknesses_are_read_correctly(given, inches):
    assert parse_thickness(given) == pytest.approx(inches, abs=1e-4)


@pytest.mark.parametrize("bad", [
    "22", "thin", "", "   ", None, [], {}, True, False, 0, -1, -0.5, float("nan"), float("inf"), "0 mm", "-3 mm", "3/0 in",
    "99 gauge", "0 ga", "abc ga", "22 ga 5", "3//8", "1/2/3 in", "\x00", "1e3 in", "22 gauge steel please",
])
def test_unreadable_or_ambiguous_thicknesses_are_refused_not_guessed(bad):
    assert parse_thickness(bad) is None


# ---------- the exam questions this exists for ----------
def fits(process, thickness):
    return check_thickness(process, thickness)


def test_q49_the_24_gauge_mig_question():
    r = fits("MIG", "24 gauge")
    assert r["ok"] and r["fits"] is False and r["too"] == "thin" and r["chart_range"] == '22 Gauge to 3/8"'
    assert r["flags"] == ["mig-thin-limit"] and "24Ga" in r["flag_notes"][0]
    assert fits("tig", "24 gauge")["fits"] is True  # TIG's chart range starts at 24
    assert fits("flux-cored", "24 gauge")["fits"] is False


@pytest.mark.parametrize("process, thickness, expected", [
    ("mig", "22 ga", True), ("mig", "3/8", True), ("mig", "0.376 in", False), ("mig", "1/2", False),
    ("flux_cored", "18 ga", True), ("flux_cored", "5/16", True), ("flux_cored", "16 ga", True), ("flux_cored", "20 ga", False), ("flux_cored", "22 ga", False),
    ("flux_cored", "3/8", False), ("stick", "10 ga", True), ("stick", "1/2", True), ("stick", "8 ga", True), ("stick", "12 ga", False), ("stick", "14 ga", False),
    ("stick", "5/8", False), ("tig", "24 ga", True), ("tig", "3/16", True), ("tig", "1/4", False), ("tig", "26 ga", False),
    ("tig", "3 mm", True), ("stick", "10 mm", True), ("stick", "13 mm", False),
])
def test_chart_thickness_limits(process, thickness, expected):
    assert fits(process, thickness)["fits"] is expected, (process, thickness)


def test_the_flag_only_appears_between_the_chart_minimum_and_the_lcd_example():
    assert fits("mig", "24 ga")["flags"] == ["mig-thin-limit"]
    assert fits("mig", "26 ga")["flags"] == []  # thinner than the LCD example too
    assert fits("mig", "22 ga")["flags"] == [] and fits("tig", "26 ga")["flags"] == []


def test_aliases_and_bad_input_never_crash():
    for name in ("MIG", " mig ", "GMAW", "gasless", "flux cored", "Flux-Cored", "stick", "SMAW", "tig", "GTAW"):
        assert chart_key(name) in {"mig", "flux_cored", "stick", "tig"}
    for bad in (None, 5, [], {}, "", "plasma", "m-i-g", "stig", "STIG"):
        assert chart_key(bad) is None
        assert check_thickness(bad, "22 ga")["ok"] is False and get_process_info(bad)["found"] is False
    for bad_t in (None, [], {}, "x", float("nan"), "99 gauge"):
        r = check_thickness("mig", bad_t)
        assert r["ok"] is False and "thickness" in r["message"]


def test_the_gauge_conversion_is_always_labelled_as_not_from_the_manual():
    r = check_thickness("mig", "22 ga")
    assert "NOT from the manual" in r["gauge_note"]


def test_process_info_bundles_the_chart_and_the_manuals_settings():
    for key in ("mig", "flux_cored", "tig", "stick"):
        info = get_process_info(key)
        assert info["found"] and info["chart"]["label"] and info["settings"]["label"] and info["lcd"]["steps"] and info["power"]
    assert get_process_info("gasless")["key"] == "flux_cored"
    assert get_process_info("mig")["lcd"] is SETTINGS["lcd"]["wire"] or get_process_info("mig")["lcd"] == SETTINGS["lcd"]["wire"]
