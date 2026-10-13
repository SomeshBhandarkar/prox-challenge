import asyncio
import json
import re
import shutil
import subprocess

import pytest

from app import agent_tools as T
from app.knowledge import TROUBLESHOOTING
from app.prompt import build_system_prompt
from app.tools.troubleshooting import PROBLEMS
from app.widgets.troubleshooting import troubleshooting_widget


def _embedded(html: str, element_id: str):
    m = re.search(rf'<script id="{element_id}" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


HTML = troubleshooting_widget("mig-porosity")["html"]


def test_embedded_data_is_exactly_the_verified_file():
    assert _embedded(HTML, "data") == TROUBLESHOOTING


@pytest.mark.parametrize("pid", list(PROBLEMS))
def test_every_problem_builds_a_page_that_starts_on_it(pid):
    w = troubleshooting_widget(pid)
    assert w["ok"] and _embedded(w["html"], "init") == {"sec": PROBLEMS[pid]["section"], "prob": pid}


@pytest.mark.parametrize("bad", ["nope", "", None, 5, ["mig-porosity"], "MIG-POROSITY"])
def test_unknown_ids_give_an_error_and_no_page(bad):
    w = troubleshooting_widget(bad)
    assert w["ok"] is False and "html" not in w and "Valid ids" in w["message"]


def test_page_is_self_contained_and_data_cannot_close_a_script_early():
    assert "http://" not in HTML and "https://" not in HTML
    assert HTML.count("</script>") == 3  # data, init, logic
    assert "IMPORTANT" in HTML and "1-800-444-3353" in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_widget_javascript_has_no_syntax_errors(tmp_path):
    js = re.findall(r"<script>(.*?)</script>", HTML, re.S)[-1]
    f = tmp_path / "w.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_tool_returns_the_exact_steps_and_flags_for_claude():
    r = asyncio.run(T.show_troubleshooting_flowchart.handler({"problem_id": "mig-porosity"}))
    out = json.loads(r["content"][0]["text"])
    assert out["ok"] and out["page"] == 43 and len(out["steps"]) == 6
    assert sum(1 for s in out["steps"] if s.get("mig_only")) == 2
    assert "html" not in out  # the page never costs Claude tokens


def test_tool_rejects_unknown_ids_with_the_valid_list():
    out = json.loads(asyncio.run(T.show_troubleshooting_flowchart.handler({"problem_id": "wire-is-sad"}))["content"][0]["text"])
    assert out["ok"] is False and "mig-porosity" in out["message"]


def test_prompt_lists_every_problem_id_and_the_rule():
    prompt = build_system_prompt()
    for pid in PROBLEMS:
        assert pid in prompt, pid
    assert "show_troubleshooting_flowchart" in prompt
