// The manual-only guardrails on the REAL page, in a real browser, against the demo server started with --guard (pretend model and pretend
// fact-checker, no API key, no cost). Proves: what the person sees contains nothing the guard objected to.
//   scripts/browser/run.sh guard_flow
import { openBrowser } from './cdp.mjs';

const SITE = process.env.SITE || 'http://localhost:8135/';
const b = await openBrowser({ site: SITE, out: process.argv[2] || '/tmp/guard-checks' });
const { ev, load, ask, idleAfterAnswer, check, finish, $, shot } = b;
const text = () => ev(`Array.from(document.querySelectorAll('.conversation:last-of-type .answer-text'), (n) => n.innerText).join('\\n')`);
const newChat = async () => { await ev(`${$('new-chat')}.click()`); await b.waitFor(`document.querySelectorAll('.conversation').length === 0`, 'the chat to clear'); };

await load();

await ask('outside please'); await idleAfterAnswer(1);
let t = await text();
check('a draft with "General advice, not from the manual" is never shown', !/general advice|not from the manual|current range/i.test(t), t.slice(0, 160));
check('...and the manual-based facts of that answer are shown', t.includes('25%') && t.includes('manual p.7') && t.includes('Power Switch ON'));
check('...as ONE answer (the rewrite is invisible)', await ev(`document.querySelectorAll('.conversation:last-of-type .msg.assistant').length === 1 && document.querySelectorAll('.msg.user').length === 1`));
await shot('1-outside-rewritten');

await newChat();
await ask('stubborn please'); await idleAfterAnswer(1);
t = await text();
check('a model that repeats the outside advice anyway has that sentence removed', !/general advice|current range/i.test(t) && t.includes('25%') && t.includes('fan can cool it'), t.slice(0, 160));

await newChat();
await ask('nothing guard please'); await idleAfterAnswer(1);
t = await text();
check('an answer with nothing trustworthy becomes "There is no specific information in the manual for this kind of problem."', t.startsWith('There is no specific information in the manual for this kind of problem.'), t);
check('...with the manual\'s own support number', t.includes('1-800-444-3353'));
check('...as plain text, not an error box', await ev(`!document.querySelector('.conversation:last-of-type .callout')`));
await shot('2-fallback');

await newChat();
await ask('judged please'); await idleAfterAnswer(1);
t = await text();
check('a sentence only the fact-checker model objects to is removed', !/small spool|scrap/i.test(t) && t.includes('25%'), t.slice(0, 200));

await newChat();
await ask('duty cycle please'); await idleAfterAnswer(1);
t = await text();
check('a clean manual-based answer passes untouched and still gets its calculator', t.includes('25%') && await ev(`document.querySelectorAll('iframe.embed').length === 1`), t.slice(0, 120));

const errs = b.errors(/Failed to load resource|net::/);
check('no JavaScript errors', errs.length === 0, errs[0]);
finish();
