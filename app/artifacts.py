"""Free-form artifacts: Claude writes a small HTML or SVG page; we wrap it so it can only draw, never reach out.

Reverse-engineered from how Claude artifacts work: a typed block (identifier / type / title / code), run in a sandboxed
iframe with no network and no access to the page around it, fed verified data through window.MANUAL, and reporting
errors and its size back to the host page via postMessage.
"""
import re
from html import escape

from app.knowledge import CONTROLS, POLARITY, SPECIFICATIONS, TROUBLESHOOTING
from app.widgets.common import BASE_CSS, script_json

MAX_CODE_CHARS = 40_000
MIN_CODE_CHARS = 100  # a real drawing is never this small: the full Haiku run showed a '<p>unused</p>' placeholder card
TYPES = {"html": "Interactive page", "svg": "Diagram"}
TYPE_ALIASES = {"html": "html", "text/html": "html", "svg": "svg", "image/svg+xml": "svg"}
FORBIDDEN = re.compile(r"<\s*(iframe|object|embed|base|meta|link)\b", re.I)
FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*[ \t]*\r?\n(.*?)\r?\n?[ \t]*```\s*$", re.S)
HARMLESS_META = re.compile(
    r"""<meta\s+charset\s*=\s*["']?[\w-]+["']?\s*/?>|<meta\s+name\s*=\s*["']viewport["'][^>]*>""", re.I
)

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
       "connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'")

# Verified manual data an artifact may read. Claude must take every number from here or from a tool result.
MANUAL = {"specifications": SPECIFICATIONS, "polarity": POLARITY, "controls": CONTROLS, "troubleshooting": TROUBLESHOOTING}

REPORTER_JS = """
(function () {
  var ID = window.__ARTIFACT_ID__;
  function send(kind, extra) { try { parent.postMessage(Object.assign({source: 'artifact', id: ID, kind: kind}, extra), '*'); } catch (e) {} }
  window.addEventListener('error', function (e) { send('error', {message: String(e.message), line: e.lineno}); });
  window.addEventListener('unhandledrejection', function (e) { send('error', {message: 'Unhandled promise rejection: ' + String(e.reason)}); });
  ['error', 'warn'].forEach(function (lvl) {
    var orig = console[lvl];
    console[lvl] = function () { send('console', {level: lvl, text: [].slice.call(arguments).join(' ')}); orig.apply(console, arguments); };
  });
  function size() { send('resize', {height: Math.ceil(document.documentElement.scrollHeight)}); }
  window.addEventListener('load', function () { size(); if (window.ResizeObserver) new ResizeObserver(size).observe(document.body); send('ready', {}); });
})();
"""


def _error(message: str) -> dict:
    return {"ok": False, "message": message}


def _slug(value) -> str | None:
    """'Polarity Cheat Sheet' -> 'polarity-cheat-sheet'. Same input always gives the same id, so updates still match."""
    if not isinstance(value, str):
        return None
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64].strip("-") or None


def _clean_code(code: str) -> str:
    """Be forgiving about how the model wraps its code: strip markdown fences and harmless charset/viewport metas."""
    fenced = FENCE.match(code)
    if fenced:
        code = fenced.group(1)
    return HARMLESS_META.sub("", code).strip()


def _document(identifier: str, title: str, artifact_type: str, code: str) -> str:
    body = code if artifact_type == "html" else f'<div class="svg-wrap">{code}</div>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<script>window.__ARTIFACT_ID__={script_json(identifier)};window.MANUAL={script_json(MANUAL)};</script>"
        f"<script>{REPORTER_JS}</script>"
        f"<style>{BASE_CSS}.svg-wrap svg{{width:100%;height:auto}}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def build_artifact(identifier, artifact_type, title, code) -> dict:
    slug = _slug(identifier)
    if slug is None:
        return _error("identifier must contain letters or digits, e.g. 'polarity-cheat-sheet'.")
    kind = TYPE_ALIASES.get(artifact_type.strip().lower()) if isinstance(artifact_type, str) else None
    if kind is None:
        return _error(f"type must be one of {sorted(TYPES)}.")
    if not isinstance(code, str) or not code.strip():
        return _error("code is empty.")
    if len(code) > MAX_CODE_CHARS:
        return _error(f"code is {len(code)} characters; the limit is {MAX_CODE_CHARS}. Make it smaller and simpler.")
    cleaned = _clean_code(code)
    if not cleaned:
        return _error("code is empty.")
    if kind == "svg" and not cleaned.lstrip("﻿ \t\r\n").lower().startswith("<svg"):
        return _error("an svg artifact must be a single <svg viewBox=...> element.")
    bad = FORBIDDEN.search(cleaned)
    if bad:
        return _error(f"<{bad.group(1).lower()}> is not allowed in artifacts. Remove it.")
    if len(cleaned) < MIN_CODE_CHARS:
        return {"ok": False, "trivial": True, "message": f"code is only {len(cleaned)} characters, too little to be a real drawing. "
                "Only call create_artifact when you have something to draw for the person; never as a test or placeholder."}
    shown = title.strip()[:80] if isinstance(title, str) and title.strip() else slug.replace("-", " ").capitalize()
    return {"ok": True, "identifier": slug, "type": kind, "title": shown, "html": _document(slug, shown, kind, cleaned)}
