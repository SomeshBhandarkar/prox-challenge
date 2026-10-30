"""Strict guardrails: the assistant may say only what the owner's manual (and the verified data built from it) says.

A prompt rule alone cannot stop a model from occasionally adding outside knowledge ("general advice", typical values, "usually", tips), so
this module checks every answer in code before the person sees it:

  1. outside-knowledge markers   words that announce content from beyond the manual ("general advice", "typically", "my inference"...)
  2. unit numbers                a number with a unit (44%, 0.03 inch, 15 CFH) must also appear with that unit in the manual or its data
  3. unsupported sentences       a sentence whose content words mostly never appear in the manual (and were not in the question)
  4. no source                   an answer with facts but no page citation

The server answers a violation by asking the model to rewrite using only the manual; if the problem is still there, `enforce` removes the
unsupported sentences, and when nothing trustworthy is left the answer becomes FALLBACK. Everything here is plain code: no model, no network.
"""
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.knowledge import DATA_DIR, ROOT

FALLBACK = "There is no specific information in the manual for this kind of problem."
SUPPORT = "For technical questions, please call 1-800-444-3353 (manual p.2)."   # the manual's own sentence, from the footer of its pages

# ---------------------------------------------------------------- 1. markers of content from beyond the manual
OUTSIDE_MARKERS = re.compile(
    r"\bgeneral (?:advice|knowledge|welding|practice|rule)\b|\bnot from the manual\b|\b(?:outside|beyond) (?:of )?the manual\b|\brule of thumb\b|"
    r"\bbest practices?\b|\bcommon practice\b|\btypically\b|\busually\b|\bgenerally\b|\bin general\b|\bcommonly\b|\bnormally\b|\bprobably\b|"
    r"\bmost (?:common|likely|frequent)\b|\b(?:i'd|i would|i) (?:recommend|suggest|guess|think|assume)\b|\bmy (?:guess|inference|opinion|experience)\b|"
    r"\binferen(?:ce|ces|ced)\b|\bi infer\b|\bin my experience\b|\bexperienced welders\b|\bprofessional welders\b|\bwelding supply (?:shop|store)\b|"
    r"\b(?:read|check) (?:online )?reviews\b|\bonline reviews\b|\bit is widely\b|\bas a general\b|\bthe quickest to check\b|\bmost welders\b|"
    r"\bplan (?:on|with|for|around)\b|\bthe (?:safe|safer|safest) (?:figure|number|bet|choice|route|way|option)\b|\b(?:safer|safest)\b|\bbetter (?:to|off)\b|"
    r"\bbest to\b|\bi'd (?:start|check|try|begin)\b|\brough(?:ly)? estimate\b|\bestimate\b|\bnot (?:rated|in the manual)[^.\n]{0,40}\bbut\b", re.I)
_QUOTED = re.compile(r'"[^"\n]{3,}"|“[^”\n]{3,}”')   # words inside quotation marks are the manual's own words, whatever they say

# ---------------------------------------------------------------- 2. numbers with units
_UNITS = {
    "%": "percent", "percent": "percent", "a": "amp", "amp": "amp", "amps": "amp", "ampere": "amp", "amperes": "amp",
    "v": "volt", "vac": "volt", "vdc": "volt", "volt": "volt", "volts": "volt", "scfh": "scfh", "cfh": "scfh", "ipm": "ipm", "lb": "lb", "lbs": "lb",
    "pound": "lb", "pounds": "lb", '"': "inch", "″": "inch", "in": "inch", "inch": "inch", "inches": "inch", "min": "minute", "mins": "minute",
    "minute": "minute", "minutes": "minute", "sec": "second", "secs": "second", "second": "second", "seconds": "second", "ft": "feet", "foot": "feet",
    "feet": "feet", "°": "degree", "degree": "degree", "degrees": "degree", "mm": "mm", "hz": "hz", "kva": "kva", "gauge": "gauge", "ga": "gauge",
    "awg": "gauge", "cm": "cm", "meters": "meter", "meter": "meter", "psi": "psi", "kg": "kg", "oz": "oz",
}
_NUM = r"(?:\d+[-\s]\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_PAIR = re.compile(rf"(?<![\w./])({_NUM}(?:\s?[-–]\s?{_NUM})?)\s?(%|percent\b|[A-Za-z]+\b|[\"″°])", re.I)
_HALF = str.maketrans({"½": ".5", "¼": ".25", "¾": ".75"})


def _to_float(token: str) -> float | None:
    token = token.strip()
    m = re.fullmatch(r"(\d+)[-\s](\d+)/(\d+)", token)   # 2-1/2 or 2 1/2
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3)) if int(m.group(3)) else None
    m = re.fullmatch(r"(\d+)/(\d+)", token)             # 3/8
    if m:
        return int(m.group(1)) / int(m.group(2)) if int(m.group(2)) else None
    try:
        return float(token)
    except ValueError:
        return None


def number_unit_pairs(text: str) -> set:
    """Every (value, unit class) in a text: '20-30 SCFH' gives (20, scfh) and (30, scfh); '2-1/2 minutes' gives (2.5, minute)."""
    text = str(text).translate(_HALF)
    found = set()
    for m in _PAIR.finditer(text):
        unit = _UNITS.get(m.group(2).lower())
        if not unit:
            continue
        parts = re.split(r"\s?[-–]\s?(?=\d)", m.group(1)) if not re.fullmatch(r"\d+-\d+/\d+", m.group(1)) else [m.group(1)]
        for part in parts:
            value = _to_float(part)
            if value is not None:
                found.add((round(value, 4), unit))
    return found


def _numbers_anywhere(text: str) -> set:
    return {round(v, 4) for v in (_to_float(t) for t in re.findall(_NUM, str(text).translate(_HALF))) if v is not None}


# ---------------------------------------------------------------- the sources: manual text + verified data
# the data files hold some numbers as plain values with the unit in the KEY (specifications.json: "amps": 200); these keys say which unit
_KEY_UNITS = {"amps": "amp", "volts": "volt", "percent": "percent", "duty_percent": "percent", "I1max_A": "amp", "I1eff_A": "amp",
              "flux_cored_in": "inch", "solid_core_in": "inch", "wire_speed_ipm": "ipm", "120VAC": "amp", "240VAC": "amp"}
_NOT_FROM_THE_MANUAL = ("gauge_reference",)   # the standard sheet-gauge table is outside knowledge: never a source


def _data_files() -> dict:
    out = {}
    for name in ("specifications", "polarity", "controls", "settings", "process_selection", "troubleshooting", "caveats", "figures"):
        path = DATA_DIR / f"{name}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = {k: v for k, v in data.items() if k not in _NOT_FROM_THE_MANUAL}
            out[name] = data
    return out


def _data_strings() -> str:
    return "\n".join(json.dumps(d, ensure_ascii=False) for d in _data_files().values())


def _data_pairs() -> set:
    pairs = set()

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, (int, float)) and not isinstance(node, bool) and key in _KEY_UNITS:
            pairs.add((round(float(node), 4), _KEY_UNITS[key]))

    walk(_data_files().get("specifications", {}))
    return pairs


@lru_cache(maxsize=1)
def sources_text() -> str:
    return (ROOT / "knowledge" / "manual.txt").read_text(encoding="utf-8") + "\n" + _data_strings()


@lru_cache(maxsize=1)
def allowed_pairs() -> frozenset:
    pairs = set(number_unit_pairs(sources_text())) | _data_pairs()
    # a duty cycle of p% means p/10 minutes of welding and (10 - p/10) of rest in every 10 (the manual's own examples: 25% = 2-1/2 and 7-1/2)
    for value, unit in list(pairs):
        if unit == "percent" and 0 < value <= 100:
            pairs |= {(round(value / 10, 4), "minute"), (round(10 - value / 10, 4), "minute")}
    return frozenset(pairs)


# ---------------------------------------------------------------- 3. sentence support
_STOP = set("""
a about above after again all also am an and any are aren't as at be because been before being below between both but by can can't cannot could couldn't did didn't
do does doesn't doing don't down during each either else even ever every few for from further get gets got had has hasn't have haven't having he her here hers him his
how however i if in into is isn't it it's its itself just let like may me might more most much must my no nor not now of off on once one only or other our ours out over
own same shall she should shouldn't so some such than that the their theirs them then there these they this those through to too under until up us very was wasn't we
were weren't what when where which while who whom whose why will with won't would wouldn't yes you your yours yourself also still already then next first second third
last able make made makes need needs want wants see sees seen use used uses using go goes going come comes take takes took give gives gave keep keeps put puts say says said
tell tells below above manual page pages step steps picture pictures diagram diagrams calculator flowchart sheet shown shows show below here there thing things way ways
if else sure okay ok thanks thank welcome sorry happy help helps you're you'll you've i'm i'll i'd i've it's that's there's we're they're let's he's she's since though although whether something anything everything someone anyone really actually exactly""".split())


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            if suffix in ("ing", "ed") and len(stem) >= 4 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
                stem = stem[:-1]   # running -> run, stopped -> stop
            return stem
    return word


def _words(text: str) -> list:
    return [_stem(w) for w in re.findall(r"[a-z][a-z'-]*", str(text).lower().replace("’", "'")) if len(w) >= 3 and w not in _STOP]


@lru_cache(maxsize=1)
def vocabulary() -> frozenset:
    return frozenset(_words(sources_text()))


def split_sentences(text: str) -> list:
    """Sentences, list items and table rows, in order. Citations, headings and blank lines are not sentences."""
    out = []
    for line in str(text).replace("\r", "").split("\n"):
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line.strip())
        line = line.replace("**", "").replace("`", "")
        if not line or re.fullmatch(r"[|:\-\s]+", line):
            continue
        out.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"“])", line) if s.strip())
    return out


# a sentence about what the manual does or does not say adds nothing, and neither does an offer to help or a thank-you
_ABSENCE = re.compile(r"\b(?:manual|chart|label|page|guide)\b[^.\n]{0,40}\b(?:doesn't|does not|never|no |nothing|isn't|is not|not (?:say|give|list|name|cover|state|show|describe))|"
                      r"\bno (?:specific )?information\b|\bnot (?:given|listed|stated|covered|in the manual)\b|"
                      r"^(?:it|the manual|the chart|the label|the page|the guide) (?:gives|lists|has|says|names|describes|states|shows|covers|mentions) (?:no|nothing)\b|"
                      r"\bthere is no\b|\bnone of (?:these|them)\b[^.\n]{0,30}\bmanual\b", re.I)
_PLEASANTRY = re.compile(r"^(?:you're welcome|you are welcome|happy to help|good luck|sorry|no problem|great|okay|ok|sure|thanks)\b", re.I)
_OFFER = re.compile(r"^(?:if you (?:tell|let|want|like|know)|tell me|let me know|want me to|would you like|i can (?:also )?(?:give|walk|pull|put|open|show|help|check|set up|list|go)|"
                    r"just ask|send me|which process|what (?:process|material|thickness|voltage)|are you)\b", re.I)
# a sentence that only points at a picture the person is shown, or sends them to the manual's own support number, claims nothing
# (the manual's page footers say "For technical questions, please call 1-800-444-3353" and page 1 gives the support email)
_POINTER = re.compile(r"\b(?:picture|diagram|image|figure|calculator|flowchart|chart|table|screen|label|sheet|page|dials?)s?\b[^.\n]{0,60}\b(?:below|above|shown)\b|"
                      r"\b(?:see|check|compare|look at)\b[^.\n]{0,40}\b(?:picture|diagram|image|figure|chart|table|calculator|flowchart)\b", re.I)
_CITE_TEXT = re.compile(r"\(?\b(?:manual |quick-start guide )?pp?\.\s?\d{1,2}(?:\s*[-–,]\s*\d{1,2})*\)?|\(selection chart\)|\(rating label[^)]*\)", re.I)
_REFERRAL = re.compile(r"\b(?:call|phone|email|contact|reach)\b[^.\n]{0,90}?(?:1-800-444-3353|productsupport@harborfreight\.com|\bsupport\b|customer service)", re.I)
_BEYOND = re.compile(r"\b(?:beyond|outside) (?:of )?the manual\b", re.I)


def points_only(sentence: str) -> bool:
    """'The specification table is shown below.' / 'See the picture below (manual p.7).': nothing but a pointer. Anything with a number or more than a
    few other words is a real sentence and is judged like any other."""
    s = _CITE_TEXT.sub(" ", str(sentence))
    m = _POINTER.search(s)
    return bool(m) and not re.search(r"\d", s) and len(_words(s[:m.start()] + " " + s[m.end():])) <= 3


def refers_to_support(sentence: str) -> bool:
    s = str(sentence)
    return len(s) <= 200 and bool(_REFERRAL.search(s))


SUPPORT_LEVEL = 0.6      # a sentence is "unsupported" when fewer than this share of its content words appear in the manual or the question
MIN_CONTENT_WORDS = 5    # shorter sentences are not judged by word overlap (the number and marker checks still apply)


@dataclass
class Finding:
    kind: str          # marker | number | unsupported | no_source
    sentence: str
    detail: str = ""


@dataclass
class Report:
    findings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def sentences(self) -> set:
        return {f.sentence for f in self.findings if f.sentence}

    def summary(self) -> str:
        return "; ".join(f"{f.kind}: {f.detail or f.sentence[:60]}" for f in self.findings)


_CITATION = re.compile(r"\bpp?\.\s?\d{1,2}\b|\bpage \d{1,2}\b|selection chart|rating label|quick[- ]start|\bmanual\b", re.I)
_STEP = re.compile(r"\b(?:plug|turn|set|connect|twist|press|unplug|clean|replace|tighten|loosen|insert|remove|hold|keep|check|use|put|place|pull|push)\b"
                   r"[^.\n]{0,60}\b(?:socket|cable|knob|switch|wire|gas|tip|nozzle|tensioner|roller|valve|clamp|screen|button|cord|regulator|torch|gun)\b", re.I)


def _is_factual(sentence: str) -> bool:
    return bool(number_unit_pairs(sentence)) or bool(_STEP.search(sentence))


def check(text: str, question: str = "") -> Report:
    """Judge one answer. `question` is what the person asked: its words may be repeated back (a tarp, a garage) without counting as new content."""
    report = Report()
    text = str(text or "").strip()
    if not text or text.strip() == FALLBACK:
        return report
    asked = set(_words(question))
    vocab = vocabulary()
    allowed = allowed_pairs()
    sentences = split_sentences(text)
    judged = 0
    for s in sentences:
        if s.endswith("?"):
            continue  # a clarifying question adds no claim
        marker = OUTSIDE_MARKERS.search(_QUOTED.sub(" ", s))
        if marker and refers_to_support(s) and not OUTSIDE_MARKERS.search(_BEYOND.sub(" ", _QUOTED.sub(" ", s))):
            marker = None   # "For anything beyond the manual, call 1-800-444-3353." is the manual's own referral, not outside knowledge
        if (_ABSENCE.search(s) or _OFFER.search(s)) and not marker:
            continue
        if marker:
            report.findings.append(Finding("marker", s, f"outside-knowledge wording: '{marker.group(0)}'"))
            continue
        typed = _numbers_anywhere(question)   # a number the person typed in the question may be repeated back
        bad = sorted({f"{v:g} {u}" for v, u in number_unit_pairs(s) if (v, u) not in allowed and v not in typed})
        if bad:
            report.findings.append(Finding("number", s, "a number the manual does not give: " + ", ".join(bad)))
            continue
        content = _words(s)
        if len(content) >= MIN_CONTENT_WORDS and not _PLEASANTRY.search(s):
            judged += 1
            support = sum(1 for w in content if w in vocab or w in asked) / len(content)
            if support < SUPPORT_LEVEL:
                missing = sorted({w for w in content if w not in vocab and w not in asked})[:5]
                report.findings.append(Finding("unsupported", s, f"words the manual never uses: {', '.join(missing)}"))
    factual = [s for s in sentences if not s.endswith("?") and _is_factual(s) and not _ABSENCE.search(s)]
    if len(factual) >= 2 and not _CITATION.search(text):
        report.findings.append(Finding("no_source", "", "the answer states facts but names no page of the manual"))
    return report


def _bare(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line.strip()).replace("**", "").replace("`", "")


def enforce(text: str, question: str = "", extra: list | None = None) -> tuple[str, Report]:
    """The last line of defence: remove every sentence the guard (or the fact-checker, via `extra`) objects to. If nothing trustworthy is left,
    the answer is FALLBACK + SUPPORT. Returns the answer to show and the report of what was found."""
    report = check(text, question)
    report.findings += [f for f in (extra or []) if f.sentence not in report.sentences()]
    if report.ok:
        return str(text).strip(), report
    bad = report.sentences()
    kept_lines = []
    for line in str(text).replace("\r", "").split("\n"):
        if _bare(line) in bad:
            continue
        pieces = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"“])", line) if s.strip()]
        if len(pieces) > 1 and any(_bare(p) in bad for p in pieces):
            line = " ".join(p for p in pieces if _bare(p) not in bad)
        kept_lines.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    substance = [s for s in split_sentences(cleaned) if not s.endswith("?") and (number_unit_pairs(s) or len(_words(s)) >= 3)]
    if not check(cleaned, question).ok or not substance or (len(substance) < 2 and not _CITATION.search(cleaned)):
        return f"{FALLBACK} {SUPPORT}", report
    return cleaned, report


def rewrite_request(report: Report) -> str:
    """What the server tells the model when its draft broke the rules."""
    lines = [f"- {f.sentence[:220]}  ({f.detail})" if f.sentence else f"- {f.detail}" for f in report.findings[:8]]
    return ("Automatic note from the app: your draft goes beyond the owner's manual, which is not allowed. The app found:\n" + "\n".join(lines) +
            "\nRewrite your whole answer using ONLY what the manual text, the tools and the manual's pictures say: restate the manual in plain words and cite "
            "the page, add nothing of your own (no general advice, no typical values, no tips, no explanations of why, no guesses), and leave out everything "
            f"the manual does not say. If the manual has nothing on this, answer exactly: \"{FALLBACK}\" Do not mention this note.")


# ---------------------------------------------------------------- drawings the model writes itself (create_artifact)
_SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
_NOT_VISIBLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_LITERAL = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\\n]){1,200})\1""")
_SOURCE = re.compile(r"\bpp?\.\s?\d{1,2}\b|\bpage \d{1,2}\b|\bwindow\.MANUAL\b|\.sources\b|selection chart|rating label|quick[- ]start", re.I)


@lru_cache(maxsize=1)
def _plain_numbers_in_sources() -> frozenset:
    return frozenset(_numbers_anywhere(sources_text()))


def artifact_findings(code: str) -> list:
    """What is wrong with a drawing the model wrote: a number with a unit that the manual does not give (in the text people read or in a script's
    labels), a bare number that appears nowhere in the manual, or no source page. Numbers the drawing READS from window.MANUAL are not checked here:
    they are the verified data. Coordinates and styling are not checked either: only words and numbers a person would read."""
    import html as _html
    code = str(code or "")
    scripts = " ".join(_SCRIPT.findall(code))
    visible = _html.unescape(re.sub(r"<[^>]+>", " ", _NOT_VISIBLE.sub(" ", code)))
    attributes = " ".join(re.findall(r"(?:title|aria-label|alt)\s*=\s*\"([^\"]*)\"", code, re.I))
    labels = " ".join(m.group(2) for m in _LITERAL.finditer(scripts))
    allowed = allowed_pairs()
    found = []
    for where, text in (("text", visible + " " + attributes), ("script label", labels)):
        bad = sorted({f"{v:g} {u}" for v, u in number_unit_pairs(text) if (v, u) not in allowed})
        if bad:
            found.append(Finding("artifact_number", "", f"a number with a unit that the manual does not give, in the {where}: {', '.join(bad)}"))
    pairs_in_visible = {v for v, _ in number_unit_pairs(visible)}
    bare = sorted({v for v in _numbers_anywhere(visible) if v not in pairs_in_visible and v not in _plain_numbers_in_sources() and not (0 <= v <= 10)})
    if bare:
        found.append(Finding("artifact_number", "", "a number that appears nowhere in the manual: " + ", ".join(f"{v:g}" for v in bare[:6])))
    if not _SOURCE.search(visible + " " + attributes + " " + scripts):
        found.append(Finding("artifact_source", "", "the drawing names no source page of the manual (add a visible line like 'Source: manual p.7')"))
    return found
