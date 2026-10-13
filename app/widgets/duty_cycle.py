"""Duty-cycle calculator: a self-contained widget. Every number in it is precomputed by the verified
get_duty_cycle(), so the widget contains no calculation logic of its own."""
from app.tools.data import get_duty_cycle, normalize_process, normalize_voltage
from app.widgets.common import html_page, script_json

AMPS_MIN, AMPS_MAX = 10, 220
PROCESSES = {"MIG": "MIG / flux-cored", "TIG": "TIG", "Stick": "Stick"}
VOLTAGES = {"120VAC": "120V", "240VAC": "240V"}

CSS = """
fieldset{border:0;padding:0;margin:0 0 12px} legend{font-weight:600;margin-bottom:4px;padding:0}
.seg{display:flex;gap:8px;flex-wrap:wrap}
.seg button{font:inherit;padding:8px 14px;border:2px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);cursor:pointer}
.seg button[aria-pressed=true]{border-color:var(--accent);background:var(--accent);color:#fff;font-weight:600}
.amps{display:flex;gap:12px;align-items:center} .amps input[type=range]{flex:1;accent-color:var(--accent)}
.amps input[type=number]{width:84px;font:inherit;padding:6px;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.result{border:2px solid var(--line);border-radius:14px;padding:14px;margin:14px 0;background:var(--card)}
.pct{font-size:44px;font-weight:700;line-height:1}
.badge{display:inline-block;margin-left:8px;padding:2px 10px;border-radius:99px;font-size:13px;font-weight:600;border:2px solid currentColor;vertical-align:middle}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)}
.bar{display:flex;height:26px;border-radius:8px;overflow:hidden;margin:12px 0 4px;border:1px solid var(--line)}
.bar .weld{background:var(--ok)} .bar .rest{background:var(--line)}
.legend{display:flex;justify-content:space-between;font-size:13px;color:var(--muted)}
ul{margin:0;padding-left:20px}
"""

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const st = JSON.parse(document.getElementById('init').textContent);
const $ = id => document.getElementById(id);
const BADGE = {continuous:['Continuous','ok'], rated_point:['Rated point','ok'], between_rated_points:['Between rated points','warn'],
  above_highest_rated_point:['Above top rated point','warn'], exceeds_machine_range:['Above machine range','bad'], below_machine_range:['Below machine range','bad']};
function render(){
  const cfg = D[st.proc][st.volt], e = cfg.amps[st.amps];
  document.querySelectorAll('[data-proc]').forEach(b => b.setAttribute('aria-pressed', b.dataset.proc === st.proc));
  document.querySelectorAll('[data-volt]').forEach(b => b.setAttribute('aria-pressed', b.dataset.volt === st.volt));
  $('range').value = st.amps; $('num').value = st.amps;
  $('limits').textContent = 'This setup can output ' + cfg.range[0] + '-' + cfg.range[1] + ' A.';
  const [label, cls] = BADGE[e.s];
  $('pct').textContent = e.p === undefined ? '\\u2014' : e.p + '%';
  $('pct').className = 'pct ' + cls;
  $('badge').textContent = label; $('badge').className = 'badge ' + cls;
  $('msg').textContent = e.m;
  $('bar').style.display = e.p === undefined ? 'none' : 'flex';
  $('wl').textContent = e.p === undefined ? '' : e.w + ' min welding';
  $('rl').textContent = e.p === undefined ? '' : e.r + ' min resting';
  if (e.p !== undefined) { $('weld').style.width = e.p + '%'; $('rest').style.width = (100 - e.p) + '%'; }
  $('est').textContent = e.e === undefined ? '' : 'Rough estimate only: about ' + e.e + '%. This number is NOT in the manual, so plan with the safer figure above.';
  $('notes').textContent = cfg.notes.join(' ');
  $('rated').innerHTML = cfg.rated.map(p => '<li>' + p.percent + '% at ' + p.amps + ' A <span class="muted">(' +
    (p.on_specifications_page ? 'manual p7' : 'rating label, p14') + ')</span></li>').join('');
}
function setAmps(v){ v = Math.max(__LO__, Math.min(__HI__, Math.round(Number(v) || __LO__))); st.amps = v; render(); }
document.querySelectorAll('[data-proc]').forEach(b => b.onclick = () => { st.proc = b.dataset.proc; render(); });
document.querySelectorAll('[data-volt]').forEach(b => b.onclick = () => { st.volt = b.dataset.volt; render(); });
$('range').oninput = e => setAmps(e.target.value);
$('num').onchange = e => setAmps(e.target.value);
render();
""".replace("__LO__", str(AMPS_MIN)).replace("__HI__", str(AMPS_MAX))


def _entry(r: dict) -> dict:  # keep only what the widget shows
    e = {"s": r["status"], "m": r["message"]}
    for src, dst in (("duty_percent", "p"), ("weld_minutes_per_10", "w"), ("rest_minutes_per_10", "r")):
        if src in r:
            e[dst] = r[src]
    if "estimate" in r:
        e["e"] = r["estimate"]["percent"]
    return e


def build_data() -> dict:
    data = {}
    for proc in PROCESSES:
        data[proc] = {}
        for volt in VOLTAGES:
            probe = get_duty_cycle(proc, volt, 100)
            data[proc][volt] = {
                "range": probe["range_A"],
                "rated": probe["rated_points"],
                "notes": probe["notes"],
                "amps": {str(a): _entry(get_duty_cycle(proc, volt, a)) for a in range(AMPS_MIN, AMPS_MAX + 1)},
            }
    return data


def _buttons(attr: str, items: dict) -> str:
    return "".join(f'<button type="button" data-{attr}="{k}" aria-pressed="false">{v}</button>' for k, v in items.items())


def duty_cycle_widget(process: str, voltage, amps: float | None = None) -> dict:
    check = get_duty_cycle(process, voltage, 100 if amps is None else amps)
    if check["status"] == "invalid":
        return {"ok": False, "message": check["message"]}
    proc, volt = normalize_process(process), normalize_voltage(voltage)
    start = max(AMPS_MIN, min(AMPS_MAX, round(100 if amps is None else amps)))
    body = (
        "<h1>Duty cycle calculator</h1>"
        '<p class="muted">Duty cycle is how many minutes out of every 10 you can weld at this current '
        "before the machine needs to cool down.</p>"
        f'<fieldset><legend>Process</legend><div class="seg">{_buttons("proc", PROCESSES)}</div></fieldset>'
        f'<fieldset><legend>Input voltage</legend><div class="seg">{_buttons("volt", VOLTAGES)}</div></fieldset>'
        '<fieldset><legend><label for="num">Welding current (amps)</label></legend><div class="amps">'
        f'<input id="range" type="range" min="{AMPS_MIN}" max="{AMPS_MAX}" step="1" aria-label="Amps slider">'
        f'<input id="num" type="number" min="{AMPS_MIN}" max="{AMPS_MAX}" step="1"></div>'
        '<div class="muted" id="limits"></div></fieldset>'
        '<div class="result" aria-live="polite"><span id="pct" class="pct"></span><span id="badge" class="badge"></span>'
        '<p id="msg"></p><div id="bar" class="bar"><div id="weld" class="weld"></div><div id="rest" class="rest"></div></div>'
        '<div class="legend"><span id="wl"></span><span id="rl"></span></div>'
        '<p id="est" class="warn"></p><p id="notes" class="muted"></p></div>'
        '<h2>Rated points for this setup</h2><ul id="rated"></ul>'
        '<p class="muted">Source: manual p7 (Specifications) and the rating label, p14.</p>'
        f'<script id="data" type="application/json">{script_json(build_data())}</script>'
        f'<script id="init" type="application/json">{script_json({"proc": proc, "volt": volt, "amps": start})}</script>'
    )
    html = html_page("Duty cycle calculator", body, CSS, f"<script>{JS}</script>")
    return {"ok": True, "title": "Duty cycle calculator", "html": html}
