import re

from app.knowledge import ROOT, TROUBLESHOOTING
from app.tools.troubleshooting import PROBLEMS, catalog_for_prompt, get_troubleshooting


def _pages() -> dict:
    text = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")
    parts = re.split(r"=====PAGE (\d+)=====", text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


PAGES = _pages()

# Counted from the manual's tables on pp 42-44 (viewed as page images).
EXPECTED_STEPS = {
    "mig_flux": [4, 4, 6, 8, 3, 5, 5, 4, 6],
    "tig_stick": [4, 2, 2, 4],
}


def test_problem_and_step_counts_match_the_manual_tables():
    for section in TROUBLESHOOTING["sections"]:
        assert [len(p["steps"]) for p in section["problems"]] == EXPECTED_STEPS[section["id"]], section["id"]


def test_every_word_of_every_entry_is_on_the_page_it_cites():
    for section in TROUBLESHOOTING["sections"]:
        assert _words(section["important"]) <= _words(PAGES[section["pages"][0]]), section["id"]
        for p in section["problems"]:
            assert p["page"] in section["pages"], p["id"]
            page_words = _words(PAGES[p["page"]])
            assert _words(p["problem"]) <= page_words, (p["id"], _words(p["problem"]) - page_words)
            for i, step in enumerate(p["steps"], 1):
                for field in ("cause", "solution"):
                    missing = _words(step[field]) - page_words
                    assert not missing, f"{p['id']} step {i} {field}: words not on p{p['page']}: {missing}"


def test_footer_and_phone_are_in_the_manual():
    assert _words(TROUBLESHOOTING["footer_safety"]) <= _words(PAGES[42])
    assert TROUBLESHOOTING["support_phone"] in PAGES[42]


def test_ids_are_unique_and_nothing_is_empty():
    ids = [p["id"] for s in TROUBLESHOOTING["sections"] for p in s["problems"]]
    assert len(ids) == len(set(ids)) == 13
    for p in PROBLEMS.values():
        assert p["problem"].strip() and p["steps"]
        for step in p["steps"]:
            assert step["cause"].strip() and step["solution"].strip()


def test_only_the_three_shielding_gas_steps_are_flagged_mig_only():
    flagged = {(p["id"], i) for p in PROBLEMS.values() for i, s in enumerate(p["steps"]) if s.get("mig_only")}
    assert flagged == {("mig-porosity", 0), ("mig-porosity", 1), ("mig-arc-not-stable", 6)}
    for pid, i in flagged:
        text = (PROBLEMS[pid]["steps"][i]["cause"] + PROBLEMS[pid]["steps"][i]["solution"]).lower()
        assert "gas" in text, (pid, i)


def test_flux_cored_porosity_has_the_polarity_step():
    r = get_troubleshooting("mig-porosity")
    polarity = [s for s in r["steps"] if "polarity" in s["cause"].lower()]
    assert r["found"] and r["page"] == 43 and len(polarity) == 1 and "DCEN for Flux-Cored" in polarity[0]["solution"]


def test_lookup_rejects_unknown_and_non_string_ids_without_crashing():
    for bad in ("nope", "", None, 7, ["mig-porosity"], {"id": 1}, "MIG-POROSITY "):
        r = get_troubleshooting(bad)
        assert r["found"] is False and "Valid ids" in r["message"]


def test_prompt_catalog_lists_every_problem():
    text = catalog_for_prompt()
    assert len(text.splitlines()) == 13
    for pid in PROBLEMS:
        assert pid in text
