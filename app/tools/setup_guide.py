"""Setup guide: everything the manual states for one process and one job, plus a ranking of the four processes.

Pure functions, no model, no guessing. Manual facts keep their page numbers. It never produces a wire speed or a voltage:
the manual has no table for them, the LCD recommends them (manual p20).
"""
import math
import re

from app.knowledge import CAVEATS, SETTINGS, SPECIFICATIONS
from app.tools.data import get_polarity, normalize_voltage
from app.tools.selection import CHART, INCONSISTENCIES, chart_key, check_thickness

ORDER = ["mig", "flux_cored", "tig", "stick"]
SPEC_KEY = {"mig": "MIG", "flux_cored": "MIG", "tig": "TIG", "stick": "Stick"}  # flux-cored uses the MIG rows
GAPS = {c["id"]: c for c in CAVEATS["not_in_manual"]}
SKILL_RANK = {"low": 0, "moderate": 1, "high": 2}

MATERIAL_LABEL = {"steel": "steel", "stainless": "stainless steel", "aluminum": "aluminum", "castings": "castings",
                  "chrome_moly": "chrome moly", "magnesium": "magnesium alloys"}
MATERIALS = {  # what people say -> the chart's material tag
    "steel": "steel", "mild steel": "steel", "carbon steel": "steel",
    "stainless": "stainless", "stainless steel": "stainless",
    "aluminum": "aluminum", "aluminium": "aluminum", "aluminum alloy": "aluminum",
    "cast iron": "castings", "castings": "castings", "casting": "castings",
    "chrome moly": "chrome_moly", "chromoly": "chrome_moly", "chrome molybdenum": "chrome_moly",
    "magnesium": "magnesium", "magnesium alloy": "magnesium", "magnesium alloys": "magnesium",
}
SKILLS = {  # the person's skill -> the chart's three levels
    "beginner": "low", "novice": "low", "new": "low", "first time": "low", "low": "low",
    "intermediate": "moderate", "moderate": "moderate", "medium": "moderate",
    "advanced": "high", "experienced": "high", "expert": "high", "pro": "high", "professional": "high", "high": "high",
}

_WIRE = SPECIFICATIONS["processes"]["MIG"]["welding_wire_capacity"]
WIRE_SIZES = {"mig": _WIRE["solid_core_in"], "flux_cored": _WIRE["flux_cored_in"]}  # manual p7
ROLLER = {"mig": "Solid Core V-Groove", "flux_cored": "Flux-Cored Knurled Groove"}  # manual p12
GROOVE = {  # which groove of that roller matches the wire size (manual p12)
    "mig": {0.025: "0.025 groove", 0.03: "0.030/0.035 groove", 0.035: "0.030/0.035 groove"},
    "flux_cored": {0.03: "0.030/0.035 groove", 0.035: "0.030/0.035 groove", 0.045: "0.045 groove"},
}
TENSION = {"mig": "3 - 5", "flux_cored": "2 - 3"}  # manual p15


def _show(value) -> str:
    return str(value)[:60]


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _flag(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("yes", "true", "y"):
            return True
        if s in ("no", "false", "n"):
            return False
    return None


def normalize_material(value) -> str | None:
    if not isinstance(value, str):
        return None
    return MATERIALS.get(re.sub(r"[\s_-]+", " ", value.strip().lower()))


def normalize_skill(value) -> str | None:
    return SKILLS.get(re.sub(r"[\s_-]+", " ", value.strip().lower())) if isinstance(value, str) else None


def parse_wire_diameter(value) -> float | None:
    """'.030', '0.030', '0.030"', '.035 in' -> inches. A bare '30', a fraction or a size in mm is refused, not guessed."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and 0 < value < 1 else None
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"(\d*\.\d+)\s*(?:\"|in\.?|inch|inches)?", value.strip().lower().replace("”", '"').replace("″", '"'))
    return float(m.group(1)) if m and 0 < float(m.group(1)) < 1 else None


def _wire_check(key: str, value) -> dict:
    d = parse_wire_diameter(value)
    kind = "solid" if key == "mig" else "flux-cored"
    sizes = ", ".join(f"{s:.3f}" for s in WIRE_SIZES[key])
    if d is None:
        return {"id": "wire", "status": "unknown",
                "text": f'Could not read the wire size "{_show(value)}". Give it in inches, like 0.030.'}
    if not any(abs(d - s) < 1e-9 for s in WIRE_SIZES[key]):
        return {"id": "wire", "status": "fail",
                "text": f"This welder takes {kind} wire in {sizes} inch (manual p7). {d:.3f} is not one of them."}
    return {"id": "wire", "status": "ok", "text": f"{d:.3f} inch is a size this welder takes for {kind} wire (manual p7)."}


def _checks(key, material, thickness, wire_diameter, outdoors, gas_ok, skill) -> tuple[list, list]:
    """Does this process suit the job? Returns (checks, warnings). Every check is status ok/warn/fail/unknown/info."""
    chart, proc = CHART[key], CHART[key]["label"]
    checks, warnings = [], []

    def warn(fid):
        if all(w["id"] != fid for w in warnings):
            c = INCONSISTENCIES[fid]
            warnings.append({"id": fid, "text": c["text"], "guidance": c["guidance"], "pages": c["pages"]})

    tag = None
    if not _blank(material):
        tag = normalize_material(material)
        if tag is None:
            checks.append({"id": "material", "status": "unknown",
                           "text": f'"{_show(material)}" is not a material the chart names. The chart lists steel, stainless steel, '
                                   "aluminum, castings, chrome moly and magnesium alloys."})
        elif tag in chart["material_tags"]:
            note = chart.get("material_notes", {}).get(tag)
            checks.append({"id": "material", "status": "ok",
                           "text": f"The chart lists {MATERIAL_LABEL[tag]} for {proc}" + (f" ({note})." if note else ".")})
            if key == "tig" and tag in ("aluminum", "magnesium"):
                warn("tig-aluminum")
            if key == "stick" and tag == "castings":
                warn("stick-materials")
        else:
            others = [CHART[k]["label"] for k in ORDER if tag in CHART[k]["material_tags"]]
            checks.append({"id": "material", "status": "fail",
                           "text": f"The chart does not list {MATERIAL_LABEL[tag]} for {proc}. It lists it for "
                                   + (", ".join(others) if others else "none of the four processes") + "."})

    if not _blank(thickness):
        r = check_thickness(key, thickness)
        if not r["ok"]:
            checks.append({"id": "thickness", "status": "unknown", "text": r["message"]})
        elif r["fits"]:
            checks.append({"id": "thickness", "status": "ok", "note": r["gauge_note"],
                           "text": f"Your thickness ({_show(thickness)}) is inside the chart's range for {proc}: {r['chart_range']}."})
        else:
            word = "thinner" if r["too"] == "thin" else "thicker"
            checks.append({"id": "thickness", "status": "fail", "note": r["gauge_note"],
                           "text": f"Your thickness ({_show(thickness)}) is {word} than the chart's range for {proc}: {r['chart_range']}."})
        for fid in r.get("flags", []):
            warn(fid)

    if not _blank(wire_diameter) and key in WIRE_SIZES:
        checks.append(_wire_check(key, wire_diameter))

    if gas_ok is False and chart["gas_required"]:
        checks.append({"id": "gas", "status": "fail", "text": f"{proc} needs shielding gas (the chart says GAS REQUIRED) and you said you have none."})
    if outdoors is True:
        warn("outdoor-use")
        if chart["gas_required"]:
            checks.append({"id": "outdoors", "status": "warn", "text": f"The chart recommends indoor welding for {proc}."})

    level = chart["skill_level"]
    user = normalize_skill(skill)
    if user is not None and SKILL_RANK[level] > SKILL_RANK[user]:
        checks.append({"id": "skill", "status": "warn",
                       "text": f"The chart rates {proc} as needing {level.upper()} skill. You said {user.upper()}."})
    else:
        checks.append({"id": "skill", "status": "info", "text": f"The chart rates {proc} as needing {level.upper()} skill."})
    return checks, warnings


def _fits(checks: list) -> bool | None:
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return False
    if "unknown" in statuses:
        return None
    return True if "ok" in statuses else None


def _limits(key: str) -> dict:
    spec = SPECIFICATIONS["processes"][SPEC_KEY[key]]
    out = {}
    for volt in ("120VAC", "240VAC"):
        points = sorted(SPECIFICATIONS["rating_label"][volt][SPEC_KEY[key]]["duty"], key=lambda p: p["amps"])
        out[volt] = {
            "range_A": spec["welding_current_range_A"][volt],
            "input_current": spec["current_input_at_output"][volt],
            "rated_points": [{"percent": p["percent"], "amps": p["amps"]} for p in points],
        }
    return out


def _pages(node, found=None) -> list:
    found = set() if found is None else found
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "page" and isinstance(v, int):
                found.add(v)
            elif k == "pages" and isinstance(v, list):
                found.update(p for p in v if isinstance(p, int))
            else:
                _pages(v, found)
    elif isinstance(node, list):
        for v in node:
            _pages(v, found)
    return sorted(found)


def get_setup_guide(process, voltage=None, material=None, thickness=None, wire_diameter=None,
                    outdoors=None, gas_ok=None, skill=None) -> dict:
    key = chart_key(process)
    if key is None:
        return {"ok": False, "message": f'Unknown process "{_show(process)}". Use mig, flux_cored, tig or stick.'}
    volt = None
    if not _blank(voltage):
        volt = normalize_voltage(voltage)
        if volt is None:
            return {"ok": False, "message": f'Unsupported input voltage "{_show(voltage)}". This welder runs on 120V or 240V.'}
    outdoors, gas_ok = _flag(outdoors), _flag(gas_ok)

    settings = SETTINGS["processes"][key]
    lcd = SETTINGS["lcd"][settings["lcd"]]
    checks, warnings = _checks(key, material, thickness, wire_diameter, outdoors, gas_ok, skill)

    polarity = get_polarity(key)["setup"]
    plug_in = {"cables": polarity["cables"], "other": polarity["other_connections"], "gas": polarity["gas"],
               "polarity_name": polarity["polarity_name"], "sources": polarity["sources"], "spool_gun": None}
    if key == "mig" and normalize_material(material) == "aluminum":
        spool = get_polarity("spool_gun")
        if spool["found"]:
            s = spool["setup"]
            plug_in["spool_gun"] = {"label": s["label"], "cables": s["cables"], "other": s["other_connections"], "sources": s["sources"]}

    wire = None
    if key in WIRE_SIZES:
        d = parse_wire_diameter(wire_diameter)
        wire = {"roller": ROLLER[key], "groove": GROOVE[key].get(round(d, 3)) if d is not None else None,
                "tension": TENSION[key], "sizes_in": WIRE_SIZES[key], "facts": settings["wire_and_feed"]}

    entries = []
    if key == "stick":
        entries.append({"knob": "Main Control Knob", "sets": "electrode type", "value": None})
    if key in WIRE_SIZES:
        d = parse_wire_diameter(wire_diameter)
        entries.append({"knob": "Left Knob", "sets": "wire diameter", "value": f"{d:.3f} inch" if d is not None else None})
    else:
        entries.append({"knob": "Left Knob", "sets": "rod diameter" if key == "tig" else "electrode diameter", "value": None})
    entries.append({"knob": "Right Knob", "sets": "material thickness", "value": None if _blank(thickness) else _show(thickness)})

    auto = [s for s in lcd["steps"] if s["text"].startswith("Auto Weld")]
    white = [n for n in lcd["notes"] if "white mark" in n["text"]]
    decides = {"facts": auto + white, "note": GAPS["wire-speed-voltage-table"]["text"]}

    not_in_manual = [GAPS["wire-speed-voltage-table"]]
    if volt in (None, "240VAC"):
        not_in_manual.append(GAPS["breaker-size-240v"])
    if key == "mig":
        not_in_manual.append(GAPS["gas-mix-names"])

    guide = {
        "ok": True, "process": key, "label": CHART[key]["label"], "settings_label": settings["label"],
        "job": {"material": None if _blank(material) else _show(material), "thickness": None if _blank(thickness) else _show(thickness),
                "wire_diameter": None if _blank(wire_diameter) else _show(wire_diameter), "voltage": volt, "outdoors": outdoors},
        "checks": checks, "warnings": warnings, "fits": _fits(checks),
        "plug_in": plug_in, "gas": settings["gas"], "wire": wire, "electrode": settings.get("electrode"),
        "technique": settings["technique"],
        "lcd": {"steps": lcd["steps"], "notes": lcd["notes"], "entries": entries,
                "optional": [o["name"] for o in lcd["optional_settings"]]},
        "decides": decides, "limits": _limits(key), "power": SETTINGS["power"],
        "not_in_manual": [{"id": g["id"], "text": g["text"]} for g in not_in_manual],
    }
    guide["pages"] = _pages(guide)
    return guide


def choose_process(material=None, thickness=None, outdoors=None, gas_ok=None, skill=None) -> dict:
    """Rank the four processes for a job. A process that fails a chart check goes last; ties go to the easier process."""
    outdoors, gas_ok = _flag(outdoors), _flag(gas_ok)
    ranked = []
    for key in ORDER:
        checks, warnings = _checks(key, material, thickness, None, outdoors, gas_ok, skill)
        ranked.append({
            "process": key, "label": CHART[key]["label"], "fits": _fits(checks),
            "problems": [c["text"] for c in checks if c["status"] == "fail"],
            "cautions": [c["text"] for c in checks if c["status"] == "warn"],
            "unclear": [c["text"] for c in checks if c["status"] == "unknown"],
            "warnings": [w["id"] for w in warnings],
            "skill": CHART[key]["skill_level"], "why": CHART[key]["use_this_process_because"][:2],
        })
    rank = {True: 0, None: 1, False: 2}
    ranked.sort(key=lambda r: (rank[r["fits"]], len(r["cautions"]), SKILL_RANK[r["skill"]], ORDER.index(r["process"])))
    answers = (("material", material, normalize_material(material) is not None),
               ("thickness", thickness, check_thickness("mig", thickness)["ok"]))
    return {"ok": True, "ranked": ranked, "best": ranked[0]["process"] if ranked[0]["fits"] else None,
            "missing": [name for name, value, ok in answers if _blank(value) or not ok],  # ask for these
            "unreadable": [name for name, value, ok in answers if not _blank(value) and not ok]}  # given, but not understood


def build_setup(process=None, voltage=None, material=None, thickness=None, wire_diameter=None,
                outdoors=None, gas_ok=None, skill=None) -> dict:
    """One guide per process (the page has a tab for each), the ranking, and which tab opens first."""
    if not _blank(process) and chart_key(process) is None:
        return {"ok": False, "message": f'Unknown process "{_show(process)}". Use mig, flux_cored, tig or stick.'}
    guides = {}
    for key in ORDER:
        g = get_setup_guide(key, voltage, material, thickness, wire_diameter, outdoors, gas_ok, skill)
        if not g["ok"]:
            return g  # the same message for every process (bad voltage)
        guides[key] = g
    ranking = choose_process(material, thickness, outdoors, gas_ok, skill)
    selected = chart_key(process) if not _blank(process) else ranking["ranked"][0]["process"]
    return {"ok": True, "selected": selected, "guides": guides, "ranking": ranking}


def digest(setup: dict) -> dict:
    """The short, verified summary that goes back to Claude (the page itself never costs Claude tokens)."""
    g = setup["guides"][setup["selected"]]
    volt = g["job"]["voltage"]
    return {
        "ok": True, "selected": setup["selected"], "label": g["label"], "fits": g["fits"],
        "fit_by_process": {k: setup["guides"][k]["fits"] for k in ORDER},
        "checks": [c["text"] for c in g["checks"]],
        "warnings": [f"{w['text']} WHAT TO DO: {w['guidance']}" for w in g["warnings"]],
        "plug_in": [f"{c['cable']} -> {c['socket']} socket" for c in g["plug_in"]["cables"]],
        "lcd_entries": g["lcd"]["entries"],
        "feed_roller": None if g["wire"] is None else {k: g["wire"][k] for k in ("roller", "groove", "tension")},
        "current_limits": g["limits"] if volt is None else {volt: g["limits"][volt]},
        "missing": setup["ranking"]["missing"],
        "reminder": "Never state a wire speed or voltage number: the LCD recommends them (white mark on the line, manual p20).",
    }
