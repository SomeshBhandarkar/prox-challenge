"""Run the website with a pretend agent: canned replies, no API key, no cost. For building and testing the page.

    .venv/bin/python -m scripts.dev_server            then open the address it prints

Type one of these words in the chat to see what the page does with it:
  figure  polarity  duty  flowchart  setup  draw  broken  badfigure  placeholder  twice  everything  lists  repeat  phantom  long  callout  unsafe  slow  limit  budget  crash
  details (tap-to-answer questions)  symptom (the same, for a problem)  panel interior (the clickable front panel and inside)  photo (a weld photo is sent with the question)
The answers are NOT from the manual. They only exercise the page. The real app is:  python3 run.py
"""
import argparse
import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from app import server
from app.guard import PHOTO_NO_MATCH
from app.server import create_app, find_free_port
from app.show import PREFIX

CHEAT_SHEET = """<h1>Cable cheat sheet (demo)</h1><div id="out"></div><p>Source: manual p.14</p>
<script>
var setups = window.MANUAL.polarity.setups, out = document.getElementById('out');
Object.keys(setups).forEach(function (k) {
  var d = document.createElement('div'); d.className = 'card'; d.style.cssText = 'border:1px solid var(--line);padding:8px;margin:6px 0;border-radius:8px';
  d.textContent = k + ': ' + setups[k].cables.map(function (c) { return c.cable + ' -> ' + c.socket; }).join('; ');
  out.appendChild(d);
});
</script>"""
BROKEN = "<h1>Broken demo</h1><p>This drawing throws an error on purpose, to test the one automatic repair.</p><p>Source: manual p.14</p><script>nothing.here.exists();</script>"
FIXED = "<h1>Fixed demo</h1><p>This is the second try, and it works: the page asked the assistant to fix it once.</p><p>Source: manual p.14</p>"
LONG = ("**Short answer:** it depends on the process.\n\n- First point with a page cite (manual p.14)\n- Second point with `inline code` "
        "and a second cite (manual p.7, p.19)\n- Third point\n\n1. Do this first\n2. Then this\n3. Last, this (Selection chart)\n\n"
        "A second paragraph so the spacing can be checked. " + "It keeps going to test wrapping on a phone. " * 8)
CALLOUTS = ("WARNING (manual p.6): Do not use the welder if the power cord or plug is damaged.\n\nDANGER: The wire and torch are live whenever "
            "the power switch is on.\n\nCAUTION - Let the machine cool before you touch the nozzle.\n\nNOTICE: Do not overtighten the knob (manual p.17).\n\n"
            "> WARNING! TO PREVENT SERIOUS INJURY: Welder is now energized and Open Circuit Voltage is present. (manual p.32)\n\n"
            "| Process | Ground clamp | Torch |\n|---|---|---|\n| TIG | Positive | Negative |\n| Stick | Negative | Positive |\n\nA plain paragraph after the table. "
            "Not a cite: Quick-start guide p.2.")
LISTS = ("Top checks:\n\n1. **Polarity.** Check the sockets (manual p.13):\n   - Ground Clamp Cable goes in the Positive (+) socket.\n"
         "   - Wire Feed Power Cable goes in the Negative (-) socket.\n2. **Dirty workpiece.** Clean it down to bare metal.\n3. **Gun too far.** Check CTWD (manual p.22).\n\n"
         "Loose bullets between numbers:\n\n1. First\n- a bullet\n- another bullet\n2. Second\n3. Third")
GUARD_CLEAN = ("At 200A on 240V the MIG duty cycle is 25% (manual p.7). That means 2.5 minutes of welding and 7.5 minutes of rest in every 10 minutes (manual p.19). "
               "Leave the Power Switch ON so the fan can cool it (manual p.23).")
GUARD_BAD = GUARD_CLEAN + " General advice, not from the manual: 240V gives you more current range."
GUARD_JUNK = "Typically you would use 15 CFH. Most welders find 18 volts works. I'd recommend checking reviews online."
UNSAFE = ('Here is <script>alert(1)</script> and <img src=x onerror="alert(2)"> and a link '
          '[click](javascript:alert(3)) and **bold** (manual p.99).')


def scenario(text: str, history: tuple = ()) -> list[tuple]:
    """Steps for one question: ("text", s) | ("tool", short_name, input) | ("sleep", seconds) | ("result", subtype) | ("raise", msg)."""
    t = text.lower()
    earlier = (history[-1] if history else "").lower()
    if "goes beyond the owner's manual" in t:   # the server's rewrite request after a draft with outside content
        if "stubborn" in earlier:                # a model that repeats the outside advice even after being told
            return [("text", GUARD_BAD)]
        if "nothing" in earlier and "guard" in earlier:
            return [("text", GUARD_JUNK)]
        return [("text", GUARD_CLEAN)]
    if "stubborn" in t:
        return [("text", GUARD_BAD)]
    if "nothing" in t and "guard" in t:          # only junk: nothing trustworthy to show
        return [("text", GUARD_JUNK)]
    if "outside" in t:
        return [("text", GUARD_BAD)]
    if "judged" in t:                            # clean by words, but the demo fact-checker flags the XJUDGE sentence
        return [("text", GUARD_CLEAN + " XJUDGE Buy a small spool first and test it on scrap.")]
    if "automatic note from the app" in t:   # the server's one-time nudge after an answer that pointed at a picture it never showed
        return [("tool", "show_figure", {"figure_id": "rating-label"}), ("text", "Here is the rating label.")]
    if "phantom" in t:
        return [("text", "The label gives 24 V at 200 A on 240V MIG. See the picture below.")]
    if t.startswith(("process:", "input voltage:", "material:", "thickness:", "wire diameter:", "what it is doing:")):   # the person tapped their answers
        if "what it is doing" in t:
            return [("tool", "show_troubleshooting_flowchart", {"problem_id": "mig-wire-stops"}), ("text", "Work through the flowchart (manual p.42).")]
        return [("tool", "show_setup_guide", {"process": "mig", "voltage": 240, "material": "steel", "thickness": "1/8 inch", "wire_diameter": "0.030"}),
                ("text", "Thanks. The setup sheet for those details is below (manual p.20).")]
    if "panel" in t:
        return [("tool", "show_figure", {"figure_id": "front-panel-controls"}), ("text", "Here is the front panel. Tap a part to see what the manual says about it (manual p.8).")]
    if "interior" in t:
        return [("tool", "show_figure", {"figure_id": "interior-controls"}), ("text", "Here is the inside of the welder (manual p.9).")]
    if "details" in t:
        return [("text", "I need a few details first: tap your answers below."),
                ("tool", "ask_for_details", {"topics": ["process", "voltage", "material", "thickness", "wire_size"]})]
    if "symptom" in t:
        return [("text", "I need to know a little more first: tap what it is doing."), ("tool", "ask_for_details", {"topics": ["process", "symptom"]})]
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
    if "repeat" in t:   # the model wrote its answer, called a picture tool, then wrote the answer again (real output from exam Q43)
        import json
        first, second = json.loads((Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "repeated_answer.json").read_text(encoding="utf-8"))["blocks"]
        return [("text", first), ("tool", "show_figure", {"figure_id": "power-input-socket"}), ("text", second)]
    if "lists" in t:
        return [("text", LISTS)]
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
                     "figure, polarity, duty, flowchart, setup, details, symptom, panel, interior, photo, draw, broken, badfigure, placeholder, twice, everything, lists, repeat, phantom, long, callout, unsafe, slow, limit, budget, crash.")]


PHOTO_REPLY = [("tool", "show_figure", {"figure_id": "wire-porosity"}),
               ("text", "Your photo matches the manual's picture of porosity (manual p.37), shown below. The manual lists these causes: dirty workpiece, "
                        "gun used too far from the workpiece, incorrect polarity and dirty welding wire (manual p.37). A photo cannot settle it, so compare it with the manual's pictures.")]
# a photo that matches nothing: the model called pictures before it made up its mind, and the page must show none of them (type "nomatch" with the photo)
PHOTO_DECLINE = [("tool", "show_figure", {"figure_id": "wire-diagnosis-examples"}), ("tool", "show_figure", {"figure_id": "wire-porosity"}),
                 ("text", PHOTO_NO_MATCH)]


class DemoClient:
    """Looks like ClaudeSDKClient to the server, but replays scenario() instead of calling Claude."""

    def __init__(self, options=None):
        self.queries: list[str] = []
        self.photos: list[bool] = []   # whether each question came with a photo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt) -> None:
        """The real client takes a string, or (for a question with a photo) a stream of message dicts holding image and text blocks."""
        if isinstance(prompt, str):
            self.queries.append(prompt)
            self.photos.append(False)
            return
        words, photo = [], False
        async for message in prompt:
            for block in message["message"]["content"]:
                if block.get("type") == "text":
                    words.append(block["text"])
                elif block.get("type") == "image" and block.get("source", {}).get("data"):
                    photo = True
        self.queries.append(" ".join(words))
        self.photos.append(photo)

    async def receive_response(self):
        subtype = "success"
        if self.photos[-1]:
            steps = PHOTO_DECLINE if "nomatch" in self.queries[-1].lower() else PHOTO_REPLY
        else:
            steps = scenario(self.queries[-1], tuple(self.queries[:-1]))
        for step in steps:
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


async def demo_judge(answer: str, question: str):
    """A pretend fact-checker for the demo: objects to any sentence containing XJUDGE."""
    from app.guard import Finding, split_sentences
    return [Finding("checker", s, "not in the manual") for s in split_sentences(answer) if "XJUDGE" in s]


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    p = argparse.ArgumentParser(prog="scripts.dev_server", description="Run the website with a pretend agent (no API, no cost).")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--web", default=None, help="serve the page from another folder (to try a draft before it goes into web/)")
    p.add_argument("--guard", action="store_true", help="switch the manual-only checks ON (words: outside, stubborn, nothing guard, judged) with a pretend fact-checker")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if args.web:
        server.WEB = Path(args.web).resolve()
    port = find_free_port("127.0.0.1", args.port)
    print(f"DEMO MODE: canned replies, nothing is sent to Claude.  Open http://localhost:{port}")
    judge = demo_judge if args.guard else None
    uvicorn.run(create_app(client_factory=DemoClient, options_factory=lambda: None, model="haiku", guard_text=args.guard, judge=judge),
                host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
