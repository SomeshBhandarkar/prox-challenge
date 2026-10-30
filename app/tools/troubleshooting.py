"""Exact lookups over the manual's troubleshooting tables (pp 42-44). Pure functions: no model, no guessing."""
from app.knowledge import TROUBLESHOOTING

SECTIONS = {s["id"]: s for s in TROUBLESHOOTING["sections"]}
PROBLEMS = {p["id"]: {**p, "section": s["id"]} for s in TROUBLESHOOTING["sections"] for p in s["problems"]}


def get_troubleshooting(problem_id) -> dict:
    problem = PROBLEMS.get(problem_id) if isinstance(problem_id, str) else None
    if problem is None:
        return {"found": False, "message": f"No troubleshooting problem '{problem_id}'. Valid ids: {sorted(PROBLEMS)}"}
    section = SECTIONS[problem["section"]]
    return {
        "found": True,
        "id": problem["id"],
        "problem": problem["problem"],
        "section": section["short"],
        "page": problem["page"],
        "important": section["important"],
        "steps": problem["steps"],
        "footer_safety": TROUBLESHOOTING["footer_safety"],
        "support_phone": TROUBLESHOOTING["support_phone"],
        "mig_only_note": TROUBLESHOOTING["mig_only_note"],
    }


def catalog_for_prompt() -> str:
    """One line per problem; goes into Claude's system prompt so it can choose the right id."""
    return "\n".join(
        f"- {p['id']}: {p['problem']} ({SECTIONS[p['section']]['short']}, p.{p['page']})" for p in PROBLEMS.values()
    )
