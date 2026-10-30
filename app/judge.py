"""The fact-checker: a second, small model that reads the manual and says which sentences of an answer the manual does NOT support.

The word-level guard (app/guard.py) catches markers, invented numbers and outside topics, but a sentence like "Buy a small spool first and test it
on scrap" uses only words the manual has, so only something that reads for meaning can catch it. This checker is given ONLY the manual and the
verified data, sees the person's question and the answer split into numbered sentences, and answers with JSON. It is cheap (a small model,
the manual cached) and it never talks to the person. If it cannot run (no network, a bad reply, a timeout) it returns None and the word-level guard
still applies: the checker adds protection, it is never a reason for an answer to fail.
"""
import asyncio
import json
import re

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock

from app.guard import FALLBACK, Finding, points_only, refers_to_support, split_sentences

JUDGE_MODEL = "haiku"
TIMEOUT_SECONDS = 40
MAX_SENTENCES = 80

JUDGE_RULES = """\
You are a strict fact-checker for a product-support assistant that may say ONLY what the owner's manual says. The sources below (the manual text and the \
verified data written from it) are the only truth. You never talk to the person; you only judge the assistant's answer.

You get the person's question and the assistant's answer, split into numbered sentences. For each sentence decide:
- SUPPORTED: its facts, numbers, steps, warnings and page citations are stated in the sources, or are a plain-words restatement of them. Also supported: \
a sentence that only says the manual does not give something; a question, a request for details or an offer to the person ("I need a few details first: tap your answers below"); a greeting or thank-you; a pointer to a picture, table, \
calculator, buttons or tool that is shown to the person ("shown below", "see the picture"); and a sentence that sends the person to the manual's own support line \
(the footer of every page says "For technical questions, please call 1-800-444-3353" and page 1 gives the support email), whatever the question was. \
Judge the facts a sentence states, never the pointer or the referral in it.
- UNSUPPORTED: it adds anything the sources do not say. That includes advice and tips; explanations of WHY something works; typical, recommended or \
"safe" values; comparisons, rankings or "most likely / most common" claims the manual does not make; guesses; definitions from general knowledge; \
descriptions of what a picture looks like when the sources do not say; steps or procedures not in the manual; and any wrong number, page or step.
If the question ends with "[the person attached a photo of their weld]", you cannot see the photo: accept a sentence that says which of the manual's \
weld pictures the photo looks closest to, and judge everything else in the answer as usual.
Rewording is fine; adding is not. Quoting the manual is supported. Arithmetic that only restates the manual's own duty-cycle examples \
(25% means 2-1/2 minutes welding and 7-1/2 minutes resting in 10) is supported. When unsure whether a sentence is in the sources, search them first; \
only mark it unsupported if the sources do not say it.

Reply with JSON only, no other text: {"unsupported": [{"n": 3, "why": "short reason"}]}. If every sentence is supported reply {"unsupported": []}.
"""


def build_judge_options(model: str = JUDGE_MODEL) -> ClaudeAgentOptions:
    from app.agent import prompt_file, resolve_model  # imported here: agent.py imports this package's tools, so keep the import graph one-way
    from app.prompt import reference_for_checker
    return ClaudeAgentOptions(
        model=resolve_model(model),
        system_prompt=prompt_file(JUDGE_RULES + "\n\nSOURCES\n\n" + reference_for_checker()),
        tools=[], allowed_tools=[], setting_sources=[],   # no tools of any kind: it can only read and answer
        max_turns=1, max_budget_usd=0.25,
    )


def _is_fallback(sentence: str) -> bool:
    """The required sentence "There is no specific information in the manual for this kind of problem." claims nothing (the checker once objected to it)."""
    return sentence.strip().rstrip(".! ").lower() == FALLBACK.rstrip(".").lower()


def numbered(answer: str, limit: int = MAX_SENTENCES) -> tuple[str, list]:
    """The answer as numbered sentences (questions, bare pointers, support referrals and the fallback sentence are left out: they claim nothing), and the sentence behind each number."""
    # questions claim nothing; neither does a bare pointer ("the table is shown below") or a referral to the manual's support number
    sentences = [s for s in split_sentences(answer) if not s.endswith("?") and not points_only(s) and not refers_to_support(s) and not _is_fallback(s)][:limit]
    return "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1)), sentences


def parse(reply: str, sentences: list) -> list | None:
    """The findings in a checker reply, or None when the reply cannot be understood."""
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        items = data["unsupported"]
        findings = []
        for item in items:
            n = int(item["n"])
            if 1 <= n <= len(sentences):
                findings.append(Finding("checker", sentences[n - 1], str(item.get("why", "not in the manual"))[:160]))
        return findings
    except (ValueError, KeyError, TypeError):
        return None


async def check_with_model(answer: str, question: str, factory=ClaudeSDKClient, options=None) -> list | None:
    """Ask the checker model. A list of Findings (possibly empty), or None if it could not be asked or answered."""
    listing, sentences = numbered(answer)
    if not sentences:
        return []
    try:
        async def ask() -> str:
            reply = []
            async with factory(options=options or build_judge_options()) as client:
                await client.query(f"QUESTION: {question[:600]}\n\nANSWER, as numbered sentences:\n{listing}")
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        reply += [b.text for b in message.content if isinstance(b, TextBlock)]
                    elif isinstance(message, ResultMessage):
                        break
            return "".join(reply)

        return parse(await asyncio.wait_for(ask(), TIMEOUT_SECONDS), sentences)
    except Exception:  # noqa: BLE001  the checker is an extra layer: any failure just means "no second opinion"
        return None
