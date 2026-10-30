"""Spotting an answer that says again what it already said (app/textdupe.py): used by the exam runner to flag it and by the server to
leave the second copy out of the page."""
import json
from pathlib import Path

from app import textdupe as T

REAL = json.loads((Path(__file__).parent / "fixtures" / "repeated_answer.json").read_text(encoding="utf-8"))["blocks"]


def test_the_real_repeated_answer_from_a_sonnet_run_is_caught():
    first, second = REAL
    share = T.repeated_share(second, T.shingles(first))
    assert share >= T.DROP_AT, f"only {share:.2f} of the repeat matched the original"


def test_two_different_long_blocks_are_not_a_repeat():
    a = "At 200A on 240V the MIG duty cycle is 25 percent, which means two and a half minutes of welding then seven and a half minutes of rest in every ten minute period."
    b = "Before you move any cable turn the Power Switch off and unplug the welder, then plug the ground clamp cable into the positive socket and twist it clockwise all the way to lock."
    assert T.repeated_share(b, T.shingles(a)) < 0.1


def test_short_blocks_are_never_judged_so_a_closing_sentence_survives():
    first = REAL[0]
    for short in ("Want me to open the setup sheet?", "Yes.", "The picture below shows it.", "Which process are you using, and on 120V or 240V?"):
        assert T.repeated_share(short, T.shingles(first)) == 0.0


def test_nothing_earlier_means_nothing_to_repeat():
    assert T.repeated_share(REAL[0], set()) == 0.0
    assert T.shingles("") == set() and T.shingles(None) == set()


def test_the_server_is_more_careful_than_the_flag():
    """Dropping text hides it from the person, so the server needs MORE overlap than the exam runner needs to merely flag a block."""
    assert T.DROP_AT > T.FLAG_AT >= 0.3 and T.MIN_GROUPS >= 10
