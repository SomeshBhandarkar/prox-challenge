// The chat page: sends questions, reads the streamed events, and shows text, manual pictures, widgets and drawings.
// No libraries, no inline script, no network calls except to this server. Widgets and drawings run in sandboxed frames.
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const log = $('log'), thread = $('thread'), welcome = $('welcome'), input = $('input'), sendBtn = $('send'), form = $('composer');
  const statusEl = $('status'), statusText = $('status-text'), counter = $('count');
  const MAX = 2000;
  const state = {
    sid: null,            // conversation id from the server
    busy: false,
    stick: true,          // keep the newest content in view unless the person scrolled up
    body: null,           // the answer being filled in
    retries: new Map(),   // drawing identifier -> how many automatic fixes were tried
    fix: null,            // a drawing that reported an error and still needs one fix request
    abort: null,
  };

  // ---------- small helpers ----------
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const keepBottom = () => { if (state.stick) log.scrollTop = log.scrollHeight; };
  log.addEventListener('scroll', () => { state.stick = log.scrollHeight - log.scrollTop - log.clientHeight < 80; });
  // pictures and frames change height after they appear: whenever the thread grows, stay at the bottom unless the person scrolled up
  new ResizeObserver(keepBottom).observe(thread);

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

  function paragraph(text) {
    const m = text.match(LEVEL);
    if (!m) return `<p>${inline(text)}</p>`;
    const level = m[1].toLowerCase();
    const body = m[3] + (m[2] ? ' ' + m[2] : '');   // the citation moves to the end of the sentence
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
    const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; };
    const flushRows = () => { if (rows.length) out.push(table(rows)); rows = []; };
    const flushAll = () => { flushPara(); flushList(); flushRows(); };
    for (const raw of String(text).replace(/\r\n?/g, '\n').split('\n')) {
      const line = raw.trimEnd().replace(/^\s{0,3}>\s?/, '');   // a quoted line ("> WARNING! ...") is read as normal text
      let m;
      if (!line.trim()) { flushAll(); continue; }
      if (/^\s*\|/.test(line)) { flushPara(); flushList(); rows.push(line); continue; }
      flushRows();
      if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) { flushPara(); if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; } list.items.push(m[1]); continue; }
      if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { flushPara(); if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; } list.items.push(m[1]); continue; }
      if (list && /^\s{2,}\S/.test(raw)) { list.items[list.items.length - 1] += ' ' + line.trim(); continue; }
      if ((m = line.match(/^#{1,4}\s+(.*)$/))) { flushAll(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { flushAll(); out.push('<hr>'); continue; }
      flushList();
      para.push(line.trim());
    }
    flushAll();
    return out.join('');
  }

  // ---------- what appears in the conversation ----------
  function addUser(text) {
    const m = el('div', 'msg user');
    m.append(el('div', 'bubble', text));
    thread.append(m);
    state.stick = true;
    keepBottom();
  }

  function addNote(text) {
    thread.append(el('p', 'note', text));
    keepBottom();
  }

  function startAnswer() {
    const m = el('div', 'msg assistant');
    state.body = el('div', 'body');
    m.append(state.body);
    thread.append(m);
    return m;
  }

  function addProse(text) {
    const d = el('div', 'prose');
    d.innerHTML = renderText(text);
    state.body.append(d);
    keepBottom();
  }

  function addProblem(message) {
    const d = el('div', 'callout lvl-error');
    d.setAttribute('role', 'alert');
    d.append(el('span', 'tag', 'PROBLEM'), el('div', '', message));
    (state.body || thread).append(d);
    keepBottom();
  }

  function figureCard(d) {
    const fig = el('figure', 'card figure');
    const zoom = el('button', 'zoom');
    zoom.type = 'button';
    zoom.setAttribute('aria-label', 'Enlarge: ' + d.caption);
    const img = el('img');
    img.src = d.url;
    img.alt = d.caption;
    img.addEventListener('load', keepBottom);
    zoom.append(img);
    zoom.addEventListener('click', () => openViewer({ title: d.caption, src: d.url }));
    const cap = el('figcaption');
    cap.append(el('span', '', d.caption));
    if (d.manual_page) {
      const b = el('button', 'cite-src', `${d.source}: open the full page`);
      b.type = 'button';
      b.dataset.page = d.manual_page;
      cap.append(b);
    } else {
      cap.append(el('span', 'src', d.source));
    }
    fig.append(zoom, cap);
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
    head.append(el('span', '', d.title), el('span', 'tag-soft', isDrawing ? 'Drawing' : 'Interactive'));
    const frame = el('iframe', 'embed');
    frame.setAttribute('sandbox', 'allow-scripts');   // no same-origin: the frame cannot touch this page, its storage or the network
    frame.title = d.title;
    frame.src = d.embed;
    if (isDrawing) frame.dataset.identifier = d.identifier;
    card.append(head, frame);
    return card;
  }

  function appendShown(d) {
    if (d.kind === 'figure') state.body.append(figureCard(d));
    else if (d.kind === 'widget' || d.kind === 'artifact') state.body.append(frameCard(d));
    else state.body.append(el('p', 'note', d.message));   // a quiet note: the assistant usually corrects itself in the same answer
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
  const viewer = $('viewer'), vImg = $('viewer-img'), vTitle = $('viewer-title'), vPrev = $('viewer-prev'), vNext = $('viewer-next');
  let vPage = null;

  function openViewer({ title, src, page = null }) {
    vPage = page;
    vTitle.textContent = title;
    vImg.src = src;
    vImg.alt = title;
    viewer.classList.remove('zoomed');
    vPrev.hidden = vNext.hidden = page === null;
    if (page !== null) { vPrev.disabled = page <= 1; vNext.disabled = page >= 48; }
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
  function setStatus(text) {
    statusEl.hidden = !text;
    statusText.textContent = text ? text + '...' : '';
  }
  function setBusy(on) {
    state.busy = on;
    sendBtn.disabled = on || !input.value.trim();
    log.setAttribute('aria-busy', String(on));
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

  async function send(text, automatic = false) {
    text = text.trim();
    if (state.busy || !text) return;
    welcome.hidden = true;
    if (automatic) addNote('The drawing had a problem, so I asked the assistant to fix it.'); else addUser(text);
    setBusy(true);
    setStatus('Thinking');
    const answer = startAnswer();
    let finished = false;
    state.abort = new AbortController();
    try {
      const resp = await fetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: state.abort.signal,
        body: JSON.stringify({ message: text, session_id: state.sid }),
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
      if (!answer.querySelector('.body').childElementCount) answer.remove();
      setBusy(false);
      setStatus(null);
      if (state.fix) runFix(); else input.focus();
    }
  }

  function newChat() {
    if (state.abort) state.abort.abort();
    if (state.sid) fetch('/api/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: state.sid }) }).catch(() => {});
    state.sid = null; state.fix = null; state.body = null; state.retries.clear();
    thread.querySelectorAll('.msg, .note').forEach((n) => n.remove());
    welcome.hidden = false;
    setStatus(null);
    input.focus();
  }

  // ---------- the composer ----------
  function grow() {
    input.style.height = 'auto';
    if (input.value) input.style.height = Math.min(input.scrollHeight, 160) + 'px';   // an empty box keeps its default height (the placeholder must not be measured)
    sendBtn.disabled = state.busy || !input.value.trim();
    counter.textContent = input.value.length > MAX - 200 ? `${input.value.length}/${MAX}` : '';
  }
  input.addEventListener('input', grow);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value;
    if (state.busy || !text.trim()) return;
    input.value = '';
    grow();
    send(text);
  });
  $('starters').addEventListener('click', (e) => { const b = e.target.closest('button[data-q]'); if (b) send(b.dataset.q); });
  $('new-chat').addEventListener('click', newChat);
  addEventListener('pagehide', () => {
    if (state.sid) navigator.sendBeacon('/api/reset', new Blob([JSON.stringify({ session_id: state.sid })], { type: 'application/json' }));
  });

  grow();
  input.focus();
})();
