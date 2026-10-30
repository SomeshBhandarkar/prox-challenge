"""Give Claude eyes: return a real manual page as an image."""
import base64

from app.knowledge import ROOT

PAGES_DIR = ROOT / "knowledge" / "pages"
LAST_PAGE = 48


def view_manual_page(page: int) -> dict:
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= LAST_PAGE:
        return {"ok": False, "message": f"Page must be between 1 and {LAST_PAGE}."}
    path = PAGES_DIR / f"page-{page:02d}.jpg"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"ok": True, "page": page, "image_b64": data}
