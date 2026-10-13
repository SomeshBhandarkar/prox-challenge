"""Run the website with a pretend agent: canned replies, no API key, no cost. For building and testing the page.

    .venv/bin/python -m scripts.dev_server            then open the address it prints

Type one of these words in the chat to see what the page does with it:
  figure  polarity  duty  flowchart  setup  draw  broken  badfigure  placeholder  twice  everything  long  callout  unsafe  slow  limit  budget  crash
The answers are NOT from the manual. They only exercise the page. The real app is:  python3 run.py
"""
import argparse
import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from app import server
from app.server import create_app, find_free_port
from app.show import PREFIX

CHEAT_SHEET = """<h1>Cable cheat sheet (demo)</h1><div id="out"></div>
<script>
var setups = window.MANUAL.polarity.setups, out = document.getElementById('out');
Object.keys(setups).forEach(function (k) {
  var d = document.createElement('div'); d.className = 'card'; d.style.cssText = 'border:1px solid var(--line);padding:8px;margin:6px 0;border-radius:8px';
  d.textContent = k + ': ' + setups[k].cables.map(function (c) { return c.cable + ' -> ' + c.socket; }).join('; ');
  out.appendChild(d);
});
</script>"""
BROKEN = "<h1>Broken demo</h1><p>This drawing throws an error on purpose, to test the one automatic repair.</p><script>nothing.here.exists();</script>"
FIXED = "<h1>Fixed demo</h1><p>This is the second try, and it works: the page asked the assistant to fix it once.</p>"
LONG = ("**Short answer:** it depends on the process.\n\n- First point with a page cite (manual p.14)\n- Second point with `inline code` "
        "and a second cite (manual p.7, p.19)\n- Third point\n\n1. Do this first\n2. Then this\n3. Last, this (Selection chart)\n\n"
        "A second paragraph so the spacing can be checked. " + "It keeps going to test wrapping on a phone. " * 8)
CALLOUTS = ("WARNING (manual p.6): Do not use the welder if the power cord or plug is damaged.\n\nDANGER: The wire and torch are live whenever "
            "the power switch is on.\n\nCAUTION - Let the machine cool before you touch the nozzle.\n\nNOTICE: Do not overtighten the knob (manual p.17).\n\n"
            "> WARNING! TO PREVENT SERIOUS INJURY: Welder is now energized and Open Circuit Voltage is present. (manual p.32)\n\n"
            "| Process | Ground clamp | Torch |\n|---|---|---|\n| TIG | Positive | Negative |\n| Stick | Negative | Positive |\n\nA plain paragraph after the table. "
            "Not a cite: Quick-start guide p.2.")
UNSAFE = ('Here is <script>alert(1)</script> and <img src=x onerror="alert(2)"> and a link '
          '[click](javascript:alert(3)) and **bold** (manual p.99).')


def scenario(text: str) -> list[tuple]:
    """Steps for one question: ("text", s) | ("tool", short_name, input) | ("sleep", seconds) | ("result", subtype) | ("raise", msg)."""
    t = text.lower()
    art = lambda ident, title, code: ("tool", "create_artifact", {"identifier": ident, "type": "html", "title": title, "code": code})  # noqa: E731
    if "reported this error" in t:
        return [("text", "Sorry about that. Here is the fixed version."), art("broken-demo", "Broken demo", FIXED)]
    if "broken" in t:
        return [("text", "Here is a drawing (it has a bug on purpose)."), art("broken-demo", "Broken demo", BROKEN)]
    if "draw" in t:
        return [("text", "Here is the cheat sheet I drew from the manual data."), art("cable-cheat-sheet", "Cable cheat sheet", CHEAT_SHEET)]
    if "placeholder" in t:
        return [("text", "Here is your answer."), ("tool", "create_artifact", {"identifier": "never-used", "type": "html", "title": "noop", "code": "<p>unused</p>"})]
    if "twice" in t:
        return [("tool", "show_figure", {"figure_id": "rating-label"}), ("tool", "show_figure", {"figure_id": "rating-label"}),
                ("tool", "show_polarity_diagram", {"process": "tig"}), ("tool", "show_polarity_diagram", {"process": "stick"}),
                ("text", "The rating label once, and two different polarity diagrams.")]
    if "badfigure" in t:
        return [("tool", "show_figure", {"figure_id": "no-such-figure"}), ("text", "That picture does not exist, so nothing was shown.")]
    if "everything" in t:
        return [("text", "Showing one of everything."), ("tool", "show_polarity_diagram", {"process": "tig"}),
                ("tool", "show_figure", {"figure_id": "rating-label"}),
                ("tool", "show_duty_cycle_calculator", {"process": "mig", "voltage": 240, "amps": 200}),
                ("text", "That is the polarity diagram, the rating label and the calculator (manual p.14, p.16, p.19).")]
    if "figure" in t:
        return [("tool", "show_figure", {"figure_id": "rating-label"}), ("text", "That is the rating label on the machine (manual p.16).")]
    if "polarity" in t:
        return [("tool", "polarity", {"process": "tig"}), ("tool", "show_polarity_diagram", {"process": "tig"}),
                ("text", "For TIG the ground clamp goes in the Positive socket and the torch in the Negative socket (manual p.24).")]
    if "duty" in t:
        return [("tool", "duty_cycle", {"process": "mig", "voltage": 240, "amps": 200}),
                ("tool", "show_duty_cycle_calculator", {"process": "mig", "voltage": 240, "amps": 200}),
                ("text", "At 200A on 240V the MIG duty cycle is 25% (manual p.7, p.19).")]
    if "flowchart" in t:
        return [("tool", "show_troubleshooting_flowchart", {"problem_id": "mig-porosity"}), ("text", "Work through the flowchart (manual p.37, p.43).")]
    if "setup" in t:
        return [("tool", "show_setup_guide", {"process": "mig", "voltage": 240, "material": "steel", "thickness": "1/8 inch", "wire_diameter": "0.030"}),
                ("text", "The setup sheet is below (manual p.20).")]
    if "slow" in t:
        return [("tool", "view_manual_page", {"page": 14}), ("sleep", 2.5), ("text", "That took a moment.")]
    if "long" in t:
        return [("text", LONG)]
    if "callout" in t:
        return [("text", CALLOUTS)]
    if "unsafe" in t:
        return [("text", UNSAFE)]
    if "limit" in t:
        return [("text", "Working on it..."), ("result", "error_max_turns")]
    if "budget" in t:
        return [("text", "One last answer."), ("result", "error_max_budget_usd")]
    if "crash" in t:
        return [("raise", "demo crash")]
    return [("text", "This is the demo agent: the answers are canned and nothing is sent to Claude. Try one of these words: "
                     "figure, polarity, duty, flowchart, setup, draw, broken, badfigure, placeholder, twice, everything, long, callout, unsafe, slow, limit, budget, crash.")]


class DemoClient:
    """Looks like ClaudeSDKClient to the server, but replays scenario() instead of calling Claude."""

    def __init__(self, options=None):
        self.queries: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, text: str) -> None:
        self.queries.append(text)

    async def receive_response(self):
        subtype = "success"
        for step in scenario(self.queries[-1]):
            if step[0] == "text":
                yield AssistantMessage(content=[TextBlock(step[1])], model="demo")
            elif step[0] == "tool":
                yield AssistantMessage(content=[ToolUseBlock(id="demo", name=PREFIX + step[1], input=step[2])], model="demo")
            elif step[0] == "sleep":
                await asyncio.sleep(step[1])
            elif step[0] == "result":
                subtype = step[1]
            elif step[0] == "raise":
                raise RuntimeError(step[1])
        yield ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=subtype != "success", num_turns=1,
                            session_id="demo", total_cost_usd=0.0)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    p = argparse.ArgumentParser(prog="scripts.dev_server", description="Run the website with a pretend agent (no API, no cost).")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--web", default=None, help="serve the page from another folder (to try a draft before it goes into web/)")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if args.web:
        server.WEB = Path(args.web).resolve()
    port = find_free_port("127.0.0.1", args.port)
    print(f"DEMO MODE: canned replies, nothing is sent to Claude.  Open http://localhost:{port}")
    uvicorn.run(create_app(client_factory=DemoClient, options_factory=lambda: None, model="haiku"), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
