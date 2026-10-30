"""How one question is answered, from the model's draft to what the person reads. Used by the website server (and testable on its own).

    1. The model drafts its answer. Pictures, widgets and statuses stream to the page at once (they come from the manual's own pictures and
       verified data); the TEXT is held back until it has been checked.
    2. The word-level guard (app/guard.py) judges the draft; if it is clean, the fact-checker model (app/judge.py) reads it against the manual.
    3. If either objects, the model is asked ONCE to rewrite the whole answer using only the manual. The draft is thrown away, never shown.
    4. The rewrite is checked again. Any sentence still unsupported is removed. If too little is left, the answer is FALLBACK:
       "There is no specific information in the manual for this kind of problem."
    A draft that points at a picture below without having shown one gets the same single follow-up (see app/phantom.py).
"""
from dataclasses import dataclass, field

from app import guard
from app.phantom import FOLLOW_UP as PHANTOM_FOLLOW_UP, points_at_a_picture


@dataclass
class Draft:
    texts: list = field(default_factory=list)
    shows: int = 0
    errored: bool = False
    done: dict | None = None


@dataclass
class Outcome:
    """What happened to one answer: for the exam runner and for tests."""
    first_findings: list = field(default_factory=list)   # what the guard / fact-checker objected to in the first draft
    rewritten: bool = False
    phantom_nudge: bool = False
    removed: list = field(default_factory=list)          # sentences removed from the final answer
    fallback: bool = False
    final_text: str = ""
    judge_used: bool = False

    @property
    def violated(self) -> bool:
        return bool(self.first_findings)


PHOTO_WORDS = "photo looks closest resembles picture"   # words the word-level guard may take as the person's own when they sent a photo
PHOTO_NOTE = " [the person attached a photo of their weld]"   # tells the fact-checker it cannot see the photo


def user_message(text: str, image: dict | None):
    """What the SDK is sent: the plain words, or (with a photo) one streamed user message holding the photo and the words.
    `image` = {"media_type": "image/jpeg", "data": <base64>} and has already been checked by the server."""
    if not image:
        return text

    async def one():
        yield {"type": "user", "message": {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": image["media_type"], "data": image["data"]}},
            {"type": "text", "text": text}]}, "parent_tool_use_id": None}
    return one()


async def collect(client, prompt, embeds, seen: set, state: dict, emit, events_for, on_fatal=lambda: None) -> Draft:
    """Send one prompt (words, or words plus a photo). Pass statuses, pictures and errors on at once; keep the text (and the final "done") for the caller."""
    draft = Draft()
    await client.query(prompt)
    async for sdk_message in client.receive_response():
        for event, data in events_for(sdk_message, embeds, seen):
            if event == "done":
                draft.done = data
                continue
            if event == "error":
                draft.errored = True
                if state["sent_error"] and not data.get("fatal"):
                    continue  # one explanation per answer is enough
                state["sent_error"] = True
                if data.get("fatal"):
                    on_fatal()  # the spending limit stays used up: this conversation is over
            elif event == "text":
                draft.texts.append(data["text"])
                continue
            elif event == "show":
                draft.shows += 1
            emit(event, data)
    return draft


def _forget_text(seen: set) -> None:
    """The rewrite replaces the draft, so the duplicate-text memory must not count the draft as 'already said'."""
    for key in [k for k in seen if k[0] == "text"]:
        seen.discard(key)


async def answer(client, question: str, embeds, emit, events_for, *, judge=None, guard_text: bool = True, on_fatal=lambda: None,
                 outcome: Outcome | None = None, image: dict | None = None) -> Outcome:
    """Answer one question. `emit(event, data)` receives what the page should see; `judge` is an async (answer, question) -> list[Finding] | None.
    guard_text=False skips the manual-only checks (the demo agent's canned replies are not from the manual); the picture follow-up still applies."""
    out = outcome or Outcome()
    seen, state = set(), {"sent_error": False}
    asked = question + " " + PHOTO_WORDS if image else question            # what the word-level guard counts as the person's own words
    asked_judge = question + PHOTO_NOTE if image else question              # what the fact-checker is told
    draft = await collect(client, user_message(question, image), embeds, seen, state, emit, events_for, on_fatal)
    text = "\n\n".join(draft.texts)

    if draft.errored or not draft.done or not draft.done.get("ok") or not text.strip():
        for t in draft.texts:                      # nothing to check: an error already explained itself, or there is no text
            emit("text", {"text": t})
        out.final_text = text
        if draft.done is not None:
            emit("done", draft.done)
        return out

    findings = list(guard.check(text, asked).findings) if guard_text else []
    if guard_text and not findings and judge is not None:
        second = await _ask_judge(judge, text, asked_judge)
        out.judge_used = second is not None
        findings = second or []
    out.first_findings = list(findings)
    phantom = not draft.shows and points_at_a_picture(text)

    final_text, done = text, draft.done
    if findings or phantom:
        if findings:
            request = guard.rewrite_request(guard.Report(findings))
            if phantom:
                request += " Also call the show tool for the picture you mention."
        else:
            request = PHANTOM_FOLLOW_UP
        out.rewritten, out.phantom_nudge = bool(findings), phantom
        if findings:
            _forget_text(seen)
        again = await collect(client, request, embeds, seen, state, emit, events_for, on_fatal)
        done = again.done or done
        if findings:
            replacement = "\n\n".join(again.texts).strip()
            final_text = replacement or text         # a rewrite that wrote nothing: clean up the first draft instead
        elif again.texts:
            final_text = (text + "\n\n" + "\n\n".join(again.texts)).strip()
        # the second opinion on whatever will be shown
        # what was already condemned stays condemned if it is still in the answer; and the rewrite gets its own second opinion
        now = set(guard.split_sentences(final_text))
        extra = [f for f in findings if f.sentence in now]
        if findings and judge is not None and final_text != text:
            extra += [f for f in (await _ask_judge(judge, final_text, asked_judge) or []) if f.sentence not in {e.sentence for e in extra}]
        if guard_text:
            cleaned, report2 = guard.enforce(final_text, asked, extra)
            out.removed = [f.sentence for f in report2.findings if f.sentence]
            out.fallback = cleaned.startswith(guard.FALLBACK)
            final_text = cleaned
    out.final_text = final_text
    if final_text.strip():
        emit("text", {"text": final_text})
    if done is not None:
        emit("done", done)
    return out


async def _ask_judge(judge, text: str, question: str):
    try:
        return await judge(text, question)
    except Exception:  # noqa: BLE001  the fact-checker is an extra layer, never a reason for an answer to fail
        return None
