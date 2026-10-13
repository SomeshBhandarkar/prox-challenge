"""Loads the verified manual data (knowledge/data/*.json) once, at import time."""
import json
from pathlib import Path

# The project root is the folder that contains app/ and knowledge/.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "knowledge" / "data"


def _load(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


SPECIFICATIONS = _load("specifications.json")
POLARITY = _load("polarity.json")
CONTROLS = _load("controls.json")
SECTION_MAP = _load("section_map.json")
FIGURES = _load("figures.json")  # catalog of cropped manual pictures (a list)
TROUBLESHOOTING = _load("troubleshooting.json")  # manual pp42-44, verbatim
PROCESS_SELECTION = _load("process_selection.json")  # the image-only selection chart, transcribed
SETTINGS = _load("settings.json")  # settings the manual states, quoted with pages
CAVEATS = _load("caveats.json")  # what the manual does NOT say + known inconsistencies
PAGE_COVERAGE = _load("page_coverage.json")  # which pages have figures, are text only, or wait for a later patch
