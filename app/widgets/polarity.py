"""Polarity diagram: which cable goes in which socket, drawn from the verified data (polarity.json)."""
from html import escape

from app.tools.data import get_polarity
from app.widgets.common import html_page

NEG, POS = "#1f6fd6", "#d23a1f"  # blue / red. Never the only cue: every socket also has a +/- sign and a label.

SOCKETS = [  # left to right, as on the machine's front panel (manual p8)
    {"id": "negative", "cx": 190, "color": NEG, "sign": "−", "label": "Negative (−) socket"},
    {"id": "positive", "cx": 430, "color": POS, "sign": "+", "label": "Positive (+) socket"},
]

CSS = """
:root{--socket:#d9dde3;--hole:#2a2d33}
@media (prefers-color-scheme:dark){:root{--socket:#383c45;--hole:#0e0f12}}
.name{color:var(--muted);margin:0 0 12px;font-size:14px}
svg{width:100%;height:auto}
.panel{fill:var(--panel);stroke:var(--line);stroke-width:2}
.cable{fill:var(--card);stroke-width:3}
.cable-name{font:600 16px system-ui,sans-serif;text-anchor:middle;fill:var(--fg)}
.socket{fill:var(--socket);stroke-width:6} .hole{fill:var(--hole)}
.sign{font:700 36px system-ui,sans-serif;text-anchor:middle}
.socket-label{font:600 15px system-ui,sans-serif;text-anchor:middle;fill:var(--fg)}
.tag{font:600 12px system-ui,sans-serif;letter-spacing:.08em;fill:var(--muted)}
ul{margin:0;padding-left:20px} .src{color:var(--muted);font-size:13px;margin-top:12px}
"""


def _socket_svg(s: dict, cable: str) -> str:
    cx, color = s["cx"], s["color"]
    return (
        f'<g data-socket="{s["id"]}" data-cable="{escape(cable)}">'
        f'<rect x="{cx - 105}" y="14" width="210" height="46" rx="10" class="cable" stroke="{color}"/>'
        f'<text x="{cx}" y="43" class="cable-name">{escape(cable)}</text>'
        f'<line x1="{cx}" y1="60" x2="{cx}" y2="152" stroke="{color}" stroke-width="9" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="198" r="46" class="socket" stroke="{color}"/>'
        f'<circle cx="{cx}" cy="198" r="26" class="hole"/>'
        f'<text x="{cx}" y="210" class="sign" fill="{color}">{s["sign"]}</text>'
        f'<text x="{cx}" y="272" class="socket-label">{s["label"]}</text>'
        "</g>"
    )


def polarity_widget(process: str) -> dict:
    found = get_polarity(process)
    if not found["found"]:
        return {"ok": False, "message": found["message"]}
    setup = found["setup"]
    by_socket = {c["socket"]: c["cable"] for c in setup["cables"]}
    summary = "; ".join(
        f"{c['cable']} goes in the {'Positive (+)' if c['socket'] == 'positive' else 'Negative (−)'} socket"
        for c in setup["cables"]
    )
    sockets = "".join(_socket_svg(s, by_socket.get(s["id"], "(empty)")) for s in SOCKETS)
    extras = "".join(f"<li>{escape(x)}</li>" for x in setup["other_connections"])
    title = f"Polarity: {setup['label']}"
    body = (
        f"<h1>{escape(setup['label'])}</h1><p class=\"name\">{escape(setup['polarity_name'])}</p>"
        f'<svg viewBox="0 0 620 300" role="img" aria-label="{escape(summary)}">'
        '<rect x="20" y="126" width="580" height="166" rx="20" class="panel"/>'
        '<text x="36" y="148" class="tag">FRONT PANEL</text>'
        f"{sockets}</svg>"
        f"<h2>Also connect</h2><ul>{extras}</ul>"
        f"<h2>Shielding gas</h2><p>{escape(setup['gas'])}</p>"
        f'<p class="src">Source: {escape(", ".join(setup["sources"]))}</p>'
    )
    return {"ok": True, "title": title, "html": html_page(title, body, CSS)}
