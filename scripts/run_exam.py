"""Run exam questions through the agent and save the transcripts. COSTS MONEY (about 0.3 cent a question on haiku): ask first.

  .venv/bin/python -m scripts.run_exam --per-category 1        one question from each category (hold-outs left out)
  .venv/bin/python -m scripts.run_exam --ids Q01,Q05,Q70       exactly these
  .venv/bin/python -m scripts.run_exam --tier 1                every tier-1 question
Hold-out questions (the ones we never tune on) run only with --include-holdouts.
Results go to evals/results/ (every answer in a .json, a short table in a .md). Nothing opens in your browser.
The automatic flags are only hints: a person reads the flagged answers.
"""
import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock, ToolUseBlock

from app.agent import make_options, require_api_key, resolve_model
from app import answering
from app.judge import check_with_model
from app.knowledge import ROOT
from app.show import PREFIX, render_show
from app import guard
from scripts import conditions
from scripts.conditions import NARRATION, PHANTOM, repeats  # noqa: F401  (tests and callers use these names from here)

QUESTIONS = ROOT / "evals" / "questions.json"
GUARDRAIL_QUESTIONS = ROOT / "evals" / "questions_guardrails.json"
RESULTS = ROOT / "evals" / "results"
STOP = {"the", "and", "for", "that", "this", "with", "are", "not", "you", "can", "from", "your", "has", "have", "was", "its", "than"}


def load_questions(path=QUESTIONS) -> list:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def pick(questions, ids=None, tier=None, per_category=None, include_holdouts=False) -> list:
    chosen = [q for q in questions if (include_holdouts or not q.get("holdout"))]
    if ids:
        wanted = {i.strip().upper() for i in ids}
        chosen = [q for q in questions if q["id"] in wanted]  # asking for an id by name is allowed even for a hold-out
    if tier:
        chosen = [q for q in chosen if q["tier"] == tier]
    if per_category:
        seen, out = {}, []
        for q in sorted(chosen, key=lambda q: q["id"]):
            if seen.get(q["category"], 0) < per_category:
                seen[q["category"]] = seen.get(q["category"], 0) + 1
                out.append(q)
        chosen = out
    return sorted(chosen, key=lambda q: q["id"])


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower().replace("**", "").replace("–", "-").replace("’", "'"))


def _words(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9./%-]*", _norm(text)) if (len(w) > 3 and w not in STOP) or any(c.isdigit() for c in w)]


def item_found(answer: str, item: str) -> bool:
    """A must_include item counts as present if an ' or ' alternative appears word for word, or 75% of its content words do."""
    text = _norm(answer)
    for alt in re.split(r"\s+or\s+", _norm(item)):
        alt = alt.strip(" .")
        if alt and alt in text:
            return True
        words = _words(alt)
        if words and sum(w in text for w in words) / len(words) >= 0.75:
            return True
    return False


def check_answer(answer: str, q: dict) -> dict:
    text = _norm(answer)
    return {
        "missing": [i for i in q.get("must_include", []) if not item_found(answer, i)],
        "forbidden": [i for i in q.get("must_not_include", []) if _norm(i) in text],
        "asked_question": "?" in answer,
        "should_clarify": bool(q.get("should_clarify")),
    }


def brief(shown: dict) -> dict:
    keep = ("kind", "tool", "id", "source", "title", "identifier", "message")
    return {k: shown[k] for k in keep if k in shown}


OUT_OF_CREDITS = "out_of_credits"
CREDIT_WORDS = re.compile(r"credit balance|out of credit|insufficient (?:credit|funds)", re.I)


async def ask_turn(client, text: str) -> dict:
    tools, shown, answer, cost, stop, seen = [], [], [], None, "success", set()
    await client.query(text)
    async for m in client.receive_response():
        if isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, ToolUseBlock):
                    tools.append({"tool": b.name.removeprefix(PREFIX), "input": b.input})
                    s = render_show(b.name, b.input)
                    key = (b.name, json.dumps(b.input, sort_keys=True, default=str))
                    if s is not None and not s.get("silent") and key not in seen:  # what the website would show: no repeats, no placeholders
                        seen.add(key)
                        shown.append(brief(s))
                elif isinstance(b, TextBlock) and b.text.strip():
                    answer.append(b.text.strip())
        elif isinstance(m, ResultMessage):
            cost, stop = m.total_cost_usd, m.subtype
    return {"question": text, "answer": "\n".join(answer), "texts": answer, "tools": tools, "shown": shown, "cost": cost, "stop": stop}


async def ask_turn_pipeline(client, text: str, embeds, judge) -> dict:
    """The same turn, but through the server's own answer path (app/answering.py): draft, manual-only check, ONE rewrite, removal, fallback.
    The result is what the person would read; `pipeline` records what the first draft did wrong."""
    from app.server import events_for
    tools, shown, texts, events = [], [], [], []

    def spy(message, embeds_, seen=None):   # the server's event maker, plus a note of every tool the model called
        if isinstance(message, AssistantMessage):
            tools.extend({"tool": b.name.removeprefix(PREFIX), "input": b.input} for b in message.content if isinstance(b, ToolUseBlock))
        return events_for(message, embeds_, seen)

    def emit(event, data):
        events.append((event, data))
        if event == "text":
            texts.append(data["text"].strip())
        elif event == "show":
            shown.append(brief(data))

    out = await answering.answer(client, text, embeds, emit, spy, judge=judge, guard_text=True)
    done = next((d for e, d in reversed(events) if e == "done"), {}) or {}
    errors = [d.get("code") for e, d in events if e == "error"]
    return {"question": text, "answer": "\n".join(texts), "texts": texts, "tools": tools, "shown": shown, "cost": done.get("cost_usd"),
            "stop": "success" if done.get("ok") else (errors[0] if errors else "error"),
            "pipeline": {"first_findings": [{"kind": f.kind, "sentence": f.sentence, "detail": f.detail} for f in out.first_findings],
                         "rewritten": out.rewritten, "phantom_nudge": out.phantom_nudge, "removed": out.removed, "fallback": out.fallback,
                         "judge_used": out.judge_used}}


def turn_specs(q: dict) -> list:
    """The first question plus each follow-up. A follow-up in the exam file is an object with its own question and checks."""
    specs = [{"question": q["question"], "must_include": q.get("must_include", []), "must_not_include": q.get("must_not_include", []),
              "should_clarify": q.get("should_clarify")}]
    for f in q.get("follow_ups") or []:
        specs.append(f if isinstance(f, dict) else {"question": str(f)})
    return specs


async def run_question(q: dict, make_client, judge=None, pipeline: bool = False) -> dict:
    started, turns, specs = time.time(), [], turn_specs(q)
    try:
        async with make_client() as client:
            from app.server import Embeds
            embeds = Embeds()
            for spec in specs:
                turns.append(await (ask_turn_pipeline(client, spec["question"], embeds, judge) if pipeline else ask_turn(client, spec["question"])))
        error = None
    except Exception as e:  # noqa: BLE001  one bad question must not end the whole run
        error = f"{type(e).__name__}: {str(e)[:200]}"
    if error is None and any(CREDIT_WORDS.search(turn["answer"]) and not turn["cost"] for turn in turns):
        error = OUT_OF_CREDITS
    checks = {"missing": [], "forbidden": [], "asked_question": False, "should_clarify": bool(q.get("should_clarify"))}
    for n, (spec, turn) in enumerate(zip(specs, turns), 1):  # each answer is checked against its own question's expectations
        c = check_answer(turn["answer"], spec)
        tag = "" if n == 1 else f"turn {n}: "
        checks["missing"] += [tag + i for i in c["missing"]]
        checks["forbidden"] += [tag + i for i in c["forbidden"]]
        checks["asked_question"] = checks["asked_question"] or (n == 1 and c["asked_question"])
    for turn in turns:   # the manual-only guard on every answer: what it objects to, and what the person would finally see
        report = guard.check(turn["answer"], turn["question"])
        turn["guard"] = {"findings": [{"kind": f.kind, "sentence": f.sentence, "detail": f.detail} for f in report.findings]}
        turn["enforced"], _ = guard.enforce(turn["answer"], turn["question"])
        turn["fallback"] = turn["enforced"].startswith(guard.FALLBACK)
        if pipeline:   # what the person reads has already been through the whole pipeline: this is the independent final check of it
            turn["enforced"], turn["fallback"] = turn["answer"], turn["pipeline"]["fallback"] or turn["answer"].startswith(guard.FALLBACK)
        if judge is not None:
            found = await judge(turn["answer"], turn["question"])
            turn["checker"] = None if found is None else [{"sentence": f.sentence, "detail": f.detail} for f in found]
    return {
        "id": q["id"], "category": q["category"], "tier": q["tier"], "expected_visual": q.get("expected_visual"),
        "expected_answer": q["expected_answer"], "turns": turns, "checks": checks, "error": error,
        "conditions": condition_results(q, turns),
        "cost": round(max((t["cost"] or 0 for t in turns), default=0), 4), "seconds": round(time.time() - started, 1),   # the SDK's figure is a running total per conversation
        "pipeline": pipeline,
    }


def condition_results(q: dict, turns: list) -> dict:
    """{condition id: [status, reason]} for a whole question: it fails if ANY turn fails, passes if some turn passes and none fails."""
    out = {}
    for cid, _, detector in conditions.CONDITIONS:
        results = [detector(q, t) for t in turns] or [(conditions.NA, "no answer")]
        fail = next((r for r in results if r[0] == conditions.FAIL), None)
        ok = next((r for r in results if r[0] == conditions.PASS), None)
        out[cid] = list(fail or ok or results[0])
    return out


def flags(r: dict) -> list:
    c, out = r["checks"], []
    if r["error"]:
        out.append("ERROR")
    if c["missing"]:
        out.append(f"MISSING {len(c['missing'])}")
    if c["forbidden"]:
        out.append(f"FORBIDDEN {len(c['forbidden'])}")
    if c["should_clarify"] and not c["asked_question"]:
        out.append("NO-QUESTION")
    turns = r.get("turns", [])
    if any(repeats(t.get("texts", [])) for t in turns):
        out.append("REPEATS")
    if any(NARRATION.search(t.get("answer", "")) for t in turns):
        out.append("NARRATES")
    if any(PHANTOM.search(t.get("answer", "")) and not t.get("shown") for t in turns):
        out.append("PHANTOM")
    if any((t.get("guard") or {}).get("findings") for t in turns):
        out.append("OUTSIDE")   # the manual-only guard objected to something in this answer (see turns[].guard in the .json)
    if (r.get("conditions") or {}).get("C06", [None])[0] == "fail":
        out.append("NO-FALLBACK")
    return out


def pipeline_note(r: dict) -> str:
    """One short cell: what the server's pipeline had to do to the first draft (only for --pipeline runs)."""
    notes = []
    for t in r["turns"]:
        p = t.get("pipeline") or {}
        if p.get("fallback"):
            notes.append("fallback")
        elif p.get("rewritten"):
            notes.append(f"rewritten ({len(p.get('first_findings', []))} objections" + (f", {len(p['removed'])} sentences removed" if p.get("removed") else "") + ")")
        elif p.get("phantom_nudge"):
            notes.append("picture follow-up")
        else:
            notes.append("clean first draft")
    return "; ".join(notes) or "-"


def summary_markdown(results: list, model: str) -> str:
    piped = any(r.get("pipeline") for r in results)
    head = "| id | category | tools | shown | flags | $ |" + (" first draft |" if piped else "")
    rows = [head, "|---|---|---|---|---|---|" + ("---|" if piped else "")]
    for r in results:
        tools = ", ".join(sorted({t["tool"] for turn in r["turns"] for t in turn["tools"]})) or "-"
        shown = ", ".join(s.get("id") or s.get("title") or s.get("kind", "?") for turn in r["turns"] for s in turn["shown"]) or "-"
        rows.append(f"| {r['id']} | {r['category']} | {tools} | {shown} | {'; '.join(flags(r)) or 'ok'} | {r['cost']:.4f} |" + (f" {pipeline_note(r)} |" if piped else ""))
    total = sum(r["cost"] for r in results)
    flagged = sum(1 for r in results if flags(r))
    table = conditions.tabulate([(r["id"], {k: tuple(v) for k, v in (r.get("conditions") or {}).items()}) for r in results if r.get("conditions")])
    stats = ""
    if piped:
        turns = [t for r in results for t in r["turns"] if t.get("pipeline")]
        bad = sum(1 for t in turns if t["pipeline"]["first_findings"])
        stats = (f"## What the server's pipeline did (what the person reads is the FINAL text)\n\n"
                 f"{len(turns)} answers: the first draft was objected to in {bad}; rewritten {sum(1 for t in turns if t['pipeline']['rewritten'])}; "
                 f"sentences removed from {sum(1 for t in turns if t['pipeline']['removed'])}; ended as the fallback sentence {sum(1 for t in turns if t['pipeline']['fallback'])}; "
                 f"fact-checker ran on {sum(1 for t in turns if t['pipeline']['judge_used'])}.\n\n")
    return (f"# Exam run on {model}{' (through the server pipeline)' if piped else ''}: {len(results)} questions, {flagged} flagged for review, about ${total:.3f}\n\n"
            "Flags are automatic hints (word matching), not a grade: read the flagged answers in the .json.\n\n" + "\n".join(rows) + "\n\n" + stats +
            "## Conditions (the rules the assistant was told to follow)\n\n" + "\n".join(table) + "\n")


async def run_all(questions: list, make_client, total_cap: float, out=print, judge=None, pipeline: bool = False) -> list:
    results, spent = [], 0.0
    for q in questions:
        if spent >= total_cap:
            out(f"Stopped before {q['id']}: the ${total_cap:.2f} total cap is used up.")
            break
        r = await run_question(q, make_client, judge, pipeline)
        if r["error"] == OUT_OF_CREDITS:   # not an answer: the account is empty, and every later question would fail the same way
            out(f"Stopped at {q['id']}: the Anthropic account is out of credits. Add credits, then run again starting from {q['id']}.")
            break
        spent += r["cost"]
        results.append(r)
        out(f"{r['id']:>4} {r['category']:<18} ${r['cost']:.4f} {r['seconds']:>5.1f}s  {'; '.join(flags(r)) or 'ok'}")
    return results


def parse_args(argv):
    p = argparse.ArgumentParser(prog="scripts.run_exam", description="Run exam questions through the agent (costs money).")
    p.add_argument("--model", default="haiku")
    p.add_argument("--ids", help="comma-separated ids, e.g. Q01,Q05")
    p.add_argument("--tier", type=int, choices=(1, 2, 3), help="3 = the guardrail questions (evals/questions_guardrails.json)")
    p.add_argument("--file", default=None, help="another questions file (default: evals/questions.json, or the guardrail set with --tier 3)")
    p.add_argument("--judge", action="store_true", help="also run the fact-checker model on every answer (about half a cent each)")
    p.add_argument("--pipeline", action="store_true", help="go through the server's whole answer path (draft, check, one rewrite, removal, fallback) and score what the person would read")
    p.add_argument("--per-category", type=int, default=None, help="this many questions from each category")
    p.add_argument("--include-holdouts", action="store_true")
    p.add_argument("--cap", type=float, default=0.05, help="spending cap per question in dollars")
    p.add_argument("--total-cap", type=float, default=0.30, help="stop the whole run after this many dollars")
    a = p.parse_args(argv)
    try:
        a.model_id = resolve_model(a.model)
    except ValueError as e:
        p.error(str(e))
    if not (a.cap > 0 and a.total_cap > 0):
        p.error("--cap and --total-cap must be positive")
    if not (a.ids or a.tier or a.per_category):
        p.error("choose what to run: --ids, --tier or --per-category")
    return a


def main() -> None:
    a = parse_args(sys.argv[1:])
    path = ROOT / a.file if a.file else (GUARDRAIL_QUESTIONS if a.tier == 3 else QUESTIONS)
    questions = pick(load_questions(path), a.ids.split(",") if a.ids else None, a.tier, a.per_category, a.include_holdouts)
    if not questions:
        sys.exit("No questions match.")
    require_api_key()
    print(f"Running {len(questions)} questions on {a.model_id} (cap ${a.cap:.2f} each, ${a.total_cap:.2f} total). Nothing opens in your browser.")
    judge = check_with_model if a.judge else None
    results = asyncio.run(run_all(questions, lambda: ClaudeSDKClient(options=make_options(a.model_id, a.cap)), a.total_cap, judge=judge, pipeline=a.pipeline))
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}-{a.model}{'-pipeline' if a.pipeline else ''}"
    (RESULTS / f"{stamp}.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    (RESULTS / f"{stamp}.md").write_text(summary_markdown(results, a.model_id), encoding="utf-8")
    print(f"\nSaved evals/results/{stamp}.json and .md")


if __name__ == "__main__":
    main()
