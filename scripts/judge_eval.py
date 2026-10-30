"""How good is the fact-checker (app/judge.py)? Feed it labelled sentences and count what it gets right. COSTS A LITTLE MONEY (one small-model call per round).

    .venv/bin/python -m scripts.judge_eval                    one round on the 32 sentences (15 beyond the manual, 17 from it) in evals/judge_cases.json
    .venv/bin/python -m scripts.judge_eval --rounds 3         three rounds, each in a different order (is it consistent?)

The cases are real sentences from earlier Sonnet answers: 15 that go beyond the manual (each read and confirmed) and 17 that restate it. The score that matters:
  caught   = how many of the sentences beyond the manual it objects to (we want all of them)
  wrongly  = how many correct sentences it objects to (we want none: a checker that rejects good answers is a bad checker)
"""
import argparse
import asyncio
import json
import random

from app.knowledge import ROOT
from app.judge import check_with_model

CASES = ROOT / "evals" / "judge_cases.json"


def load_cases(path=CASES) -> tuple[list, list]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [c["sentence"] for c in data["unsupported"]], [c["sentence"] for c in data["supported"]]


def build_answer(unsupported: list, supported: list, seed: int = 0) -> str:
    """All the sentences as one 'answer' (one per line, shuffled), so a single call judges every one of them."""
    allx = unsupported + supported
    random.Random(seed).shuffle(allx)
    return "\n".join(allx)


def score(flagged: set, unsupported: list, supported: list) -> dict:
    caught = [s for s in unsupported if s in flagged]
    wrongly = [s for s in supported if s in flagged]
    return {"caught": len(caught), "of_unsupported": len(unsupported), "missed": [s for s in unsupported if s not in flagged],
            "wrongly_rejected": len(wrongly), "of_supported": len(supported), "wrongly_rejected_sentences": wrongly}


async def run_round(unsupported, supported, seed, judge) -> dict | None:
    answer = build_answer(unsupported, supported, seed)
    found = await judge(answer, "Judge each sentence on its own.")
    if found is None:
        return None
    return score({f.sentence for f in found}, unsupported, supported)


def report(rounds: list) -> str:
    lines = []
    for n, r in enumerate(rounds, 1):
        if r is None:
            lines.append(f"round {n}: the checker could not be run (no network, no credits, or an unreadable reply)")
            continue
        lines.append(f"round {n}: caught {r['caught']} of {r['of_unsupported']} sentences beyond the manual; wrongly rejected {r['wrongly_rejected']} of {r['of_supported']} correct ones")
        for s in r["missed"]:
            lines.append(f"    MISSED (outside the manual, not flagged): {s}")
        for s in r["wrongly_rejected_sentences"]:
            lines.append(f"    WRONGLY REJECTED (it is in the manual): {s}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--model", default=None, help="fact-checker model to measure: haiku (the app's default), sonnet or opus")
    a = ap.parse_args(argv)
    from app.agent import require_api_key
    require_api_key()
    unsupported, supported = load_cases()
    from app.judge import JUDGE_MODEL, build_judge_options
    options = build_judge_options(a.model or JUDGE_MODEL)

    async def judge(answer, question):
        return await check_with_model(answer, question, options=options)

    print(f"fact-checker model: {options.model}")
    rounds = [asyncio.run(run_round(unsupported, supported, seed, judge)) for seed in range(a.rounds)]
    print(report(rounds))


if __name__ == "__main__":
    main()
