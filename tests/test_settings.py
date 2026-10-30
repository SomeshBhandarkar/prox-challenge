import re

from app.knowledge import CAVEATS, ROOT, SETTINGS


def _pages() -> dict:
    text = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")
    parts = re.split(r"=====PAGE (\d+)=====", text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


PAGES = _pages()
ALL_WORDS = _words(" ".join(PAGES.values()))


def _facts(node):
    """Every {'text': ..., 'page': N} fact anywhere in the settings file."""
    if isinstance(node, dict):
        if "text" in node and "page" in node:
            yield node
        for v in node.values():
            yield from _facts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _facts(v)


def test_every_word_of_every_fact_is_on_the_page_it_cites():
    facts = list(_facts(SETTINGS))
    assert len(facts) > 60  # guards against the walker silently finding nothing
    for f in facts:
        assert 1 <= f["page"] <= 48
        missing = _words(f["text"]) - _words(PAGES[f["page"]])
        assert not missing, f"p{f['page']} {f['text'][:60]!r}: words not on that page: {missing}"
        if "name" in f:
            assert _words(f["name"]) <= _words(PAGES[f["page"]]), f["name"]


def test_lcd_step_counts_match_the_manual():
    lcd = SETTINGS["lcd"]
    assert [len(lcd[k]["steps"]) for k in ("wire", "tig", "stick")] == [6, 6, 7]
    assert [len(lcd[k]["optional_settings"]) for k in ("wire", "tig", "stick")] == [5, 2, 4]
    assert [o["name"] for o in lcd["wire"]["optional_settings"]] == ["Run-In WFS", "Inductance", "Spot Timer", "Recall Setting", "Save Setting"]
    assert [o["name"] for o in lcd["stick"]["optional_settings"]] == ["Hot Start", "Arc Force", "Recall Setting", "Save Setting"]


def test_each_process_points_at_an_lcd_flow_that_exists():
    assert set(SETTINGS["processes"]) == {"mig", "flux_cored", "tig", "stick"}
    for key, p in SETTINGS["processes"].items():
        assert p["lcd"] in SETTINGS["lcd"], key


def test_the_numbers_that_matter_are_exactly_what_the_manual_says():
    mig = " ".join(f["text"] for f in SETTINGS["processes"]["mig"]["gas"])
    tig = " ".join(f["text"] for f in SETTINGS["processes"]["tig"]["gas"])
    feed = " ".join(f["text"] for f in SETTINGS["processes"]["mig"]["wire_and_feed"])
    assert "SCFH between 20-30" in mig and "SCFH between 10-25" in tig and "100% Argon" in tig
    assert "3 - 5 for solid wire and 2 - 3 for flux-cored" in feed
    assert "1/2" in feed  # stickout


def test_the_wire_steps_carry_the_manuals_white_mark_note_and_never_a_made_up_number():
    notes = " ".join(n["text"] for n in SETTINGS["lcd"]["wire"]["notes"])
    assert "white mark on the line" in notes
    steps = " ".join(s["text"] for s in SETTINGS["lcd"]["wire"]["steps"])
    assert not re.search(r"\b\d+\s*(ipm|in/min|volts?)\b", steps, re.I)  # no invented wire speed or voltage values


def test_the_energized_warnings_are_present_for_tig_and_stick():
    for k in ("tig", "stick"):
        warn = [n for n in SETTINGS["lcd"][k]["notes"] if n.get("level") == "WARNING"]
        assert warn and "Open Circuit Voltage is present" in warn[0]["text"]


# ---------- caveats: the claims must stay true ----------
def test_nothing_listed_as_not_in_the_manual_is_actually_in_the_manual():
    for item in CAVEATS["not_in_manual"]:
        for term in item.get("search_terms", []):
            assert term.lower() not in " ".join(PAGES.values()).lower(), f"{item['id']}: the manual mentions {term!r}"


def test_the_pulse_and_generator_claims_are_backed_by_the_search():
    ids = {i["id"]: i for i in CAVEATS["not_in_manual"]}
    assert "pulse" in ids["pulse-mode"]["search_terms"] and "generator" in ids["generator-use"]["search_terms"]


def test_inconsistency_claims_are_backed_by_the_pages_they_cite():
    p = {k: v.lower() for k, v in ((n, t) for n, t in PAGES.items())}
    assert "do not use outdoors" in p[4] and "do not expose welders to rain or wet conditions" in p[4]
    assert "inside of the welder door" in p[14] and "inside of the welder door" in p[30]
    assert "on top of welder" in p[26]
    assert "ac tig welding is used to weld aluminum" in re.sub(r"\s+", " ", p[28].replace("|", ""))
    assert "20 amp rated" in p[16] and "240 vac" in p[16]


def test_every_inconsistency_has_text_guidance_pages_and_sources():
    for c in CAVEATS["known_inconsistencies"]:
        assert c["text"] and c["guidance"] and c["pages"] and c["sources"], c["id"]
        assert all(1 <= pg <= 48 for pg in c["pages"]), c["id"]
    assert {c["id"] for c in CAVEATS["known_inconsistencies"]} == {
        "outdoor-use", "tig-aluminum", "mig-thin-limit", "settings-chart-location", "stick-materials"}


# ---------- the wiring schematic facts (found by the full Haiku run: the model read a connector as CN8; the LCD plugs into CN5) ----------
def _manual_pages():
    import re
    from app.knowledge import ROOT
    text = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")
    parts = re.split(r"=====PAGE (\d+)=====", text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def test_every_schematic_fact_uses_words_that_are_on_the_pages_it_cites():
    pages = _manual_pages()
    for f in CAVEATS["schematic_facts"]:
        assert f["terms"] and set(int(p) for p in f["terms"]) <= set(f["pages"]), f["id"]
        for page, terms in f["terms"].items():
            for term in terms:
                assert term.lower() in pages[int(page)].lower(), f"{f['id']}: '{term}' is not on page {page}"


def test_the_schematic_facts_reach_the_prompt_and_tell_the_model_not_to_guess_other_connectors():
    from app.prompt import build_system_prompt
    from app.tools.caveats import schematic_for_prompt
    prompt = build_system_prompt()
    assert len(schematic_for_prompt().splitlines()) == len(CAVEATS["schematic_facts"]) == 3
    for f in CAVEATS["schematic_facts"]:
        assert f["text"] in prompt, f["id"]
    assert "cannot be read reliably from a page image" in prompt and "state ONLY these checked facts" in prompt
    assert "CN5" in schematic_for_prompt() and "CN8" not in schematic_for_prompt()
