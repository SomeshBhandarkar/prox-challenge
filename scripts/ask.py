"""Ask the agent from the terminal. This costs real money: about 0.1 cent a question on haiku. Needs ANTHROPIC_API_KEY in .env.

  .venv/bin/python -m scripts.ask "What's the duty cycle for MIG at 200A on 240V?"
  .venv/bin/python -m scripts.ask "How do I set up TIG?" --model sonnet --open
  .venv/bin/python -m scripts.ask                       (chat: type a question, an empty line quits)

Every picture, diagram, calculator or drawing the agent shows is saved in previews/ (and opened with --open).
"""
import argparse
import asyncio
import json
import re
import sys
import webbrowser
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock, ToolUseBlock

from app.agent import DEFAULT_BUDGET_USD, make_options, require_api_key, resolve_model
from app.knowledge import ROOT
from app.show import PREFIX, render_show
from scripts.preview import artifact_host

PREVIEWS = ROOT / "previews"
MAX_QUESTION_CHARS = 2000  # a pasted wall of text would cost real money
DEFAULT_CAPS = {"claude-haiku-5-5": 0.10, "claude-sonnet-5-5": 0.30}  # per run, in dollars; anything else gets the app default
STOPPED = {
    "error_max_budget_usd": "It hit the spending cap (raise it with --cap).",
    "error_max_turns": "It hit the turn limit before it could finish.",
}
HINTS = {"authentication_failed": "Check ANTHROPIC_API_KEY in .env.", "billing_error": "Check the credit balance on your Anthropic account.",
         "rate_limit": "Rate limited: wait a moment and try again."}


def _short(value, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


class Runner:
    """Prints what the agent does. Collects nothing: output goes to `out` (print) so tests can read it."""

    def __init__(self, previews: Path = PREVIEWS, open_pages: bool = False, out=print, opener=webbrowser.open):
        self.previews, self.open_pages, self.out, self.opener = previews, open_pages, out, opener
        self.turn = 0
        self.pages = 0
        self.last_cost: float | None = None

    def _save(self, shown: dict) -> Path:
        self.pages += 1
        self.previews.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", str(shown.get("identifier") or shown["tool"]).lower()).strip("-")[:40] or "page"
        path = self.previews / f"ask-{self.turn:02d}-{self.pages}-{slug}.html"
        path.write_text(artifact_host(shown["html"]) if shown["kind"] == "artifact" else shown["html"], encoding="utf-8")
        return path

    def _open(self, path: Path) -> None:
        if self.open_pages:
            self.opener(path.resolve().as_uri())

    def show(self, block: ToolUseBlock) -> None:
        shown = render_show(block.name, block.input)
        if shown is None:
            return
        if shown["kind"] == "figure":
            self.out(f"  [FIGURE SHOWN] {shown['caption']} ({shown['source']})\n                 {shown['path']}")
            self._open(Path(shown["path"]))
        elif shown["kind"] in ("widget", "artifact"):
            path = self._save(shown)
            label = "ARTIFACT" if shown["kind"] == "artifact" else "WIDGET"
            self.out(f"  [{label} SHOWN] {shown['title']}\n                 {path}" + ("" if self.open_pages else "   (add --open to open it)"))
            self._open(path)
        else:
            self.out(f"  [SHOW FAILED] {shown['message']}")

    def handle(self, message) -> None:
        if isinstance(message, AssistantMessage):
            if message.error:
                self.out(f"  [error] {message.error}. {HINTS.get(message.error, '')}".rstrip())
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    self.out(f"  [tool] {block.name.removeprefix(PREFIX)} {_short(block.input)}")
                    self.show(block)
                elif isinstance(block, TextBlock) and block.text.strip():
                    self.out(f"\nagent> {block.text.strip()}")
        elif isinstance(message, ResultMessage):
            if message.is_error or message.subtype != "success":
                why = STOPPED.get(message.subtype) or "; ".join(message.errors or []) or message.result or message.subtype
                self.out(f"\n  [stopped] {message.subtype}: {why}")
            self.out(self._cost_line(message))

    def _cost_line(self, message: ResultMessage) -> str:
        cost = message.total_cost_usd
        if cost is None:
            return "  [cost] not reported"
        delta, self.last_cost = (None if self.last_cost is None else cost - self.last_cost), cost
        if delta is None:
            return f"  [cost] SDK reports ${cost:.4f}"
        if delta >= 0:
            return f"  [cost] SDK reports ${cost:.4f} (+${delta:.4f} since the last answer)"
        return f"  [cost] SDK reports ${cost:.4f} (lower than the last answer, so it is a per-answer figure)"


async def ask(client, question: str, runner: Runner) -> None:
    if len(question) > MAX_QUESTION_CHARS:
        runner.out(f"That question is {len(question)} characters; the limit is {MAX_QUESTION_CHARS}. Nothing was sent.")
        return
    runner.turn += 1
    await client.query(question)
    async for message in client.receive_response():
        runner.handle(message)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="scripts.ask", description="Ask the Vulcan OmniPro 220 agent a question.")
    p.add_argument("question", nargs="*", help="what to ask; leave empty to chat")
    p.add_argument("--model", default="haiku", help="haiku (cheapest, default), sonnet or opus")
    p.add_argument("--open", action="store_true", help="open pictures, widgets and drawings in your browser")
    p.add_argument("--cap", type=float, default=None, help="spending cap in dollars for this run (haiku 0.10, sonnet 0.30, opus 0.50)")
    args = p.parse_args(argv)
    try:
        args.model_id = resolve_model(args.model)
    except ValueError as e:
        p.error(str(e))
    if args.cap is None:
        args.cap = DEFAULT_CAPS.get(args.model_id, DEFAULT_BUDGET_USD)
    if not args.cap > 0:
        p.error("--cap must be a positive number of dollars")
    return args


async def run(args: argparse.Namespace, client_factory=ClaudeSDKClient, read=input, out=print, previews: Path = PREVIEWS) -> None:
    require_api_key()
    runner = Runner(previews, args.open, out)
    async with client_factory(options=make_options(args.model_id, args.cap)) as client:
        if args.question:
            await ask(client, " ".join(args.question), runner)
            return
        out(f"Ask about the welder ({args.model_id}, cap ${args.cap:.2f}). An empty line quits.")
        while True:
            try:
                question = read("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question or question.lower() in ("exit", "quit"):
                break
            await ask(client, question, runner)


def main() -> None:
    args = parse_args(sys.argv[1:])
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
