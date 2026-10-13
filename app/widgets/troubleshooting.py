"""Troubleshooting flowchart: a guided widget built from the manual's own tables (pp 42-44)."""
from app.knowledge import TROUBLESHOOTING
from app.tools.troubleshooting import PROBLEMS, get_troubleshooting
from app.widgets.common import html_page, script_json

CSS = """
fieldset{border:0;padding:0;margin:0 0 12px} legend{font-weight:600;margin-bottom:4px;padding:0}
.seg{display:flex;gap:8px;flex-wrap:wrap}
button{font:inherit;padding:8px 14px;border:2px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);cursor:pointer}
.seg button[aria-pressed=true]{border-color:var(--accent);background:var(--accent);color:#fff;font-weight:600}
.important{border:2px solid var(--warn);border-radius:10px;padding:8px 12px;margin:12px 0}
.important b{color:var(--warn);margin-right:6px}
.flow{list-style:none;padding:0;margin:16px 0} .node{border:2px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 24px;position:relative;background:var(--card)}
.node:not(:last-child)::after{content:"\\2193";position:absolute;left:50%;bottom:-24px;color:var(--muted);font-size:18px}
.node .label{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)} .node .cause{font-weight:600}
.node .sol{margin-top:6px} .tag{margin-top:6px;font-size:13px;color:var(--warn)}
.problem{border-color:var(--accent)} .active{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 25%,transparent)}
.tried{opacity:.65} .later{opacity:.55} .skipped{opacity:.5;border-style:dashed} .fixed,.ok{border-color:var(--ok)} .end{border-color:var(--warn)}
.row{display:flex;gap:8px;margin-top:10px} .row .yes{border-color:var(--ok);color:var(--ok);font-weight:600} .row .no{border-color:var(--warn);color:var(--warn);font-weight:600}
"""

JS = """
const T = JSON.parse(document.getElementById('data').textContent);
const init = JSON.parse(document.getElementById('init').textContent);
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const button = (label, onclick, cls) => { const b = el('button', cls || '', label); b.type = 'button'; b.onclick = onclick; return b; };
const st = {sec: init.sec, prob: init.prob, i: 0, fixed: false, flux: false};
const sec = () => T.sections.find(s => s.id === st.sec);
const prob = () => sec().problems.find(p => p.id === st.prob);
const skipped = s => st.flux && st.sec === 'mig_flux' && s.mig_only;
const nextOpen = from => { const steps = prob().steps; let i = from; while (i < steps.length && skipped(steps[i])) i++; return i; };
const restart = () => { st.fixed = false; st.i = nextOpen(0); render(); };
function render(){
  const s = sec(), p = prob(), steps = p.steps;
  $('important').textContent = s.important;
  document.querySelectorAll('[data-sec]').forEach(b => b.setAttribute('aria-pressed', b.dataset.sec === st.sec));
  $('flux-row').style.display = st.sec === 'mig_flux' ? 'block' : 'none';
  const pb = $('problems'); pb.replaceChildren();
  s.problems.forEach(q => { const b = button(q.problem, () => { st.prob = q.id; restart(); }); b.setAttribute('aria-pressed', q.id === st.prob); pb.append(b); });
  const flow = $('flow'); flow.replaceChildren();
  const head = el('li', 'node problem'); head.append(el('strong', '', p.problem), el('div', 'muted', s.short + ' \\u00b7 manual p' + p.page)); flow.append(head);
  steps.forEach((step, n) => {
    const state = skipped(step) ? 'skipped' : st.fixed && n === st.i ? 'fixed' : n < st.i ? 'tried' : n === st.i ? 'active' : 'later';
    const li = el('li', 'node ' + state);
    const tail = {tried: ' \\u00b7 didn\\u2019t help', fixed: ' \\u00b7 fixed it', skipped: ' \\u00b7 skipped'}[state] || '';
    li.append(el('div', 'label', 'Check ' + (n + 1) + ' of ' + steps.length + tail), el('div', 'cause', step.cause));
    if (step.mig_only) li.append(el('div', 'tag', 'MIG only: gasless flux-cored welding uses no shielding gas (manual p37).'));
    if (state !== 'later' && state !== 'skipped') li.append(el('div', 'sol', 'Try: ' + step.solution));
    if (state === 'active') {
      const row = el('div', 'row');
      row.append(button('That fixed it', () => { st.fixed = true; render(); }, 'yes'),
                 button('Didn\\u2019t help', () => { st.i = nextOpen(st.i + 1); render(); }, 'no'));
      li.append(row);
    }
    flow.append(li);
  });
  if (st.fixed) flow.append(el('li', 'node end ok', 'Fixed. If it comes back, start again from Check 1.'));
  else if (st.i >= steps.length) flow.append(el('li', 'node end', 'None of these checks fixed it. The manual says to call technical support: ' + T.support_phone + '.'));
}
document.querySelectorAll('[data-sec]').forEach(b => b.onclick = () => { st.sec = b.dataset.sec; st.prob = sec().problems[0].id; restart(); });
$('flux').onchange = e => { st.flux = e.target.checked; restart(); };
$('restart').onclick = restart;
restart();
"""


def troubleshooting_widget(problem_id) -> dict:
    found = get_troubleshooting(problem_id)
    if not found["found"]:
        return {"ok": False, "message": found["message"]}
    sections = "".join(
        f'<button type="button" data-sec="{s["id"]}" aria-pressed="false">{s["short"]}</button>'
        for s in TROUBLESHOOTING["sections"]
    )
    body = (
        "<h1>Troubleshooting guide</h1>"
        '<p class="muted">From the manual\'s troubleshooting tables (pp 42-44). Checks are in the manual\'s order.</p>'
        '<div class="important"><b>IMPORTANT</b><span id="important"></span></div>'
        f'<fieldset><legend>What are you welding with?</legend><div class="seg">{sections}</div>'
        '<label id="flux-row"><input type="checkbox" id="flux"> I\'m using gasless flux-cored wire (skip the gas checks)</label></fieldset>'
        '<fieldset><legend>What\'s going wrong?</legend><div id="problems" class="seg"></div></fieldset>'
        '<ol id="flow" class="flow" aria-live="polite"></ol>'
        '<button type="button" id="restart">Start over</button>'
        f'<p class="muted">{TROUBLESHOOTING["footer_safety"]}</p>'
        f'<script id="data" type="application/json">{script_json(TROUBLESHOOTING)}</script>'
        f'<script id="init" type="application/json">{script_json({"sec": PROBLEMS[problem_id]["section"], "prob": problem_id})}</script>'
    )
    html = html_page("Troubleshooting guide", body, CSS, f"<script>{JS}</script>")
    return {"ok": True, "title": "Troubleshooting guide", "html": html}
