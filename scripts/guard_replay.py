"""Run the strict guardrails (app/guard.py) over answers that were ALREADY saved by earlier exam runs: no model, no network, no cost.

    .venv/bin/python -m scripts.guard_replay                              all saved results
    .venv/bin/python -m scripts.guard_replay evals/results/*sonnet.json   some of them
    .venv/bin/python -m scripts.guard_replay --show 80                    print up to 80 flagged sentences

It reports, per kind of finding, how many answers the guard would have objected to, and prints the sentences so a person can judge each one:
a sentence that really goes beyond the manual is a catch; a sentence that is in the manual is a false alarm that the guard needs to learn.
"""
import argparse
import glob
import json
from collections import Counter

from app import guard as G


def load(paths):
    for path in paths:
        try:
            rows = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rows, list):
            for r in rows:
                for n, t in enumerate(r.get("turns", [])):
                    yield path.split("/")[-1], r.get("id", "?"), n, t.get("question", ""), t.get("answer", "") or ""


def conditions_report(paths) -> list:
    """Score every saved answer against the conditions (scripts/conditions.py) and return the markdown table."""
    from scripts import conditions as C
    from scripts.run_exam import condition_results
    rows = []
    for path in paths:
        try:
            results = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in results if isinstance(results, list) else []:
            turns = r.get("turns", [])
            for t in turns:
                report = G.check(t.get("answer", "") or "", t.get("question", ""))
                t["guard"] = {"findings": [{"kind": f.kind, "sentence": f.sentence, "detail": f.detail} for f in report.findings]}
            q = {"should_clarify": (r.get("checks") or {}).get("should_clarify"), "expect_fallback": r.get("expect_fallback", False)}
            rows.append((r.get("id", "?"), {k: tuple(v) for k, v in condition_results(q, turns).items()}))
    return [f"{len(rows)} questions scored against {len(C.CONDITIONS)} conditions", ""] + C.tabulate(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", action="store_true", help="score every saved answer against the conditions and print the table")
    ap.add_argument("files", nargs="*", help="result .json files (default: all in evals/results)")
    ap.add_argument("--show", type=int, default=40, help="how many flagged sentences to print")
    ap.add_argument("--kind", choices=["marker", "number", "unsupported", "no_source"], help="only print this kind")
    a = ap.parse_args(argv)
    paths = a.files or sorted(glob.glob("evals/results/*.json"))
    if a.conditions:
        print("\n".join(conditions_report(paths)))
        return
    total = flagged = 0
    kinds, shown = Counter(), 0
    fallbacks = 0
    lines = []
    for fname, qid, turn, question, answer in load(paths):
        if not answer.strip():
            continue
        total += 1
        report = G.check(answer, question)
        if report.ok:
            continue
        flagged += 1
        for f in report.findings:
            kinds[f.kind] += 1
            if (not a.kind or f.kind == a.kind) and shown < a.show:
                shown += 1
                lines.append(f"[{f.kind}] {fname[:15]} {qid} t{turn}: {(f.sentence or '(whole answer)')[:170]}\n        -> {f.detail}")
        if G.enforce(answer, question)[0].startswith(G.FALLBACK):
            fallbacks += 1
    print(f"{total} answers checked, {flagged} would be objected to ({flagged * 100 // max(total, 1)}%), {fallbacks} would end as the 'no specific information' fallback")
    print("findings by kind:", dict(kinds))
    print()
    print("\n".join(lines))


if __name__ == "__main__":
    main()
