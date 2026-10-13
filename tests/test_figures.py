import re
import struct

from app.knowledge import FIGURES, ROOT
from app.tools.figures import FIGURES_DIR, PDFS, catalog_for_prompt, dpi_of, pdf_of, show_figure, source_label


def png_size(figure_id: str) -> tuple[int, int]:
    data = (FIGURES_DIR / f"{figure_id}.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", figure_id
    return struct.unpack(">II", data[16:24])


def test_ids_are_unique():
    ids = [f["id"] for f in FIGURES]
    assert len(ids) == len(set(ids))


def test_every_entry_is_well_formed():
    for f in FIGURES:
        pdf = pdf_of(f)
        assert pdf in PDFS, f"{f['id']}: unknown pdf {pdf}"
        assert (ROOT / "files" / pdf).exists(), f"{f['id']}: files/{pdf} is missing"
        assert 1 <= f["page"] <= PDFS[pdf]["pages"], f["id"]
        x0, y0, x1, y1 = f["box"]
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, f"{f['id']}: bad box"
        assert f["caption"].strip() and f["answers"], f["id"]


def test_every_figure_has_a_png_crop():
    for f in FIGURES:
        assert (FIGURES_DIR / f"{f['id']}.png").exists(), f"missing crop for {f['id']} (run scripts.make_figures)"


def test_crop_is_a_real_png_and_not_the_whole_page():
    for f in FIGURES:
        width, height = png_size(f["id"])
        # a thin strip of text is a legitimate figure; a near-empty sliver (a mis-set box) is not
        assert min(width, height) >= 100 and width * height >= 40_000, f"{f['id']} crop is tiny ({width}x{height})"
        page_w, page_h = (pts * dpi_of(f) / 72 for pts in PDFS[pdf_of(f)]["size_pts"])
        assert width < page_w * 0.98 or height < page_h * 0.98, f"{f['id']} looks like a whole page"


def test_each_crop_matches_its_box_so_a_changed_box_cannot_leave_a_stale_picture():
    for f in FIGURES:
        page_w, page_h = (pts * dpi_of(f) / 72 for pts in PDFS[pdf_of(f)]["size_pts"])
        x0, y0, x1, y1 = f["box"]
        width, height = png_size(f["id"])
        assert abs(width - (x1 - x0) * page_w) <= 2, f"{f['id']}: width {width} does not match its box (re-run scripts.make_figures)"
        assert abs(height - (y1 - y0) * page_h) <= 2, f"{f['id']}: height {height} does not match its box (re-run scripts.make_figures)"


def test_no_orphan_pngs_without_a_catalog_entry():
    ids = {f["id"] for f in FIGURES}
    for png in FIGURES_DIR.glob("*.png"):
        assert png.stem in ids, f"{png.name} has no catalog entry (renamed or removed? delete the file)"


def test_show_figure_returns_caption_page_and_url():
    r = show_figure("feed-mechanism")
    assert r["ok"] and r["page"] == 12 and r["url"] == "/figures/feed-mechanism.png"
    assert r["source"] == "Manual p.12"


def test_show_figure_labels_the_selection_chart_and_the_lcd_screens():
    chart = show_figure("selection-chart")
    assert chart["ok"] and chart["source"] == "Selection chart" and chart["url"] == "/figures/selection-chart.png"
    for fid in ("selection-chart-processes", "selection-chart-mig-vs-flux"):
        assert show_figure(fid)["source"] == "Selection chart"
    for fid, page in (("lcd-front-panel-knobs", 20), ("lcd-wire-diameter-thickness", 20), ("lcd-auto-weld-screen", 20),
                      ("lcd-polarity-gas-screen", 20), ("lcd-optional-settings", 21)):
        r = show_figure(fid)
        assert r["ok"] and r["page"] == page and r["source"] == f"Manual p.{page}", fid


def test_show_figure_rejects_unknown_and_path_tricks():
    for bad in ("nope", "", "../../.env", "feed-mechanism.png", None, [], {}):
        r = show_figure(bad)
        assert r["ok"] is False and "Valid ids" in r["message"]


def test_prompt_catalog_lists_every_figure_with_its_source():
    text = catalog_for_prompt()
    for f in FIGURES:
        assert f["id"] in text
        assert f"({source_label(f)})" in text
    assert "(Selection chart)" in text and "(Manual p.20)" in text


def test_figure_ids_are_safe_for_urls_and_unique_in_the_server_route():
    # the website serves /figures/<id>.png with the pattern [a-z0-9-]+
    for f in FIGURES:
        assert re.fullmatch(r"[a-z0-9-]+", f["id"]), f["id"]


def test_a_custom_dpi_is_sane_and_actually_used():
    custom = [f for f in FIGURES if "dpi" in f]
    assert custom and all(72 <= f["dpi"] <= 1200 for f in custom)
    label = next(f for f in FIGURES if f["id"] == "rating-label")
    width, height = png_size("rating-label")
    assert label["dpi"] == 1200 and width > 450 and height > 700  # the tiny label is cut big enough to read


def _pages() -> dict:
    text = (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8")
    parts = re.split(r"=====PAGE (\d+)=====", text)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def test_every_number_in_a_manual_figure_caption_is_on_the_page_it_cites_or_in_its_picture_text():
    """picture_text lists text that is visible only inside a picture (like an LCD screen), checked by eye when the figure was made."""
    pages, problems = _pages(), []
    for f in FIGURES:
        if pdf_of(f) != "owner-manual.pdf":
            continue  # the selection chart has no text layer
        allowed = set(re.findall(r"\d+", pages[f["page"]])) | set(re.findall(r"\d+", " ".join(f.get("picture_text", []))))
        missing = set(re.findall(r"\d+", f["caption"])) - allowed
        if missing:
            problems.append(f"{f['id']} (p{f['page']}): {sorted(missing)}")
    assert not problems, "caption numbers that are neither on the cited page nor in picture_text: " + "; ".join(problems)


def test_picture_text_is_a_list_of_short_strings_that_the_caption_actually_uses():
    for f in FIGURES:
        for item in f.get("picture_text", []):
            assert isinstance(item, str) and 0 < len(item) <= 30, f["id"]
            assert item.split()[0].strip('"') in f["caption"] or item in f["caption"], f"{f['id']}: picture_text {item!r} is not used in the caption"


def test_no_two_figures_share_a_caption():
    captions = [f["caption"] for f in FIGURES]
    assert len(captions) == len(set(captions))


def test_a_caption_never_says_something_is_energized_unless_its_page_does():
    """Found by the full Haiku run: my caption for the p.28 and p.18 pictures said the Power Switch energizes the torch/gun; the page does not say that
    (the LCD pages say the Right Knob ON energizes). The agent repeated the caption as if it were the manual."""
    pages = _pages()
    for f in FIGURES:
        if pdf_of(f) != "owner-manual.pdf":
            continue
        claims = " ".join([f["caption"], *f["answers"]]).lower()
        if "energize" in claims:
            assert "energize" in pages[f["page"]].lower(), f"{f['id']} (p{f['page']}): says 'energized' but that page does not"
