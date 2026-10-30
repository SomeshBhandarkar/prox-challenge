// Shared helper for the browser checks in this folder. It starts a headless Chrome (no window opens), talks to it over its
// debugging port, and prints PASS / FAIL lines. Needs Node 22+ and Chrome or Chromium (set CHROME_PATH if it is not found).
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const CANDIDATES = [process.env.CHROME_PATH, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
const KEYS = { Enter: 13, Escape: 27, ArrowLeft: 37, ArrowRight: 39 };

export async function openBrowser({ site, out }) {
  const exe = CANDIDATES.find((p) => p && existsSync(p));
  if (!exe) throw new Error('Chrome was not found. Set CHROME_PATH to your Chrome or Chromium program.');
  mkdirSync(out, { recursive: true });
  // port 0 = Chrome picks a free one and writes it into the profile folder, so two runs can never talk to each other's browser
  const chrome = spawn(exe, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${out}/profile`,
    '--no-first-run', '--disable-gpu', '--window-size=1100,800', 'about:blank'], { stdio: 'ignore' });
  let port = null;
  for (let i = 0; i < 60 && !port; i++) {
    try { port = readFileSync(`${out}/profile/DevToolsActivePort`, 'utf8').split('\n')[0].trim() || null; } catch (e) { /* not written yet */ }
    if (!port) await sleep(200);
  }
  if (!port) { chrome.kill('SIGKILL'); throw new Error('Chrome did not start'); }
  const die = (e) => { console.log('FAIL (the check script stopped): ' + ((e && e.message) || e)); try { chrome.kill('SIGKILL'); } catch (x) { /* already gone */ } process.exit(1); };
  process.on('uncaughtException', die); process.on('unhandledRejection', die);
  let wsUrl;
  for (let i = 0; i < 60 && !wsUrl; i++) {
    try { wsUrl = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page')?.webSocketDebuggerUrl; } catch (e) { /* still starting */ }
    if (!wsUrl) await sleep(200);
  }
  if (!wsUrl) { chrome.kill('SIGKILL'); throw new Error('Chrome did not start'); }

  const ws = new WebSocket(wsUrl);
  let nextId = 0;
  const pending = new Map();
  const events = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) {
      const { res, rej } = pending.get(d.id);
      pending.delete(d.id);
      d.error ? rej(new Error(JSON.stringify(d.error))) : res(d.result);
    } else if (d.method) events.push(d);
  };
  await new Promise((r) => { ws.onopen = r; });
  const cdp = (method, params = {}) => new Promise((res, rej) => { const id = ++nextId; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
  const ev = async (expression) => {
    const r = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('page JS error: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  };
  const waitFor = async (expr, label, ms = 10000) => {
    const t = Date.now();
    while (Date.now() - t < ms) { if (await ev(expr)) return; await sleep(80); }
    throw new Error('timed out waiting for: ' + label);
  };
  // wait for a condition and record PASS or FAIL (instead of stopping the whole run when it never comes true)
  const expect = async (name, expr, ms = 10000) => { try { await waitFor(expr, name, ms); check(name, true); } catch (e) { check(name, false, 'timed out'); } };
  const shot = async (name) => writeFileSync(`${out}/${name}.png`, Buffer.from((await cdp('Page.captureScreenshot', { format: 'png' })).data, 'base64'));
  const describe = (e) => {
    if (e.method === 'Runtime.exceptionThrown') return 'exception: ' + (e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text);
    if (e.method === 'Runtime.consoleAPICalled') return 'console.error: ' + e.params.args.map((a) => a.value ?? a.description).join(' ');
    return 'log: ' + e.params.entry.text + ' ' + (e.params.entry.url || '');
  };
  const errors = (ignore) => events
    .filter((e) => e.method === 'Runtime.exceptionThrown' || (e.method === 'Runtime.consoleAPICalled' && e.params.type === 'error') || (e.method === 'Log.entryAdded' && e.params.entry.level === 'error'))
    .map(describe).filter((m) => !(ignore && ignore.test(m)));

  await cdp('Page.enable'); await cdp('Runtime.enable'); await cdp('Log.enable'); await cdp('Network.enable');

  let injected = null;
  const $ = (id) => `document.getElementById('${id}')`;
  // Open the site with some script running first. seen: true (default) skips the startup screen as if it was already shown in this
  // tab; false forces it to show; null leaves the tab's storage alone.
  const load = async (script = '', { seen = true, path = '' } = {}) => {
    await cdp('Page.navigate', { url: 'about:blank' });
    if (injected) await cdp('Page.removeScriptToEvaluateOnNewDocument', { identifier: injected });
    const flag = seen === true ? "try { sessionStorage.setItem('omnipro-seen', '1'); } catch (e) {}\n"
      : seen === false ? "try { sessionStorage.removeItem('omnipro-seen'); } catch (e) {}\n" : '';
    injected = (await cdp('Page.addScriptToEvaluateOnNewDocument', { source: flag + script })).identifier;
    await cdp('Page.navigate', { url: site + path });
    await waitFor(`location.href.startsWith(${JSON.stringify(site)}) && document.readyState === 'complete' && Boolean(document.getElementById('app-shell'))`, 'the page to load');
    if (seen === true) await waitFor(`!${$('app-shell')}.hidden`, 'the app to show');
  };
  const ask = (text) => ev(`(() => { const i = ${$('input')}; i.value = ${JSON.stringify(text)}; i.dispatchEvent(new Event('input')); ${$('composer')}.requestSubmit(); })()`);
  // true once the n-th question has been asked and its answer has finished (the page marks the log busy while it writes)
  const idleAfterAnswer = (n = 1, ms = 20000) => waitFor(`document.querySelectorAll('.conversation').length >= ${n} && ${$('log')}.getAttribute('aria-busy') === 'false' && ${$('status-text')}.textContent === 'Ready when you are.'`, 'the answer to finish', ms);
  const press = async (key, mods = 0) => {
    const base = { key, code: key, windowsVirtualKeyCode: KEYS[key], nativeVirtualKeyCode: KEYS[key], modifiers: mods };
    await cdp('Input.dispatchKeyEvent', { type: key === 'Enter' ? 'keyDown' : 'rawKeyDown', ...base, ...(key === 'Enter' ? { text: '\r' } : {}) });
    await cdp('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
  };
  const viewport = (width, height, { mobile = false, dark = false, reduced = false } = {}) => Promise.all([
    cdp('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile }),
    cdp('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }, { name: 'prefers-reduced-motion', value: reduced ? 'reduce' : 'no-preference' }] }),
  ]);
  const offline = (on) => cdp('Network.emulateNetworkConditions', { offline: on, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });

  let fails = 0, total = 0;
  const check = (name, ok, detail = '') => { total++; if (!ok) fails++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? `   [${String(detail).slice(0, 240)}]` : '')); };
  const finish = () => {
    console.log(fails ? `\n${fails} of ${total} CHECKS FAILED` : `\nALL ${total} CHECKS PASSED`);
    try { ws.close(); } catch (e) { /* closing anyway */ }
    chrome.kill('SIGKILL');
    process.exit(fails ? 1 : 0);
  };
  return { cdp, ev, waitFor, expect, shot, events, errors, load, ask, idleAfterAnswer, press, viewport, offline, check, finish, $, sleep };
}
