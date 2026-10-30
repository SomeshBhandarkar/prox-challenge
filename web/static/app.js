// The chat page: sends questions, reads the streamed events, and shows text, manual pictures, widgets and drawings.
// No libraries, no inline script, no network calls except to this server. Widgets and drawings run in sandboxed frames.
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const startup = $('startup'), shell = $('app-shell'), phrase = $('intro-phrase'), loading = $('startup-loading');
  const log = $('log'), thread = $('thread'), welcome = $('welcome'), input = $('input'), sendBtn = $('send'), form = $('composer');
  const statusText = $('status-text'), statusDot = $('status-dot'), counter = $('count'), micBtn = $('mic');
  const photoBtn = $('photo'), photoInput = $('photo-input'), attachment = $('attachment'), attachImg = $('attachment-img'), attachRemove = $('attachment-remove');
  const MAX = 2000;
  const PHOTO_QUESTION = "What's wrong with this weld?";   // sent when a photo goes with no words (the server uses the same sentence)
  const MAX_SIDE = 1568, MAX_PHOTO_CHARS = 2800000;   // longest side in pixels, and the size of the text form of the shrunken photo
  const HINT = 'Enter to send · Shift + Enter for a new line';
  const INTRO = ['Welding', 'shouldn’t', 'feel', 'like', 'a', 'full-time', 'job.'];
  const EYEBROW = {   // the small label above a card's title
    show_duty_cycle_calculator: 'TOOL', show_polarity_diagram: 'GUIDE', show_setup_guide: 'REFERENCE',
    show_troubleshooting_flowchart: 'TROUBLESHOOTING', create_artifact: 'SKETCH',
  };
  const state = {
    sid: null,            // conversation id from the server
    busy: false,
    stick: true,          // keep the newest content in view unless the person scrolled up
    body: null,           // the answer being filled in
    retries: new Map(),   // drawing identifier -> how many automatic fixes were tried
    fix: null,            // a drawing that reported an error and still needs one fix request
    abort: null,
    photo: null,          // a photo waiting to be sent: { media_type, data (base64), url (for the preview) }
  };

  // ---------- small helpers ----------
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const icon = (name) => {   // a small inline icon from the sprite in index.html
    const svg = document.createElementNS(SVG_NS, 'svg'), use = document.createElementNS(SVG_NS, 'use');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    use.setAttribute('href', '#i-' + name);
    svg.append(use);
    return svg;
  };
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const keepBottom = () => { if (state.stick) log.scrollTop = log.scrollHeight; };
  log.addEventListener('scroll', () => { state.stick = log.scrollHeight - log.scrollTop - log.clientHeight < 80; });
  // pictures and frames change height after they appear: whenever the thread grows, stay at the bottom unless the person scrolled up
  new ResizeObserver(keepBottom).observe(thread);

  // ---------- startup screen: a few words, then the app (shown once per visit, skippable) ----------
  function showApp() {
    startup.hidden = true;
    shell.hidden = false;
    try { sessionStorage.setItem('omnipro-seen', '1'); } catch (e) { /* storage can be blocked */ }
    input.focus();
  }
  async function runStartup() {
    let seen = false;
    try { seen = sessionStorage.getItem('omnipro-seen') === '1'; } catch (e) { /* storage can be blocked */ }
    if (seen || matchMedia('(prefers-reduced-motion: reduce)').matches) { showApp(); return; }
    let skipped = false;
    const skip = () => { skipped = true; };
    startup.addEventListener('click', skip);
    addEventListener('keydown', skip, { once: true });
    for (const word of INTRO) {
      if (skipped) break;
      await wait(230);
      phrase.append(el('span', 'intro-word', word));
    }
    if (!skipped) { await wait(350); loading.classList.add('visible'); loading.setAttribute('aria-hidden', 'false'); await wait(800); }
    showApp();
  }

  // ---------- text: a small, safe markdown ----------
  // Everything is escaped first; only the tags written below can appear. No links, no images, no raw HTML.
  function inline(raw) {
    let t = esc(raw);
    t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(^|[\s(])\*([^*\s][^*\n]*?)\*(?=$|[\s).,;:!?])/g, '$1<em>$2</em>');
    // "p.14" becomes a button that opens that manual page (but not "Quick-start guide p.2", which is another document)
    t = t.replace(/\bpp?\.\s?(\d{1,2})\b/g, (m, n, offset) => {
      const page = Number(n);
      const before = t.slice(Math.max(0, offset - 26), offset);
      if (page < 1 || page > 48 || /quick[- ]?start/i.test(before)) return m;
      return `<button type="button" class="cite" data-page="${page}" aria-label="Open manual page ${page}">p.${page}</button>`;
    });
    return t;
  }

  const LEVEL = /^(?:\*\*)?(DANGER|WARNING|CAUTION|NOTICE)(?:\*\*)?(?:\s*(\([^)]*\)))?\s*[:!–—-]+\*{0,2}\s*(.*)$/s;

  // "**WARNING: do this (manual p.10).**": the opening ** goes with the label, so the closing one is left over and would show as two stars
  function dropStrayBold(body) {
    return (body.match(/\*\*/g) || []).length % 2 === 1 ? body.replace(/\*\*(?![\s\S]*\*\*)/, '') : body;
  }

  function paragraph(text) {
    const m = text.match(LEVEL);
    if (!m) return `<p>${inline(text)}</p>`;
    const level = m[1].toLowerCase();
    const body = dropStrayBold(m[3] + (m[2] ? ' ' + m[2] : ''));   // the citation moves to the end of the sentence
    return `<div class="callout lvl-${level}"><span class="tag">${m[1]}</span><div>${inline(body)}</div></div>`;
  }

  function table(rows) {
    const cells = (r) => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
    const hasHead = rows.length > 1 && /^\s*\|?\s*:?-{2,}/.test(rows[1]);
    const head = hasHead ? `<thead><tr>${cells(rows[0]).map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>` : '';
    const body = rows.slice(hasHead ? 2 : 0).map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('');
    return `<div class="scroll-x"><table>${head}<tbody>${body}</tbody></table></div>`;
  }

  function renderText(text) {
    const out = [];
    let para = [], list = null, rows = [];
    const flushPara = () => { if (para.length) out.push(paragraph(para.join(' '))); para = []; };
    // an item is { text, sub? }: sub is one level of indented bullets or numbers under it. A numbered list that resumes at 2, 3... keeps its numbers.
    const items = (l) => l.items.map((i) => `<li>${inline(i.text)}${i.sub ? `<${i.sub.tag}>${i.sub.items.map((s) => `<li>${inline(s)}</li>`).join('')}</${i.sub.tag}>` : ''}</li>`).join('');
    const flushList = () => { if (list) out.push(`<${list.tag}${list.start > 1 ? ` start="${list.start}"` : ''}>${items(list)}</${list.tag}>`); list = null; };
    const flushRows = () => { if (rows.length) out.push(table(rows)); rows = []; };
    const flushAll = () => { flushPara(); flushList(); flushRows(); };
    for (const raw of String(text).replace(/\r\n?/g, '\n').split('\n')) {
      const line = raw.trimEnd().replace(/^\s{0,3}>\s?/, '');   // a quoted line ("> WARNING! ...") is read as normal text
      let m;
      if (!line.trim()) { flushAll(); continue; }
      if (/^\s*\|/.test(line)) { flushPara(); flushList(); rows.push(line); continue; }
      flushRows();
      if ((m = line.match(/^(\s*)([-*•]|\d+[.)])\s+(.*)$/))) {
        const indent = m[1].replace(/\t/g, '    ').length, ordered = /\d/.test(m[2]), tag = ordered ? 'ol' : 'ul';
        flushPara();
        if (list && indent >= list.indent + 2) {   // indented under an item above: a sub-point of that item
          const parent = list.items[list.items.length - 1];
          if (!parent.sub) parent.sub = { tag, items: [] };
          parent.sub.items.push(m[3]);
          continue;
        }
        if (!list || list.tag !== tag) { flushList(); list = { tag, indent, items: [], start: ordered ? Math.min(99, parseInt(m[2], 10)) : 1 }; }
        list.items.push({ text: m[3] });
        continue;
      }
      if (list && /^\s{2,}\S/.test(raw)) {   // a wrapped line of the item above
        const last = list.items[list.items.length - 1];
        if (last.sub) last.sub.items[last.sub.items.length - 1] += ' ' + line.trim(); else last.text += ' ' + line.trim();
        continue;
      }
      if ((m = line.match(/^#{1,4}\s+(.*)$/))) { flushAll(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { flushAll(); out.push('<hr>'); continue; }
      flushList();
      para.push(line.trim());
    }
    flushAll();
    return out.join('');
  }

  // ---------- what appears in the conversation ----------
  // One exchange = the person's question (if any) and the assistant's answer, which fills in as events arrive.
  function startExchange(userText, photo = null) {
    const wrap = el('div', 'conversation');
    if (userText) {
      const u = el('div', 'msg user');
      const bubble = el('div', 'bubble', userText);
      if (photo) {
        const thumb = el('img', 'sent-photo');
        thumb.src = photo.url;
        thumb.alt = 'The photo you sent';
        bubble.prepend(thumb);
      }
      u.append(bubble);
      wrap.append(u);
    }
    const msg = el('div', 'msg assistant');
    const label = el('div', 'assistant-label');
    label.append(el('div', 'mini-mark', '220'), el('span', '', 'OmniPro assistant'),
      el('span', 'time', new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })));
    // the answer's text always comes first and its pictures, widgets and drawings after it, however the events arrive
    state.body = el('div', 'body');
    state.prose = el('div', 'answer-text');
    state.visuals = el('div', 'answer-visuals');
    state.body.append(state.prose, state.visuals);
    state.msg = msg;
    state.sawText = false;
    msg.append(label, state.body);
    wrap.append(msg);
    thread.append(wrap);
    state.stick = true;
    keepBottom();
    return msg;
  }

  function addNote(text) {
    thread.append(el('p', 'note', text));
    keepBottom();
  }

  function proseBlock(text) {   // the escaping renderer's output: the only place the page writes HTML
    const d = el('div', 'prose');
    d.innerHTML = renderText(text);
    return d;
  }

  function addProse(text) {
    const d = proseBlock(text);
    state.prose.append(d);
    if (!state.sawText) {   // the answer is what they came for: bring its start into view and stop following the bottom while pictures load below it
      state.sawText = true;
      state.stick = false;
      state.msg.scrollIntoView({ block: 'start' });
    }
  }

  function addProblem(message) {
    const d = el('div', 'callout lvl-error');
    d.setAttribute('role', 'alert');
    d.append(el('span', 'tag', 'PROBLEM'), el('div', '', message));
    (state.prose || thread).append(d);
    keepBottom();
  }

  function figureCard(d) {
    const fig = el('figure', 'card figure');
    const hot = Array.isArray(d.hotspots) && d.hotspots.length > 0;   // a picture whose parts can be tapped (front panel, inside)
    const enlarge = () => openViewer({ title: d.caption, eyebrow: d.source, src: d.url });
    const img = el('img');
    img.src = d.url;
    img.alt = d.caption;
    img.addEventListener('load', keepBottom);
    let art, info = null;
    if (hot) {
      art = el('div', 'figure-art hot');
      const stage = el('div', 'hot-stage');   // exactly as big as the picture, so a box in percent lands on the same spot
      stage.append(img);
      info = el('div', 'hotspot-info');
      info.hidden = true;
      info.setAttribute('aria-live', 'polite');
      const spots = [];
      for (const h of d.hotspots) {
        const b = el('button', 'hotspot');
        b.type = 'button';
        b.title = h.label;
        b.setAttribute('aria-label', `${h.label}: what the manual says`);
        b.setAttribute('aria-pressed', 'false');
        const [x, y, w, hh] = h.box;
        Object.assign(b.style, { left: x * 100 + '%', top: y * 100 + '%', width: w * 100 + '%', height: hh * 100 + '%' });
        b.addEventListener('click', () => {
          spots.forEach((o) => { o.classList.toggle('on', o === b); o.setAttribute('aria-pressed', String(o === b)); });
          info.replaceChildren(el('h4', '', h.label), proseBlock(h.text));
          info.hidden = false;
          info.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        });
        spots.push(b);
        stage.append(b);
      }
      art.append(stage);
    } else {
      art = el('button', 'figure-art zoom');
      art.type = 'button';
      art.setAttribute('aria-label', 'Enlarge: ' + d.caption);
      art.append(img);
      art.addEventListener('click', enlarge);
    }
    const foot = el('div', 'figure-foot');
    const source = el('span');
    source.append(icon('file'), document.createTextNode(d.source));
    foot.append(source);
    if (hot) {
      const z = el('button', 'enlarge');
      z.type = 'button';
      z.append(icon('expand'), document.createTextNode('Enlarge'));
      z.addEventListener('click', enlarge);
      foot.append(z);
    }
    if (d.manual_page) {
      const b = el('button', 'cite-src');
      b.type = 'button';
      b.dataset.page = d.manual_page;
      b.append(icon('expand'), document.createTextNode('Open full page'));
      foot.append(b);
    }
    fig.append(art);
    if (hot) fig.append(el('p', 'hotspot-hint', 'Tap a part of the picture to see what the manual says about it.'), info);
    fig.append(el('figcaption', 'figure-caption', d.caption), foot);
    return fig;
  }

  function frameCard(d) {
    const isDrawing = d.kind === 'artifact';
    if (isDrawing) {   // drawing the same thing again replaces the earlier drawing instead of piling up copies
      for (const old of thread.querySelectorAll('.frame')) if (old.dataset.identifier === d.identifier) old.remove();
    }
    const card = el('section', 'card frame');
    if (isDrawing) card.dataset.identifier = d.identifier;
    const head = el('div', 'frame-head');
    const titles = el('div');
    titles.append(el('span', 'eyebrow', EYEBROW[d.tool] || 'TOOL'), el('h3', '', d.title));
    head.append(titles, el('span', 'tag-soft', isDrawing ? 'Drawing' : 'Interactive'));
    const frame = el('iframe', 'embed');
    frame.setAttribute('sandbox', 'allow-scripts');   // no same-origin: the frame cannot touch this page, its storage or the network
    frame.title = d.title;
    frame.src = d.embed;
    if (isDrawing) frame.dataset.identifier = d.identifier;
    card.append(head, frame);
    return card;
  }

  // Tap-to-answer questions. The options come from the server's verified data; the taps go back as the person's next message.
  function choicesCard(d) {
    const card = el('section', 'card choices');
    const titles = el('div', 'frame-head');
    const heading = el('div');
    heading.append(el('span', 'eyebrow', 'QUICK ANSWERS'), el('h3', '', d.title));
    titles.append(heading);
    card.append(titles);
    const picked = new Map();   // group id -> what was tapped or typed
    const go = el('button', 'choices-send');
    go.type = 'button';
    go.append(document.createTextNode('Send my answers'), icon('send'));
    const refresh = () => { go.disabled = state.busy || picked.size === 0; };
    card.refresh = refresh;
    for (const g of d.groups) {
      const set = el('fieldset', 'choice-group');
      set.append(el('legend', '', g.label));
      const chips = el('div', 'chips');
      const buttons = [];
      let typed = null;
      for (const o of g.options) {
        const b = el('button', 'chip', o.label);
        b.type = 'button';
        b.setAttribute('aria-pressed', 'false');
        b.addEventListener('click', () => {
          const turnOn = picked.get(g.id) !== o.value;   // tapping the chosen one again takes it back
          picked.delete(g.id);
          buttons.forEach((x) => x.setAttribute('aria-pressed', 'false'));
          if (typed) typed.value = '';
          if (turnOn) { picked.set(g.id, o.value); b.setAttribute('aria-pressed', 'true'); }
          refresh();
        });
        buttons.push(b);
        chips.append(b);
      }
      if (g.free_text) {
        typed = el('input', 'chip-text');
        typed.type = 'text';
        typed.maxLength = 40;
        typed.placeholder = g.placeholder || 'Something else';
        typed.setAttribute('aria-label', g.label + ' (type your own)');
        typed.addEventListener('input', () => {
          buttons.forEach((x) => x.setAttribute('aria-pressed', 'false'));
          const v = typed.value.trim();
          if (v) picked.set(g.id, v); else picked.delete(g.id);
          refresh();
        });
        typed.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); if (!go.disabled) go.click(); } });
        chips.append(typed);
      }
      set.append(chips);
      card.append(set);
    }
    go.addEventListener('click', () => {
      if (state.busy || !picked.size) return;
      const text = d.groups.filter((g) => picked.has(g.id)).map((g) => `${g.phrase}: ${picked.get(g.id)}`).join('. ') + '.';
      card.classList.add('done');   // one use: the answers are sent, so the card stops taking taps
      card.querySelectorAll('button, input').forEach((n) => { n.disabled = true; });
      send(text);
    });
    card.append(go);
    refresh();
    return card;
  }

  function appendShown(d) {
    if (d.kind === 'figure') state.visuals.append(figureCard(d));
    else if (d.kind === 'choices') state.visuals.append(choicesCard(d));
    else if (d.kind === 'widget' || d.kind === 'artifact') state.visuals.append(frameCard(d));
    else state.visuals.append(el('p', 'note', d.message));   // a quiet note: the assistant usually corrects itself in the same answer
    keepBottom();
  }

  // Frames tell us how tall they are, and drawings tell us when they hit an error.
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (!d || typeof d !== 'object' || (d.source !== 'widget' && d.source !== 'artifact')) return;
    const frame = Array.from(document.querySelectorAll('iframe.embed')).find((f) => f.contentWindow === e.source);
    if (!frame) return;
    if (d.kind === 'resize' && Number.isFinite(d.height)) {
      frame.style.height = Math.min(Math.max(Math.ceil(d.height) + 2, 80), 5000) + 'px';   // the cap stops a runaway drawing from growing forever
      keepBottom();
    } else if (d.kind === 'error' && frame.dataset.identifier) {
      drawingFailed(frame, String(d.message || 'unknown error'));
    }
  });

  // One automatic fix per drawing: tell the assistant what the drawing reported, once.
  function drawingFailed(frame, message) {
    const id = frame.dataset.identifier;
    const card = frame.closest('.frame');
    const tries = state.retries.get(id) || 0;
    if (!card.querySelector('.problem')) card.append(el('p', 'problem', tries ? 'This drawing still has a problem. Ask me to try again.' : 'This drawing hit an error. Asking the assistant to fix it...'));
    if (tries >= 1) return;
    state.retries.set(id, tries + 1);
    state.fix = { id, title: frame.title, message: message.slice(0, 200) };
    if (!state.busy) runFix();
  }

  function runFix() {
    const f = state.fix;
    state.fix = null;
    if (!f) return;
    send(`The drawing "${f.title}" (identifier ${f.id}) reported this error: ${f.message}. Please fix it and draw it again with the same identifier.`, true);
  }

  // ---------- the manual page / picture viewer ----------
  const viewer = $('viewer'), vImg = $('viewer-img'), vTitle = $('viewer-title'), vEyebrow = $('viewer-eyebrow');
  const vNav = $('viewer-nav'), vPrev = $('viewer-prev'), vNext = $('viewer-next'), vCount = $('viewer-count');
  let vPage = null;

  function openViewer({ title, eyebrow = 'OWNER’S MANUAL', src, page = null }) {
    vPage = page;
    vEyebrow.textContent = eyebrow.toUpperCase();
    vTitle.textContent = title;
    vImg.src = src;
    vImg.alt = title;
    viewer.classList.remove('zoomed');
    vNav.hidden = page === null;
    if (page !== null) { vPrev.disabled = page <= 1; vNext.disabled = page >= 48; vCount.textContent = `Page ${page} of 48`; }
    if (!viewer.open) viewer.showModal();
  }
  const openPage = (n) => { const p = Math.min(48, Math.max(1, Number(n) || 1)); openViewer({ title: `Owner's manual, page ${p}`, src: `/pages/${p}.jpg`, page: p }); };
  vPrev.addEventListener('click', () => vPage > 1 && openPage(vPage - 1));
  vNext.addEventListener('click', () => vPage !== null && vPage < 48 && openPage(vPage + 1));
  $('viewer-close').addEventListener('click', () => viewer.close());
  vImg.addEventListener('click', () => viewer.classList.toggle('zoomed'));
  viewer.addEventListener('click', (e) => { if (e.target === viewer) viewer.close(); });
  viewer.addEventListener('keydown', (e) => {
    if (vPage === null) return;
    if (e.key === 'ArrowLeft' && vPage > 1) openPage(vPage - 1);
    if (e.key === 'ArrowRight' && vPage < 48) openPage(vPage + 1);
  });
  log.addEventListener('click', (e) => {
    const b = e.target.closest('.cite, .cite-src');
    if (b) openPage(b.dataset.page);
  });

  // ---------- talking to the server ----------
  function setStatus(text, plain) {   // plain = a full sentence, so no "..." is added
    statusText.textContent = text ? (plain ? text : text + '...') : 'Ready when you are.';
    statusDot.classList.toggle('active', Boolean(text));
  }
  function setBusy(on) {
    state.busy = on;
    micBtn.disabled = on;
    photoBtn.disabled = on;
    sendBtn.disabled = on || (!input.value.trim() && !state.photo);
    log.setAttribute('aria-busy', String(on));
    thread.querySelectorAll('.choices:not(.done)').forEach((c) => c.refresh && c.refresh());
  }

  function parseBlock(block) {
    let name = 'message';
    const data = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) name = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return null;
    try { return { name, data: JSON.parse(data.join('\n')) }; } catch (e) { return null; }
  }

  async function readEvents(stream, onEvent) {
    const reader = stream.getReader(), decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const ev = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (ev) onEvent(ev.name, ev.data);
      }
    }
  }

  function describeFailure(status, body) {
    if (status === 409) return 'I am still answering the last question. Give me a moment.';
    if (body && body.error) return body.error;
    return `The server had a problem (error ${status}).`;
  }

  async function send(text, automatic = false, photo = null) {
    text = text.trim();
    if (state.busy || !text) return;
    cancelListening();   // a new question: stop listening for the old one and stop reading the last answer
    stopReading();
    welcome.hidden = true;
    if (automatic) addNote('The drawing had a problem, so I asked the assistant to fix it.');
    const answer = startExchange(automatic ? null : text, photo);
    setBusy(true);
    setStatus('Thinking');
    let finished = false;
    state.abort = new AbortController();
    try {
      const resp = await fetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: state.abort.signal,
        body: JSON.stringify({ message: text, session_id: state.sid, ...(photo ? { image: { media_type: photo.media_type, data: photo.data } } : {}) }),
      });
      if (!resp.ok) {
        let body = null;
        try { body = await resp.json(); } catch (e) { /* not JSON */ }
        addProblem(describeFailure(resp.status, body));
        finished = true;
      } else {
        await readEvents(resp.body, (name, d) => {
          if (name === 'session') {
            if (state.sid && !d.resumed) addNote('Your earlier conversation expired, so this is a fresh start.');
            state.sid = d.session_id;
          } else if (name === 'status') setStatus(d.text);
          else if (name === 'text') { addProse(d.text); setStatus('Writing the answer'); }
          else if (name === 'show') appendShown(d);
          else if (name === 'error') { addProblem(d.message); if (d.fatal) state.sid = null; }
          else if (name === 'done') finished = true;
        });
      }
      if (!finished) addProblem('The answer was cut off. Please ask again.');
    } catch (e) {
      if (e.name !== 'AbortError') addProblem("I couldn't reach the server. Is it still running?");
    } finally {
      state.abort = null;
      if (!answer.querySelectorAll('.answer-text > *, .answer-visuals > *').length) answer.remove();
      else addListenButton(answer);
      setBusy(false);
      setStatus(null);
      if (state.fix) runFix(); else input.focus();
    }
  }

  function newChat() {
    cancelListening();
    clearPhoto();
    stopReading();
    if (state.abort) state.abort.abort();
    if (state.sid) fetch('/api/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: state.sid }) }).catch(() => {});
    state.sid = null; state.fix = null; state.body = state.prose = state.visuals = state.msg = null; state.retries.clear();
    thread.querySelectorAll('.conversation, .note').forEach((n) => n.remove());
    welcome.hidden = false;
    setStatus(null);
    input.focus();
  }

  // ---------- the composer ----------
  function grow() {
    input.style.height = 'auto';
    if (input.value) input.style.height = Math.min(input.scrollHeight, 160) + 'px';   // an empty box keeps its default height (the placeholder must not be measured)
    sendBtn.disabled = state.busy || (!input.value.trim() && !state.photo);
    const near = input.value.length > MAX - 200;
    counter.textContent = near ? `${input.value.length} / ${MAX}` : HINT;
    counter.classList.toggle('near', near);
  }
  input.addEventListener('input', grow);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value, photo = state.photo;
    if (state.busy || (!text.trim() && !photo)) return;
    input.value = '';
    clearPhoto();
    send(text.trim() || PHOTO_QUESTION, false, photo);
  });
  $('starters').addEventListener('click', (e) => { const b = e.target.closest('button[data-q]'); if (b) send(b.dataset.q); });
  $('new-chat').addEventListener('click', newChat);
  addEventListener('pagehide', () => {
    if (synth) synth.cancel();
    if (state.sid) navigator.sendBeacon('/api/reset', new Blob([JSON.stringify({ session_id: state.sid })], { type: 'application/json' }));
  });

  // ---------- a photo of the weld (optional) ----------
  // The photo is shrunk and re-saved as a JPEG in this browser before it is sent: that keeps it small, drops any location data the camera added,
  // and means the server only ever receives a plain JPEG. It is shown back as a small thumbnail and is never stored.
  function flash(message) {
    setStatus(message, true);
    setTimeout(() => { if (!state.busy && statusText.textContent === message) setStatus(null); }, 6000);
  }
  function clearPhoto() {
    state.photo = null;
    attachment.hidden = true;
    attachImg.removeAttribute('src');
    grow();
  }
  async function attachPhoto(file) {
    if (!file || !String(file.type).startsWith('image/')) { flash('Please choose a photo (a JPG, PNG or WebP file).'); return; }
    if (file.size > 25 * 1024 * 1024) { flash('That photo is too large. Choose one under 25 MB.'); return; }
    let bitmap;
    try { bitmap = await createImageBitmap(file); } catch (e) { flash('I could not read that photo. Try a JPG or PNG.'); return; }
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';   // a transparent PNG would turn black as a JPEG
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    if (bitmap.close) bitmap.close();
    let quality = 0.85, url = canvas.toDataURL('image/jpeg', quality);
    while (url.length > MAX_PHOTO_CHARS && quality > 0.4) { quality -= 0.15; url = canvas.toDataURL('image/jpeg', quality); }
    if (url.length > MAX_PHOTO_CHARS) { flash('That photo is still too large. Try a smaller one.'); return; }
    state.photo = { media_type: 'image/jpeg', data: url.slice(url.indexOf(',') + 1), url };
    attachImg.src = url;
    attachment.hidden = false;
    grow();
    input.focus();
  }
  photoBtn.addEventListener('click', () => { if (!state.busy) photoInput.click(); });
  photoInput.addEventListener('change', () => { const f = photoInput.files && photoInput.files[0]; photoInput.value = ''; if (f) attachPhoto(f); });
  attachRemove.addEventListener('click', () => { clearPhoto(); input.focus(); });

  // ---------- voice (optional: the buttons stay hidden where the browser has no speech support) ----------
  // Speaking FILLS the question box; the person checks what was heard and presses send, so a misheard word never goes out by itself.
  // Both halves use the browser's own speech features: no extra key, no extra server call.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = window.speechSynthesis;
  const LANG = navigator.language || 'en-US';
  const MIC_BLOCKED = 'The microphone is blocked. Allow it in your browser’s address bar, then try again.';
  const MIC_PROBLEMS = {
    'not-allowed': MIC_BLOCKED, 'service-not-allowed': MIC_BLOCKED,
    'no-speech': 'I didn’t hear anything. Tap the microphone and try again.',
    'audio-capture': 'I couldn’t find a microphone.',
    network: 'Speech recognition needs an internet connection.',
  };
  let recog = null, reading = null;

  function micIdle() {
    recog = null;
    micBtn.classList.remove('listening');
    micBtn.setAttribute('aria-pressed', 'false');
    micBtn.setAttribute('aria-label', 'Speak your question');
  }
  function cancelListening() {   // a question was sent or the chat was reset: drop whatever is being heard
    if (!recog) return;
    const r = recog;
    r.onresult = r.onerror = r.onend = null;
    try { r.abort(); } catch (e) { /* already stopped */ }
    micIdle();
  }
  function startListening() {
    if (state.busy || recog) return;
    const base = input.value.trim();
    let problem = false;
    const r = recog = new Recognition();
    r.lang = LANG; r.interimResults = true; r.continuous = false;
    r.onresult = (e) => {   // only fills the box: nothing is sent by voice alone
      const said = Array.from(e.results, (res) => res[0].transcript).join('').trim();
      input.value = ((base ? base + ' ' : '') + said).slice(0, MAX);
      grow();
    };
    r.onerror = (e) => {
      if (e.error === 'aborted') return;
      problem = true;
      setStatus(MIC_PROBLEMS[e.error] || 'The microphone stopped (' + e.error + ').', true);
      statusDot.classList.remove('active');
    };
    r.onend = () => { micIdle(); if (!problem && !state.busy) setStatus(null); input.focus(); };
    try { r.start(); } catch (err) { micIdle(); return; }
    micBtn.classList.add('listening');
    micBtn.setAttribute('aria-pressed', 'true');
    micBtn.setAttribute('aria-label', 'Stop listening');
    setStatus('Listening... tap the microphone when you are done.', true);
  }
  if (Recognition) {
    micBtn.hidden = false;
    micBtn.addEventListener('click', () => (recog ? recog.stop() : startListening()));
  }

  function stopReading() {
    if (!synth) return;
    synth.cancel();
    if (reading) {
      reading.classList.remove('reading');
      reading.setAttribute('aria-pressed', 'false');
      reading.setAttribute('aria-label', 'Read this answer aloud');
      reading = null;
    }
  }
  function spokenText(msg) {   // the answer's words only (no pictures); "p.19" is said as "page 19"
    return Array.from(msg.querySelectorAll('.answer-text'), (n) => n.innerText).join('\n').replace(/\bp\.\s?(\d+)/g, 'page $1');
  }
  function toggleReading(btn) {
    const wasThis = reading === btn;
    stopReading();
    if (wasThis) return;
    // one short sentence at a time: some browsers cut off long speech, and "0.030" is not split
    const parts = spokenText(btn.closest('.msg')).split(/(?<=[.!?])\s+|\n+/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    reading = btn;
    btn.classList.add('reading');
    btn.setAttribute('aria-pressed', 'true');
    btn.setAttribute('aria-label', 'Stop reading');
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      u.lang = LANG;
      u.onerror = () => { if (reading === btn) stopReading(); };
      if (i === parts.length - 1) u.onend = () => { if (reading === btn) stopReading(); };
      synth.speak(u);
    });
  }
  function addListenButton(msg) {   // a small speaker in the answer's header, once the answer has text
    if (!synth || msg.querySelector('.listen') || !msg.querySelector('.answer-text > *')) return;
    const b = el('button', 'listen');
    b.type = 'button';
    b.title = 'Read this answer aloud';
    b.setAttribute('aria-label', 'Read this answer aloud');
    b.setAttribute('aria-pressed', 'false');
    b.append(icon('speaker'));
    msg.querySelector('.assistant-label').append(b);
  }
  log.addEventListener('click', (e) => { const b = e.target.closest('.listen'); if (b) toggleReading(b); });

  grow();
  runStartup();
})();
