"""Exact lookups over the verified manual data. Pure functions: no model, no guessing."""
import math
import re

from app.knowledge import POLARITY, SPECIFICATIONS

SOURCES = ["manual p7 (Specifications)", "manual p14 rating label (60% points)"]


def normalize_process(text) -> str | None:
    if not isinstance(text, str):
        return None
    s = text.strip().lower()
    if s in ("mig", "gmaw", "flux", "flux-cored", "flux cored", "fcaw", "gasless", "solid"):
        return "MIG"  # flux-cored uses the MIG rows in the manual
    if s in ("tig", "gtaw"):
        return "TIG"
    if s in ("stick", "smaw"):
        return "Stick"
    return None


def normalize_voltage(value) -> str | None:
    match = re.match(r"\s*(\d+)", str(value))  # accepts 240, "240", "240V"
    if not match:
        return None
    return {120: "120VAC", 240: "240VAC"}.get(int(match.group(1)))


def _minutes(n: float) -> str:
    return str(int(n)) if n == int(n) else f"{n:.1f}"


def _invalid(message: str) -> dict:
    return {"status": "invalid", "message": message, "rated_points": [], "sources": [], "notes": []}


def get_duty_cycle(process: str, voltage, amps: float) -> dict:
    proc = normalize_process(process)
    volt = normalize_voltage(voltage)
    if proc is None:
        return _invalid(f'Unknown process "{process}". Use MIG (including flux-cored), TIG or Stick.')
    if volt is None:
        return _invalid(f'Unsupported input voltage "{voltage}". This welder runs on 120V or 240V.')
    if isinstance(amps, bool) or not isinstance(amps, (int, float)) or not math.isfinite(amps) or amps <= 0:
        return _invalid("Amps must be a positive, finite number.")

    spec = SPECIFICATIONS["processes"][proc]
    spec_points = spec["rated_duty_cycles"][volt]
    # The rating label has every rated point, including the 60% ones that p7 doesn't list.
    points = sorted(SPECIFICATIONS["rating_label"][volt][proc]["duty"], key=lambda p: p["amps"])
    min_amps, max_amps = spec["welding_current_range_A"][volt]
    base = {
        "process": proc, "voltage": volt, "amps": amps, "range_A": [min_amps, max_amps],
        "rated_points": [
            {"percent": p["percent"], "amps": p["amps"],
             "on_specifications_page": any(s["amps"] == p["amps"] and s["duty_percent"] == p["percent"] for s in spec_points)}
            for p in points
        ],
        "sources": SOURCES,
        "notes": ["Flux-cored welding uses the MIG rows; the manual lists no separate flux-cored duty cycle."] if proc == "MIG" else [],
    }

    def result(status: str, message: str, **extra) -> dict:
        return {**base, "status": status, "message": message, **extra}

    # 1. Above what the machine can output on this voltage (e.g. 200A on 120V).
    if amps > max_amps:
        return result("exceeds_machine_range",
                      f"{amps}A is above the {proc} range on {volt[:3]}V ({min_amps}-{max_amps}A), so the machine cannot output it on this input voltage.")

    # 1b. Below what the machine can output (e.g. 10A MIG): not "continuous", simply not possible.
    if amps < min_amps:
        return result("below_machine_range",
                      f"{amps}A is below the {proc} range on {volt[:3]}V ({min_amps}-{max_amps}A), so the machine cannot output it.")

    # 2. At or below the 100% point: continuous welding.
    continuous = next(p for p in points if p["percent"] == 100)
    if amps <= continuous["amps"]:
        return result("continuous", f"At {amps}A (at or below {continuous['amps']}A) the rating is 100%: continuous welding.",
                      duty_percent=100, weld_minutes_per_10=10, rest_minutes_per_10=0)

    # 3. Exactly a rated point.
    exact = next((p for p in points if p["amps"] == amps), None)
    if exact:
        weld = exact["percent"] / 10
        return result("rated_point",
                      f"{exact['percent']}% duty cycle at {amps}A: {_minutes(weld)} minutes of welding then {_minutes(10 - weld)} minutes of rest in every 10 minutes.",
                      duty_percent=exact["percent"], weld_minutes_per_10=weld, rest_minutes_per_10=10 - weld)

    # 4. Between two rated points: never invent a number, plan with the safer one.
    lower = max((p for p in points if p["amps"] < amps), key=lambda p: p["amps"], default=None)
    higher = min((p for p in points if p["amps"] > amps), key=lambda p: p["amps"], default=None)
    if lower and higher:
        safe_weld = higher["percent"] / 10
        guess = min(100, lower["percent"] * (lower["amps"] / amps) ** 2, higher["percent"] * (higher["amps"] / amps) ** 2)
        return result("between_rated_points",
                      f"{amps}A is not a rated point. It falls between {lower['percent']}% at {lower['amps']}A and {higher['percent']}% at {higher['amps']}A, "
                      f"so the duty cycle is somewhere between {higher['percent']}% and {lower['percent']}%. The safe figure to plan with is {higher['percent']}% "
                      f"({_minutes(safe_weld)} min welding, {_minutes(10 - safe_weld)} min rest per 10).",
                      bracketing_points=[lower, higher], conservative_percent=higher["percent"],
                      duty_percent=higher["percent"], weld_minutes_per_10=safe_weld, rest_minutes_per_10=10 - safe_weld,
                      estimate={"percent": round(guess),
                                "note": "Rough estimate only (duty cycle x current squared is roughly constant). It is NOT in the manual; plan with the conservative figure."})

    # 5. Above the highest rated point but still inside the machine's range.
    top = points[-1]
    return result("above_highest_rated_point",
                  f"{amps}A is above the highest rated point ({top['percent']}% at {top['amps']}A) but inside the machine range (up to {max_amps}A). "
                  f"The manual gives no duty cycle there; expect less than {top['percent']}% and keep welds very short.",
                  conservative_percent=top["percent"])


def get_polarity(process: str) -> dict:
    name = process.strip().lower() if isinstance(process, str) else ""
    # accept aliases ("gasless") and the canonical keys the tools advertise ("flux_cored", "spool_gun")
    key = POLARITY["process_aliases"].get(name) or (name if name in POLARITY["setups"] else None)
    if key is None:
        known = ", ".join(POLARITY["setups"])
        return {"found": False, "message": f'Unknown process "{process}". Known: {known}.'}
    setup = POLARITY["setups"][key]
    cables = "; ".join(
        f"{c['cable']} -> {'Positive (+)' if c['socket'] == 'positive' else 'Negative (-)'} socket"
        for c in setup["cables"]
    )
    return {"found": True, "key": key, "setup": setup, "message": f"{setup['label']}: {cables}. {setup['polarity_name'].rstrip('.')}."}
