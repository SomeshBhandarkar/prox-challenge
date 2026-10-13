"""Setup sheet: what the manual states for one job, one tab per process. No numbers are made up here:
everything comes from app/tools/setup_guide.py, and the wire speed and voltage are left to the LCD (manual p20)."""
from html import escape

from app.tools.setup_guide import ORDER, build_setup
from app.widgets.common import html_page

SHORT = {"mig": "MIG", "flux_cored": "Flux-cored", "tig": "TIG", "stick": "Stick"}
BADGE = {True: "✓ fits", False: "✗ no fit", None: "? check"}
ICON = {"ok": "✓", "fail": "✗", "warn": "!", "unknown": "?", "info": "i"}
WORD = {"ok": "OK", "fail": "Problem", "warn": "Careful", "unknown": "Check", "info": "Note"}
SOCKET = {"negative": "Negative (−) socket", "positive": "Positive (+) socket"}

CSS = """
.job{color:var(--muted);margin:0 0 10px;font-size:14px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.tab{font:600 14px system-ui,sans-serif;min-height:44px;padding:6px 12px;border:2px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);cursor:pointer}
.tab[aria-selected=true]{border-color:var(--accent);background:var(--panel)}
.tab small{display:block;font-weight:600;color:var(--muted)}
.card{border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0;background:var(--card)}
.card h2{margin:0 0 6px;font-size:16px}
.n{display:inline-block;min-width:22px;height:22px;line-height:22px;text-align:center;border-radius:50%;background:var(--accent);color:var(--bg);font-size:13px;margin-right:6px}
ul,ol{margin:4px 0;padding-left:22px} li{margin:3px 0}
.pg{color:var(--muted);font-size:12px;white-space:nowrap}
.chk{list-style:none;margin-left:-22px}
.ic{display:inline-block;width:22px;font-weight:700} .st{font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin-right:4px}
.ok .ic,.ok .st{color:var(--ok)} .fail .ic,.fail .st{color:var(--bad)} .warn .ic,.warn .st,.unknown .ic,.unknown .st{color:var(--warn)}
.box{border:2px solid var(--warn);border-radius:10px;padding:8px 12px;margin:8px 0}
.note{border-color:var(--line)} .danger{border-color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:14px} th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--panel)} .sel{background:var(--panel);font-weight:600}
.small{color:var(--muted);font-size:13px}
@media print{.tabs{display:none}[hidden]{display:block!important}}
"""

SCRIPT = """<script>
var tabs=document.querySelectorAll('[role=tab]'),panels=document.querySelectorAll('[role=tabpanel]');
function show(k){tabs.forEach(function(t){t.setAttribute('aria-selected',String(t.dataset.p===k))});
panels.forEach(function(p){p.hidden=p.dataset.p!==k})}
tabs.forEach(function(t){t.addEventListener('click',function(){show(t.dataset.p)})});
</script>"""


def _facts(items: list) -> str:
    return "<ul>" + "".join(f'<li>{escape(i["text"])} <span class="pg">p.{i["page"]}</span></li>' for i in items) + "</ul>"


def _card(number: int, title: str, inner: str) -> str:
    return f'<section class="card"><h2><span class="n">{number}</span>{escape(title)}</h2>{inner}</section>'


def _job_line(job: dict) -> str:
    parts = [job["material"], job["thickness"], f'{job["wire_diameter"]} wire' if job["wire_diameter"] else None,
             job["voltage"].replace("VAC", "V") if job["voltage"] else None, "outdoors" if job["outdoors"] else None]
    parts = [p for p in parts if p]
    return ("Your job: " + ", ".join(escape(p) for p in parts)) if parts else \
        "No job details yet, so this shows what the manual states for each process. Tell me the material, thickness and voltage to check it."


def _fit_card(g: dict) -> str:
    items = "".join(
        f'<li class="chk {c["status"]}"><span class="ic" aria-hidden="true">{ICON[c["status"]]}</span>'
        f'<b class="st">{WORD[c["status"]]}</b> {escape(c["text"])}'
        + (f' <span class="small">{escape(c["note"])}</span>' if c.get("note") else "") + "</li>"
        for c in g["checks"]
    )
    boxes = "".join(
        f'<div class="box"><b>The manual disagrees with itself.</b> {escape(w["text"])}<br><b>What to do:</b> {escape(w["guidance"])}</div>'
        for w in g["warnings"]
    )
    return _card(1, f"Will {g['label']} work for your job?", f"<ul>{items}</ul>{boxes}")


def _plug_card(g: dict) -> str:
    p = g["plug_in"]
    cables = "".join(f"<li><b>{escape(c['cable'])}</b> → {SOCKET.get(c['socket'], escape(c['socket']))}</li>" for c in p["cables"])
    other = "".join(f"<li>{escape(x)}</li>" for x in p["other"])
    spool = ""
    if p["spool_gun"]:
        s = p["spool_gun"]
        spool = (f'<div class="box"><b>Aluminum needs the optional Spool Gun.</b> {escape(s["label"])}: ' + "; ".join(
            f"{escape(c['cable'])} → {SOCKET.get(c['socket'], escape(c['socket']))}" for c in s["cables"]) + "</div>")
    return _card(2, "Plug in", f'<p class="small">{escape(p["polarity_name"])}</p><ul>{cables}</ul>'
                 f'<p class="small">Also connect:</p><ul>{other}</ul>{spool}'
                 f'<p class="small">Source: {escape(", ".join(p["sources"]))}</p>')


def _gas_card(g: dict) -> str:
    return _card(3, "Shielding gas", _facts(g["gas"]))


def _wire_card(g: dict, number: int) -> str:
    w = g["wire"]
    if w:
        groove = f", turned to the {w['groove']}" if w["groove"] else " (turn it to the groove that matches your wire size)"
        mine = (f'<ul><li><b>Feed roller:</b> {escape(w["roller"])}{escape(groove)} <span class="pg">p.12</span></li>'
                f'<li><b>Feed tension:</b> {escape(w["tension"])} <span class="pg">p.15</span></li></ul>')
        return _card(number, "Wire, feed roller and tension", mine + _facts(w["facts"]) + "<h2>Technique</h2>" + _facts(g["technique"]))
    if g["electrode"]:
        return _card(number, "Electrode and technique", _facts(g["electrode"]) + _facts(g["technique"]))
    return _card(number, "Technique", _facts(g["technique"]))


def _lcd_card(g: dict, number: int) -> str:
    lcd = g["lcd"]
    steps = "<ol>" + "".join(f'<li>{escape(s["text"])} <span class="pg">p.{s["page"]}</span></li>' for s in lcd["steps"]) + "</ol>"
    rows = "".join(
        f"<tr><td>{escape(e['knob'])}</td><td>{escape(e['sets'])}</td><td>{escape(e['value']) if e['value'] else '—'}</td></tr>"
        for e in lcd["entries"]
    )
    table = f"<table><tr><th>Knob</th><th>Sets</th><th>Your entry</th></tr>{rows}</table>"
    note = '<p class="small">Enter the thickness the way the screen shows it; the manual\'s example screen shows 24Ga (p.20).</p>'
    repeated = {f["text"] for f in g["decides"]["facts"]}  # shown again under "What the LCD decides"
    notes = "".join(
        f'<div class="box {"danger" if n.get("level") == "WARNING" else "note"}">'
        + (f'<b>{escape(n["level"])}:</b> ' if n.get("level") else "") + f'{escape(n["text"])} <span class="pg">p.{n["page"]}</span></div>'
        for n in lcd["notes"] if n["text"] not in repeated
    )
    optional = f'<p class="small">Optional Settings: {escape(", ".join(lcd["optional"]))}.</p>'
    return _card(number, "On the LCD", steps + table + note + notes + optional)


def _decides_card(g: dict, number: int) -> str:
    d = g["decides"]
    return _card(number, "What the LCD decides for you",
                 _facts(d["facts"]) + f'<p><b>Not in the manual:</b> {escape(d["note"])}</p>'
                 '<p class="small">General advice, not from the manual: try a short weld on scrap first.</p>')


def _limits_card(g: dict, number: int) -> str:
    rows = ""
    for volt in ("120VAC", "240VAC"):
        lim = g["limits"][volt]
        points = "; ".join(f"{p['percent']}% at {p['amps']} A" for p in lim["rated_points"])
        mine = ' class="sel"' if g["job"]["voltage"] == volt else ""
        rows += (f"<tr{mine}><td>{volt.replace('VAC', ' V')}{' (yours)' if mine else ''}</td>"
                 f"<td>{lim['range_A'][0]}–{lim['range_A'][1]} A</td><td>{escape(points)}</td><td>{escape(lim['input_current'])}</td></tr>")
    table = ("<table><tr><th>Input</th><th>Current range</th><th>Rated duty cycle points</th><th>Input current</th></tr>"
             f"{rows}</table>")
    return _card(number, "Current limits and power", table + '<p class="small">Source: manual p.7 and the rating label (p.14). '
                 "Ask for the duty-cycle calculator to try an amperage.</p>" + _facts(g["power"]))


def _gaps_card(g: dict, number: int) -> str:
    items = "".join(f"<li>{escape(x['text'])}</li>" for x in g["not_in_manual"])
    return _card(number, "Not in the manual", f"<ul>{items}</ul>")


def _panel(g: dict, selected: bool) -> str:
    cards = [_fit_card(g), _plug_card(g), _gas_card(g), _wire_card(g, 4), _lcd_card(g, 5),
             _decides_card(g, 6), _limits_card(g, 7), _gaps_card(g, 8)]
    pages = ", ".join(str(p) for p in g["pages"])
    return (f'<div role="tabpanel" id="panel-{g["process"]}" data-p="{g["process"]}"{"" if selected else " hidden"}>'
            + "".join(cards) + f'<p class="small">Manual pages used: {pages}.</p></div>')


def setup_guide_widget(process=None, voltage=None, material=None, thickness=None, wire_diameter=None,
                       outdoors=None, gas_ok=None, skill=None) -> dict:
    setup = build_setup(process, voltage, material, thickness, wire_diameter, outdoors, gas_ok, skill)
    if not setup["ok"]:
        return {"ok": False, "message": setup["message"]}
    selected = setup["selected"]
    guides = setup["guides"]
    tabs = "".join(
        f'<button class="tab" role="tab" data-p="{k}" aria-selected="{"true" if k == selected else "false"}">'
        f'{SHORT[k]}<small>{BADGE[guides[k]["fits"]]}</small></button>'
        for k in ORDER
    )
    body = (
        "<h1>Setup sheet</h1>"
        f'<p class="job">{_job_line(guides[selected]["job"])}</p>'
        f'<div class="tabs" role="tablist" aria-label="Welding process">{tabs}</div>'
        + "".join(_panel(guides[k], k == selected) for k in ORDER)
    )
    title = f"Setup sheet: {SHORT[selected]}"
    return {"ok": True, "title": title, "html": html_page(title, body, CSS, SCRIPT), "selected": selected}
