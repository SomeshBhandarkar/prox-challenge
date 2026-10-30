// Real-browser checks of the voice buttons (speak a question, hear an answer), using a SIMULATED microphone and speaker, against the
// demo server (no API key, no cost). Real speech accuracy cannot be tested this way: try the microphone by hand in Chrome for that.
//   .venv/bin/python -m scripts.dev_server --port 8135 &
//   node scripts/browser/voice_check.mjs /tmp/voice-checks
import { openBrowser, sleep } from './cdp.mjs';

const SITE = process.env.SITE || 'http://localhost:8135/';
const b = await openBrowser({ site: SITE, out: process.argv[2] || '/tmp/voice-checks' });
const { ev, waitFor, expect, load, ask, idleAfterAnswer, viewport, check, finish, $, shot } = b;

// what the page sees instead of a real microphone and speaker
const SUPPORTED = `(() => {
  const S = window.__speech = { instances: [], spoken: [], cancelled: 0, delay: 20 };
  class FakeRecognition {
    constructor() { S.instances.push(this); }
    start() { this.started = true; }
    stop() { this.stopped = true; setTimeout(() => this.onend && this.onend(), 0); }
    abort() { this.aborted = true; }
    say(text) { this.onresult && this.onresult({ results: [[{ transcript: text }]] }); }
    fail(code) { this.onerror && this.onerror({ error: code }); this.onend && this.onend(); }
  }
  window.webkitSpeechRecognition = FakeRecognition;
  window.SpeechRecognition = FakeRecognition;
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
    speak(u) { S.spoken.push(u.text); setTimeout(() => u.onend && u.onend(), S.delay); },
    cancel() { S.cancelled++; },
  } });
})();`;
const UNSUPPORTED = `(() => {
  Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined });
  Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: undefined });
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
})();`;

const inst = 'window.__speech.instances[window.__speech.instances.length - 1]';
const status = () => ev(`${$('status-text')}.textContent`);
const idle = `!${$('mic')}.classList.contains('listening')`;
const setBox = (v) => ev(`(() => { const i = ${$('input')}; i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('input')); })()`);
const tapMic = () => ev(`${$('mic')}.click()`);

// =========================== a browser WITH speech support ===========================
await viewport(1100, 800);
await load(SUPPORTED);
check('the mic button is visible when speech recognition exists', await ev(`${$('mic')}.hidden === false`));
check('the mic starts idle (not pressed)', await ev(`${$('mic')}.getAttribute('aria-pressed') === 'false'`));

await tapMic();
check('tapping the mic starts listening', await ev(`${inst}.started === true && ${$('mic')}.classList.contains('listening')`));
check('the status line says it is listening', (await status()).startsWith('Listening... tap the microphone'), await status());
check('the mic is announced as "Stop listening" and pressed', await ev(`${$('mic')}.getAttribute('aria-label') === 'Stop listening' && ${$('mic')}.getAttribute('aria-pressed') === 'true'`));
await shot('1-listening');
await ev(`${inst}.say('what is the duty cycle for TIG')`);
check('what was heard appears in the question box', await ev(`${$('input')}.value === 'what is the duty cycle for TIG'`));
check('Send becomes available', await ev(`${$('send')}.disabled === false`));
check('nothing was sent by voice alone', await ev(`document.querySelectorAll('.msg.user').length === 0`));
await ev(`${inst}.say('what is the duty cycle for TIG at 125 amps')`);
check('a longer result REPLACES the earlier text (no duplication)', await ev(`${$('input')}.value === 'what is the duty cycle for TIG at 125 amps'`));
await tapMic();
await expect('tapping again stops listening', idle);
check('the status line is back to Ready', (await status()) === 'Ready when you are.', await status());
check('the box keeps what was heard and has focus for editing', await ev(`${$('input')}.value.endsWith('125 amps') && document.activeElement === ${$('input')}`));

await setBox('hello');
await tapMic();
await ev(`${inst}.say('world')`);
check('speech is added after text already typed', await ev(`${$('input')}.value === 'hello world'`));
await ev(`${inst}.stop()`); await expect('idle again', idle);

await tapMic();
await ev(`${inst}.say('a'.repeat(3000))`);
check('a very long speech is cut at the 2000-character limit', await ev(`${$('input')}.value.length === 2000`));
await ev(`${inst}.stop()`); await expect('idle again', idle);
await setBox('');

for (const [code, expected] of [['not-allowed', 'microphone is blocked'], ['service-not-allowed', 'microphone is blocked'], ['no-speech', 'didn’t hear anything'],
  ['audio-capture', 'couldn’t find a microphone'], ['network', 'internet connection'], ['weird', 'microphone stopped (weird)']]) {
  await tapMic();
  await ev(`${inst}.fail(${JSON.stringify(code)})`);
  const s = await status();
  check(`error "${code}" shows a plain message`, s.includes(expected) && !s.includes('...'), s);
  check(`  ...and the mic returns to idle with the dot not pulsing (${code})`, await ev(`${idle} && !${$('status-dot')}.classList.contains('active')`));
}
await tapMic();
await ev(`${inst}.fail('aborted')`);
check('"aborted" is silent: no error message, back to Ready', (await status()) === 'Ready when you are.' && await ev(idle), await status());

// sending while listening: the question goes, listening is cancelled, late words are ignored
await tapMic();
await ev(`${inst}.say('duty cycle MIG at 200A')`);
await ev(`${$('composer')}.requestSubmit()`);
await waitFor(`document.querySelectorAll('.msg.user').length === 1`, 'the question to be sent');
check('sending while listening cancels the recognizer', await ev(`${inst}.aborted === true && ${idle}`));
await ev(`${inst}.say('late words that must be ignored')`);
check('late words never refill the box', await ev(`${$('input')}.value === ''`));
await idleAfterAnswer(1);
check('the answer has a speaker button', await ev(`document.querySelectorAll('.listen').length === 1`));
check('the mic is usable again after the answer', await ev(`${$('mic')}.disabled === false`));
await shot('2-answer-with-speaker');

await ask('slow one');
await sleep(250);
check('the mic is disabled while an answer is being written', await ev(`${$('mic')}.disabled === true`));
await idleAfterAnswer(2, 15000);
check('the mic is enabled again afterwards', await ev(`${$('mic')}.disabled === false`));

// reading aloud
await ev(`window.__speech.delay = 1500`);
await ev(`document.querySelectorAll('.listen')[0].click()`);
const spoken = await ev(`window.__speech.spoken.slice()`);
check('the answer is read one sentence at a time, page numbers as words', JSON.stringify(spoken) === JSON.stringify(['At 200A on 240V the MIG duty cycle is 25% (manual page 7, page 19).']), JSON.stringify(spoken));
check('the speaker shows it is reading', await ev(`document.querySelectorAll('.listen')[0].classList.contains('reading') && document.querySelectorAll('.listen')[0].getAttribute('aria-label') === 'Stop reading'`));
const before = await ev(`window.__speech.cancelled`);
await ev(`document.querySelectorAll('.listen')[0].click()`);
check('pressing it again stops the reading', await ev(`!document.querySelectorAll('.listen')[0].classList.contains('reading') && window.__speech.cancelled > ${before}`));
await ev(`window.__speech.delay = 20`);
await ev(`document.querySelectorAll('.listen')[0].click()`);
await expect('when the speech ends by itself the button resets', `!document.querySelectorAll('.listen')[0].classList.contains('reading') && document.querySelectorAll('.listen')[0].getAttribute('aria-label') === 'Read this answer aloud'`);

await ev(`window.__speech.delay = 1500`);
await ev(`document.querySelectorAll('.listen')[0].click()`);
const c0 = await ev(`window.__speech.cancelled`);
await ev(`${$('new-chat')}.click()`);
check('New chat stops the speech', await ev(`window.__speech.cancelled > ${c0}`));
check('New chat clears the conversation', await ev(`document.querySelectorAll('.conversation').length === 0`));

await ask('duty cycle please'); await idleAfterAnswer(1);
await ev(`document.querySelectorAll('.listen')[0].click()`);
const c1 = await ev(`window.__speech.cancelled`);
await ask('polarity please');
check('asking a new question stops the speech of the old answer', await ev(`window.__speech.cancelled > ${c1}`));
await idleAfterAnswer(2);

await viewport(390, 844, { mobile: true, dark: true });
await sleep(300);
await tapMic(); await sleep(200);
await shot('3-listening-phone-dark');
check('no sideways scrolling on a phone with the mic button', await ev(`document.documentElement.scrollWidth <= window.innerWidth + 1`));
await ev(`${inst}.stop()`);
check('no JavaScript errors in a browser with speech support', b.errors().length === 0, b.errors()[0]);

// =========================== a browser WITHOUT speech support ===========================
await viewport(1100, 800);
b.events.length = 0;
await load(UNSUPPORTED);
check('without speech support the mic button is not shown', await ev(`getComputedStyle(${$('mic')}).display === 'none'`));
await ask('duty cycle please'); await idleAfterAnswer(1);
check('without speech support there is no speaker button', await ev(`document.querySelectorAll('.listen').length === 0`));
check('the rest of the page works as normal (answer + calculator frame)', await ev(`document.querySelectorAll('iframe').length === 1`));
check('no JavaScript errors in a browser without speech support', b.errors().length === 0, b.errors()[0]);
finish();
