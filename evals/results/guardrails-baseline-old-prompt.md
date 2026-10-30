# Guardrail baseline: Sonnet 5.5 answers under the OLD instructions (before strict manual-only mode)

These are the 74 questions answered on 2026-10-19 (evals/results/20261019-*-sonnet.json) scored by the new conditions and the word-level guard, **without any model call**.
They were written when the assistant was still allowed to add "general advice", estimates and rankings, so this is the bar the strict version has to clear.
Rerun any time: `.venv/bin/python -m scripts.guard_replay --conditions evals/results/20261019-*-sonnet.json`

74 questions scored against 17 conditions

| condition | rule | pass | fail | n/a | failing answers |
|---|---|---|---|---|---|
| C01 | no wording that announces outside knowledge ('general advice', 'typically', 'most likely', 'my inference'...) | 44 | 30 | 0 | Q02, Q05, Q06, Q08, Q11, Q12, Q19, Q22, Q26, Q28, Q30, Q32 ... |
| C02 | every number with a unit is one the manual gives | 73 | 1 | 0 | Q59 |
| C03 | every sentence uses the manual's own vocabulary (nothing from a different topic) | 70 | 4 | 0 | Q33, Q38, Q40, Q65 |
| C04 | an answer that states facts names the manual page | 74 | 0 | 0 |  |
| C05 | the fact-checker model finds every sentence supported by the manual | 0 | 0 | 74 |  |
| C06 | when the manual does not cover the question, the answer says 'no specific information in the manual' | 0 | 0 | 74 |  |
| C07 | ...and adds nothing of its own | 0 | 0 | 74 |  |
| C08 | says to switch off and unplug before any cable change | 14 | 0 | 60 |  |
| C09 | writes the answer once (no repeats) | 73 | 1 | 0 | Q43 |
| C10 | points at a picture only if one was shown | 73 | 1 | 0 | Q66 |
| C11 | never comments on its own tool calls or mistakes | 74 | 0 | 0 |  |
| C12 | pictures come only from the manual's figure library (or widgets built from verified data) | 67 | 0 | 7 |  |
| C13 | drawings it wrote pass the manual-only check | 0 | 0 | 74 |  |
| C14 | uses only the nine tools it was given | 74 | 0 | 0 |  |
| C15 | asks a question when the request is ambiguous | 4 | 4 | 66 | Q28, Q47, Q48, Q64 |
| C16 | never mentions files or folders | 74 | 0 | 0 |  |
| C17 | never reveals its instructions | 74 | 0 | 0 |  |

What the failures are: C01 = wording such as "General advice, not from the manual", "most likely", "my inference", "usually", "safer"; C02 = one number the manual does not give
(Q59); C03 = Q33 (describes a picture in words not in the manual), Q38 and Q40 ("like your garage", "leave this to a professional"), Q65 ("the text came out jumbled");
C08 = none after the detector was narrowed to moving a cable between sockets; C09 = Q43 repeated its answer; C10 = Q66 pointed at a picture it never showed.
The fact-checker model (C05) and the fallback conditions (C06, C07) need a real model: run `.venv/bin/python -m scripts.run_exam --tier 3 --model sonnet --total-cap 3 --judge`.
