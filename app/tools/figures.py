"""Figure library: exact crops of the manual's pictures, chosen by id."""
from app.knowledge import FIGURES, ROOT

FIGURES_DIR = ROOT / "knowledge" / "figures"
DEFAULT_PDF = "owner-manual.pdf"
CROP_DPI = 200
# every PDF a figure can come from: page count and page size in points (the manual is all A4; the chart is one square page; the quick-start guide is two A5 pages)
PDFS = {
    "owner-manual.pdf": {"pages": 48, "size_pts": (595.276, 841.89)},
    "selection-chart.pdf": {"pages": 1, "size_pts": (1200.0, 1200.0)},
    "quick-start-guide.pdf": {"pages": 2, "size_pts": (419.528, 595.276)},
}
BY_ID = {f["id"]: f for f in FIGURES}


def pdf_of(f: dict) -> str:
    return f.get("pdf", DEFAULT_PDF)


def dpi_of(f: dict) -> int:
    """Crops are cut at 200 DPI; a tiny detail (like the rating label) can ask for more."""
    return f.get("dpi", CROP_DPI)


def source_label(f: dict) -> str:
    """What the screen shows under the picture: 'Manual p.12' or 'Selection chart'."""
    return f.get("source") or f"Manual p.{f['page']}"


def show_figure(figure_id: str) -> dict:
    f = BY_ID.get(figure_id) if isinstance(figure_id, str) else None
    if f is None or not (FIGURES_DIR / f"{figure_id}.png").exists():
        return {"ok": False, "message": f"No figure '{figure_id}'. Valid ids: {sorted(BY_ID)}"}
    return {
        "ok": True,
        "id": figure_id,
        "page": f["page"],
        "source": source_label(f),
        "caption": f["caption"],
        "url": f"/figures/{figure_id}.png",
    }


def catalog_for_prompt() -> str:
    """One line per figure; goes into Claude's system prompt so it can choose without opening pages."""
    ordered = sorted(FIGURES, key=lambda f: (pdf_of(f) != DEFAULT_PDF, f["page"]))  # manual pages in order, then other PDFs
    return "\n".join(
        f"- {f['id']} ({source_label(f)}): {f['caption']}. Useful for: {', '.join(f['answers'])}"
        for f in ordered
    )
