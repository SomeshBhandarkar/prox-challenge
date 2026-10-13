import base64

from app.tools.manual import LAST_PAGE, PAGES_DIR, view_manual_page


def test_page_14_returns_a_jpeg_image():
    result = view_manual_page(14)
    assert result["ok"] and result["page"] == 14
    assert base64.b64decode(result["image_b64"])[:3] == b"\xff\xd8\xff"  # JPEG signature


def test_out_of_range_pages_are_rejected():
    for bad in (0, 49, -1):
        assert view_manual_page(bad)["ok"] is False


def test_non_integer_page_is_rejected():
    assert view_manual_page("14")["ok"] is False


def test_all_48_page_files_exist():
    for page in range(1, LAST_PAGE + 1):
        assert (PAGES_DIR / f"page-{page:02d}.jpg").exists(), f"missing page {page}"


def test_tool_wrappers_import_and_register():
    from app.agent_tools import TOOL_NAMES, server

    assert len(TOOL_NAMES) == 9 and server is not None
