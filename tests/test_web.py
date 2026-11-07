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


def test_the_working_line_sits_under_the_question_and_the_top_strip_goes_quiet_while_busy():
    start = JS[JS.index("function startExchange"):JS.index("function addNote")]
    assert "el('div', 'working')" in start and "state.body.append(state.prose, state.visuals, state.working)" in start  # the answer fills in above it
    assert "aria-hidden" in start  # the status strip stays the one live region, so screen readers do not hear it twice
    assert "state.working.lastChild.textContent = line" in JS and ".remove()" in JS[JS.index("working.remove()"):][:20]
    assert "statusStrip.classList.toggle('quiet', on)" in JS
    assert re.search(r"\.status-strip\.quiet \{ opacity: 0;", CSS)  # hidden, not removed: no layout jump and still announced
    assert ".working-dot { animation: none; }" in CSS  # reduced motion: no endless flicker


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
    app = S.create_app(client_factory=DemoClient, options_factory=lambda: None, model="haiku", guard_text=False)
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


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed (this test runs the page's own helper)")
def test_a_callout_written_as_one_bold_sentence_does_not_show_leftover_stars():
    """Found on the real page (setup sheet): "**WARNING: Turn the Power Switch off before setup** (manual p.10)." showed 'setup**' inside the callout."""
    helper = re.search(r"function dropStrayBold\(body\) \{.*?\n  \}", JS, re.S).group(0)
    cases = {"Turn it off before setup** (manual p.10).": "Turn it off before setup (manual p.10).",
             "Plain text (manual p.10).": "Plain text (manual p.10).",
             "A **bold** word and more.": "A **bold** word and more.",
             "**Both** ends are bold** here.": "**Both** ends are bold here."}
    script = f"{helper}; const c = {json.dumps(cases)}; console.log(JSON.stringify(Object.keys(c).map((k) => dropStrayBold(k))))"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == list(cases.values())
    assert "dropStrayBold(m[3]" in JS   # and the callout really uses it


def test_the_page_really_talks_to_the_server_and_contains_no_mock_up_leftovers():
    """The v0 design came as a mock-up with canned replies and demo buttons; the page must call the real chat and show only what the server sends."""
    assert "fetch('/api/chat'" in JS and "fetch('/api/reset'" in JS and "readEvents(resp.body" in JS
    for leftover in ("Preview states", "demo-controls", "Manual pages 1", "MIG at 200A on 240V: 25% duty cycle"):
        assert leftover not in HTML and leftover not in JS and leftover not in CSS, leftover
    assert "Start: 18V" not in JS and "C25 mix" not in JS  # the mock's invented settings must never come back


def test_the_startup_screen_waits_for_a_key_or_a_click_and_is_shown_once_per_visit():
    body = re.search(r"async function runStartup\(\) \{(.*?)\n  \}\n", JS, re.S).group(1)
    words = re.search(r"const INTRO = \[(.*?)\];", JS, re.S).group(1).count("'") // 2
    waits = [int(n) for n in re.findall(r"await wait\((\d+)\)", body)]
    animation = waits[0] * words + sum(waits[1:])  # one wait per word, then the pause before the "press any key" line
    assert 0 < animation <= 3000, f"the words would take {animation} ms before the 'press any key' line: reviewers should not wait for it"
    assert "sessionStorage" in JS and "omnipro-seen" in JS and "prefers-reduced-motion" in JS  # once per visit, and none for people who ask for less motion
    assert "startup.addEventListener('click', enter" in body and "addEventListener('keydown', onKey)" in body  # a click, a tap or a key opens the app
    # nothing closes the screen by itself: the app is shown from the early shortcut and from `enter` (a key or a click), never after a timer
    assert body.count("showApp()") == 2 and "setTimeout" not in body and "setInterval" not in body
    assert body.rindex("enterLine.classList.add('visible')") > body.rindex("await wait(")  # the last thing it does is show the line and wait
    # the key that opens the app must not type into the box; browser shortcuts and a lone Shift are not a way in
    assert "e.preventDefault()" in body and "e.ctrlKey || e.metaKey || e.altKey" in body and "NOT_ENTER" in body and r"/^F\d+$/" in body
    assert "pointer: coarse" in JS  # a phone says "Tap to enter" and the box is not focused (it would open the keyboard over the starter questions)
    assert 'id="startup-prompt"' in HTML and "any key" in HTML and "startup-hint" not in HTML and "Getting your manual ready" not in HTML
    assert 'id="startup"' in HTML and 'id="app-shell" hidden' in HTML  # the app is hidden until the person comes in
    assert ".startup-prompt.visible { animation: none; }" in CSS  # reduced motion: an endless animation squeezed to 0.01 ms would flicker


def test_the_answer_text_is_placed_before_its_pictures_and_the_view_goes_to_the_start_of_the_answer():
    """The prompt tells the model its pictures appear BELOW its text, so the page must really put them there (and not bury the text under a tall card)."""
    assert "state.prose.append(d)" in JS and "state.visuals.append(figureCard(d))" in JS and "state.visuals.append(frameCard(d))" in JS
    assert JS.index("state.prose = el('div', 'answer-text')") < JS.index("state.visuals = el('div', 'answer-visuals')")
    assert "state.msg.scrollIntoView({ block: 'start' })" in JS and "state.stick = false" in JS
    assert "state.body.append(figureCard" not in JS and "state.body.append(frameCard" not in JS


# ---------- voice: speaking a question, and hearing an answer read aloud ----------
def test_the_microphone_is_hidden_until_the_browser_proves_it_can_listen():
    mic = re.search(r'<button[^>]*\bid="mic"[^>]*>', HTML).group(0)
    assert " hidden" in mic and "aria-label=" in mic and 'type="button"' in mic  # hidden by default, named for screen readers, never submits the form
    assert 'id="i-mic"' in HTML and 'id="i-speaker"' in HTML
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in JS
    assert re.search(r"if \(Recognition\) \{\s*micBtn\.hidden = false;", JS), "the button may only be shown when speech recognition exists"
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", CSS), "a display rule on .mic must not be able to show a hidden button"


def test_speaking_only_fills_the_question_box_and_never_sends_it():
    """A misheard word ('tick' for 'TIG') must never reach the assistant by itself: the person reads the box and presses send."""
    onresult = re.search(r"r\.onresult = \(e\) => \{(.*?)\n    \};", JS, re.S).group(1)
    assert "input.value" in onresult and "grow()" in onresult
    for sending in ("send(", "requestSubmit", "submit", "fetch("):
        assert sending not in onresult, f"voice must not call {sending}"
    assert ".slice(0, MAX)" in onresult  # a long speech cannot go past the 2000-character limit
    assert "r.onresult = r.onerror = r.onend = null" in JS  # cancelling must stop late results from refilling the box
    send_body = re.search(r"async function send\(.*?\n  \}\n", JS, re.S).group(0)
    assert "cancelListening()" in send_body and "stopReading()" in send_body  # a new question stops listening and reading
    new_chat = re.search(r"function newChat\(\) \{(.*?)\n  \}\n", JS, re.S).group(1)
    assert "cancelListening()" in new_chat and "stopReading()" in new_chat


def test_the_microphone_keeps_listening_through_pauses_and_has_a_two_minute_safety_stop():
    start = re.search(r"function startListening\(\) \{(.*?)\n  \}\n", JS, re.S).group(1)
    assert "r.continuous = true" in start and "r.continuous = false" not in JS             # a pause does not end it
    assert "SILENCE_LIMIT_MS = 120000;" in JS and "arm();" in start                       # two minutes without words ends it, and every result restarts that clock
    onend = re.search(r"r\.onend = \(\) => \{(.*?)\n    \};", start, re.S).group(1)
    assert "r.start()" in onend and "wantStop" in onend and "carried" in onend            # a round the browser ended by itself is started again, keeping the words
    assert "quickEnds <= 4" in onend                                                      # ...but not forever when every round ends at once
    assert "'no-speech'" not in re.search(r"const MIC_PROBLEMS = \{.*?\};", JS, re.S).group(0)   # a quiet moment is not an error message
    assert "recog ? stopListening() : startListening()" in JS                             # tapping the microphone is the way to stop
    assert "clearTimeout(silenceTimer)" in re.search(r"function micIdle\(\) \{(.*?)\n  \}\n", JS, re.S).group(1)   # a stopped microphone leaves no timer behind


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed (this test runs the page's reading-aloud patterns)")
def test_reading_aloud_says_page_numbers_in_words_and_does_not_split_decimals():
    split = re.search(r"\.split\((/\(\?<=\[\.!\?\]\)\\s\+\|\\n\+/)\)", JS).group(1)
    page = re.search(r"\.replace\((/\\bp\\\.\\s\?\(\\d\+\)/g), 'page \$1'\)", JS).group(1)
    text = "The duty cycle is 25% (manual p.19). Use 0.030 wire.\nIs that clear? Yes!"
    script = f"const t = {json.dumps(text)}.replace({page}, 'page $1'); console.log(JSON.stringify(t.split({split}).map((s) => s.trim()).filter(Boolean)))"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["The duty cycle is 25% (manual page 19).", "Use 0.030 wire.", "Is that clear?", "Yes!"]
    assert "'.answer-text'" in JS and "answer-visuals" not in re.search(r"function spokenText.*?\n  \}\n", JS, re.S).group(0)  # only the answer's words are read


def test_the_listening_button_shows_it_is_listening_without_relying_on_animation():
    assert re.search(r"\.mic\.listening \{[^}]*background:\s*var\(--accent\)", CSS), "a filled button must show the state even with no animation"
    reduced = CSS[CSS.index("prefers-reduced-motion: reduce"):]
    assert ".mic.listening { animation: none; }" in reduced
    assert "var(--on-accent)" in re.search(r"\.mic\.listening \{[^}]*\}", CSS).group(0)  # readable text colour on the accent in light and dark


def test_voice_adds_no_new_way_to_write_html_or_reach_outside():
    assert JS.count("innerHTML") == 1  # the escaping renderer is still the only HTML sink (spoken text uses innerText, buttons use el())
    voice = JS[JS.index("// ---------- voice"):]
    for outside in ("fetch(", "XMLHttpRequest", "WebSocket", "http://", "https://", "navigator.sendBeacon"):
        assert outside not in voice, outside


# ---------- the text renderer, run on its own in Node ----------
def _render_in_node(cases):
    """Run the page's real markdown code (not a copy) on some texts and return the HTML it makes for each."""
    esc = re.search(r"^\s*const esc = .*;$", JS, re.M).group(0)
    start = JS.index("  // ---------- text: a small, safe markdown ----------")
    end = JS.index("  // ---------- what appears in the conversation ----------")
    script = f"{esc}\n{JS[start:end]}\nconsole.log(JSON.stringify({json.dumps(cases)}.map(renderText)))"
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed (this test runs the page's text renderer)")
def test_numbered_lists_keep_their_numbers_when_bullets_sit_inside_or_between_the_items():
    """Found in a real Sonnet answer: bullets under '1. Polarity' cut the list in two, so the next items showed as 1, 2, 3 again."""
    nested, between, plain, resumed, capped, wrapped, hostile = _render_in_node([
        "1. **Polarity.** check it\n   - Ground clamp in Positive\n   - Wire feed in Negative\n2. **Dirty workpiece.** clean it\n3. **Gun too far.** check CTWD",
        "1. First\n- a bullet\n- another\n2. Second\n3. Third",
        "1. one\n2. two\n\n- x\n- y",
        "3. three\n4. four",
        "999. huge number",
        "1. a long item that\n   wraps onto a second line\n   - and a sub-point that\n     wraps too",
        "- <img src=x onerror=alert(1)>\n   - <script>alert(2)</script>",
    ])
    assert nested.count("<ol") == 1 and nested.count("</ol>") == 1, nested
    assert nested.startswith("<ol><li><strong>Polarity.</strong> check it<ul><li>Ground clamp in Positive</li><li>Wire feed in Negative</li></ul></li><li><strong>Dirty workpiece.</strong>"), nested
    assert nested.count("<li><strong>") == 3  # three numbered items, so the list reads 1, 2, 3
    assert between == "<ol><li>First</li></ol><ul><li>a bullet</li><li>another</li></ul><ol start=\"2\"><li>Second</li><li>Third</li></ol>", between
    assert plain == "<ol><li>one</li><li>two</li></ol><ul><li>x</li><li>y</li></ul>", plain  # ordinary lists are unchanged (no start attribute)
    assert resumed.startswith('<ol start="3">'), resumed
    assert capped.startswith('<ol start="99">'), capped  # a silly number cannot become a silly attribute
    assert "a long item that wraps onto a second line" in wrapped and "a sub-point that wraps too" in wrapped, wrapped
    assert "<img" not in hostile and "<script" not in hostile and "&lt;img" in hostile and "&lt;script&gt;" in hostile, hostile


# ---------- the two newer features: tap-to-answer questions and tappable pictures ----------
def test_tappable_picture_boxes_are_placed_by_script_not_by_inline_style_attributes():
    assert "Object.assign(b.style, { left:" in JS and 'style="' not in HTML                 # the page policy forbids style attributes in markup
    assert "proseBlock(h.text)" in JS and "info.replaceChildren(el('h4', '', h.label)" in JS   # the explanation goes through the escaping renderer


def test_tap_to_answer_cards_build_their_message_from_the_labels_the_server_sent():
    assert "`${g.phrase}: ${picked.get(g.id)}`" in JS and "typed.maxLength = 40" in JS
    assert "card.classList.add('done')" in JS and "c.refresh && c.refresh()" in JS         # a used card stops taking taps; an open one wakes up when the answer ends
    from app.tools.details import FREE_TEXT_LIMIT
    assert FREE_TEXT_LIMIT == 40


def test_the_server_sends_click_areas_only_for_the_pictures_that_have_them_and_never_to_the_model(client):
    r = client.post("/api/chat", json={"message": "panel please"})
    figure = next(json.loads(b.split("data: ", 1)[1]) for b in r.text.split("\n\n") if b.startswith("event: show"))
    assert figure["id"] == "front-panel-controls" and len(figure["hotspots"]) == 13
    assert set(figure["hotspots"][0]) == {"id", "label", "box", "text"}
    other = next(json.loads(b.split("data: ", 1)[1]) for b in client.post("/api/chat", json={"message": "figure please"}).text.split("\n\n") if b.startswith("event: show"))
    assert "hotspots" not in other
    from app.tools.figures import show_figure
    assert "hotspots" not in show_figure("front-panel-controls")                             # what the model is sent stays small
