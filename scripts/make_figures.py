"""Cut every figure in figures.json out of its PDF at 200 DPI (authoring tool, needs poppler).

Run from the project folder:  .venv/bin/python -m scripts.make_figures
The finished PNGs are committed, so reviewers never need to run this.
"""
import html
import re
import subprocess

from app.knowledge import FIGURES, ROOT
from app.tools.figures import PDFS, dpi_of, pdf_of, source_label

FILES = ROOT / "files"
OUT = ROOT / "knowledge" / "figures"


def page_size_pts(pdf: str, page: int) -> tuple[float, float]:
    out = subprocess.run(
        ["pdfinfo", "-f", str(page), "-l", str(page), str(FILES / pdf)],
        capture_output=True, text=True, check=True,
    ).stdout
    w, h = re.search(rf"Page\s+{page} size:\s+([\d.]+) x ([\d.]+)", out).groups()
    return float(w), float(h)


def check_entry(f: dict) -> None:
    pdf = pdf_of(f)
    if pdf not in PDFS:
        raise SystemExit(f"{f['id']}: unknown pdf {pdf!r}; add it to PDFS in app/tools/figures.py")
    if not 1 <= f["page"] <= PDFS[pdf]["pages"]:
        raise SystemExit(f"{f['id']}: page {f['page']} is outside 1-{PDFS[pdf]['pages']} of {pdf}")
    if not 72 <= dpi_of(f) <= 1200:
        raise SystemExit(f"{f['id']}: dpi {dpi_of(f)} must be between 72 and 1200")
    x0, y0, x1, y1 = f["box"]
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise SystemExit(f"{f['id']}: box {f['box']} must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for f in FIGURES:
        check_entry(f)
        pdf = pdf_of(f)
        w, h = page_size_pts(pdf, f["page"])
        dpi = dpi_of(f)
        px_w, px_h = w * dpi / 72, h * dpi / 72
        x0, y0, x1, y1 = f["box"]
        subprocess.run(
            [
                "pdftoppm", "-png", "-singlefile", "-r", str(dpi),
                "-f", str(f["page"]), "-l", str(f["page"]),
                "-x", str(int(x0 * px_w)), "-y", str(int(y0 * px_h)),
                "-W", str(int((x1 - x0) * px_w)), "-H", str(int((y1 - y0) * px_h)),
                str(FILES / pdf), str(OUT / f["id"]),
            ],
            check=True,
        )
    # contact sheet: open in a browser to spot-check every crop
    cards = "".join(
        f'<figure style="margin:0;max-width:440px"><img src="{f["id"]}.png" width="420" style="border:1px solid #ccc">'
        f'<figcaption><b>{html.escape(f["id"])}</b> ({html.escape(source_label(f))})<br>{html.escape(f["caption"])}</figcaption></figure>'
        for f in FIGURES
    )
    (OUT / "index.html").write_text(
        f"<!doctype html><meta charset='utf-8'><title>Figure contact sheet</title>"
        f"<body style='font-family:sans-serif;display:flex;flex-wrap:wrap;gap:20px;padding:16px'>{cards}</body>",
        encoding="utf-8",
    )
    print(f"Made {len(FIGURES)} figures in {OUT}. Open knowledge/figures/index.html to check them.")


if __name__ == "__main__":
    main()
