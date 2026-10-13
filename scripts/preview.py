"""Preview a widget in your browser.
  .venv/bin/python -m scripts.preview polarity tig
  .venv/bin/python -m scripts.preview duty mig 240 200
  .venv/bin/python -m scripts.preview troubleshooting mig-porosity
  .venv/bin/python -m scripts.preview artifact path/to/drawing.html      (or .svg)
  .venv/bin/python -m scripts.preview setup process=mig voltage=240 material=steel thickness="22 gauge" wire_diameter=0.030
"""
import subprocess
import sys
from html import escape
from pathlib import Path

from app.artifacts import build_artifact
from app.knowledge import ROOT
from app.widgets.duty_cycle import duty_cycle_widget
from app.widgets.polarity import polarity_widget
from app.widgets.setup_guide import setup_guide_widget
from app.widgets.troubleshooting import troubleshooting_widget

USAGE = (
    "Usage:\n  .venv/bin/python -m scripts.preview polarity <mig|flux_cored|tig|stick|spool_gun>\n"
    "  .venv/bin/python -m scripts.preview duty <mig|tig|stick> <120|240> <amps>\n"
    "  .venv/bin/python -m scripts.preview troubleshooting <problem-id, e.g. mig-porosity>\n"
    "  .venv/bin/python -m scripts.preview artifact <file.html or file.svg>\n"
    "  .venv/bin/python -m scripts.preview setup [process=] [voltage=] [material=] [thickness=] [wire_diameter=] [outdoors=] [gas_ok=] [skill=]"
)


def artifact_host(doc: str) -> str:
    """Dev stand-in for the website's artifact frame: sandbox="allow-scripts" only (no allow-same-origin)."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Artifact host (dev)</title>'
        "<style>body{font:14px system-ui;margin:12px}iframe{width:100%;height:240px;border:2px solid #888;border-radius:8px}"
        "pre{background:#f3f3f3;padding:8px;white-space:pre-wrap}</style></head><body>"
        '<p><b>DEV HOST</b>: mirrors the website\'s artifact frame (<code>sandbox="allow-scripts"</code>, no allow-same-origin).</p>'
        f'<iframe id="f" sandbox="allow-scripts" srcdoc="{escape(doc, quote=True)}"></iframe>'
        '<p><b>Messages from the artifact</b></p><pre id="log"></pre>'
        '<script>const f=document.getElementById("f"),log=document.getElementById("log");'
        'window.addEventListener("message",function(e){if(e.source!==f.contentWindow||!e.data||e.data.source!=="artifact")return;'
        'if(e.data.kind==="resize")f.style.height=Math.min(e.data.height+4,2000)+"px";'
        'log.textContent+=JSON.stringify(e.data)+"\\n";});</script></body></html>'
    )


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "polarity":
        widget = polarity_widget(args[1])
    elif args and args[0] == "setup":
        names = {"process", "voltage", "material", "thickness", "wire_diameter", "outdoors", "gas_ok", "skill"}
        try:
            pairs = dict(a.split("=", 1) for a in args[1:])
        except ValueError:
            sys.exit(USAGE)
        if set(pairs) - names:
            sys.exit(USAGE)
        widget = setup_guide_widget(**pairs)
    elif len(args) == 2 and args[0] == "troubleshooting":
        widget = troubleshooting_widget(args[1])
    elif len(args) == 4 and args[0] == "duty":
        try:
            widget = duty_cycle_widget(args[1], args[2], float(args[3]))
        except ValueError:
            sys.exit(USAGE)
    elif len(args) == 2 and args[0] == "artifact":
        source = Path(args[1])
        if not source.is_file():
            sys.exit(f"No such file: {source}")
        kind = "svg" if source.suffix.lower() == ".svg" else "html"
        widget = build_artifact(source.stem, kind, source.stem, source.read_text(encoding="utf-8"))
        if widget["ok"]:
            widget["html"] = artifact_host(widget["html"])
    else:
        sys.exit(USAGE)

    if not widget["ok"]:
        sys.exit(widget["message"])
    out = ROOT / "previews"
    out.mkdir(exist_ok=True)
    path = out / ("-".join(a.replace("/", "_") for a in args) + ".html")
    path.write_text(widget["html"], encoding="utf-8")
    subprocess.run(["open", str(path)])
    print(f"Opened {path}")


if __name__ == "__main__":
    main()
