// Ask real questions through the REAL page, server and Claude (COSTS MONEY), and record what the person would see.
//   python3 run.py --no-open --port 8400 --model sonnet &            (needs your key in .env)
//   QUESTIONS=questions.json SITE=http://localhost:8400/ node scripts/browser/real_stack.mjs out-folder
// questions.json: [{"id": "duty", "q": "What's the duty cycle ...?", "follow": ["and on 120V?"]}, ...]  (each id is a fresh conversation)
// Writes out-folder/results.json and one screenshot per question, and prints a short summary of each answer.
import { readFileSync, writeFileSync } from 'node:fs';
import { openBrowser, sleep } from './cdp.mjs';

const SITE = process.env.SITE || 'http://localhost:8400/';
const out = process.argv[2] || '/tmp/real-stack';
const questions = JSON.parse(readFileSync(process.env.QUESTIONS, 'utf8'));
const b = await openBrowser({ site: SITE, out });
const { ev, waitFor, load, ask, viewport, check, finish, $, shot } = b;

// record every chat response's raw text so cost and event names are known
const TEE = `(() => {
  window.__chats = [];
  const real = window.fetch;
  window.fetch = async (...args) => {
    const resp = await real(...args);
    if (String(args[0]).includes('/api/chat')) { resp.clone().text().then((t) => window.__chats.push(t)).catch(() => {}); }
    return resp;
  };
})();`;

await viewport(1100, 1500);
await load(TEE);
const results = [];
let spent = 0;
for (const item of questions) {
  await ev(`${$('new-chat')}.click()`);
  await waitFor(`document.querySelectorAll('.conversation').length === 0`, 'the chat to clear');
  await ev(`window.__chats.length = 0`);
  const turns = [item.q, ...(item.follow || [])];
  const rec = { id: item.id, turns: [] };
  for (let i = 0; i < turns.length; i++) {
    const started = Date.now();
    await ask(turns[i]);
    let finished = true;
    try {
      await waitFor(`document.querySelectorAll('.conversation').length >= ${i + 1} && ${$('log')}.getAttribute('aria-busy') === 'false' && window.__chats.length >= ${i + 1}`, `the answer to ${item.id}`, 240000);
    } catch (e) { finished = false; }
    await sleep(1500);   // let frames report their height and pictures load
    const turn = await ev(`(() => {
      const convs = Array.from(document.querySelectorAll('.conversation'));
      const last = convs[convs.length - 1];
      const text = Array.from(last.querySelectorAll('.answer-text'), (n) => n.innerText).join('\\n').trim();
      return {
        text,
        figures: Array.from(last.querySelectorAll('figure.card.figure'), (f) => ({ caption: f.querySelector('figcaption').textContent, source: f.querySelector('.figure-foot span').textContent, loaded: f.querySelector('img').naturalWidth > 100 })),
        frames: Array.from(last.querySelectorAll('.frame'), (f) => ({ title: f.querySelector('h3').textContent, kind: f.querySelector('.tag-soft').textContent, height: parseInt(f.querySelector('iframe').style.height) || 0, drawing: Boolean(f.dataset.identifier), problem: Boolean(f.querySelector('.problem')) })),
        notes: Array.from(last.querySelectorAll('.note'), (n) => n.textContent),
        problems: Array.from(last.querySelectorAll('.callout.lvl-error'), (n) => n.textContent),
        callouts: Array.from(last.querySelectorAll('.answer-text .callout:not(.lvl-error) .tag'), (n) => n.textContent),
        citations: Array.from(new Set(Array.from(last.querySelectorAll('.cite'), (n) => n.dataset.page))),
        textBeforeVisuals: (() => { const t = last.querySelector('.answer-text'), v = last.querySelector('.answer-visuals'); return !t || !v || Boolean(t.compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING); })(),
      };
    })()`);
    const raw = await ev(`window.__chats[${i}] || ''`);
    const costs = [...raw.matchAll(/"cost_usd":\s*([0-9.]+)/g)].map((m) => Number(m[1]));
    const eventNames = [...raw.matchAll(/^event: (\w+)/gm)].map((m) => m[1]);
    Object.assign(turn, { question: turns[i], seconds: Math.round((Date.now() - started) / 1000), finished, events: eventNames.filter((n, k, a) => n !== a[k - 1]).join(' > '), cost_usd: costs.length ? costs[costs.length - 1] : null });
    rec.turns.push(turn);
    await ev(`document.querySelector('.msg.assistant:last-of-type') && document.querySelector('.conversation:last-of-type .msg.assistant').scrollIntoView({ block: 'start' })`);
    await shot(`${item.id}-turn${i + 1}`);
  }
  results.push(rec);
  // the SDK's cost looks like a running total per conversation, so the last turn's figure is the conversation's cost
  const last = rec.turns[rec.turns.length - 1].cost_usd;
  if (last) spent += last;
  console.log(`\n=== ${item.id}  (${rec.turns.map((t) => t.seconds + 's').join(', ')}; cost ${last === null ? '?' : '$' + last.toFixed(4)})`);
  for (const t of rec.turns) {
    console.log(`Q: ${t.question}`);
    console.log(`   events: ${t.events}`);
    console.log(`   figures: ${t.figures.map((f) => `${f.caption.slice(0, 60)} [${f.source}${f.loaded ? '' : ', NOT LOADED'}]`).join(' | ') || '-'}`);
    console.log(`   frames: ${t.frames.map((f) => `${f.title} (${f.kind}, ${f.height}px${f.problem ? ', PROBLEM' : ''})`).join(' | ') || '-'}`);
    console.log(`   cites: ${t.citations.join(', ') || '-'}   callouts: ${t.callouts.join(', ') || '-'}   text-first: ${t.textBeforeVisuals}`);
    if (t.notes.length) console.log(`   notes: ${t.notes.join(' | ')}`);
    if (t.problems.length) console.log(`   PROBLEMS: ${t.problems.join(' | ')}`);
    console.log('   ANSWER: ' + t.text.replace(/\n+/g, '\n           '));
  }
  writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 2));
}
console.log(`\nTotal reported spend this run: $${spent.toFixed(4)}`);
const errs = b.errors(/Failed to load resource|net::/);
check('no JavaScript errors in the browser during the real run', errs.length === 0, errs[0]);
finish();
