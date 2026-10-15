"""The locked-down Claude Agent SDK options. One place, so the terminal runner and the website behave the same."""
import math
import os

from claude_agent_sdk import ClaudeAgentOptions
from dotenv import load_dotenv

from app.agent_tools import TOOL_NAMES, server
from app.knowledge import ROOT
from app.prompt import build_system_prompt

load_dotenv(ROOT / ".env")  # a key already in the shell wins over the file

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
DEFAULT_MODEL = "sonnet"  # measured on 6 real conversations (4-8 cents an answer); haiku is about 20x cheaper, opus is stronger but was never run here
MAX_TURNS = 8
DEFAULT_BUDGET_USD = 0.50
KEY_PLACEHOLDER = "your-api-key-here"  # what .env.example ships with


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def resolve_model(name: str | None = None) -> str:
    """'haiku' / 'sonnet' / 'opus' or a full model id. Order: argument, then MODEL in .env, then the default."""
    chosen = _clean(name) or _clean(os.environ.get("MODEL")) or DEFAULT_MODEL
    if chosen.lower() in MODELS:
        return MODELS[chosen.lower()]
    if chosen.lower().startswith("claude-"):
        return chosen
    raise ValueError(f'Unknown model "{chosen[:60]}". Use haiku, sonnet, opus, or a full id like claude-opus-5-5.')


def require_api_key() -> None:
    key = _clean(os.environ.get("ANTHROPIC_API_KEY"))
    if not key or key == KEY_PLACEHOLDER:
        raise SystemExit("ANTHROPIC_API_KEY is missing. Run: cp .env.example .env, then paste your key into .env")


def _budget(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("max_budget_usd must be a positive number of dollars, like 0.50")
    return float(value)


def make_options(model: str | None = None, max_budget_usd: float = DEFAULT_BUDGET_USD) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=resolve_model(model),
        system_prompt=build_system_prompt(),
        tools=[],                       # no built-in tools: no files, no shell, no web
        mcp_servers={"welder": server},
        allowed_tools=TOOL_NAMES,       # only our tools, pre-approved so nothing waits for a click
        setting_sources=[],             # ignore any Claude settings on the reviewer's machine
        max_turns=MAX_TURNS,
        max_budget_usd=_budget(max_budget_usd),
        # no `env=`: it would replace the whole process environment and lose the API key
    )
