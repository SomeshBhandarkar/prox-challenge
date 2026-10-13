import json
import re

import pytest

from app.knowledge import SETTINGS
from app.tools.setup_guide import (GROOVE, ORDER, ROLLER, TENSION, WIRE_SIZES, build_setup, choose_process, digest,
                                   get_setup_guide, normalize_material, parse_wire_diameter)
from app.widgets.setup_guide import setup_guide_widget

ODD = [None, 5, 5.5, True, [], ["tig"], {}, {"a": 1}, "", "  ", "\n", "x" * 10_000, "<script>alert(1)</script>", float("nan"), float("inf")]


def status(g: dict) -> dict:
    return {c["id"]: c["status"] for c in g["checks"]}


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S))


# ---------- reading what people type ----------
@pytest.mark.parametrize("given, inches", [(".030", 0.03), ("0.030", 0.03), ('0.030"', 0.03), (".035 in", 0.035), (" 0.045 inch ", 0.045),
                                          ("0.025 INCHES", 0.025), (0.03, 0.03), (0.045, 0.045)])
def test_wire_diameters_are_read(given, inches):
    assert parse_wire_diameter(given) == pytest.approx(inches)


@pytest.mark.parametrize("bad", ["30", "030", "1/32", "0.8mm", "0.8 mm", "thick", "", None, True, [], {}, 0, -0.03, 1.5, 30, float("nan"),
                                 float("inf"), "0.030.5", "1e-2", "\x00"])
def test_ambiguous_or_unreadable_wire_diameters_are_refused_not_guessed(bad):
    assert parse_wire_diameter(bad) is None


@pytest.mark.parametrize("given, tag", [("steel", "steel"), ("Mild Steel", "steel"), ("  STAINLESS  steel ", "stainless"), ("Stainless", "stainless"),
                                        ("aluminum", "aluminum"), ("Aluminium", "aluminum"), ("cast iron", "castings"),
                                        ("chrome-moly", "chrome_moly"), ("chrome_moly", "chrome_moly"), ("magnesium alloy", "magnesium")])
def test_materials_are_recognised(given, tag):
    assert normalize_material(given) == tag


@pytest.mark.parametrize("bad", ["unobtanium", "galvanized", "", None, 5, [], {}, True])
def test_unknown_materials_are_not_guessed(bad):
    assert normalize_material(bad) is None


# ---------- the sheet for a normal job ----------
def test_a_normal_mig_job_fits_and_gets_its_own_roller_and_tension():
    g = get_setup_guide("MIG", 240, "steel", "22 gauge", "0.030")
    assert g["ok"] and g["fits"] is True and g["job"]["voltage"] == "240VAC"
    assert status(g) == {"material": "ok", "thickness": "ok", "wire": "ok", "skill": "info"}
    assert g["wire"]["roller"] == "Solid Core V-Groove" and g["wire"]["groove"] == "0.030/0.035 groove" and g["wire"]["tension"] == "3 - 5"
    assert [(e["knob"], e["value"]) for e in g["lcd"]["entries"]] == [("Left Knob", "0.030 inch"), ("Right Knob", "22 gauge")]
    assert [c["socket"] for c in g["plug_in"]["cables"]] == ["negative", "positive"]  # DCEP: clamp negative, wire feed positive
    assert g["limits"]["240VAC"]["range_A"] == [30, 220] and g["limits"]["120VAC"]["range_A"] == [30, 140]
    assert g["warnings"] == [] and g["plug_in"]["spool_gun"] is None


def test_flux_cored_gets_the_knurled_roller_the_lower_tension_and_the_opposite_polarity():
    g = get_setup_guide("flux-cored", 120, "steel", "1/8 inch", "0.045")
    assert g["fits"] is True and g["wire"]["roller"] == "Flux-Cored Knurled Groove" and g["wire"]["groove"] == "0.045 groove"
    assert g["wire"]["tension"] == "2 - 3"
    assert [c["socket"] for c in g["plug_in"]["cables"]] == ["positive", "negative"]  # DCEN: clamp positive, wire feed negative


def test_tig_and_stick_have_no_wire_section_and_the_lcd_entries_name_the_right_knobs():
    tig, stick = get_setup_guide("tig", 240, "steel", "1/8 inch"), get_setup_guide("stick", 240, "steel", "1/4 inch")
    assert tig["wire"] is None and stick["wire"] is None and tig["electrode"] and stick["electrode"] is None
    assert [e["sets"] for e in tig["lcd"]["entries"]] == ["rod diameter", "material thickness"]
    assert [e["knob"] for e in stick["lcd"]["entries"]] == ["Main Control Knob", "Left Knob", "Right Knob"]
    for g in (tig, stick):
        assert any("Open Circuit Voltage is present" in n["text"] for n in g["lcd"]["notes"])  # the energized WARNING


def test_the_roller_groove_and_tension_constants_match_the_manual_text():
    for key in ("mig", "flux_cored"):
        facts = SETTINGS["processes"][key]["wire_and_feed"]
        roller = next(f for f in facts if f["text"].startswith(ROLLER[key] + ":"))
        assert roller["page"] == 12
        for size, groove in GROOVE[key].items():
            assert groove in roller["text"] and f"{size:.3f}" in groove, (key, size)
        assert set(GROOVE[key]) == set(WIRE_SIZES[key])
        tension = next(f for f in facts if "tension should be" in f["text"])
        assert tension["page"] == 15 and TENSION[key] in tension["text"]
    assert "3 - 5 for solid" in SETTINGS["processes"]["mig"]["wire_and_feed"][2]["text"]
    assert "2 - 3 for flux-cored" in SETTINGS["processes"]["mig"]["wire_and_feed"][2]["text"]


# ---------- the checks that protect a new owner ----------
def test_q49_24_gauge_mig_does_not_fit_and_the_manual_contradiction_is_shown():
    g = get_setup_guide("mig", 240, "steel", "24 gauge", "0.025")
    assert g["fits"] is False and status(g)["thickness"] == "fail"
    assert [w["id"] for w in g["warnings"]] == ["mig-thin-limit"] and "24Ga" in g["warnings"][0]["text"]
    assert get_setup_guide("tig", 240, "steel", "24 gauge")["fits"] is True


def test_a_bare_number_for_thickness_is_not_guessed():
    g = get_setup_guide("mig", 240, "steel", "22")
    assert status(g)["thickness"] == "unknown" and g["fits"] is None


def test_wire_sizes_that_do_not_exist_for_that_wire_are_a_problem_not_a_silent_pass():
    assert status(get_setup_guide("flux_cored", None, None, None, "0.025"))["wire"] == "fail"  # flux-cored starts at 0.030
    assert status(get_setup_guide("mig", None, None, None, "0.045"))["wire"] == "fail"  # solid stops at 0.035
    assert status(get_setup_guide("mig", None, None, None, "0.035"))["wire"] == "ok"
    assert status(get_setup_guide("mig", None, None, None, "30"))["wire"] == "unknown"
    assert get_setup_guide("mig", None, None, None, "0.045")["fits"] is False
    assert "wire" not in status(get_setup_guide("tig", None, None, None, "0.045"))  # TIG has no wire size to check


def test_material_checks_name_the_processes_that_do_work():
    stick_alu = get_setup_guide("stick", 240, "aluminum")
    assert stick_alu["fits"] is False
    text = next(c["text"] for c in stick_alu["checks"] if c["id"] == "material")
    assert "MIG / GMAW" in text and "TIG / GTAW" in text and "Stick" not in text.split("It lists it for")[1]
    assert status(get_setup_guide("mig", 240, "unobtanium"))["material"] == "unknown"


def test_aluminum_notes_the_spool_gun_and_the_tig_disagreement_and_stick_castings():
    mig = get_setup_guide("mig", 240, "aluminum", "1/8 inch")
    assert any("Spool gun required" in c["text"] for c in mig["checks"]) and mig["plug_in"]["spool_gun"]["cables"]
    tig = get_setup_guide("tig", 240, "aluminum", "1/8 inch")
    assert tig["fits"] is True and [w["id"] for w in tig["warnings"]] == ["tig-aluminum"]
    assert any("AC TIG required" in c["text"] for c in tig["checks"])
    assert [w["id"] for w in get_setup_guide("stick", 240, "castings")["warnings"]] == ["stick-materials"]


def test_outdoors_always_raises_the_outdoor_contradiction_and_gas_processes_get_the_chart_note():
    for key in ORDER:
        g = get_setup_guide(key, 240, outdoors=True)
        assert [w["id"] for w in g["warnings"]] == ["outdoor-use"], key
        assert ("outdoors" in status(g)) == (key in ("mig", "tig")), key
    assert get_setup_guide("mig", None, outdoors="yes")["warnings"][0]["id"] == "outdoor-use"
    for odd in ("maybe", 1, [], "nope"):
        assert get_setup_guide("mig", None, outdoors=odd)["warnings"] == [], odd


def test_no_gas_rules_out_the_gas_processes_only():
    fits = {k: get_setup_guide(k, None, "steel", gas_ok=False)["fits"] for k in ORDER}
    assert fits == {"mig": False, "flux_cored": True, "tig": False, "stick": True}


def test_skill_adds_a_caution_only_when_the_chart_needs_more_skill_than_they_have():
    assert status(get_setup_guide("stick", None, skill="beginner"))["skill"] == "warn"
    assert status(get_setup_guide("stick", None, skill="experienced"))["skill"] == "info"
    assert status(get_setup_guide("tig", None, skill="wizard"))["skill"] == "info"  # unknown word: no false alarm


# ---------- ranking the four processes ----------
def test_ranking_for_thin_aluminum_puts_the_easier_working_process_first():
    r = choose_process("aluminum", "22 ga")
    assert r["best"] == "mig" and r["ranked"][0]["process"] == "mig" and r["ranked"][1]["process"] == "tig"
    assert {x["process"] for x in r["ranked"] if x["fits"] is False} == {"flux_cored", "stick"}
    assert r["missing"] == [] and r["unreadable"] == []


def test_ranking_for_thick_steel_and_a_beginner_with_no_gas():
    r = choose_process("steel", "3/8 inch", outdoors=True, gas_ok=False, skill="beginner")
    assert r["best"] == "stick" and [x["process"] for x in r["ranked"] if x["fits"] is False] == ["flux_cored", "mig", "tig"]


def test_ranking_asks_for_what_is_missing_and_flags_what_it_could_not_read():
    assert choose_process()["missing"] == ["material", "thickness"] and choose_process()["best"] is None
    r = choose_process("steel", "22")
    assert r["missing"] == ["thickness"] and r["unreadable"] == ["thickness"]
    r = choose_process("galvanized", "22 gauge")
    assert r["missing"] == ["material"] and r["unreadable"] == ["material"]


def test_ranking_is_stable_and_complete_for_every_input_combination():
    for material in (None, "steel", "aluminum", "castings", "nonsense"):
        for thickness in (None, "24 gauge", "1/8 inch", "1 inch", "22"):
            for outdoors in (None, True, False):
                for gas in (None, True, False):
                    r = choose_process(material, thickness, outdoors, gas, "beginner")
                    assert sorted(x["process"] for x in r["ranked"]) == sorted(ORDER)
                    order = [x["fits"] for x in r["ranked"]]
                    assert order == sorted(order, key=lambda f: {True: 0, None: 1, False: 2}[f])  # failures always last


# ---------- bad input never crashes ----------
def test_unknown_process_or_voltage_is_a_message_not_a_crash():
    for r in (get_setup_guide("plasma"), build_setup("plasma"), setup_guide_widget("plasma")):
        assert r["ok"] is False and "mig, flux_cored, tig or stick" in r["message"]
    for r in (get_setup_guide("mig", 480), build_setup("mig", 480), setup_guide_widget("mig", 480)):
        assert r["ok"] is False and "120V or 240V" in r["message"]


@pytest.mark.parametrize("value", ODD, ids=repr)
@pytest.mark.parametrize("field", ["process", "voltage", "material", "thickness", "wire_diameter", "outdoors", "gas_ok", "skill"])
def test_odd_values_in_any_field_never_crash(field, value):
    w = setup_guide_widget(**{field: value})
    assert w["ok"] in (True, False)
    if w["ok"]:
        assert "<script>alert(1)</script>" not in w["html"] and "x" * 100 not in w["html"]
    g = get_setup_guide(**({"process": "mig"} | {field: value}))
    assert g["ok"] in (True, False)


# ---------- what Claude is told ----------
def test_the_digest_is_short_verified_and_json_safe():
    d = digest(build_setup("mig", 240, "steel", "22 gauge", "0.030"))
    assert d["selected"] == "mig" and d["fit_by_process"] == {"mig": True, "flux_cored": False, "tig": True, "stick": False}
    assert d["plug_in"] == ["Ground Clamp Cable -> negative socket", "Wire Feed Power Cable -> positive socket"]
    assert list(d["current_limits"]) == ["240VAC"] and d["feed_roller"]["tension"] == "3 - 5"
    assert "Never state a wire speed or voltage" in d["reminder"] and d["missing"] == []
    assert len(json.dumps(d)) < 4000
    assert set(digest(build_setup("tig"))["current_limits"]) == {"120VAC", "240VAC"}  # no voltage given: both


def test_with_no_process_the_sheet_opens_on_the_best_fit():
    assert build_setup(None, 240, "aluminum", "22 ga")["selected"] == "mig"
    assert build_setup("", 240, "steel", "3/8 inch")["selected"] == "mig"  # MIG and Stick both reach 3/8; MIG is the easier
    assert build_setup("", 240, "steel", "1/2 inch")["selected"] == "stick"  # only Stick reaches 1/2 inch
    assert build_setup("tig", 240, "steel", "3/8 inch")["selected"] == "tig"  # asked for TIG: shown, with the problem


# ---------- the page ----------
def test_the_page_has_a_tab_and_a_panel_for_each_process_and_only_one_is_open():
    html = setup_guide_widget("mig", 240, "steel", "22 gauge", "0.030")["html"]
    assert html.count('role="tab"') == 4 and html.count('role="tabpanel"') == 4 and html.count(" hidden>") == 3
    assert re.search(r'data-p="mig" aria-selected="true"', html) and 'data-p="tig" aria-selected="false"' in html
    for badge in ("✓ fits", "✗ no fit"):
        assert badge in html
    text = text_of(html)
    for card in ("Will MIG / GMAW work for your job?", "Plug in", "Shielding gas", "Wire, feed roller and tension", "On the LCD",
                 "What the LCD decides for you", "Current limits and power", "Not in the manual"):
        assert card in text, card
    assert "Your job: steel, 22 gauge, 0.030 wire, 240V" in text
    assert "Feed roller: Solid Core V-Groove, turned to the 0.030/0.035 groove" in text and "Feed tension: 3 - 5" in text


def test_the_page_is_self_contained():
    html = setup_guide_widget("flux_cored", 120, "steel", "1/8 inch", "0.045")["html"]
    assert not re.search(r"https?://|<link|<img|<iframe|src=|@import|fetch\(|XMLHttpRequest", html)


def test_each_panel_shows_the_lcd_deciding_and_never_a_made_up_number():
    for key in ORDER:
        text = text_of(setup_guide_widget(key, 240, "steel", "1/8 inch", "0.030")["html"])
        assert "What the LCD decides for you" in text and "not reproduced in the manual" in text
        numbers = re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:ipm|in/min|volts?|vac|vdc|v)\b", text, flags=re.I)
        assert set(numbers) <= {"120", "240"}, f"{key}: a wire speed or voltage number appeared: {numbers}"
    mig = text_of(setup_guide_widget("mig")["html"])
    assert "white mark on the line shows the recommended setting" in mig and "p.20" in mig


def test_user_text_is_escaped_in_the_page():
    w = setup_guide_widget("mig", 240, "<img src=x onerror=alert(1)>", "<b>3/16</b>", '"><script>alert(2)</script>')
    assert "<img src=x" not in w["html"] and "<script>alert(2)" not in w["html"] and "&lt;img" in w["html"]


def test_warnings_appear_as_boxes_that_say_what_to_do():
    text = text_of(setup_guide_widget("mig", 240, "steel", "24 gauge", outdoors=True)["html"])
    assert text.count("The manual disagrees with itself.") >= 2 and "What to do:" in text
    assert "Do not use outdoors" in text and "24Ga" in text


# ---------- through the same MCP layer the Claude CLI talks to (SDK pinned, so its internals are stable) ----------
def test_the_mcp_layer_lists_the_tool_and_accepts_what_a_model_would_send():
    import asyncio

    from app.agent_tools import server
    handlers = server["instance"]._request_handlers
    lst, call = handlers["tools/list"], handlers["tools/call"]

    async def go():
        tools = (await lst.handler(None, lst.params_type())).tools
        schema = next(t for t in tools if t.name == "show_setup_guide").input_schema
        sent = {"process": "mig", "voltage": 240, "material": "steel", "thickness": "22 gauge", "wire_diameter": 0.03, "outdoors": False}
        full = await call.handler(None, call.params_type(name="show_setup_guide", arguments=sent))
        empty = await call.handler(None, call.params_type(name="show_setup_guide", arguments={}))
        return len(tools), schema, full, empty
    count, schema, full, empty = asyncio.run(go())
    assert count == 9 and "required" not in schema and set(schema["properties"]) >= {"process", "voltage", "thickness", "wire_diameter"}
    for res in (full, empty):
        assert not res.is_error and json.loads(res.content[0].text)["ok"] is True
    assert json.loads(full.content[0].text)["feed_roller"]["groove"] == "0.030/0.035 groove"
