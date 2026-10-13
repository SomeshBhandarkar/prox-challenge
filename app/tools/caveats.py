"""The manual's known contradictions and gaps, as text for Claude's system prompt (generated from caveats.json)."""
from app.knowledge import CAVEATS


def inconsistencies_for_prompt() -> str:
    return "\n".join(f"- {c['text']} WHAT TO DO: {c['guidance']}" for c in CAVEATS["known_inconsistencies"])


def not_in_manual_for_prompt() -> str:
    return "\n".join(f"- {c['text']}" for c in CAVEATS["not_in_manual"])
