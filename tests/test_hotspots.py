"""The clickable front panel and interior pictures: click areas (knowledge/data/hotspots.json) whose text is the manual's own wording."""
import re
from functools import lru_cache

import pytest

from app.guard import _words, split_sentences
from app.knowledge import HOTSPOTS, POLARITY, ROOT

FIGURES_WITH_HOTSPOTS = {"front-panel-controls": 8, "interior-controls": 9}
# the names printed on the manual's own pictures (pages 8 and 9): every one of them is clickable
LABELS = {
    "front-panel-controls": {"Home Button", "Back Button", "LCD Display", "Left Knob", "Control Knob", "Right Knob", "Storage Compartment", "Power Switch",
                             "MIG Gun / Spool Gun Cable Socket", "Spool Gun Gas Outlet", "Negative Socket", "Wire Feed Power Cable", "Positive Socket"},
    "interior-controls": {"Cold Wire Feed Switch", "Feed Tensioner", "Wire Feed Mechanism", "Idler Arm", "Feed Roller Knob", "Wire Spool", "Spool Knob",
                          "Wire Inlet Liner", "Foot Pedal Socket", "Wire Feed Control Socket"},
}
CITATION = re.compile(r"\(manual [^)]*\)")


@lru_cache(maxsize=None)
def page_text(n: int) -> str:
    text = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")
    return re.search(rf"=====PAGE {n}=====(.*?)(?=\n=====PAGE |\Z)", text, re.S).group(1)


def spots(figure):
    return HOTSPOTS[figure]


def all_spots():
    return [(f, h) for f in FIGURES_WITH_HOTSPOTS for h in spots(f)]


def test_every_name_printed_on_the_two_pictures_is_clickable_and_nothing_else_is():
    for figure, expected in LABELS.items():
        assert {h["label"] for h in spots(figure)} == expected, figure
    assert set(k for k in HOTSPOTS if k != "source") == set(FIGURES_WITH_HOTSPOTS)


@pytest.mark.parametrize("figure, spot", all_spots(), ids=lambda v: v if isinstance(v, str) else v["id"])
def test_each_label_is_really_printed_on_its_manual_page_and_the_box_is_sane(figure, spot):
    words = set(_words(page_text(FIGURES_WITH_HOTSPOTS[figure])))
    assert set(_words(spot["label"])) <= words, spot["label"]
    x, y, w, h = spot["box"]
    assert 0 <= x and 0 <= y and w >= 0.03 and h >= 0.03 and x + w <= 1 and y + h <= 1, spot["box"]
    assert re.fullmatch(r"[a-z_]+", spot["id"])


def test_ids_are_unique_and_no_two_click_areas_are_nearly_the_same_box():
    for figure in FIGURES_WITH_HOTSPOTS:
        ids = [h["id"] for h in spots(figure)]
        assert len(ids) == len(set(ids))
        boxes = [h["box"] for h in spots(figure)]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
                union = a[2] * a[3] + b[2] * b[3] - ix
                assert ix / union < 0.9, (a, b)   # a box inside a bigger one (the spool knob in the spool) is fine; the same box twice is not


@pytest.mark.parametrize("figure, spot", all_spots(), ids=lambda v: v if isinstance(v, str) else v["id"])
def test_every_sentence_cites_a_page_and_every_word_in_it_is_on_the_cited_pages(figure, spot):
    allowed_label = set(_words(spot["label"]))
    chunks = [c for c in re.split(r"(?<=\))\.\s+|(?<=\)\.)\s+", spot["text"]) if c.strip()]   # a chunk is one or more sentences ending in a page citation
    assert chunks
    for chunk in chunks:
        cites = CITATION.findall(chunk)
        assert cites and chunk.rstrip().endswith((")", ").")), f"does not end with a page citation: {chunk}"
        pages = {int(n) for c in cites for n in re.findall(r"p\.(\d+)", c)}
        assert pages and all(1 <= p <= 48 for p in pages), chunk
        on_pages = set().union(*(set(_words(page_text(p))) for p in pages))
        missing = sorted(w for w in set(_words(CITATION.sub(" ", chunk))) if w not in on_pages and w not in allowed_label)
        assert not missing, f"{spot['id']}: words not on the cited pages {sorted(pages)}: {missing} in: {chunk}"


def test_the_two_socket_texts_agree_with_the_verified_polarity_data():
    by = {h["id"]: h["text"] for h in spots("front-panel-controls")}
    for process, label in (("mig", "Solid Core"), ("flux_cored", "Flux-Cored"), ("tig", "TIG"), ("stick", "Stick")):
        for cable in POLARITY["setups"][process]["cables"]:
            text = by[f"{cable['socket']}_socket"]
            sentence = next(s for s in split_sentences(text) if s.startswith(label))
            assert cable["cable"] in sentence, (process, cable)
            other = "positive" if cable["socket"] == "negative" else "negative"
            assert cable["cable"] not in next(s for s in split_sentences(by[f"{other}_socket"]) if s.startswith(label)), (process, cable)
