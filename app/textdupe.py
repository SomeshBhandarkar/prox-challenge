"""Spotting an answer that says again what it already said: the model writes its answer, calls a picture tool, then writes the answer
again (seen in real runs on Haiku and on Sonnet). The exam runner uses this to flag it; the server uses it to leave the second copy out
of the page. Measured on runs of overlapping six-word groups, so a reworded copy still counts but a different point does not."""
import re

GROUP = 6            # words per group
MIN_GROUPS = 12      # shorter blocks (a closing sentence, "Want me to open the setup sheet?") are never judged
FLAG_AT = 0.35       # the exam runner flags a block when this share of it was already said (sensitive: a person then reads it)
DROP_AT = 0.5        # the server leaves a block out only when at least this share of it was already said (conservative: dropping hides text)


def shingles(text: str, n: int = GROUP) -> set:
    words = re.findall(r"[a-z0-9']+", str(text).lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def repeated_share(text: str, earlier: set) -> float:
    """The share of this text's word groups that the earlier text already had (0.0 when there is too little text to judge)."""
    groups = shingles(text)
    if len(groups) < MIN_GROUPS or not earlier:
        return 0.0
    return len(groups & earlier) / len(groups)
