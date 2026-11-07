// Real-browser checks of the chat page, against the demo server (canned answers, no API key, no cost).
//   .venv/bin/python -m scripts.dev_server --port 8135 &
//   node scripts/browser/page_flows.mjs /tmp/page-checks            (SITE=http://localhost:8135/ by default)
import { openBrowser, sleep } from './cdp.mjs';

const SITE = process.env.SITE || 'http://localhost:8135/';
const b = await openBrowser({ site: SITE, out: process.argv[2] || '/tmp/page-checks' });
const { ev, waitFor, expect, load, ask, idleAfterAnswer, press, viewport, offline, check, finish, $, cdp, shot } = b;
const count = (sel) => ev(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
const text = (sel) => ev(`(document.querySelector(${JSON.stringify(sel)}) || {}).textContent || ''`);
const newChat = () => ev(`${$('new-chat')}.click()`);
const reset = async () => { await newChat(); await waitFor(`document.querySelectorAll('.conversation').length === 0`, 'the chat to clear'); };

// ---------------------------------------------------------------- startup screen
// raw key / mouse events, so the checks can send a real typed letter, a lone Shift and Ctrl+A
const key = async (k, { code = k, mods = 0, text, vk = 0 } = {}) => {
  await cdp('Input.dispatchKeyEvent', { type: text ? 'keyDown' : 'rawKeyDown', key: k, code, modifiers: mods, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, ...(text ? { text } : {}) });
  await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, modifiers: mods, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
};
const click = async (x, y) => {
  await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
};
const inApp = `!${$('app-shell')}.hidden && ${$('startup')}.hidden`;
const atGate = `${$('app-shell')}.hidden && !${$('startup')}.hidden`;

await viewport(1100, 800);
await load('', { seen: false });
check('startup screen shows first, the app is hidden behind it', await ev(atGate));
const t0 = Date.now();
await waitFor(`${$('startup-prompt')}.classList.contains('visible')`, 'the "press any key" line', 5000);
check('the "press any key" line appears within 3 seconds', Date.now() - t0 <= 3000, `${Date.now() - t0} ms`);
check('the line tells the person to press a key or click', /any key/i.test(await text('#startup-prompt')) && /click/i.test(await text('#startup-prompt')));
await shot('startup-gate');
await sleep(5000);   // far longer than the old automatic exit (about 3 s)
check('the app does NOT open by itself: it waits for the person', await ev(atGate) && await ev(`sessionStorage.getItem('omnipro-seen') === null`));
await key('Shift', { code: 'ShiftLeft', mods: 8, vk: 16 });
await key('a', { code: 'KeyA', mods: 2, vk: 65 });   // Ctrl+A
await key('F5', { code: 'F5', vk: 116 });
await sleep(300);
check('a lone Shift, Ctrl+A and F5 do not open the app', await ev(atGate));
await key('h', { code: 'KeyH', text: 'h', vk: 72 });   // a real typed letter
await expect('a letter opens the app', inApp, 2500);
check('the letter that opened the app is NOT typed into the question box', await ev(`${$('input')}.value === ''`), await ev(`JSON.stringify(${$('input')}.value)`));
check('the question box has the cursor, ready for typing', await ev(`document.activeElement === ${$('input')}`));
check('the visit is remembered for this tab', await ev(`sessionStorage.getItem('omnipro-seen') === '1'`));
await load('', { seen: null });   // a second visit in the same tab: leave the tab's storage alone this time
const t1 = Date.now();
await waitFor(`!${$('app-shell')}.hidden`, 'the app on the second visit', 3000);
check('a second visit in the same tab skips the startup screen', Date.now() - t1 < 1500 && await ev(`${$('startup')}.hidden`), `${Date.now() - t1} ms`);

await load('', { seen: false });
await waitFor(`${$('startup-prompt')}.classList.contains('visible')`, 'the "press any key" line', 5000);
await click(550, 400);
await expect('a click opens the app', inApp, 2500);

await load('', { seen: false });
await sleep(400);   // in the middle of the words
await press('Escape');
await expect('any key opens the app at once, even while the words are still appearing', inApp, 2500);
await sleep(1500);   // the rest of the animation must not touch the page after the person came in
check('nothing from the unfinished animation comes back after the app is open', await ev(`${$('startup')}.hidden && !${$('app-shell')}.hidden && ${$('startup-prompt')}.getAttribute('aria-hidden') === 'true'`));

// a phone: "Tap to enter", and the question box is NOT focused (that would open the keyboard over the starter questions)
await viewport(390, 844, { mobile: true });
await load(`const mm = window.matchMedia.bind(window); window.matchMedia = (q) => /pointer:\\s*coarse/.test(q) ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : mm(q);`, { seen: false });
await waitFor(`${$('startup-prompt')}.classList.contains('visible')`, 'the "tap" line on a phone', 5000);
check('on a phone the line says "Tap to enter"', (await text('#startup-prompt')) === 'Tap to enter', await text('#startup-prompt'));
check('the phone startup screen has no sideways scroll', await ev(`document.documentElement.scrollWidth <= innerWidth`));
await click(195, 420);
await expect('a tap opens the app on a phone', inApp, 2500);
check('on a phone the question box is not focused (no keyboard pops up)', await ev(`document.activeElement !== ${$('input')}`));
await viewport(1100, 800);

await viewport(1100, 800, { reduced: true });
await load('', { seen: false });
const t2 = Date.now();
await waitFor(`!${$('app-shell')}.hidden`, 'reduced motion to skip the startup screen', 2000);
check('reduced motion skips the startup screen', Date.now() - t2 < 1200, `${Date.now() - t2} ms`);
await viewport(1100, 800);

// ---------------------------------------------------------------- welcome + a duty-cycle answer
await load();
check('the welcome screen offers six starter questions', await count('#starters button[data-q]') === 6);
check('the composer starts empty with Send disabled', await ev(`${$('input')}.value === '' && ${$('send')}.disabled`));
await ev(`document.querySelector('#starters button[data-q]').click()`);
await idleAfterAnswer(1);
check('the starter question appears as the person\'s message', (await text('.msg.user .bubble')).includes('duty cycle for MIG'));
check('the welcome screen goes away once a conversation starts', await ev(`${$('welcome')}.hidden`));
check('the answer text comes BEFORE its pictures in the page', await ev(`(() => { const t = document.querySelector('.answer-text'), v = document.querySelector('.answer-visuals'); return Boolean(t.compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING); })()`));
check('one calculator frame is shown', await count('iframe.embed') === 1);
check('the frame is sandboxed with scripts only (no same-origin)', await ev(`document.querySelector('iframe.embed').getAttribute('sandbox') === 'allow-scripts'`));
await expect('the frame resized itself from its own height report', `parseInt(document.querySelector('iframe.embed').style.height) > 150`);
const embedCsp = await ev(`fetch(document.querySelector('iframe.embed').src).then((r) => r.headers.get('content-security-policy'))`);
check('the frame\'s own page carries a sandbox Content-Security-Policy', (embedCsp || '').startsWith('sandbox allow-scripts') && embedCsp.includes("connect-src 'none'"), embedCsp);
check('page citations became buttons (p.7 and p.19)', await ev(`['7', '19'].every((p) => document.querySelector('.answer-text .cite[data-page="' + p + '"]'))`));
await ev(`document.querySelector('.answer-text .cite[data-page="7"]').click()`);
await waitFor(`${$('viewer')}.open`, 'the manual page viewer');
check('clicking p.7 opens the manual page viewer on page 7', (await text('#viewer-title')) === "Owner's manual, page 7" && (await text('#viewer-count')) === 'Page 7 of 48');
await waitFor(`${$('viewer-img')}.complete && ${$('viewer-img')}.naturalWidth > 500`, 'the page image to load');
check('the real page image loaded (it is a picture of the manual)', await ev(`${$('viewer-img')}.src.endsWith('/pages/7.jpg')`));
await press('ArrowRight');
await expect('the right arrow key moves to the next page', `${$('viewer-count')}.textContent === 'Page 8 of 48'`);
await press('ArrowLeft'); await press('ArrowLeft');
await expect('the left arrow key moves back', `${$('viewer-count')}.textContent === 'Page 6 of 48'`);
await press('Escape');
await expect('Escape closes the viewer', `!${$('viewer')}.open`);
await shot('1-duty-answer');

// ---------------------------------------------------------------- a picture from the manual
await reset();
await ask('figure please');
await idleAfterAnswer(1);
await waitFor(`(() => { const i = document.querySelector('figure.card.figure img'); return i && i.complete && i.naturalWidth > 100; })()`, 'the figure to load');
check('a manual figure is shown with its caption and source', (await text('figcaption')).length > 10 && (await text('.figure-foot')).includes('Manual p.'));
check('the figure image has alternative text', await ev(`document.querySelector('figure.card.figure img').alt.length > 5`));
await ev(`document.querySelector('.figure-art').click()`);
await waitFor(`${$('viewer')}.open`, 'the figure viewer');
check('clicking the figure enlarges it without page buttons', await ev(`${$('viewer-nav')}.hidden === true`));
await ev(`${$('viewer-close')}.click()`);
await waitFor(`!${$('viewer')}.open`, 'the viewer to close');
await ev(`document.querySelector('.cite-src').click()`);
await expect('"Open full page" shows the whole manual page the figure came from', `${$('viewer')}.open && ${$('viewer-count')}.textContent === 'Page 16 of 48'`);
await ev(`${$('viewer-close')}.click()`);

// ---------------------------------------------------------------- warnings, tables, hostile text
await reset();
await ask('callout please');
await idleAfterAnswer(1);
const tags = await ev(`Array.from(document.querySelectorAll('.answer-text .callout .tag'), (n) => n.textContent)`);
check('WARNING, DANGER, CAUTION and NOTICE paragraphs become callouts', ['WARNING', 'DANGER', 'CAUTION', 'NOTICE'].every((t) => tags.includes(t)), tags.join(','));
check('a quoted "WARNING!" line is a callout too', tags.filter((t) => t === 'WARNING').length >= 2);
check('a markdown table is shown as a real table', await count('.answer-text table tbody tr') === 2);
check('"Quick-start guide p.2" is not turned into a manual-page button', await ev(`!document.querySelector('.answer-text .cite[data-page="2"]')`));
await shot('2-callouts');
await reset();
await ask('lists please');
await idleAfterAnswer(1);
check('a numbered list with bullets under item 1 stays ONE list of three items, two sub-points under the first', await ev(`(() => { const o = document.querySelectorAll('.answer-text ol')[0]; return Boolean(o) && o.children.length === 3 && o.children[0].querySelectorAll(':scope > ul > li').length === 2; })()`));
check('numbers that resume after loose bullets continue from 2, not 1', await ev(`(() => { return Array.from(document.querySelectorAll('.answer-text ol')).some((o) => o.getAttribute('start') === '2' && o.children.length === 2); })()`));
await shot('2b-lists');
await reset();
await ask('repeat please');
await idleAfterAnswer(1);
check('an answer the model wrote twice (around a picture tool) is shown ONCE', await count('.answer-text .prose') === 1 && await count('figure.card.figure') === 1);
await reset();
await ask('phantom please');
await idleAfterAnswer(1);
check('an answer that said "see the picture below" but showed nothing gets its picture after one automatic nudge, in the SAME answer', await count('figure.card.figure') === 1 && await count('.msg.user') === 1 && (await text('.answer-text')).includes('See the picture below'));
await reset();
await ask('unsafe please');
await idleAfterAnswer(1);
check('hostile text runs nothing: still only the page\'s own script', await count('script') === 1);
check('hostile text creates no image or link elements', await ev(`!document.querySelector('.answer-text img') && !document.querySelector('.answer-text a')`));
check('the hostile text is shown as plain words', (await text('.answer-text')).includes('<script>alert(1)</script>'));
check('a page number outside the manual (p.99) is not a button', await ev(`!document.querySelector('.answer-text .cite[data-page="99"]')`));

// ---------------------------------------------------------------- drawings: replace by identifier and one automatic repair
await reset();
await ask('draw it'); await idleAfterAnswer(1);
await ask('draw it again'); await idleAfterAnswer(2);
check('drawing the same thing twice leaves ONE drawing (replace by identifier)', await count('.frame[data-identifier="cable-cheat-sheet"]') === 1);
check('a drawing is labelled as a drawing', (await text('.frame .tag-soft')).includes('Drawing'));
await reset();
await ask('broken one');
await waitFor(`document.querySelectorAll('.note').length >= 1`, 'the automatic repair note', 15000);
await waitFor(`document.querySelectorAll('.conversation').length >= 2 && ${$('log')}.getAttribute('aria-busy') === 'false'`, 'the repair to finish', 15000);
await sleep(1500);
const notes = await ev(`Array.from(document.querySelectorAll('.note'), (n) => n.textContent).filter((t) => t.includes('asked the assistant to fix it'))`);
check('a drawing that errors is repaired automatically exactly ONCE', notes.length === 1, notes.length);
check('the repaired drawing replaced the broken one', await count('.frame[data-identifier="broken-demo"]') === 1 && await count('.frame .problem') === 0);

// ---------------------------------------------------------------- the same picture twice, a bad picture
await reset();
await ask('twice please'); await idleAfterAnswer(1);
check('asking for the same picture twice shows it once', await count('figure.card.figure') === 1);
check('two different diagrams are both shown', await count('iframe.embed') === 2);
await reset();
await ask('badfigure'); await idleAfterAnswer(1);
check('a picture that does not exist shows a quiet note, not a crash', (await text('.answer-visuals .note')).includes("couldn't show a picture"));

// ---------------------------------------------------------------- a picture and its text appear together
// the picture is asked for first and the text follows 1.5 s later; the page used to show the picture alone and then pop the text in above it
await reset();
await ask('together please');
await sleep(700);
check('while the answer is still being checked, no picture and no text are on the page yet', await ev(`document.querySelectorAll('figure.figure').length === 0 && !document.querySelector('.answer-text').textContent.trim()`));
await idleAfterAnswer(1);
check('then the text and its picture arrive together', await ev(`document.querySelectorAll('figure.figure').length === 1 && document.querySelector('.answer-text').textContent.includes('rating label')`));

// ---------------------------------------------------------------- busy, double send, keyboard
await reset();
await ask('slow one');
await sleep(300);
check('Send is disabled while an answer is being written', await ev(`${$('send')}.disabled`));
check('the status line says what is happening', (await text('#status-text')).length > 3 && !(await text('#status-text')).startsWith('Ready'));
// "Thinking..." belongs under the person's question, at the left, not up in the status strip
const where = await ev(`(() => { const w = document.querySelector('.conversation .working'); if (!w) return null;
  const q = document.querySelector('.conversation .bubble').getBoundingClientRect(), r = w.getBoundingClientRect(), m = document.querySelector('.conversation .msg.assistant').getBoundingClientRect(),
    strip = ${$('status')}.getBoundingClientRect(), vis = getComputedStyle(${$('status')}).opacity;
  return { under: r.top > q.bottom, leftOfBubble: r.left < q.left, insideAnswer: r.left >= m.left && r.right <= m.right + 1, stripTop: strip.bottom <= q.top, stripHidden: vis === '0', words: w.textContent.trim(), ariaHidden: w.getAttribute('aria-hidden') };
})()`);
check('a working line appears under the question while the answer is being written', Boolean(where && where.under), JSON.stringify(where));
check('...at the left of the answer, not under the right-aligned question bubble', Boolean(where && where.leftOfBubble && where.insideAnswer), JSON.stringify(where));
check('...and says what is happening', Boolean(where) && where.words.length > 3 && !where.words.startsWith('Ready'), where && where.words);
check('...while the status strip at the top is not showing it any more', Boolean(where && where.stripHidden && where.stripTop), JSON.stringify(where));
check('...and screen readers still hear the status through the strip, not twice', Boolean(where && where.ariaHidden === 'true') && (await text('#status-text')).length > 3);
await shot('thinking-under-question');
await ev(`(() => { const i = ${$('input')}; i.value = 'second question typed too early'; i.dispatchEvent(new Event('input')); ${$('composer')}.requestSubmit(); })()`);
await sleep(200);
check('a second question while busy is NOT sent', await count('.msg.user') === 1);
check('...and what was typed is kept in the box', await ev(`${$('input')}.value === 'second question typed too early'`));
await idleAfterAnswer(1);
check('when the answer is finished the working line is gone and the strip at the top is back', await count('.working') === 0 && await ev(`getComputedStyle(${$('status')}).opacity === '1'`));
await ev(`(() => { const i = ${$('input')}; i.value = ''; i.dispatchEvent(new Event('input')); })()`);
await ev(`${$('input')}.focus()`);
await cdp('Input.insertText', { text: 'first line' });
await press('Enter', 8);
await cdp('Input.insertText', { text: 'second line' });
check('Shift + Enter makes a new line and does not send', await ev(`${$('input')}.value === 'first line\\nsecond line'`) && await count('.msg.user') === 1);
await ev(`(() => { const i = ${$('input')}; i.value = 'figure please'; i.dispatchEvent(new Event('input')); })()`);
await press('Enter');
await idleAfterAnswer(2);
check('Enter sends the question', await count('.msg.user') === 2 && await ev(`${$('input')}.value === ''`));
await ev(`(() => { const i = ${$('input')}; i.value = '   '; i.dispatchEvent(new Event('input')); ${$('composer')}.requestSubmit(); })()`);
await sleep(200);
check('a blank message is never sent', await count('.msg.user') === 2 && await ev(`${$('send')}.disabled`));
await ev(`(() => { const i = ${$('input')}; i.value = ''; i.dispatchEvent(new Event('input')); })()`);

// ---------------------------------------------------------------- errors the person can hit
await reset();
await ask('crash please'); await idleAfterAnswer(1);
check('a server crash shows a plain PROBLEM box', await ev(`(() => { const c = document.querySelector('.callout.lvl-error'); return c && c.getAttribute('role') === 'alert' && c.textContent.includes('PROBLEM'); })()`));
await ask('figure please'); await idleAfterAnswer(2);
check('after a crash the next question simply works', await count('figure.card.figure') >= 1);
await reset();
await ask('limit please'); await idleAfterAnswer(1);
check('hitting the turn limit says so in plain words', (await text('.callout.lvl-error')).length > 20, await text('.callout.lvl-error'));
await reset();
await ask('budget please'); await idleAfterAnswer(1);
check('hitting the spending limit says so in plain words', (await text('.callout.lvl-error')).length > 20, await text('.callout.lvl-error'));
await reset();
await offline(true);
await ask('figure please'); await idleAfterAnswer(1, 8000);
check('with the network off: "I couldn\'t reach the server"', (await text('.callout.lvl-error')).includes("couldn't reach the server"));
await offline(false);
await ask('figure please'); await idleAfterAnswer(2);
check('when the network is back the same chat carries on', await count('figure.card.figure') >= 1);

// ---------------------------------------------------------------- new chat
await newChat();
await waitFor(`document.querySelectorAll('.conversation').length === 0`, 'the chat to clear');
check('New chat clears the conversation and brings the welcome back', await ev(`!${$('welcome')}.hidden && ${$('status-text')}.textContent === 'Ready when you are.'`));

// ---------------------------------------------------------------- layout, light and dark, desktop and phone
for (const [name, w, h, mobile, dark] of [['desktop-light', 1100, 800, false, false], ['desktop-dark', 1100, 800, false, true], ['phone-light', 390, 844, true, false], ['phone-dark', 390, 844, true, true]]) {
  await viewport(w, h, { mobile, dark });
  await load();
  await ask('everything please'); await idleAfterAnswer(1);
  await sleep(1200);
  check(`${name}: no sideways scrolling with a diagram, a picture and a calculator`, await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`), await ev(`document.documentElement.scrollWidth + ' vs ' + window.innerWidth`));
  check(`${name}: the question box stays on screen`, await ev(`${$('composer')}.getBoundingClientRect().bottom <= window.innerHeight + 1`));
  await ask('long answer please'); await idleAfterAnswer(2);
  check(`${name}: a long answer does not overflow`, await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`));
  await shot(`3-layout-${name}`);
}
await viewport(1100, 800);

// ---------------------------------------------------------------- accessibility basics and headers
await load();
await ask('everything please'); await idleAfterAnswer(1);
check('every button has a name', await ev(`Array.from(document.querySelectorAll('button')).every((x) => (x.textContent || '').trim() || x.getAttribute('aria-label'))`));
check('every picture has alternative text (except the viewer\'s empty one)', await ev(`Array.from(document.querySelectorAll('img')).filter((i) => i.id !== 'viewer-img').every((i) => i.alt.trim())`));
check('every frame has a title', await ev(`Array.from(document.querySelectorAll('iframe')).every((f) => f.title.trim())`));
check('the page is labelled: language, a live log, a labelled dialog', await ev(`document.documentElement.lang === 'en' && ${$('log')}.getAttribute('role') === 'log' && ${$('viewer')}.getAttribute('aria-labelledby') === 'viewer-title'`));
const headers = await ev(`fetch('/').then((r) => Object.fromEntries(['content-security-policy', 'x-frame-options', 'x-content-type-options', 'referrer-policy'].map((h) => [h, r.headers.get(h)])))`);
check('the page is served with a strict Content-Security-Policy', (headers['content-security-policy'] || '').includes("script-src 'self'") && !(headers['content-security-policy'] || '').includes('unsafe-inline'), headers['content-security-policy']);
check('it cannot be framed, sniffed, or leak its address', headers['x-frame-options'] === 'DENY' && headers['x-content-type-options'] === 'nosniff' && headers['referrer-policy'] === 'no-referrer', JSON.stringify(headers));

const errs = b.errors(/Failed to load resource|ERR_INTERNET_DISCONNECTED|net::|Failed to fetch|NetworkError/);
check('no JavaScript errors or policy violations in the whole run', errs.length === 0, errs[0]);
finish();
