"""An answer that points at a picture 'below' when nothing was shown (found in real runs: Haiku exam Q29, Sonnet exam Q66 "See the picture
below" after answering the rating-label question without ever calling a show tool). The server asks the model once to show the picture."""
import re

# a picture word, then "below" or "above" within the same sentence: "see the picture below", "the calculator and the label are below"
POINTS_AT_A_PICTURE = re.compile(r"\b(?:picture|diagram|image|figure|calculator|flowchart|chart|screen|label)s?\b[^.\n]{0,40}\b(?:below|above)\b", re.I)

FOLLOW_UP = ("Automatic note from the app: your answer points at a picture, diagram or tool below, but nothing was shown on the screen. "
             "Call the show tool that matches now (show_figure, show_polarity_diagram, show_duty_cycle_calculator, "
             "show_troubleshooting_flowchart or show_setup_guide). Do not write the answer again.")


def points_at_a_picture(text) -> bool:
    return bool(POINTS_AT_A_PICTURE.search(str(text or "")))
