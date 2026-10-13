"""Artifact tool: it must accept messy-but-reasonable model output, refuse unsafe output with a clear message, and never crash."""
import asyncio
import json
import re
from pathlib import Path

import pytest

from app import agent_tools as T
from app.artifacts import CSP, MANUAL, MAX_CODE_CHARS, MIN_CODE_CHARS, build_artifact
from app.prompt import INSTRUCTIONS
from app.widgets.common import script_json

FIX = Path(__file__).parent / "fixtures" / "artifacts"


PAD = "<!-- " + "padding so this sample counts as a real drawing " * 3 + "-->"


def padded(code):
    """Real drawings are never a few characters (see MIN_CODE_CHARS); samples in these tests are short, so they get a harmless comment."""
    if not isinstance(code, str) or not code.strip() or len(code.strip()) >= MIN_CODE_CHARS:
        return code
    stripped = code.rstrip()
    return stripped[:-3].rstrip() + PAD + "\n```" if stripped.endswith("```") else code + PAD


def make(code="<p>hi</p>", identifier="demo", kind="html", title="Demo", pad=True):
    return build_artifact(identifier, kind, title, padded(code) if pad else code)


def manual_in(doc: str):
    m = re.search(r"window\.MANUAL=(\{.*?\});</script>", doc, re.S)
    return json.loads(m.group(1))


# ---------- the basics ----------
def test_a_minimal_html_and_svg_artifact_build():
    h = make()
    s = make('<svg viewBox="0 0 10 10"><circle r="4"/></svg>', kind="svg")
    assert h["ok"] and h["type"] == "html" and "<p>hi</p>" in h["html"]
    assert s["ok"] and s["type"] == "svg" and 'class="svg-wrap"' in s["html"]


def test_building_twice_gives_identical_output():
    assert make()["html"] == make()["html"]


# ---------- identifiers: a confused model should still work, and updates must still match ----------
@pytest.mark.parametrize("given, expected", [
    ("polarity-cheat-sheet", "polarity-cheat-sheet"),
    ("Polarity Cheat Sheet", "polarity-cheat-sheet"),
    ("  duty_cycle v2!! ", "duty-cycle-v2"),
    ("../../etc/passwd", "etc-passwd"),
    ("<script>alert(1)</script>", "script-alert-1-script"),
    ("a" * 200, "a" * 64),
    ("--leading--and--trailing--", "leading-and-trailing"),
    ("v1", "v1"),
])
def test_identifiers_are_cleaned_not_rejected(given, expected):
    assert make(identifier=given)["identifier"] == expected


def test_the_same_messy_identifier_always_maps_to_the_same_artifact():
    assert make(identifier="My Chart!")["identifier"] == make(identifier="my-chart")["identifier"]


@pytest.mark.parametrize("bad", [None, 5, "", "   ", "!!!", "---", [], {}, "ÄÖ", "\n"])
def test_unusable_identifiers_give_a_clear_error(bad):
    r = make(identifier=bad)
    assert r["ok"] is False and "identifier" in r["message"]


# ---------- types ----------
@pytest.mark.parametrize("given", ["html", "HTML", " Html ", "text/html"])
def test_html_type_spellings_are_accepted(given):
    assert make(kind=given)["type"] == "html"


@pytest.mark.parametrize("given", ["svg", "SVG", "image/svg+xml"])
def test_svg_type_spellings_are_accepted(given):
    assert make('<svg viewBox="0 0 1 1"/>', kind=given)["type"] == "svg"


@pytest.mark.parametrize("bad", [None, 5, "", "react", "jsx", "javascript", "html; drop", "markdown", [], {}])
def test_unknown_types_are_refused_and_list_the_valid_ones(bad):
    r = make(kind=bad)
    assert r["ok"] is False and "html" in r["message"] and "svg" in r["message"]


# ---------- titles ----------
@pytest.mark.parametrize("bad", [None, "", "   ", 7, [], {}])
def test_missing_titles_fall_back_to_the_identifier(bad):
    assert make(identifier="polarity-cheat-sheet", title=bad)["title"] == "Polarity cheat sheet"


def test_long_titles_are_shortened_not_rejected():
    assert len(make(title="x" * 500)["title"]) == 80


def test_a_title_cannot_inject_markup():
    html = make(title="</title><script>alert(1)</script>")["html"]
    assert "</title><script>alert(1)" not in html and "&lt;/title&gt;" in html


# ---------- code: empty, huge, odd ----------
@pytest.mark.parametrize("bad", [None, 5, "", "   \n\t ", [], {}, "```html\n\n```"])
def test_empty_or_non_text_code_is_refused(bad):
    r = make(code=bad, pad=False)
    assert r["ok"] is False and "empty" in r["message"]


def test_size_limit_is_exact():
    assert make("a" * MAX_CODE_CHARS)["ok"] is True
    r = make("a" * (MAX_CODE_CHARS + 1))
    assert r["ok"] is False and str(MAX_CODE_CHARS) in r["message"]


def test_unicode_emoji_and_control_characters_do_not_crash():
    for code in ["<p>✅ café 中文 \U0001f527</p>", "<p>\x00\x01 nul and control</p>", "<p>‮ rtl</p>", "﻿<p>bom</p>"]:
        assert make(code)["ok"] is True


def test_markdown_fences_around_code_are_removed():
    for code in ["```html\n<p>hi</p>\n```", "```\n<p>hi</p>\n```", "  ```HTML \n<p>hi</p>\n```  \n"]:
        r = make(code)
        assert r["ok"] and "<p>hi</p>" in r["html"] and "```" not in r["html"]


def test_a_whole_html_document_is_accepted_and_keeps_exactly_our_three_metas():
    r = make((FIX / "full_document.html").read_text(encoding="utf-8"))
    assert r["ok"]
    assert r["html"].count("<meta") == 3  # charset, Content-Security-Policy, viewport: all ours
    assert r["html"].count('http-equiv="Content-Security-Policy"') == 1


# ---------- forbidden tags: refused with a message that says what to remove ----------
@pytest.mark.parametrize("code, tag", [
    ('<iframe src="https://x"></iframe>', "iframe"),
    ("<IFRAME src=x>", "iframe"),
    ("<iframe\nsrc=x>", "iframe"),
    ("<object data=x>", "object"),
    ("<embed src=x>", "embed"),
    ('<base href="https://evil.example/">', "base"),
    ('<meta http-equiv="refresh" content="0;url=https://evil.example/">', "meta"),
    ('<meta http-equiv="Content-Security-Policy" content="default-src *">', "meta"),
    ('<link rel="stylesheet" href="https://evil.example/x.css">', "link"),
    ('<svg viewBox="0 0 1 1"><foreignObject><iframe src=x></iframe></foreignObject></svg>', "iframe"),
    ('<div>ok</div><p>fine</p><IfRaMe src=x>', "iframe"),
])
def test_forbidden_tags_are_refused_with_a_clear_message(code, tag):
    r = make(code)
    assert r["ok"] is False and f"<{tag}>" in r["message"]


def test_a_viewport_meta_carrying_a_refresh_is_stripped_whole_not_passed_through():
    r = make('<meta name="viewport" http-equiv="refresh" content="0;url=https://evil.example/"><p>x</p>')
    assert r["ok"] and "evil.example" not in r["html"]


def test_svg_type_must_start_with_an_svg_element():
    for bad in ["<p>not svg</p>", "hello", "<div><svg/></div>"]:
        r = make(bad, kind="svg")
        assert r["ok"] is False and "<svg" in r["message"]
    assert make("﻿ \n\t<SVG viewBox='0 0 1 1'/>", kind="svg")["ok"] is True


# ---------- the wrapper itself ----------
def test_csp_is_the_first_thing_in_the_head_and_before_any_script():
    doc = make("<script>var a = 1;</script>")["html"]
    csp = doc.index("Content-Security-Policy")
    assert csp < doc.index("<script") and csp < doc.index("<style")
    assert CSP in doc
    for directive in ("default-src 'none'", "connect-src 'none'", "frame-src 'none'", "form-action 'none'", "base-uri 'none'"):
        assert directive in CSP
    assert "unsafe-eval" not in CSP and "http" not in CSP


def test_the_manual_data_is_injected_exactly_and_cannot_break_out_of_its_script():
    doc = make()["html"]
    assert manual_in(doc) == MANUAL
    assert "window.__ARTIFACT_ID__" in doc and "Content-Security-Policy" in doc
    assert "</script><" not in script_json({"a": "</script><b>hi</b>"}) and "<" not in script_json({"a": "<!--</script>"})


def test_artifact_code_containing_closing_tags_cannot_remove_our_reporter_or_csp():
    doc = make("</main></body></html><script>var x=1</script>")["html"]
    assert doc.index("Content-Security-Policy") < doc.index("var x=1")
    assert doc.index("window.addEventListener('error'") < doc.index("var x=1")  # reporter runs before the artifact's code


def test_dark_mode_variables_are_available_to_artifacts():
    doc = make()["html"]
    for var in ("--bg", "--fg", "--muted", "--card", "--panel", "--line", "--ok", "--warn", "--bad", "--accent"):
        assert var + ":" in doc
    assert "prefers-color-scheme:dark" in doc


# ---------- the prompt and the data must agree ----------
def test_the_prompt_teaches_only_manual_keys_that_really_exist():
    assert set(MANUAL) == {"specifications", "polarity", "controls", "troubleshooting"}
    section = INSTRUCTIONS[INSTRUCTIONS.index("DRAW IT YOURSELF"):INSTRUCTIONS.index("ASK WHEN IT MATTERS")]
    for key in MANUAL:
        assert key in section
    assert section.count("window.MANUAL.polarity.setups.tig.cables") == 1
    assert MANUAL["polarity"]["setups"]["tig"]["cables"][0]["cable"]
    for path in (["specifications", "processes", "MIG"], ["specifications", "rating_label"], ["controls", "front_panel"],
                 ["controls", "interior"], ["troubleshooting", "sections"]):
        node = MANUAL
        for part in path:
            node = node[part]
    for setup in ("mig", "flux_cored", "tig", "stick", "spool_gun"):
        s = MANUAL["polarity"]["setups"][setup]
        assert s["cables"] and "other_connections" in s and "gas" in s and "sources" in s
        assert all({"cable", "socket"} <= set(c) for c in s["cables"])
        assert setup in section


# ---------- the tool as Claude calls it ----------
def call(args):
    return json.loads(asyncio.run(T.create_artifact.handler(args))["content"][0]["text"])


def test_tool_success_names_the_final_identifier_and_never_returns_html():
    r = call({"identifier": "Polarity Cheat Sheet", "type": "HTML", "title": "T", "code": padded("<p>hi</p>")})
    assert r["ok"] and "'polarity-cheat-sheet'" in r["message"] and "html" not in r


def test_tool_refusals_explain_what_to_fix():
    r = call({"identifier": "x", "type": "html", "title": "t", "code": "<iframe src=x>"})
    assert r["ok"] is False and "iframe" in r["message"]


@pytest.mark.parametrize("args", [
    {}, {"identifier": None, "type": None, "title": None, "code": None},
    {"identifier": ["a"], "type": {}, "title": 5, "code": 7},
    {"identifier": "x" * 10_000, "type": "html" * 1000, "title": "t" * 10_000, "code": "<p>" * 50_000},
    {"identifier": "ok", "type": "html", "title": "t", "code": "<p>x</p>", "extra": "ignored"},
])
def test_tool_never_crashes_on_garbage(args):
    r = asyncio.run(T.create_artifact.handler(args))
    assert isinstance(r["content"], list) and r["content"][0]["type"] == "text"


def test_replacing_an_artifact_is_just_calling_again():
    first = call({"identifier": "x", "type": "html", "title": "T", "code": padded("<p>one</p>")})
    second = call({"identifier": "x", "type": "html", "title": "T", "code": padded("<p>two</p>")})
    assert first["ok"] and second["ok"]


# ---------- the sample artifacts ----------
@pytest.mark.parametrize("name", ["cheat_sheet.html", "broken.html", "syntax_error.html", "hostile.html", "full_document.html", "sample.svg"])
def test_every_sample_artifact_passes_the_static_checks(name):
    kind = "svg" if name.endswith(".svg") else "html"
    assert build_artifact(Path(name).stem, kind, name, (FIX / name).read_text(encoding="utf-8"))["ok"] is True


def test_the_cheat_sheet_only_reads_data_that_exists():
    code = (FIX / "cheat_sheet.html").read_text(encoding="utf-8")
    assert "window.MANUAL.polarity.setups" in code
    for key in re.findall(r"'(mig|flux_cored|tig|stick)'", code):
        assert key in MANUAL["polarity"]["setups"]


# ---------- placeholders (found by the full Haiku run: a '<p>unused</p>' card, then an apology in the answer) ----------
@pytest.mark.parametrize("code", ["<p>unused</p>", "<p>test</p>", "x", '<svg viewBox="0 0 1 1"/>'])
def test_a_tiny_placeholder_is_refused_quietly_with_a_message_that_tells_the_model_why(code):
    r = build_artifact("never-used", "html" if code.startswith("<p>") or code == "x" else "svg", "noop", code)
    assert r["ok"] is False and r["trivial"] is True
    assert "too little to be a real drawing" in r["message"] and "never as a test or placeholder" in r["message"]


def test_the_smallest_real_drawing_is_accepted_and_the_floor_counts_the_code_not_the_fences():
    ok = "<p>" + "a" * (MIN_CODE_CHARS - 7) + "</p>"
    assert len(ok) == MIN_CODE_CHARS and build_artifact("d", "html", "t", ok)["ok"] is True
    assert build_artifact("d", "html", "t", ok[:-1])["ok"] is False
    assert build_artifact("d", "html", "t", "```html\n<p>unused</p>\n```")["ok"] is False  # fences do not make it bigger
