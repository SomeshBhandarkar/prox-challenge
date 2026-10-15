"""Checks on the web page files that need no browser. They catch the mistakes that break the page silently:
inline code the page's strict policy would block, external addresses, ids the script looks up that the HTML does not have."""
import json
import re
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from app import server as S
from app.agent_tools import TOOL_NAMES
from scripts.dev_server import DemoClient

WEB = S.ROOT / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "static" / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "style.css").read_text(encoding="utf-8")


def test_the_page_has_no_inline_script_style_or_event_handlers_because_the_policy_blocks_them():
    assert not re.search(r"<script(?![^>]*\bsrc=)", HTML), "inline <script> would be blocked by script-src 'self'"
    assert "<style" not in HTML.lower() and not re.search(r"\sstyle\s*=", HTML), "inline styles would be blocked by style-src 'self'"
    assert not re.search(r"\son[a-z]+\s*=", HTML, re.I), "inline event handlers would be blocked"
    assert "javascript:" not in HTML.lower()


def test_every_address_in_the_page_is_local_or_inline_data():
    for attr, value in re.findall(r"""\b(src|href|action)\s*=\s*["']([^"']*)["']""", HTML):
        assert value.startswith(("/static/", "data:", "#")), f"{attr}={value[:50]!r} must be local"
    assert not re.search(r"@import|url\(\s*[\"']?https?:", CSS), "the stylesheet must not load anything from outside"
    assert not re.search(r"""(?:fetch|open|src\s*=)\s*\(?\s*["']https?://""", JS), "the script must not call outside addresses"


def test_every_element_the_script_looks_up_exists_in_the_html():
    wanted = set(re.findall(r"\$\('([\w-]+)'\)", JS))
    assert len(wanted) >= 12
    have = set(re.findall(r'\bid="([\w-]+)"', HTML))
    assert not wanted - have, f"the script looks up ids the page does not have: {sorted(wanted - have)}"


def test_the_page_and_the_server_agree_on_the_event_names_and_limits():
    for name in ("session", "status", "text", "show", "error", "done"):
        assert f"'{name}'" in JS, f"app.js does not handle the '{name}' event"
    for field in ("session_id", "resumed", "manual_page", "embed", "identifier", "fatal", "caption", "source", "url"):
        assert field in JS, field
    assert int(re.search(r"const MAX = (\d+)", JS).group(1)) == S.MAX_QUESTION_CHARS
    assert int(re.search(r'maxlength="(\d+)"', HTML).group(1)) == S.MAX_QUESTION_CHARS
    assert "> 48" in JS and S.MANUAL_PAGES == 48  # the citation chips stop at the manual's last page


def test_every_status_the_server_can_send_is_plain_text_the_page_just_displays():
    assert "STATUS" in dir(S) and "statusText.textContent" in JS  # never innerHTML for status or error text


def test_frames_are_sandboxed_without_same_origin_and_the_message_sources_match_what_frames_send():
    assert "setAttribute('sandbox', 'allow-scripts')" in JS and "allow-same-origin" not in JS
    from app.artifacts import REPORTER_JS
    from app.show import WIDGET_REPORTER
    assert "source: 'artifact'" in REPORTER_JS and "source:'widget'" in WIDGET_REPORTER
    assert "'widget'" in JS and "'artifact'" in JS
    assert "e.source" in JS and "contentWindow" in JS  # messages are matched to a frame by identity, not by origin (it is "null")


def test_the_only_way_html_is_written_into_the_page_is_the_escaping_renderer():
    assert JS.count("innerHTML") == 1 and "innerHTML = renderText(" in JS
    for sink in ("insertAdjacentHTML", "outerHTML", "document.write", "eval(", "new Function", "setTimeout('", 'setTimeout("'):
        assert sink not in JS, sink
    assert "function esc" in JS or "const esc" in JS
    for ch in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert ch in JS, f"esc() must turn the character into {ch}"
    assert JS.index("esc(raw)") < JS.index("<strong>")  # escape first, add our own tags after


def test_the_automatic_fix_request_uses_the_wording_the_demo_agent_and_the_prompt_expect():
    assert "reported this error" in JS and "same identifier" in JS
    assert "state.retries" in JS and ">= 1" in JS  # one automatic fix per drawing, never a loop


def test_the_stylesheet_has_dark_mode_reduced_motion_and_every_variable_it_uses_is_defined():
    assert "prefers-color-scheme: dark" in CSS and "prefers-reduced-motion" in CSS
    defined = set(re.findall(r"(--[\w-]+)\s*:", CSS))
    used = set(re.findall(r"var\((--[\w-]+)", CSS))
    assert not used - defined, f"undefined CSS variables: {sorted(used - defined)}"


def test_the_page_is_ready_for_phones_and_keyboards():
    assert 'name="viewport"' in HTML and "width=device-width" in HTML and 'lang="en"' in HTML
    assert 'role="log"' in HTML and 'aria-live' in HTML and "<label" in HTML and "sr-only" in CSS
    assert "100dvh" in CSS  # the page fills a phone screen even with the browser bar showing
    phone_breakpoints = [int(n) for n in re.findall(r"@media \(max-width:\s*(\d+)px\)", CSS)]
    assert any(400 <= n <= 800 for n in phone_breakpoints), f"no phone breakpoint in the stylesheet: {phone_breakpoints}"
    assert "focus-visible" in CSS


def test_the_starter_questions_are_real_questions_within_the_limit():
    starters = re.findall(r'data-q="([^"]+)"', HTML)
    assert len(starters) >= 4
    assert all(5 < len(q) <= S.MAX_QUESTION_CHARS for q in starters)


# ---------- served by the real app ----------
@pytest.fixture
def client():
    app = S.create_app(client_factory=DemoClient, options_factory=lambda: None, model="haiku")
    with TestClient(app) as c:
        yield c


def test_the_app_serves_the_real_page_and_its_files(client):
    page = client.get("/")
    assert page.status_code == 200 and page.text == HTML and "script-src 'self'" in page.headers["content-security-policy"]
    js, css = client.get("/static/app.js"), client.get("/static/style.css")
    assert js.status_code == css.status_code == 200 and js.text == JS and css.text == CSS
    assert "javascript" in js.headers["content-type"] and css.headers["content-type"].startswith("text/css")


def test_the_pictures_the_page_can_ask_for_all_exist(client):
    from app.knowledge import FIGURES
    assert all(client.get(f"/figures/{f['id']}.png").status_code == 200 for f in FIGURES[:5])
    assert client.get("/pages/1.jpg").status_code == 200 and client.get("/pages/48.jpg").status_code == 200


def test_every_registered_tool_has_a_status_line_so_the_page_never_shows_a_blank():
    assert {n[len(S.PREFIX):] for n in TOOL_NAMES} == set(S.STATUS)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed (this test runs the page's callout pattern)")
def test_the_callout_pattern_recognises_the_manuals_warning_forms_and_leaves_normal_sentences_alone():
    regex = re.search(r"const LEVEL = (/.*/s);", JS).group(1)
    cases = {
        "WARNING (manual p.6): Do not use it.": True, "DANGER: live parts": True, "CAUTION - let it cool": True,
        "NOTICE: do not overtighten (manual p.17).": True, "WARNING! TO PREVENT SERIOUS INJURY: energized (manual p.32)": True,
        "**WARNING:** bold form": True, "Warning: lowercase is just text": False, "CAUTION is advised here": False,
        "WARNING signs are small": False, "Use caution: it is hot": False,
    }
    script = f"const L = {regex}; console.log(JSON.stringify({json.dumps(list(cases))}.map((c) => L.test(c))))"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == list(cases.values())


def test_the_page_really_talks_to_the_server_and_contains_no_mock_up_leftovers():
    """The v0 design came as a mock-up with canned replies and demo buttons; the page must call the real chat and show only what the server sends."""
    assert "fetch('/api/chat'" in JS and "fetch('/api/reset'" in JS and "readEvents(resp.body" in JS
    for leftover in ("Preview states", "demo-controls", "Manual pages 1", "MIG at 200A on 240V: 25% duty cycle"):
        assert leftover not in HTML and leftover not in JS and leftover not in CSS, leftover
    assert "Start: 18V" not in JS and "C25 mix" not in JS  # the mock's invented settings must never come back


def test_the_startup_screen_is_short_skippable_and_shown_once_per_visit():
    words = re.search(r"const INTRO = \[(.*?)\];", JS, re.S).group(1).count("'") // 2
    waits = [int(n) for n in re.findall(r"await wait\((\d+)\)", JS)]
    total = waits[0] * words + sum(waits[1:])  # one wait per word, then the pause before and after the "getting ready" line
    assert 0 < total <= 3500, f"the startup screen would take {total} ms: reviewers should not wait for it"
    assert "sessionStorage" in JS and "omnipro-seen" in JS and "prefers-reduced-motion" in JS  # once per visit, and none for people who ask for less motion
    assert "addEventListener('keydown', skip" in JS and "startup.addEventListener('click', skip)" in JS  # any key or a tap skips it
    assert 'id="startup"' in HTML and 'id="app-shell" hidden' in HTML  # the app is hidden until the startup screen is done (or skipped)


def test_the_answer_text_is_placed_before_its_pictures_and_the_view_goes_to_the_start_of_the_answer():
    """The prompt tells the model its pictures appear BELOW its text, so the page must really put them there (and not bury the text under a tall card)."""
    assert "state.prose.append(d)" in JS and "state.visuals.append(figureCard(d))" in JS and "state.visuals.append(frameCard(d))" in JS
    assert JS.index("state.prose = el('div', 'answer-text')") < JS.index("state.visuals = el('div', 'answer-visuals')")
    assert "state.msg.scrollIntoView({ block: 'start' })" in JS and "state.stick = false" in JS
    assert "state.body.append(figureCard" not in JS and "state.body.append(frameCard" not in JS
