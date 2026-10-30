// Real-browser checks of the three newer page features, against the demo server (canned answers, no API key, no cost):
// tap-to-answer questions, the clickable front panel, and sending a photo of a weld.
//   scripts/browser/run.sh new_features
import { openBrowser, sleep } from './cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { deflateSync, crc32 } from 'node:zlib';

const SITE = process.env.SITE || 'http://localhost:8135/';
const out = process.argv[2] || '/tmp/new-feature-checks';
const b = await openBrowser({ site: SITE, out });
const { ev, waitFor, expect, load, ask, idleAfterAnswer, viewport, check, finish, $, cdp, shot } = b;
const count = (sel) => ev(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
const text = (sel) => ev(`(document.querySelector(${JSON.stringify(sel)}) || {}).textContent || ''`);
const click = (sel, i = 0) => ev(`document.querySelectorAll(${JSON.stringify(sel)})[${i}].click()`);
const reset = async () => { await ev(`${$('new-chat')}.click()`); await waitFor(`document.querySelectorAll('.conversation').length === 0`, 'the chat to clear'); };
// a real PNG (a gradient), made here so the browser has an actual picture to decode and shrink
function makePng(width, height) {
  const chunk = (type, data) => { const t = Buffer.from(type), len = Buffer.alloc(4); len.writeUInt32BE(data.length); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(Buffer.concat([t, data])) >>> 0); return Buffer.concat([len, t, data, crc]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2;
  const row = Buffer.alloc(1 + width * 3);
  const raw = Buffer.alloc(row.length * height);
  for (let y = 0; y < height; y++) { for (let x = 0; x < width; x++) { const o = y * row.length + 1 + x * 3; raw[o] = (x * 255 / width) | 0; raw[o + 1] = (y * 255 / height) | 0; raw[o + 2] = 120; } }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
// every question the page posts, kept so the checks can look at exactly what was sent
const TEE = `(() => { window.__sent = []; const real = window.fetch; window.fetch = (...a) => { try { if (String(a[0]).includes('/api/chat')) window.__sent.push(JSON.parse(a[1].body)); } catch (e) {} return real(...a); }; })();`;
const noOverflow = () => ev(`document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1`);

await viewport(1100, 900);
await load(TEE);

// ================================================================ 1. tap-to-answer questions
await ask('details please');
await idleAfterAnswer(1);
check('the question comes with a card of buttons, placed after the sentence', await ev(`(() => { const t = document.querySelector('.answer-text'), v = document.querySelector('.answer-visuals .choices'); return Boolean(t && v && (t.compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING)); })()`));
check('one group for each topic asked', await count('.choices fieldset.choice-group') === 5);
const labelsOf = (g) => ev(`Array.from(document.querySelectorAll('.choices fieldset')[${g}].querySelectorAll('.chip'), (c) => c.textContent)`);
check('the process buttons are the four welding processes', JSON.stringify(await labelsOf(0)) === JSON.stringify(['MIG (solid wire with gas)', 'Flux-cored (gasless)', 'TIG', 'Stick']), JSON.stringify(await labelsOf(0)));
check('the voltage buttons are 120V and 240V', JSON.stringify(await labelsOf(1)) === JSON.stringify(['120V', '240V']));
check('material and thickness also take typed answers, the others do not', await ev(`Array.from(document.querySelectorAll('.choices fieldset'), (f) => Boolean(f.querySelector('input.chip-text'))).join()`) === 'false,false,true,true,false');
check('"Send my answers" waits until something is picked', await ev(`document.querySelector('.choices-send').disabled`));
await click('.choices fieldset:nth-of-type(1) .chip', 0);
check('tapping a button marks it chosen and enables Send', await ev(`document.querySelector('.choices fieldset .chip').getAttribute('aria-pressed') === 'true' && !document.querySelector('.choices-send').disabled`));
await click('.choices fieldset:nth-of-type(1) .chip', 0);
check('tapping it again takes it back', await ev(`document.querySelector('.choices fieldset .chip').getAttribute('aria-pressed') === 'false' && document.querySelector('.choices-send').disabled`));
await shot('choices-before');

// choose: MIG, 240V, steel, 1/8 inch, 0.030, then send
const tap = (group, label) => ev(`Array.from(document.querySelectorAll('.choices fieldset')[${group}].querySelectorAll('.chip')).find((c) => c.textContent === ${JSON.stringify(label)}).click()`);
await tap(0, 'MIG (solid wire with gas)'); await tap(1, '240V'); await tap(2, 'Steel'); await tap(3, '1/8 inch'); await tap(4, '0.030 in');
check('one choice per group at a time (choosing 240V did not keep 120V)', await ev(`document.querySelectorAll('.choices [aria-pressed="true"]').length === 5`));
await click('.choices-send');
await idleAfterAnswer(2);
check('their taps went back as their message, in plain words', (await text('.conversation:nth-of-type(2) .msg.user .bubble')) === 'Process: MIG. Input voltage: 240V. Material: steel. Thickness: 1/8 inch. Wire diameter: 0.030 inch.', await text('.conversation:nth-of-type(2) .msg.user .bubble'));
check('and the assistant carried on with the setup sheet', await ev(`Boolean(document.querySelector('.conversation:nth-of-type(2) iframe.embed'))`));
check('the used card stops taking taps', await ev(`(() => { const c = document.querySelector('.choices'); return c.classList.contains('done') && Array.from(c.querySelectorAll('button, input')).every((n) => n.disabled); })()`));

// typed answers: they replace a tapped one, are sent as plain text, and cannot become markup
await reset();
await ask('details please');
await idleAfterAnswer(1);
await tap(3, '1/8 inch');
await ev(`(() => { const i = document.querySelectorAll('.choices fieldset')[3].querySelector('input.chip-text'); i.value = '<img src=x onerror=alert(1)> 7/16 inch'; i.dispatchEvent(new Event('input')); })()`);
check('typing your own thickness un-picks the tapped one', await ev(`Array.from(document.querySelectorAll('.choices fieldset')[3].querySelectorAll('.chip')).every((c) => c.getAttribute('aria-pressed') === 'false')`));
check('the typed box stops at 40 characters', await ev(`document.querySelectorAll('.choices fieldset')[3].querySelector('input.chip-text').maxLength === 40`));
await ev(`(() => { const i = document.querySelectorAll('.choices fieldset')[3].querySelector('input.chip-text'); i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); })()`);
await idleAfterAnswer(2);
const bubble = await text('.conversation:nth-of-type(2) .msg.user .bubble');
check('Enter in the typed box sends, and typed markup stays plain text', bubble.startsWith('Thickness: <img src=x onerror=alert(1)> 7/16 inch') && await count('.msg.user img') === 0 && await count('.msg.user script') === 0, bubble);

// a problem: the buttons are the manual's own problem names
await reset();
await ask('symptom please');
await idleAfterAnswer(1);
check('the problem buttons are the 13 problems the manual lists', await ev(`document.querySelectorAll('.choices fieldset')[1].querySelectorAll('.chip').length`) === 13);
await tap(1, 'Wire Stops During Welding (MIG or flux-cored)');
await click('.choices-send');
await idleAfterAnswer(2);
check('picking a problem opens the troubleshooting flowchart', await ev(`document.querySelector('.conversation:nth-of-type(2) .msg.user .bubble').textContent === 'What it is doing: Wire Stops During Welding (MIG or flux-cored).' && Boolean(document.querySelector('.conversation:nth-of-type(2) iframe.embed'))`));

// phone width and dark mode
await reset();
await viewport(390, 800, { mobile: true });
await ask('details please');
await idleAfterAnswer(1);
check('on a phone the buttons wrap and nothing runs off the edge', await noOverflow());
await shot('choices-phone');
await viewport(1100, 900, { dark: true });
await shot('choices-dark');
check('in dark mode the chosen button is still readable (the stylesheet defines the colours it uses)', await ev(`getComputedStyle(document.documentElement).getPropertyValue('--on-accent').trim().length > 0`));
await viewport(1100, 900);

// ================================================================ 2. the clickable front panel and inside picture
await reset();
await viewport(1100, 900);
await ask('panel please');
await idleAfterAnswer(1);
check('the front-panel picture has a tappable box for each of its 13 labels', await count('.figure .hotspot') === 13);
check('the hint tells people they can tap a part', (await text('.hotspot-hint')).includes('Tap a part'));
check('nothing is explained until a part is tapped', await ev(`document.querySelector('.hotspot-info').hidden`));
check('every box sits inside the picture', await ev(`(() => { const st = document.querySelector('.hot-stage').getBoundingClientRect(); return Array.from(document.querySelectorAll('.hotspot'), (h) => h.getBoundingClientRect()).every((r) => r.left >= st.left - 1 && r.right <= st.right + 1 && r.top >= st.top - 1 && r.bottom <= st.bottom + 1 && r.width > 12 && r.height > 12); })()`));
// all boxes lit for one screenshot, to look at the alignment
await ev(`document.querySelectorAll('.hotspot').forEach((h) => h.classList.add('on'))`);
await viewport(1100, 2000);
await ev(`document.querySelector('.figure').scrollIntoView()`);
await shot('panel-all-boxes');
await viewport(1100, 900);
await ev(`document.querySelectorAll('.hotspot').forEach((h) => h.classList.remove('on'))`);
const tapSpot = (label) => ev(`Array.from(document.querySelectorAll('.hotspot')).find((h) => h.title === ${JSON.stringify(label)}).click()`);
await tapSpot('Power Switch');
check('tapping the Power Switch explains it, with the manual\'s page', await ev(`(() => { const i = document.querySelector('.hotspot-info'); return !i.hidden && i.querySelector('h4').textContent === 'Power Switch' && i.textContent.includes('unplug the Welder before setup') && i.querySelectorAll('.cite').length >= 2; })()`));
check('the tapped box is marked, and only that one', await ev(`document.querySelectorAll('.hotspot.on').length === 1 && document.querySelector('.hotspot.on').title === 'Power Switch' && document.querySelector('.hotspot.on').getAttribute('aria-pressed') === 'true'`));
await tapSpot('Negative Socket');
check('tapping another part replaces the explanation', await ev(`(() => { const i = document.querySelector('.hotspot-info'); return i.querySelectorAll('h4').length === 1 && i.querySelector('h4').textContent === 'Negative Socket' && i.textContent.includes('TIG Torch Cable') && document.querySelectorAll('.hotspot.on').length === 1; })()`));
await ev(`document.querySelector('.hotspot-info .cite').click()`);
await waitFor(`document.getElementById('viewer').open`, 'the manual page viewer');
check('a page chip in the explanation opens that manual page', await ev(`document.getElementById('viewer-img').src.includes('/pages/')`));
await ev(`document.getElementById('viewer').close()`);
// keyboard: focus a box and press Enter
await ev(`Array.from(document.querySelectorAll('.hotspot')).find((h) => h.title === 'Left Knob').focus()`);
await b.press('Enter');
check('a box can be used from the keyboard', await ev(`document.querySelector('.hotspot-info h4').textContent === 'Left Knob'`));
check('every box has a name for screen readers', await ev(`Array.from(document.querySelectorAll('.hotspot')).every((h) => h.getAttribute('aria-label').endsWith(': what the manual says'))`));
await click('.figure-foot .enlarge');
await waitFor(`document.getElementById('viewer').open`, 'Enlarge to open the viewer');
check('Enlarge still opens the picture bigger', await ev(`document.getElementById('viewer-img').src.includes('/figures/front-panel-controls.png')`));
await ev(`document.getElementById('viewer').close()`);
await tapSpot('Home Button');
await shot('panel-home-selected');

await reset();
await ask('interior please');
await idleAfterAnswer(1);
check('the inside picture has a tappable box for each of its 10 labels', await count('.figure .hotspot') === 10);
await ev(`document.querySelectorAll('.hotspot').forEach((h) => h.classList.add('on'))`);
await viewport(1100, 1700);
await ev(`document.querySelector('.figure').scrollIntoView()`);
await shot('interior-all-boxes');
await viewport(1100, 900);
await ev(`document.querySelectorAll('.hotspot').forEach((h) => h.classList.remove('on'))`);
await tapSpot('Cold Wire Feed Switch');
check('the Cold Wire Feed Switch explanation is the manual\'s own steps', await ev(`document.querySelector('.hotspot-info').textContent.includes('Press and hold the Cold Wire Feed Switch until the wire feeds through two inches')`));

// a picture with no tappable parts is unchanged: the whole picture enlarges
await reset();
await ask('figure please');
await idleAfterAnswer(1);
check('an ordinary figure has no boxes and still enlarges when clicked', await count('.figure .hotspot') === 0 && await ev(`document.querySelector('.figure-art').tagName === 'BUTTON'`));

// the picture on a phone
await reset();
await viewport(390, 800, { mobile: true });
await ask('panel please');
await idleAfterAnswer(1);
check('on a phone the picture and its boxes fit the screen', await noOverflow() && await ev(`(() => { const st = document.querySelector('.hot-stage').getBoundingClientRect(); return st.right <= window.innerWidth + 1; })()`));
await tapSpot('Positive Socket');
check('on a phone the explanation shows under the picture', await ev(`!document.querySelector('.hotspot-info').hidden`) && await noOverflow());
await shot('panel-phone');
await viewport(1100, 900);

// ================================================================ 3. sending a photo of a weld
mkdirSync(out, { recursive: true });
// absolute paths: the browser runs in its own folder and would not find a relative one
const here = resolve(out);
const bigPng = `${here}/weld-big.png`, smallPng = `${here}/weld-small.png`, notAPhoto = `${here}/notes.txt`, brokenPng = `${here}/broken.png`;
writeFileSync(bigPng, makePng(2400, 1600)); writeFileSync(smallPng, makePng(300, 200));
writeFileSync(notAPhoto, 'this is not a photo'); writeFileSync(brokenPng, Buffer.from('definitely not a png, only named like one'));
const upload = async (path) => {
  const { root } = await cdp('DOM.getDocument', { depth: 1 });
  const { nodeId } = await cdp('DOM.querySelector', { nodeId: root.nodeId, selector: '#photo-input' });
  await cdp('DOM.setFileInputFiles', { files: [path], nodeId });
};
const attached = () => ev(`!document.getElementById('attachment').hidden`);
const lastSent = () => ev(`(() => { const s = window.__sent[window.__sent.length - 1]; return s ? { message: s.message, hasImage: Boolean(s.image), type: s.image && s.image.media_type, head: s.image && s.image.data.slice(0, 4), size: s.image && s.image.data.length, keys: Object.keys(s).sort().join() } : null; })()`);
const sentDims = () => ev(`new Promise((res) => { const s = window.__sent[window.__sent.length - 1]; const i = new Image(); i.onload = () => res([i.naturalWidth, i.naturalHeight]); i.onerror = () => res(null); i.src = 'data:' + s.image.media_type + ';base64,' + s.image.data; })`);

await reset();
await viewport(1100, 900);
check('there is a button for attaching a photo, with a name for screen readers', await ev(`(() => { const b = document.getElementById('photo'); return !b.disabled && !b.hidden && b.getAttribute('aria-label').includes('photo'); })()`));
check('nothing is attached at first and Send waits', !(await attached()) && await ev(`document.getElementById('send').disabled`));
await upload(bigPng);
await expect('choosing a photo shows a preview strip', `!document.getElementById('attachment').hidden && document.getElementById('attachment-img').src.startsWith('data:image/jpeg')`, 8000);
check('a photo alone is enough to send (no words needed)', await ev(`!document.getElementById('send').disabled`));
await shot('photo-attached');
await click('#attachment-remove');
check('the remove button takes the photo back and disables Send again', !(await attached()) && await ev(`document.getElementById('send').disabled && !document.getElementById('attachment-img').getAttribute('src')`));

// send a photo with no words
await upload(bigPng);
await expect('a photo is attached again', `!document.getElementById('attachment').hidden`, 8000);
await ev(`document.getElementById('composer').requestSubmit()`);
await idleAfterAnswer(1);
const sent1 = await lastSent();
check('the request carried the default question and one JPEG photo, nothing else', sent1 && sent1.message === "What's wrong with this weld?" && sent1.hasImage && sent1.type === 'image/jpeg' && sent1.head === '/9j/' && sent1.keys === 'image,message,session_id', JSON.stringify(sent1));
const dims = await sentDims();
check('the big photo was shrunk to 1568 pixels on its longest side before it left the browser', dims && Math.max(...dims) === 1568 && Math.min(...dims) === 1045, JSON.stringify(dims));
check('the photo that went out is small enough to be sent quickly (under 2 MB of text)', sent1 && sent1.size < 2000000, String(sent1 && sent1.size));
check('the sent bubble shows the photo as a thumbnail with the question', await ev(`(() => { const b = document.querySelector('.msg.user .bubble'); return Boolean(b.querySelector('img.sent-photo[src^="data:image/jpeg"]')) && b.textContent.includes("What's wrong with this weld?"); })()`));
check('the assistant answers with the manual\'s own pictures and says which one the photo is closest to', await ev(`document.querySelectorAll('.answer-visuals figure.figure').length === 2 && document.querySelector('.answer-text').textContent.includes('Your photo looks closest to the manual')`));
check('the photo strip is cleared after sending and Send waits again', !(await attached()) && await ev(`document.getElementById('send').disabled`));
await shot('photo-answer');

// with words, a small photo
await reset();
await upload(smallPng);
await expect('a small photo is attached', `!document.getElementById('attachment').hidden`, 8000);
await ev(`(() => { const i = document.getElementById('input'); i.value = 'my weld has little holes in it'; i.dispatchEvent(new Event('input')); document.getElementById('composer').requestSubmit(); })()`);
await idleAfterAnswer(1);
const sent2 = await lastSent();
check('typed words and the photo travel together', sent2 && sent2.message === 'my weld has little holes in it' && sent2.hasImage, JSON.stringify(sent2));
const dims2 = await sentDims();
check('a small photo is not blown up', dims2 && dims2[0] === 300 && dims2[1] === 200, JSON.stringify(dims2));

// files that are not photos
await reset();
await upload(notAPhoto);
await sleep(400);
check('a text file is refused with a plain sentence and nothing is attached', !(await attached()) && (await text('#status-text')).includes('Please choose a photo'), await text('#status-text'));
await upload(brokenPng);
await expect('a broken picture file is refused too', `document.getElementById('status-text').textContent.includes('could not read that photo')`, 6000);
check('...and still nothing is attached', !(await attached()));

// busy, new chat, phone
await ask('slow please');
await expect('the photo button waits while an answer is being written', `document.getElementById('photo').disabled`, 4000);
await idleAfterAnswer(1);
check('and it comes back afterwards', await ev(`!document.getElementById('photo').disabled`));
await upload(smallPng);
await expect('a photo is attached before New chat', `!document.getElementById('attachment').hidden`, 8000);
await reset();
check('New chat drops a photo that was waiting', !(await attached()));
await viewport(390, 800, { mobile: true });
await upload(smallPng);
await expect('a photo can be attached on a phone', `!document.getElementById('attachment').hidden`, 8000);
check('on a phone the preview strip fits and nothing runs off the edge', await noOverflow());
await shot('photo-phone');
await viewport(1100, 900);


const errs = b.errors(/Failed to load resource|net::/);
check('no JavaScript errors in the browser during the run', errs.length === 0, errs[0]);
finish();
