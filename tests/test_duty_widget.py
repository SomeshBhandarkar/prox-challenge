import json
import re
import shutil
import subprocess

import pytest

from app.tools.data import get_duty_cycle
from app.widgets.duty_cycle import AMPS_MAX, AMPS_MIN, PROCESSES, VOLTAGES, duty_cycle_widget


def _embedded(html: str, element_id: str):
    m = re.search(rf'<script id="{element_id}" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


HTML = duty_cycle_widget("mig", 240, 200)["html"]
DATA = _embedded(HTML, "data")


def test_every_table_entry_equals_the_verified_lookup():
    for proc in PROCESSES:
        for volt in VOLTAGES:
            for a in range(AMPS_MIN, AMPS_MAX + 1):
                r, e = get_duty_cycle(proc, volt, a), DATA[proc][volt]["amps"][str(a)]
                assert e["s"] == r["status"] and e["m"] == r["message"], (proc, volt, a)
                assert e.get("p") == r.get("duty_percent"), (proc, volt, a)
                assert e.get("w") == r.get("weld_minutes_per_10"), (proc, volt, a)
                assert e.get("r") == r.get("rest_minutes_per_10"), (proc, volt, a)


def test_prox_sample_case_mig_200a_240v_starts_as_25_percent():
    assert _embedded(HTML, "init") == {"proc": "MIG", "volt": "240VAC", "amps": 200}
    e = DATA["MIG"]["240VAC"]["amps"]["200"]
    assert (e["s"], e["p"], e["w"], e["r"]) == ("rated_point", 25, 2.5, 7.5)


def test_120v_trap_shows_above_machine_range():
    e = DATA["MIG"]["120VAC"]["amps"]["200"]
    assert e["s"] == "exceeds_machine_range" and "p" not in e


def test_label_only_60_percent_point_is_shown_with_its_source():
    rated = DATA["MIG"]["240VAC"]["rated"]
    point = next(p for p in rated if p["amps"] == 130)
    assert point["percent"] == 60 and point["on_specifications_page"] is False


def test_start_values_follow_the_arguments_and_are_clamped():
    assert _embedded(duty_cycle_widget("flux-cored", "120V", 85)["html"], "init") == {"proc": "MIG", "volt": "120VAC", "amps": 85}
    assert _embedded(duty_cycle_widget("tig", 240, 999)["html"], "init")["amps"] == AMPS_MAX
    assert _embedded(duty_cycle_widget("stick", 240)["html"], "init")["amps"] == 100


def test_invalid_input_gives_an_error_and_no_widget():
    for args in (("plasma", 240, 100), ("mig", 230, 100), ("mig", 240, -5)):
        w = duty_cycle_widget(*args)
        assert w["ok"] is False and "html" not in w and w["message"]


def test_page_is_self_contained_and_a_sane_size():
    assert "http://" not in HTML and "https://" not in HTML
    assert HTML.count("</script>") == 3  # data, init, logic: nothing in the data can close a script early
    assert len(HTML) < 600_000


def test_all_three_processes_and_both_voltages_are_offered():
    for key in ("MIG", "TIG", "Stick", "120VAC", "240VAC"):
        assert f'="{key}"' in HTML
    assert "MIG / flux-cored" in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_widget_javascript_has_no_syntax_errors(tmp_path):
    js = re.findall(r"<script>(.*?)</script>", HTML, re.S)[-1]
    f = tmp_path / "w.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
