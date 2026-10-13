"""Shared page shell for widgets: one light/dark theme, one font, no external resources."""
import json
from html import escape

BASE_CSS = """
:root{--bg:#fff;--fg:#1b1b1b;--muted:#5b5b5b;--card:#fff;--panel:#eceff3;--line:#c9ced6;--ok:#1a7f37;--warn:#a85b00;--bad:#c62828;--accent:#1f6fd6}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#f0f1f3;--muted:#a8adb7;--card:#20232a;--panel:#23262d;--line:#3a3f49;--ok:#4cc26a;--warn:#f0a030;--bad:#ff7a7a;--accent:#6aa7ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:680px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:15px;margin:16px 0 4px}
.muted{color:var(--muted);font-size:14px}
"""


def html_page(title: str, body: str, css: str = "", script: str = "") -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{BASE_CSS}{css}</style></head>"
        f"<body><main>{body}</main>{script}</body></html>"
    )


def script_json(obj) -> str:
    """JSON that is safe inside a <script> tag: no "</script>" can appear in it."""
    return json.dumps(obj, separators=(",", ":")).replace("<", "\\u003c")
