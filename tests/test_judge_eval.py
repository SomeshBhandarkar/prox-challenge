"""The scoring of the fact-checker evaluation (scripts/judge_eval.py), tested with a pretend checker."""
import asyncio

from app.guard import Finding, split_sentences
from scripts import judge_eval as J

UNSUPPORTED, SUPPORTED = J.load_cases()


def test_the_labelled_cases_are_15_beyond_the_manual_and_17_from_it_and_never_overlap():
    assert len(UNSUPPORTED) == 15 and len(SUPPORTED) == 17 and not set(UNSUPPORTED) & set(SUPPORTED)
    assert all(s.strip() for s in UNSUPPORTED + SUPPORTED)


def test_every_sentence_survives_being_sent_as_a_numbered_answer_one_per_line():
    from app.judge import numbered
    _, sentences = numbered(J.build_answer(UNSUPPORTED, SUPPORTED, 0))
    asked = [s for s in UNSUPPORTED + SUPPORTED if not s.endswith("?")]
    assert sorted(sentences) == sorted(asked)   # (questions are left out on purpose: they claim nothing)


def test_a_perfect_checker_catches_every_outside_sentence_and_rejects_no_correct_one():
    async def perfect(answer, question):
        return [Finding("checker", s, "x") for s in split_sentences(answer) if s in UNSUPPORTED]
    r = asyncio.run(J.run_round(UNSUPPORTED, SUPPORTED, 0, perfect))
    assert r["caught"] == 15 and r["missed"] == [] and r["wrongly_rejected"] == 0


def test_a_lazy_checker_and_a_trigger_happy_one_are_both_scored_as_the_failures_they_are():
    async def lazy(answer, question):
        return []
    async def trigger_happy(answer, question):
        return [Finding("checker", s, "x") for s in split_sentences(answer) if not s.endswith("?")]   # like the real one, it is never shown questions
    lazy_r = asyncio.run(J.run_round(UNSUPPORTED, SUPPORTED, 0, lazy))
    happy_r = asyncio.run(J.run_round(UNSUPPORTED, SUPPORTED, 0, trigger_happy))
    assert lazy_r["caught"] == 0 and len(lazy_r["missed"]) == 15 and lazy_r["wrongly_rejected"] == 0
    assert happy_r["wrongly_rejected"] == len([s for s in SUPPORTED if not s.endswith("?")]) and happy_r["caught"] == 15


def test_a_checker_that_cannot_be_run_is_reported_not_scored_and_the_report_lists_misses():
    async def down(answer, question):
        return None
    assert asyncio.run(J.run_round(UNSUPPORTED, SUPPORTED, 0, down)) is None
    text = J.report([None, {"caught": 15, "of_unsupported": 16, "missed": ["Buy a small spool first."], "wrongly_rejected": 1, "of_supported": 16,
                            "wrongly_rejected_sentences": ["Do not use an extension cord (manual p.6)."]}])
    assert "could not be run" in text and "MISSED" in text and "WRONGLY REJECTED" in text and "caught 15 of 16" in text


def test_different_rounds_use_different_orders():
    assert J.build_answer(UNSUPPORTED, SUPPORTED, 0) != J.build_answer(UNSUPPORTED, SUPPORTED, 1)
