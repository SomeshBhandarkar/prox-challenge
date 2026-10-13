from app.knowledge import FIGURES, PAGE_COVERAGE
from app.tools.figures import DEFAULT_PDF, PDFS, pdf_of

ALL = set(range(1, PDFS[DEFAULT_PDF]["pages"] + 1))


def covered() -> set:
    return {f["page"] for f in FIGURES if pdf_of(f) == DEFAULT_PDF}


def text_only() -> set:
    return {int(p) for p in PAGE_COVERAGE["text_only"]}


def pending() -> dict:
    return {patch: set(pages) for patch, pages in PAGE_COVERAGE["pending"].items()}


def test_every_manual_page_is_accounted_for_exactly_once():
    waiting = set().union(*pending().values()) if pending() else set()
    groups = {"figures": covered(), "text only": text_only(), "pending": waiting}
    assert covered() | text_only() | waiting == ALL, f"pages nobody accounted for: {sorted(ALL - (covered() | text_only() | waiting))}"
    for a in groups:
        for b in groups:
            if a < b:
                assert not (groups[a] & groups[b]), f"pages listed as both {a} and {b}: {sorted(groups[a] & groups[b])}"
    assert all(1 <= p <= 48 for g in groups.values() for p in g)


def test_all_patches_are_done_so_nothing_is_pending():
    assert pending() == {}, f"pages still waiting for a patch: {PAGE_COVERAGE['pending']}"


def test_text_only_pages_are_few_and_each_has_a_real_reason():
    assert len(text_only()) <= 3, "most pages should have a figure; justify any more text-only pages carefully"
    for page, reason in PAGE_COVERAGE["text_only"].items():
        assert len(reason.strip()) > 20 and ("text" in reason.lower()), page


def test_every_page_of_every_other_pdf_has_a_figure():
    for pdf, info in PDFS.items():
        if pdf == DEFAULT_PDF:
            continue
        pages = {f["page"] for f in FIGURES if pdf_of(f) == pdf}
        assert pages == set(range(1, info["pages"] + 1)), f"{pdf}: pages with figures {sorted(pages)} of {info['pages']}"


def test_the_most_cited_pages_always_have_figures():
    # the exam cites these pages most; they must never silently drop out of the library
    assert {7, 8, 9, 12, 13, 14, 16, 17, 20, 21, 35, 36, 37, 38, 39, 40, 42, 43, 44, 45, 46, 47} <= covered()


def test_the_record_matches_its_own_description():
    assert "after patch 5" in PAGE_COVERAGE["note"].lower()
    assert set(PAGE_COVERAGE) == {"note", "text_only", "pending"}
