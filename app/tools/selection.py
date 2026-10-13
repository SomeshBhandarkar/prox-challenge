"""Exact lookups over the selection chart and the settings facts. Pure functions: no model, no guessing."""
import math
import re
from fractions import Fraction

from app.knowledge import CAVEATS, PROCESS_SELECTION, SETTINGS

CHART = PROCESS_SELECTION["processes"]
GAUGE_IN = {int(k): v for k, v in PROCESS_SELECTION["gauge_reference"]["inches"].items()}
GAUGE_NOTE = PROCESS_SELECTION["gauge_reference"]["note"]
INCONSISTENCIES = {c["id"]: c for c in CAVEATS["known_inconsistencies"]}
ALIASES = {
    "mig": "mig", "gmaw": "mig", "solid": "mig", "solid wire": "mig", "gas mig": "mig",
    "flux": "flux_cored", "flux-cored": "flux_cored", "flux cored": "flux_cored", "fluxcored": "flux_cored",
    "flux_cored": "flux_cored", "fcaw": "flux_cored", "gasless": "flux_cored",
    "tig": "tig", "gtaw": "tig", "stick": "stick", "smaw": "stick",
}

_NUM = r"(?:\d+\s*/\s*\d+|\d*\.\d+|\d+)"
_GAUGE = re.compile(r"(\d{1,2})\s*-?\s*(?:ga|gauge|gage|g)\.?")
_MM = re.compile(rf"({_NUM})\s*mm")
_MIXED = re.compile(r"(\d+)[\s-]+(\d+)\s*/\s*(\d+)\s*(?:\"|in\.?|inch|inches)?")
_INCHES = re.compile(rf"({_NUM})\s*(\"|in\.?|inch|inches)?")


def _show(value) -> str:
    return str(value)[:60]  # never echo a huge or hostile input back in a message


def _number(text: str) -> float | None:
    try:
        if "/" in text:
            top, bottom = (int(p) for p in text.split("/"))
            return top / bottom
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


def chart_key(process) -> str | None:
    return ALIASES.get(process.strip().lower()) if isinstance(process, str) else None


def parse_thickness(value) -> float | None:
    """'22 ga', '3/8\"', '.375', '1/4 inch', '1-1/2 in', '3 mm', 0.25 -> inches. None if it cannot be read safely.
    A plain number in text with no unit ('22') is ambiguous, so it is refused instead of guessed."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):  # a JSON number is taken as inches
        return float(value) if math.isfinite(value) and value > 0 else None
    if not isinstance(value, str):
        return None
    s = value.strip().lower().replace("”", '"').replace("″", '"')
    if g := _GAUGE.fullmatch(s):
        return GAUGE_IN.get(int(g.group(1)))
    if m := _MM.fullmatch(s):
        n = _number(m.group(1))
        return n / 25.4 if n and n > 0 else None
    if m := _MIXED.fullmatch(s):
        whole, top, bottom = (int(x) for x in m.groups())
        return whole + top / bottom if bottom else None
    if m := _INCHES.fullmatch(s):
        number, unit = m.group(1), m.group(2)
        if unit is None and "/" not in number and "." not in number:
            return None  # a bare '22' could be gauge or inches
        n = _number(number)
        return n if n and n > 0 else None
    return None


def chart_limits_in(key: str) -> tuple[float, float]:
    t = CHART[key]["thickness"]
    return GAUGE_IN[t["min_gauge"]], float(Fraction(t["max_inches"]))


def check_thickness(process, thickness) -> dict:
    key = chart_key(process)
    if key is None:
        return {"ok": False, "message": f'Unknown process "{_show(process)}". Use mig, flux_cored, tig or stick.'}
    inches = parse_thickness(thickness)
    if inches is None:
        return {"ok": False, "message": f'Could not read the thickness "{_show(thickness)}". Give it with a unit, like "22 gauge", '
                                         '"3/8 inch", "0.25 in" or "3 mm".'}
    lo, hi = chart_limits_in(key)
    eps = 1e-9
    fits = lo - eps <= inches <= hi + eps
    too = None if fits else ("thin" if inches < lo else "thick")
    flags = []
    if key == "mig" and too == "thin" and inches >= GAUGE_IN[24] - 0.0005:
        flags.append("mig-thin-limit")  # between the chart's 22 gauge and the LCD example's 24Ga
    return {
        "ok": True, "process": key, "label": CHART[key]["label"], "thickness_in": round(inches, 4), "fits": fits, "too": too,
        "chart_range": CHART[key]["thickness"]["as_printed"], "range_in": [round(lo, 4), round(hi, 4)],
        "flags": flags, "flag_notes": [INCONSISTENCIES[f]["text"] for f in flags],
        "gauge_note": GAUGE_NOTE,
    }


def get_process_info(process) -> dict:
    key = chart_key(process)
    if key is None:
        return {"found": False, "message": f'Unknown process "{_show(process)}". Use mig, flux_cored, tig or stick.'}
    settings = SETTINGS["processes"][key]
    return {
        "found": True, "key": key, "chart": CHART[key], "settings": settings,
        "lcd": SETTINGS["lcd"][settings["lcd"]], "power": SETTINGS["power"],
    }


def chart_for_prompt() -> str:
    """The image-only selection chart as text for Claude's system prompt (generated from process_selection.json)."""
    lines = []
    for p in CHART.values():
        gas = p["shielding_gas"] + (f" ({p['gas_note']})" if p.get("gas_note") else "")
        lines.append(
            f"- {p['label']}: skill {p['skill_level'].upper()}; {gas}; materials: {'; '.join(p['materials'])}; "
            f"thickness {p['thickness']['as_printed']}; weld: {p['weld_cleanliness']}; "
            f"typical uses: {', '.join(p['applications'])}; why choose it: {'; '.join(p['use_this_process_because'])}"
        )
    rows = PROCESS_SELECTION["mig_or_flux_cored_table"]["rows"]
    lines.append("- MIG or flux-cored? (the chart's side table). Check mark under MIG: "
                 + "; ".join(r["feature"] for r in rows if r["mig"])
                 + ". Check mark under flux-cored: " + "; ".join(r["feature"] for r in rows if r["flux_cored"]) + ".")
    box = PROCESS_SELECTION["duty_cycle_box"]
    lines.append(f'- The chart\'s banner reads "{PROCESS_SELECTION["important"]}". Its duty-cycle box: {box["definition"]} Example: {box["example"]}.')
    lines.append("- Gauge: a HIGHER gauge number is THINNER steel (22 gauge is thinner than 18 gauge). That rule and any gauge-to-inch "
                 "conversion are general knowledge, not from the manual: say so when you use them.")
    return "\n".join(lines)
