"""The pre-submission check (scripts/check_ready.py): each part tested on small made-up inputs."""
from pathlib import Path

import pytest

from scripts import check_ready as C


def test_placeholders_are_found_and_ordinary_html_or_code_is_not():
    text = "Watch <VIDEO_LINK> and <CREDITS_REMAINING> on <DATE>; <b>bold</b> <br> <div class='x'> List<String> <p>"
    assert C.placeholders(text) == ["CREDITS_REMAINING", "DATE", "VIDEO_LINK"]
    assert C.placeholders("nothing to fill here") == []


def test_links_to_files_that_do_not_exist_are_reported_and_web_links_are_not(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ok.png").write_bytes(b"x")
    text = ('![a](docs/ok.png) ![b](docs/gone.png) [site](https://example.com/x.png) [anchor](#top) [mail](mailto:a@b.c)\n'
            '<img src="docs/also-gone.png"> <a href="docs/ok.png#part">p</a> [dir](docs/)')
    assert C.missing_links(text, tmp_path) == ["docs/also-gone.png", "docs/gone.png"]


def test_key_shaped_text_is_found_but_obviously_fake_short_ones_are_not():
    assert C.key_shaped("sk-ant-api03-" + "A1b2C3d4" * 6) != []
    assert C.key_shaped("sk-ant-mine and sk-ant-test-0000") == []


def test_the_real_key_is_found_by_value_and_only_the_file_name_is_returned(tmp_path: Path):
    leaky, clean = tmp_path / "notes.md", tmp_path / "ok.py"
    leaky.write_text("my key is SECRETVALUE-123456 oops")
    clean.write_text("print('hello')")
    binary = tmp_path / "pic.png"
    binary.write_bytes(b"SECRETVALUE-123456")   # not a text file: skipped
    real, shaped = C.scan_for_keys([leaky, clean, binary], "SECRETVALUE-123456")
    assert real == [leaky] and shaped == []
    assert C.scan_for_keys([leaky], "")[0] == []   # no key in .env: nothing to compare


def test_env_key_ignores_the_placeholder_and_missing_files(tmp_path: Path):
    assert C.env_key(tmp_path) == ""
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=your-api-key-here\n")
    assert C.env_key(tmp_path) == ""
    (tmp_path / ".env").write_text('# comment\nANTHROPIC_API_KEY="abc123"\n')
    assert C.env_key(tmp_path) == "abc123"


@pytest.mark.skipif(not (C.ROOT / ".git").exists(), reason="not a git checkout (for example a downloaded zip)")
def test_the_real_repository_ignores_env_and_the_private_notes():
    assert C.ignored(".env") and C.ignored("CLAUDE.md") and not C.ignored("README.md")
