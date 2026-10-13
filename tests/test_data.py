"""Checks the lookups against the ground-truth answers in evals/questions.json."""
from app.tools.data import get_duty_cycle, get_polarity


def socket_of(process: str, cable_word: str) -> str:
    cables = get_polarity(process)["setup"]["cables"]
    return next(c["socket"] for c in cables if cable_word in c["cable"])


# ---------- duty cycle ----------
def test_mig_200a_on_240v_is_25_percent():
    r = get_duty_cycle("MIG", 240, 200)
    assert r["status"] == "rated_point"
    assert r["duty_percent"] == 25
    assert r["weld_minutes_per_10"] == 2.5
    assert r["rest_minutes_per_10"] == 7.5


def test_mig_200a_on_120v_is_over_the_range():
    r = get_duty_cycle("MIG", 120, 200)
    assert r["status"] == "exceeds_machine_range"
    assert r["range_A"] == [30, 140]


def test_mig_130a_on_240v_is_60_percent_from_the_label():
    r = get_duty_cycle("MIG", 240, 130)
    assert r["duty_percent"] == 60
    assert r["weld_minutes_per_10"] == 6
    point = next(p for p in r["rated_points"] if p["amps"] == 130)
    assert point["on_specifications_page"] is False  # only on the rating label


def test_tig_175a_on_240v_is_30_percent():
    r = get_duty_cycle("tig", "240", 175)
    assert r["duty_percent"] == 30
    assert r["weld_minutes_per_10"] == 3


def test_mig_150a_on_240v_is_between_points_and_plans_on_25():
    r = get_duty_cycle("MIG", 240, 150)
    assert r["status"] == "between_rated_points"
    assert r["conservative_percent"] == 25
    assert 25 < r["estimate"]["percent"] < 60
    assert "NOT in the manual" in r["estimate"]["note"]


def test_stick_100a_is_continuous_and_175a_is_25_percent():
    assert get_duty_cycle("stick", 240, 100)["status"] == "continuous"
    assert get_duty_cycle("stick", 240, 175)["duty_percent"] == 25


def test_flux_cored_uses_the_mig_rows_and_says_so():
    r = get_duty_cycle("flux-cored", 240, 200)
    assert r["duty_percent"] == 25
    assert any("flux-cored" in note.lower() for note in r["notes"])


def test_above_highest_rated_point_gives_no_invented_number():
    r = get_duty_cycle("MIG", 240, 215)
    assert r["status"] == "above_highest_rated_point"
    assert "duty_percent" not in r


def test_mig_130a_on_120v_is_above_the_highest_rated_point():
    r = get_duty_cycle("MIG", 120, 130)   # Q70, turn 1
    assert r["status"] == "above_highest_rated_point"
    assert r["conservative_percent"] == 40


def test_mig_220a_on_240v_has_no_100_percent_rating():
    r = get_duty_cycle("MIG", 240, 220)   # Q: "220A at 100% duty cycle?"
    assert r["status"] == "above_highest_rated_point"
    assert r["conservative_percent"] == 25


def test_invalid_inputs_are_rejected_clearly():
    assert get_duty_cycle("plasma", 240, 100)["status"] == "invalid"
    assert get_duty_cycle("MIG", 208, 100)["status"] == "invalid"
    assert get_duty_cycle("MIG", 240, -5)["status"] == "invalid"


# ---------- polarity ----------
def test_tig_clamp_positive_torch_negative():
    assert socket_of("TIG", "Ground") == "positive"
    assert socket_of("TIG", "Torch") == "negative"


def test_flux_cored_is_the_opposite_of_mig():
    assert socket_of("flux-cored", "Ground") == "positive"
    assert socket_of("flux-cored", "Wire Feed") == "negative"
    assert socket_of("MIG", "Ground") == "negative"
    assert socket_of("MIG", "Wire Feed") == "positive"


def test_stick_aliases_and_unknown_process():
    assert socket_of("SMAW", "Ground") == "negative"
    assert socket_of("SMAW", "Electrode Holder") == "positive"
    assert get_polarity("spool gun")["key"] == "spool_gun"
    assert get_polarity("laser")["found"] is False


def test_messages_have_no_double_period():
    for process in ("mig", "flux-cored", "tig", "stick", "spool gun"):
        assert ".." not in get_polarity(process)["message"]


def test_polarity_accepts_the_canonical_keys_the_tools_advertise():
    for key in ("mig", "flux_cored", "tig", "stick", "spool_gun"):
        assert get_polarity(key)["found"] is True and get_polarity(key)["key"] == key


def test_below_the_machine_range_is_not_reported_as_continuous():
    for args in (("MIG", 240, 10), ("MIG", 120, 20), ("TIG", 240, 5), ("Stick", 120, 9)):
        r = get_duty_cycle(*args)
        assert r["status"] == "below_machine_range", args
        assert "duty_percent" not in r and "cannot output" in r["message"]


def test_the_minimum_current_itself_is_still_valid():
    assert get_duty_cycle("MIG", 240, 30)["status"] == "continuous"
    assert get_duty_cycle("TIG", 240, 10)["status"] == "continuous"
