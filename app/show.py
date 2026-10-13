"""The "show" contract: turn one tool call the agent made into something the screen can display.

The agent's show tools are pure functions of their inputs, so the terminal runner and the website both call this with the
tool call's name and input and display what comes back. Nothing here talks to Claude, and the page itself never costs tokens.
"""
from app.artifacts import build_artifact
from app.tools.figures import FIGURES_DIR, show_figure
from app.widgets.duty_cycle import duty_cycle_widget
from app.widgets.polarity import polarity_widget
from app.widgets.setup_guide import setup_guide_widget
from app.widgets.troubleshooting import troubleshooting_widget

PREFIX = "mcp__welder__"
SETUP_FIELDS = ("process", "voltage", "material", "thickness", "wire_diameter", "outdoors", "gas_ok", "skill")
LOOKUPS = {"duty_cycle", "polarity", "view_manual_page"}  # tools that answer Claude but show the person nothing


def _error(tool: str, message: str, silent: bool = False) -> dict:
    """silent: a refused placeholder the person should never hear about (the agent still gets the message)."""
    return {"kind": "error", "tool": tool, "message": str(message), "silent": silent}


# Widgets run in a sandboxed frame on the website. This tells the page how tall they are, the same way artifacts do.
WIDGET_REPORTER = (
    "<script>(function(){function s(){try{parent.postMessage({source:'widget',kind:'resize',"
    "height:Math.ceil(document.documentElement.scrollHeight)},'*')}catch(e){}}"
    "addEventListener('load',function(){s();if(window.ResizeObserver)new ResizeObserver(s).observe(document.body)})})();</script>"
)


def _with_reporter(html: str) -> str:
    return html.replace("</body>", WIDGET_REPORTER + "</body>", 1) if "</body>" in html else html + WIDGET_REPORTER


def _widget(tool: str, w: dict) -> dict:
    if not w["ok"]:
        return _error(tool, w["message"])
    return {"kind": "widget", "tool": tool, "title": w["title"], "html": _with_reporter(w["html"])}


def _build(short: str, args: dict) -> dict:
    if short == "show_figure":
        r = show_figure(args.get("figure_id"))
        if not r["ok"]:
            return _error(short, r["message"])
        return {"kind": "figure", "tool": short, "id": r["id"], "caption": r["caption"], "source": r["source"],
                "url": r["url"], "path": str(FIGURES_DIR / f"{r['id']}.png")}
    if short == "show_polarity_diagram":
        return _widget(short, polarity_widget(args.get("process")))
    if short == "show_duty_cycle_calculator":
        return _widget(short, duty_cycle_widget(args.get("process"), args.get("voltage"), args.get("amps")))
    if short == "show_troubleshooting_flowchart":
        return _widget(short, troubleshooting_widget(args.get("problem_id")))
    if short == "show_setup_guide":
        return _widget(short, setup_guide_widget(**{k: args.get(k) for k in SETUP_FIELDS}))
    if short == "create_artifact":
        a = build_artifact(args.get("identifier"), args.get("type"), args.get("title"), args.get("code"))
        if not a["ok"]:
            return _error(short, a["message"], silent=bool(a.get("trivial")))
        return {"kind": "artifact", "tool": short, "identifier": a["identifier"], "type": a["type"],
                "title": a["title"], "html": a["html"]}
    return _error(short, f"No way to show the tool '{short}'.")


def render_show(tool_name, tool_input) -> dict | None:
    """None for tools that show nothing. Otherwise {"kind": "figure" | "widget" | "artifact" | "error", ...}.
    A bug in one builder must not stop the whole answer, so it is reported as an error instead of raised."""
    if not isinstance(tool_name, str) or not tool_name.startswith(PREFIX):
        return None
    short = tool_name[len(PREFIX):]
    if short in LOOKUPS:
        return None
    try:
        return _build(short, tool_input if isinstance(tool_input, dict) else {})
    except Exception as e:  # noqa: BLE001
        return _error(short, f"Could not draw this ({type(e).__name__}).")
