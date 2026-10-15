import re

from app.knowledge import CAVEATS, FIGURES, PROCESS_SELECTION
from app.prompt import INSTRUCTIONS, build_system_prompt
from app.tools.caveats import inconsistencies_for_prompt, not_in_manual_for_prompt
from app.tools.selection import chart_for_prompt

FIGURE_IDS = {f["id"] for f in FIGURES}


def test_every_figure_id_is_listed_in_the_prompt():
    prompt = build_system_prompt()
    for f in FIGURES:
        assert f["id"] in prompt, f"{f['id']} missing from the prompt"


def test_manual_text_is_included_with_page_markers():
    prompt = build_system_prompt()
    for page in (1, 14, 35, 48):
        assert f"=====PAGE {page}=====" in prompt, f"page {page} missing"


def test_rules_name_the_tools_and_the_no_invention_rule():
    for needle in ("duty_cycle", "polarity", "show_figure", "view_manual_page", "Never invent"):
        assert needle in INSTRUCTIONS, needle


def test_prompt_has_no_secrets():
    prompt = build_system_prompt()
    assert "sk-ant" not in prompt and "ANTHROPIC_API_KEY" not in prompt


def test_prompt_size_is_sane():
    # ~110 KB of manual + instructions + chart/caveats + about 90 figure lines; guards against an empty or doubled manual
    assert 100_000 < len(build_system_prompt()) < 185_000


# ---------- the chart, the contradictions and the gaps are generated from the tested data files ----------
def test_each_generated_block_is_in_the_prompt_verbatim():
    prompt = build_system_prompt()
    for block in (chart_for_prompt(), inconsistencies_for_prompt(), not_in_manual_for_prompt()):
        assert block and block in prompt


def test_the_chart_block_has_every_process_and_the_side_table():
    text = chart_for_prompt()
    for p in PROCESS_SELECTION["processes"].values():
        assert p["label"] in text and f"skill {p['skill_level'].upper()}" in text, p["label"]
        assert p["thickness"]["as_printed"] in text and p["shielding_gas"] in text, p["label"]
        assert all(m in text for m in p["materials"]) and all(a in text for a in p["applications"]), p["label"]
    for row in PROCESS_SELECTION["mig_or_flux_cored_table"]["rows"]:
        assert row["feature"] in text, row["feature"]
    assert PROCESS_SELECTION["duty_cycle_box"]["example"] in text and "120 VOLT OR 240 VOLT" in text
    assert "HIGHER gauge number is THINNER" in text and "not from the manual" in text
    assert "?." not in text  # the banner ends in a question mark: no doubled punctuation


def test_every_inconsistency_and_every_gap_is_in_the_prompt_with_what_to_do():
    text = inconsistencies_for_prompt()
    assert text.count("WHAT TO DO:") == len(CAVEATS["known_inconsistencies"]) == 5
    for c in CAVEATS["known_inconsistencies"]:
        assert c["text"] in text and c["guidance"] in text, c["id"]
    gaps = not_in_manual_for_prompt()
    assert len(gaps.splitlines()) == len(CAVEATS["not_in_manual"])
    for c in CAVEATS["not_in_manual"]:
        assert c["text"] in gaps, c["id"]


def test_the_prompt_tells_claude_to_use_these_sections():
    prompt = build_system_prompt()
    for header in ("THE SELECTION CHART", "WHERE THE MANUAL DISAGREES WITH ITSELF", "THE MANUAL DOES NOT SAY"):
        assert header in prompt, header
    assert prompt.index("THE MANUAL DOES NOT SAY") < prompt.index("=====PAGE 1=====")  # read before the long manual


def test_the_settings_rule_asks_first_and_never_gives_numbers():
    for needle in ("SETTINGS QUESTIONS", "ONE short message", "Never state a numeric wire speed or voltage",
                   "white mark on the line", "test on scrap", "no pulse mode", "120V or 240V"):
        assert needle in INSTRUCTIONS, needle


def test_every_figure_named_in_the_instructions_exists_and_the_new_ones_are_routed():
    families = r"quick-start-[a-z-]+|warning-symbols-and-definitions|general-safety-rules|fume-and-gas-safety|arc-ray-safety|electrical-safety|fire-safety|welder-use-and-care|maintenance-safety-rules|cylinder-safety-and-save-instructions|grounding-extension-and-replacement-cords|symbology-table|wire-setup-power-off-and-door|wire-spool-installation-[0-9a-z-]+|release-feed-tension-step|basic-wire-welding-gear-and-processes|wire-welding-fire-warning|strike-test|cleaning-the-weld|table-of-contents|manual-cover-page|troubleshooting-table|wiring-schematic|parts-list-table|parts-ordering-notes|assembly-diagram|wire-loading-hold-wire-steps|idler-arm-and-feed-tensioner-latch|remove-nozzle-and-contact-tip|stainless-wire-important-note|maintenance-warning-and-inspection|mig-nozzle-contact-tip-cleaning|lcd-screen-cover-replacement|duty-cycle-section-mig|follow-duty-cycle-box|overheat-warning-screen|shutdown-and-storage-steps|tig-[a-z]+|stick-[a-z]+|tungsten-sharpening|duty-cycle-section-tig-stick|ground-clamp-to-workpiece|weld-setup-clamping|energized-tip-fire-warning|wire-bead-types|mig-gun-angles-fillet-butt|push-drag-angle-and-ctwd|selection-chart|lcd|spec-table|front-panel-controls|interior-controls|rating-label|polarity-[a-z]+-[a-z]+-setup|gas-cylinder-regulator-setup|wire-tension-test|nozzle-contact-tip|gun-cable-connection|cold-wire-feed-step|spool-gun-setup|danger-live-parts-wire-feed"
    named = set(re.findall(rf"\b(?:{families})(?:-[a-z0-9]+)*\b", INSTRUCTIONS))
    assert named and named <= FIGURE_IDS, f"instructions name figures that do not exist: {named - FIGURE_IDS}"
    assert {"selection-chart-processes", "selection-chart-mig-vs-flux", "lcd-wire-diameter-thickness",
            "lcd-auto-weld-screen", "lcd-optional-settings", "front-panel-controls", "interior-controls", "spec-table-mig", "spec-table-tig",
            "spec-table-stick", "rating-label", "polarity-flux-cored-setup", "polarity-solid-core-setup", "gas-cylinder-regulator-setup",
            "wire-tension-test", "nozzle-contact-tip", "gun-cable-connection", "cold-wire-feed-step", "spool-gun-setup",
            "danger-live-parts-wire-feed", "tig-cable-setup", "stick-cable-setup", "tungsten-sharpening", "tig-torch-assembly", "tig-lcd-auto-weld-screen",
            "stick-lcd-auto-weld-screen", "duty-cycle-section-tig-stick", "push-drag-angle-and-ctwd", "wiring-schematic", "parts-list-table", "assembly-diagram",
            "troubleshooting-table-mig-flux-cored-p42", "troubleshooting-table-mig-flux-cored-p43", "troubleshooting-table-tig-stick-p44",
            "duty-cycle-section-mig", "overheat-warning-screen", "lcd-screen-cover-replacement", "quick-start-all-cable-setups", "quick-start-tig-cable-setup",
            "warning-symbols-and-definitions", "symbology-table", "strike-test", "cleaning-the-weld", "wire-spool-installation-10-12-lb"} <= named


def test_manual_facts_are_never_called_general_advice_and_forbidden_things_get_no_workarounds():
    flat = " ".join(INSTRUCTIONS.split())
    for needle in ("ONLY what is not in the manual", "weld diagnosis pages (35-40)", "never call it general advice",
                   "do not offer ways to do it anyway"):
        assert needle in flat, needle


def test_polarity_checks_name_both_sockets_thick_120v_jobs_are_not_promised_and_contradictions_stay_on_topic():
    flat = " ".join(build_system_prompt().split())
    for needle in ("check or fix polarity (DCEN or DCEP)", "name BOTH sockets", "does not say which input voltage it needs",
                   "does not confirm the job is achievable on 120V", "Never say a job is realistic",
                   "mention one ONLY when the question is about that very topic", "never bring one up otherwise"):
        assert needle in flat, needle


def test_artifacts_are_never_placeholders_pictures_are_not_stacked_and_the_label_is_shown_when_quoted():
    """Found by the Haiku check of patches 2-5: a junk 'noop' artifact (Q15), five pictures for one cheat sheet (Q84), label numbers without the label (Q67)."""
    flat = " ".join(build_system_prompt().split())
    for needle in ("Every call puts a card on the person's screen", 'never as a test, a placeholder or a "noop"',
                   "One picture per idea", "do not also show a polarity diagram for each one",
                   "show it whenever you quote a voltage or a 60% point read off the label"):
        assert needle in flat, needle


def test_rules_from_the_full_haiku_run():
    """Each needle is a fix for something the 85-question run showed (answers repeated, stray-call commentary, hookup withheld, missing unplug,
    invented stand-ins, a misdescribed calculator, ambiguous push/drag wording, the LCD polarity screen not shown)."""
    flat = " ".join(build_system_prompt().split())
    for needle in ("Call your show tools FIRST, then write the answer ONCE", "Never show the same picture, diagram or widget twice",
                   'Do not comment on your own tool calls or mistakes', "first give the part that needs nothing more",
                   "first say to turn the Power Switch OFF and unplug the welder", "leave the Power Switch ON so the fan cools",
                   "Never suggest a setting as a stand-in", "never mention files or project folders", "clearly labelled as NOT from the manual",
                   "quote it exactly and show push-drag-angle-and-ctwd", "lcd-polarity-gas-screen"):
        assert needle in flat, needle
    # the push/drag quotes must be the manual's real words
    from app.prompt import MANUAL_TEXT
    page22 = MANUAL_TEXT.split("=====PAGE 22=====")[1].split("=====PAGE 23=====")[0]
    flat22 = " ".join(page22.replace("|", " ").split())
    # (the page text interleaves columns, so the push sentence is checked in two pieces)
    assert "straight on and 15° away" in flat22 and "from the direction you are welding" in flat22
    assert "straight on and 15° in the direction you are welding" in flat22


def test_the_prompt_says_where_pictures_appear_so_the_words_match_the_screen():
    """Found by real Sonnet runs: the answer said 'see the diagram below' while the page showed it above (and sometimes said 'above')."""
    flat = " ".join(build_system_prompt().split())
    assert "appear BELOW your answer text" in flat and 'never "above"' in flat and "do not add a second message that only describes what you showed" in flat
