"""Tap-to-answer questions. When the assistant needs a detail from the person (which process? 120V or 240V?), it names the TOPICS it needs and
the page shows buttons. The buttons themselves are built here from verified data, so the model only chooses which questions to ask: it cannot
invent an option, and every option is a name the manual itself uses."""
from app.knowledge import SPECIFICATIONS, TROUBLESHOOTING

MAX_TOPICS = 5
FREE_TEXT_LIMIT = 40   # characters the person may type into a free-text box

# one tap for each: (label on the button, the words sent back to the assistant)
PROCESSES = [("MIG (solid wire with gas)", "MIG"), ("Flux-cored (gasless)", "flux-cored"), ("TIG", "TIG"), ("Stick", "Stick")]
MATERIALS = [("Steel", "steel"), ("Stainless steel", "stainless steel"), ("Aluminum", "aluminum")]
# thicknesses: the ends of the selection chart's ranges, plus two very common ones (these are the person's input, not claims about the welder)
THICKNESSES = ["24 gauge", "22 gauge", "18 gauge", "10 gauge", "1/8 inch", "3/16 inch", "1/4 inch", "5/16 inch", "3/8 inch", "1/2 inch"]


def _voltages() -> list:
    """120V and 240V, read from the specifications (the manual lists 120VAC and 240VAC)."""
    found = sorted({int("".join(c for c in v if c.isdigit())) for p in SPECIFICATIONS["processes"].values() for v in p["input_voltages"]})
    return [(f"{v}V", f"{v}V") for v in found]


def _wire_sizes() -> list:
    cap = SPECIFICATIONS["processes"]["MIG"]["welding_wire_capacity"]
    sizes = sorted({s for key in ("solid_core_in", "flux_cored_in") for s in cap[key]})
    return [(f"{s:.3f} in", f"{s:.3f} inch") for s in sizes]


def _symptoms() -> list:
    """The manual's own troubleshooting problems, named as the manual names them (with the section, because two sections share some names)."""
    out = []
    for section in TROUBLESHOOTING["sections"]:
        where = "MIG or flux-cored" if section["id"] == "mig_flux" else "TIG or Stick"
        for p in section["problems"]:
            out.append((f"{p['problem']} ({where})", f"{p['problem']} ({where})"))
    return out


def _group(topic: str, label: str, phrase: str, options: list, free_text: bool = False, placeholder: str = "") -> dict:
    return {"id": topic, "label": label, "phrase": phrase, "free_text": free_text, "placeholder": placeholder,
            "options": [{"label": a, "value": b} for a, b in options]}


def _builders() -> dict:
    return {
        "process": lambda: _group("process", "Which welding process?", "Process", PROCESSES),
        "voltage": lambda: _group("voltage", "Which input voltage?", "Input voltage", _voltages()),
        "material": lambda: _group("material", "What are you welding?", "Material", MATERIALS, True, "Something else"),
        "thickness": lambda: _group("thickness", "How thick is it?", "Thickness", [(t, t) for t in THICKNESSES], True, "Type another thickness"),
        "wire_size": lambda: _group("wire_size", "Which wire diameter? (MIG and flux-cored)", "Wire diameter", _wire_sizes()),
        "symptom": lambda: _group("symptom", "What is it doing?", "What it is doing", _symptoms()),
    }


TOPICS = tuple(_builders())


def build_choices(topics) -> dict:
    """{"ok": True, "groups": [...]} for the topics asked for, in the order given and without repeats; or {"ok": False, "message": ...}."""
    if not isinstance(topics, (list, tuple)) or not topics:
        return {"ok": False, "message": f"Name at least one topic to ask about: {', '.join(TOPICS)}."}
    wanted, builders = [], _builders()
    for t in topics:
        if not isinstance(t, str) or t.strip().lower() not in builders:
            return {"ok": False, "message": f"'{str(t)[:30]}' is not a topic. Use only: {', '.join(TOPICS)}."}
        key = t.strip().lower()
        if key not in wanted:
            wanted.append(key)
    if len(wanted) > MAX_TOPICS:
        return {"ok": False, "message": f"Ask about at most {MAX_TOPICS} things at once."}
    return {"ok": True, "title": "A few details first", "groups": [builders[k]() for k in wanted]}
