"""The tools Claude can call. Each one is a thin wrapper over exact, tested code."""
import json

from claude_agent_sdk import create_sdk_mcp_server, tool

from app.artifacts import build_artifact
from app.tools.data import get_duty_cycle, get_polarity
from app.tools.figures import show_figure as lookup_figure
from app.tools.manual import view_manual_page
from app.tools.setup_guide import build_setup, digest
from app.tools.troubleshooting import get_troubleshooting
from app.widgets.duty_cycle import duty_cycle_widget
from app.widgets.polarity import polarity_widget
from app.widgets.setup_guide import setup_guide_widget
from app.widgets.troubleshooting import troubleshooting_widget


def _text(obj) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


@tool(
    "duty_cycle",
    "Exact duty cycle from the manual for a process, input voltage and amps.",
    {"process": str, "voltage": int, "amps": float},
)
async def duty_cycle(args):
    return _text(get_duty_cycle(args.get("process"), args.get("voltage"), args.get("amps")))


@tool(
    "polarity",
    "Which cable goes in which socket for a process (mig, flux_cored, tig, stick).",
    {"process": str},
)
async def polarity(args):
    return _text(get_polarity(args.get("process")))


@tool("view_manual_page", "Look at a real page of the owner's manual (1-48) as an image.", {"page": int})
async def view_page(args):
    result = view_manual_page(args.get("page"))
    if not result["ok"]:
        return _text(result)
    return {
        "content": [
            {"type": "text", "text": f"Manual page {result['page']}"},
            {"type": "image", "data": result["image_b64"], "mimeType": "image/jpeg"},
        ]
    }


@tool(
    "show_figure",
    "Show the user an exact picture from the manual (a cropped figure, not a whole page). "
    "Pick the id from the figure list in your instructions.",
    {"figure_id": str},
)
async def show_figure(args):
    result = lookup_figure(args.get("figure_id"))
    if result["ok"]:
        result["message"] = f"Now showing the user: {result['caption']} (manual p.{result['page']})."
    return _text(result)


@tool(
    "show_polarity_diagram",
    "Draw the user a diagram of which cable plugs into which front-panel socket, for a process "
    "(mig, flux_cored, tig, stick, spool_gun).",
    {"process": str},
)
async def show_polarity_diagram(args):
    w = polarity_widget(args.get("process"))
    return _text({"ok": w["ok"], "message": "The diagram is now shown to the user." if w["ok"] else w["message"]})


@tool(
    "show_duty_cycle_calculator",
    "Show the user an interactive duty-cycle calculator starting at the given process (mig, tig, stick; flux-cored "
    "uses mig), input voltage (120 or 240) and amps, so they can try other amps. Call duty_cycle first for the numbers you quote. "
    "The calculator lists the manual's rated points, flags amps outside the machine's range, and for amps between two rated points plans with the "
    "higher-amp rating and shows an estimate clearly labelled as NOT from the manual.",
    {"process": str, "voltage": int, "amps": float},
)
async def show_duty_cycle_calculator(args):
    w = duty_cycle_widget(args.get("process"), args.get("voltage"), args.get("amps"))
    return _text({"ok": w["ok"], "message": "The calculator is now shown to the user." if w["ok"] else w["message"]})


@tool(
    "show_troubleshooting_flowchart",
    "Show the user an interactive troubleshooting flowchart for a problem id from the troubleshooting list in your "
    "instructions. Returns the manual's exact checks (cause and solution, in the manual's order) for you to quote.",
    {"problem_id": str},
)
async def show_troubleshooting_flowchart(args):
    problem_id = args.get("problem_id")
    w = troubleshooting_widget(problem_id)
    if not w["ok"]:
        return _text({"ok": False, "message": w["message"]})
    found = get_troubleshooting(problem_id)
    keep = {k: found[k] for k in ("problem", "section", "page", "important", "steps", "mig_only_note")}
    return _text({"ok": True, "message": "The flowchart is now shown to the user.", **keep})


_NUMBER_OR_TEXT = {"anyOf": [{"type": "number"}, {"type": "string"}]}
SETUP_GUIDE_SCHEMA = {  # every field is optional: pass what you know and leave out the rest
    "type": "object",
    "properties": {
        "process": {"type": "string", "description": "mig, flux_cored, tig or stick. Leave it out to open on the best fit for the job."},
        "voltage": {**_NUMBER_OR_TEXT, "description": "120 or 240"},
        "material": {"type": "string", "description": "steel, stainless steel, aluminum, castings, chrome moly or magnesium"},
        "thickness": {**_NUMBER_OR_TEXT, "description": 'with a unit, like "22 gauge", "3/8 inch" or "3 mm"'},
        "wire_diameter": {**_NUMBER_OR_TEXT, "description": 'in inches, like "0.030" (MIG and flux-cored only)'},
        "outdoors": {"type": "boolean", "description": "true if they will weld outdoors or in wind"},
        "gas_ok": {"type": "boolean", "description": "true if they have or can use shielding gas, false if not"},
        "skill": {"type": "string", "description": "beginner, intermediate or experienced"},
    },
}


@tool(
    "show_setup_guide",
    "Show the user a setup sheet for their job: it checks material, thickness and wire size against the selection chart, "
    "then lists what to plug in, gas, feed roller and tension, the LCD steps with their entries, and current limits, with a "
    "tab for every process. Pass what you know and leave out the rest. Returns a short verified summary for you to quote.",
    SETUP_GUIDE_SCHEMA,
)
async def show_setup_guide(args):
    inputs = {k: args.get(k) for k in SETUP_GUIDE_SCHEMA["properties"]}
    w = setup_guide_widget(**inputs)
    if not w["ok"]:
        return _text({"ok": False, "message": w["message"]})
    return _text({**digest(build_setup(**inputs)), "message": "The setup sheet is now shown to the user."})


@tool(
    "create_artifact",
    "Draw something yourself as a small HTML page or SVG when no ready-made tool fits. Follow the DRAW IT YOURSELF "
    "rules in your instructions. Re-using an identifier replaces that artifact.",
    {"identifier": str, "type": str, "title": str, "code": str},
)
async def create_artifact(args):
    a = build_artifact(args.get("identifier"), args.get("type"), args.get("title"), args.get("code"))
    if not a["ok"]:
        return _text({"ok": False, "message": a["message"]})
    return _text({
        "ok": True,
        "message": f"Artifact '{a['identifier']}' is now shown to the user. "
                   "Calling create_artifact again with the same identifier replaces it.",
    })


server = create_sdk_mcp_server(
    name="welder",
    version="1.0.0",
    tools=[duty_cycle, polarity, view_page, show_figure, show_polarity_diagram, show_duty_cycle_calculator,
           show_troubleshooting_flowchart, show_setup_guide, create_artifact],
)
TOOL_NAMES = [
    "mcp__welder__duty_cycle",
    "mcp__welder__polarity",
    "mcp__welder__view_manual_page",
    "mcp__welder__show_figure",
    "mcp__welder__show_polarity_diagram",
    "mcp__welder__show_duty_cycle_calculator",
    "mcp__welder__show_troubleshooting_flowchart",
    "mcp__welder__show_setup_guide",
    "mcp__welder__create_artifact",
]
