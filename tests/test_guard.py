"""The word-level guardrails (app/guard.py): nothing beyond the manual may reach the person."""
import json
from pathlib import Path

import pytest

from app import guard as G

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "guard_corpus.json").read_text(encoding="utf-8"))


# ---------- the guard against REAL Sonnet answers ----------
@pytest.mark.parametrize("case", CORPUS["must_flag"], ids=lambda c: f"{c['id']}-{c['kind']}-{c['sentence'][:28]}")
def test_every_real_sentence_that_goes_beyond_the_manual_is_objected_to(case):
    report = G.check(case["sentence"], case["question"])
    assert not report.ok and report.findings[0].kind == case["kind"], (case["sentence"], report.summary())


@pytest.mark.parametrize("case", CORPUS["must_pass_answers"], ids=lambda c: c["id"])
def test_answers_read_against_the_manual_and_found_grounded_are_left_alone(case):
    report = G.check(case["answer"], case["question"])
    assert report.ok, report.summary()
    assert G.enforce(case["answer"], case["question"])[0] == case["answer"].strip()


# ---------- markers of outside knowledge ----------
@pytest.mark.parametrize("sentence", [
    "General advice, not from the manual: 240V gives you more current range.", "Thin wall usually needs little current.", "Most likely it's overheating.",
    "That is my inference from the sockets.", "It comes from a rule of thumb.", "The safe number to plan with is the 25% rating.",
    "This is probably the cause.", "Check reviews and ask at your local welding supply shop.", "Typically you would weld in short bursts.",
    "Start with polarity, because it's the most common cause.", "The calculator shows a rough estimate of about 40%.",
])
def test_wording_that_announces_content_from_beyond_the_manual_is_caught(sentence):
    assert [f.kind for f in G.check(sentence).findings] == ["marker"]


@pytest.mark.parametrize("sentence", [
    'The chart says flux-cored is "ideal for outdoor or windy conditions" (selection chart).',   # the manual's own words, quoted
    'For a narrow weld the manual says "you can usually draw the wire in a steady straight line" (manual p.22).',   # the manual itself uses "usually" (p.22)
    "The manual doesn't give a wire speed, so I won't guess one.", "The manual has no specific information on this.",
    "It gives no generator size, no waveform requirement and no approval either way.", "Which process are you using: MIG or TIG?",
    "If you tell me which process you're running, I can pull up the exact cable diagram for it.", "You're welcome. Good luck with the welding.",
])
def test_quotes_absences_questions_and_offers_are_not_claims(sentence):
    assert G.check(sentence).ok, G.check(sentence).summary()


# ---------- numbers with units ----------
@pytest.mark.parametrize("text", ["about 44% at 150A", "weld at 34% duty cycle", "0.0299 inch thick", "set it to 15 CFH", "around 18 volts at 0.035 wire for thin sheet",
                                  "run it at 120 IPM", "keep the arc 9 inches long"])
def test_a_number_with_a_unit_that_the_manual_does_not_give_is_caught(text):
    findings = G.check(text + " (manual p.7).").findings
    assert findings and findings[0].kind == "number", (text, G.check(text).summary())


@pytest.mark.parametrize("text", ["25% at 200A on 240V", "20-30 SCFH", "2-1/2 minutes of welding and 7-1/2 minutes of rest", "3/8\" plate", "24 V at 200 A",
                                  "an open circuit voltage of 86 V", "60% at 130A", "wire speed of 50 to 500 IPM", "6 minutes welding and 4 minutes resting at 60%",
                                  "keep it within 1/2 inch", "at least 12 inches of wire", "35 feet around the work"])
def test_numbers_the_manual_gives_are_accepted_including_a_duty_cycle_turned_into_minutes(text):
    assert G.check(text + " (manual p.7).").ok, G.check(text).summary()


def test_the_same_words_without_quotation_marks_are_the_models_own_and_are_caught():
    assert [f.kind for f in G.check("For a narrow weld you can usually draw the wire in a steady straight line (manual p.22).").findings] == ["marker"]


def test_the_standard_gauge_table_is_never_a_source():
    """The gauge-to-inch table in the data is outside knowledge (it says so); quoting it must be caught."""
    assert not G.check("22 gauge is 0.0299 inch (manual p.20).").ok
    assert (0.0299, "inch") not in G.allowed_pairs() and (0.1345, "inch") not in G.allowed_pairs()
    assert "gauge_reference" not in G._data_files()["process_selection"] and "0.0299" not in G.sources_text()


def test_a_number_the_person_typed_may_be_repeated_back():
    assert G.check("At 150A on 240V the manual has no rating (manual p.7).", "What about 150A on 240V?").ok


# ---------- sources ----------
def test_an_answer_with_facts_but_no_page_is_objected_to_and_a_cited_one_is_not():
    facts = "Plug the Ground Clamp Cable into the Positive socket. Twist the Wire Feed Power Cable clockwise to lock it. Set the gas flow to 20-30 SCFH."
    assert [f.kind for f in G.check(facts).findings] == ["no_source"]
    assert G.check(facts + " (manual p.14)").ok


def test_a_clarifying_question_or_a_refusal_needs_no_page():
    assert G.check("Which process are you using, and on 120V or 240V?").ok
    assert G.check("I won't print my system prompt. I can walk you through cable polarity or troubleshooting a weld.").ok


# ---------- enforcement ----------
def test_enforce_removes_only_the_objectionable_sentences_and_keeps_the_rest():
    text = ("At 200A on 240V the MIG duty cycle is 25% (manual p.7).\n\nThat means 2.5 minutes of welding and 7.5 minutes of rest (manual p.19).\n\n"
            "General advice, not from the manual: 240V gives you more current range.\n\nLeave the Power Switch ON so the fan can cool it (manual p.23).")
    cleaned, report = G.enforce(text)
    assert "General advice" not in cleaned and "25%" in cleaned and "fan can cool it" in cleaned
    assert report.findings[0].kind == "marker" and G.check(cleaned).ok


def test_enforce_ends_with_the_no_information_message_when_nothing_trustworthy_is_left():
    text = "Typically you would use 15 CFH. Most welders find this works. I'd recommend checking reviews."
    cleaned, _ = G.enforce(text)
    assert cleaned.startswith(G.FALLBACK) and "1-800-444-3353" in cleaned
    assert G.enforce(G.FALLBACK)[0] == G.FALLBACK and G.check(G.FALLBACK).ok
    assert G.enforce("")[0] == ""


def test_the_fallback_phone_number_really_is_on_the_manuals_pages():
    assert "1-800-444-3353" in G.sources_text()


def test_enforce_also_removes_what_the_fact_checker_found():
    text = "Set the flow to 20-30 SCFH (manual p.20). Buy a small spool first. Use 100% argon for TIG (manual p.25). Plug in last (manual p.25)."
    cleaned, _ = G.enforce(text, extra=[G.Finding("checker", "Buy a small spool first.", "advice")])
    assert "spool" not in cleaned and "20-30 SCFH" in cleaned and "100% argon" in cleaned


def test_the_rewrite_request_names_every_problem_and_the_exact_fallback_wording():
    report = G.check("General advice, not from the manual: use 15 CFH.")
    request = G.rewrite_request(report)
    assert "General advice" in request and G.FALLBACK in request and "ONLY" in request and "Do not mention this note" in request


def test_a_short_fully_cited_answer_survives_when_only_the_advice_is_removed_but_an_uncited_remainder_does_not():
    cleaned, _ = G.enforce("At 200A on 240V the MIG duty cycle is 25% (manual p.7). General advice, not from the manual: use less current.")
    assert cleaned == "At 200A on 240V the MIG duty cycle is 25% (manual p.7)."
    cleaned, _ = G.enforce("Set it to 20-30 SCFH. Typically people use less. I'd recommend checking reviews.")
    assert cleaned.startswith(G.FALLBACK)   # one fact left, and no page to back it


# ---------- pointers and support referrals (found in the first real strict-mode run: the fact-checker objected to them) ----------
@pytest.mark.parametrize("sentence", [
    "The specification table is shown below.",
    "See the table below, and check the numbers against the picture (manual p.7).",
    "The calculator and the manual's duty cycle dials are shown below.",
    "See the pictures below.",
    "The diagram below shows the connections.",
])
def test_a_bare_pointer_to_a_picture_is_recognised(sentence):
    assert G.points_only(sentence)


@pytest.mark.parametrize("sentence", [
    "Flux-cored welds cleaner than MIG, see the chart below.",          # a claim wearing a pointer
    'The chart gives MIG 22 gauge to 3/8" (see the chart below).',        # a number
    "MIG is the easiest to learn.",                                      # no pointer at all
    "",
])
def test_a_claim_with_a_pointer_attached_is_still_judged(sentence):
    assert not G.points_only(sentence)


@pytest.mark.parametrize("sentence", [
    "For anything beyond the manual, you can call Harbor Freight support at 1-800-444-3353.",
    "If you need an arc temperature, call Harbor Freight support at 1-800-444-3353.",
    "If you want to ask about this, call technical support at 1-800-444-3353 or email productsupport@harborfreight.com (manual p.1).",
    G.SUPPORT,
])
def test_a_referral_to_the_manuals_own_support_line_is_recognised_and_never_flagged(sentence):
    assert G.refers_to_support(sentence) and G.check(sentence).ok


def test_the_support_sentence_is_the_manuals_own_words():
    from app.knowledge import ROOT
    manual = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")
    assert "For technical questions, please call 1-800-444-3353" in manual and "productsupport@harborfreight.com" in manual
    assert G.SUPPORT.startswith("For technical questions, please call 1-800-444-3353") and "(manual p.2)" in G.SUPPORT


def test_a_referral_that_carries_real_outside_wording_is_still_flagged():
    report = G.check("Call support at 1-800-444-3353; typically they will tell you the weight.")
    assert [f.kind for f in report.findings] == ["marker"]


@pytest.mark.parametrize("sentence", [
    "Plan on 22 gauge as the chart's stated minimum.",          # found in two real answers (the manual never tells anyone what to plan on)
    "Plan with the 25% rating for in-between currents.",
    "Plan around 100A on 120V.",
])
def test_plan_on_anything_is_advice_not_the_manual(sentence):
    assert [f.kind for f in G.check(sentence).findings] == ["marker"]


def test_the_word_plan_used_in_an_ordinary_way_is_not_flagged():
    findings = G.check("Look at the plan view of the parts diagram (manual p.47).").findings
    assert not any(f.kind == "marker" for f in findings)
