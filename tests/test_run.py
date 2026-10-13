import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_py", ROOT / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


@pytest.mark.parametrize("version, ok", [((3, 9, 18), False), ((3, 8, 0), False), ((2, 7, 18), False), ((3, 10, 0), True),
                                         ((3, 12, 4), True), ((4, 0, 0), True)])
def test_an_old_python_gets_a_clear_message_instead_of_a_crash(version, ok):
    message = run.check_python(version)
    assert (message is None) == ok
    if not ok:
        assert "Python 3.10" in message and "python.org" in message


def test_the_minimum_python_matches_the_syntax_the_project_uses():
    # app code uses `str | None` annotations (Python 3.10+); if that ever goes away this constant can be relaxed
    assert run.MIN_PYTHON == (3, 10)
    assert "str | None" in (ROOT / "app" / "agent.py").read_text()


def test_the_venv_python_path_is_right_on_both_kinds_of_system():
    assert run.venv_python(False).parts[-2:] == ("bin", "python")
    assert run.venv_python(True).parts[-2:] == ("Scripts", "python.exe")


def test_install_runs_when_the_stamp_is_missing_or_stale_and_not_otherwise(tmp_path):
    stamp = tmp_path / "stamp"
    wanted = run.requirements_hash()
    assert run.needs_install(stamp, wanted)  # never installed, or an install that was interrupted before the stamp
    stamp.write_text("an-old-hash")
    assert run.needs_install(stamp, wanted)  # requirements changed
    stamp.write_text(wanted + "\n")
    assert not run.needs_install(stamp, wanted)  # up to date (a trailing newline is fine)


def test_the_requirements_hash_changes_when_a_pin_changes(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("claude-agent-sdk==0.2.165\n")
    b.write_text("claude-agent-sdk==0.2.166\n")
    assert run.requirements_hash(a) != run.requirements_hash(b) and run.requirements_hash(a) == run.requirements_hash(a)


def test_env_is_created_from_the_example_once_and_never_overwritten(tmp_path):
    (tmp_path / ".env.example").write_text("ANTHROPIC_API_KEY=your-api-key-here\n")
    assert run.ensure_env(tmp_path) is True
    assert (tmp_path / ".env").read_text() == "ANTHROPIC_API_KEY=your-api-key-here\n"
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-mine\n")
    assert run.ensure_env(tmp_path) is False  # a real key is never replaced
    assert (tmp_path / ".env").read_text() == "ANTHROPIC_API_KEY=sk-ant-mine\n"


def test_no_example_means_nothing_is_created(tmp_path):
    assert run.ensure_env(tmp_path) is False and not (tmp_path / ".env").exists()


def test_every_requirement_is_pinned_exactly():
    lines = [l.strip() for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert lines and all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(\.\d+)*", l) for l in lines), lines
    dev = (ROOT / "requirements-dev.txt").read_text()
    assert "-r requirements.txt" in dev


def test_the_launcher_is_valid_for_old_pythons_so_it_can_print_its_message():
    import ast
    source = (ROOT / "run.py").read_text()
    tree = ast.parse(source, feature_version=(3, 6))  # raises SyntaxError if it uses newer syntax
    assert not any(isinstance(n, ast.AnnAssign) or (isinstance(n, ast.FunctionDef) and n.returns) for n in ast.walk(tree))


def test_the_website_is_what_starts_by_default_and_the_terminal_chat_is_opt_in():
    py = run.venv_python(False)
    assert run.launch_command(py, []) == [str(py), "-m", "app.server"]
    assert run.launch_command(py, ["--model", "sonnet", "--no-open"]) == [str(py), "-m", "app.server", "--model", "sonnet", "--no-open"]
    assert run.launch_command(py, ["--terminal", "How do I set up TIG?", "--model", "haiku"]) == [str(py), "-m", "scripts.ask", "How do I set up TIG?", "--model", "haiku"]
    assert "--setup-only" not in run.launch_command(py, ["--setup-only"])


def test_both_launch_targets_exist():
    import importlib
    for module in ("app.server", "scripts.ask"):
        assert callable(importlib.import_module(module).main), module
