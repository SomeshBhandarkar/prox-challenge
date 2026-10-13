#!/usr/bin/env python3
"""One command for reviewers: set up a private .venv, install the pinned requirements, then start the app.

    cp .env.example .env      (then paste your ANTHROPIC_API_KEY into .env)
    python3 run.py            (the first run installs; later runs start straight away)

This starts the website and opens it in your browser (the next free port is used if 8000 is busy). Extra arguments are passed along:
    python3 run.py --model sonnet    (haiku, sonnet or opus; the default is opus)
    python3 run.py --no-open         (do not open the browser)
    python3 run.py --terminal "How do I set up TIG?" --model haiku     (the terminal chat instead of the website)
    python3 run.py --setup-only      (install and check, then stop: no key, no cost)

Uses only the standard library and syntax that works on old Pythons, so it can say "your Python is too old" instead of crashing.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements-installed"
MIN_PYTHON = (3, 10)


def check_python(version_info):
    """A message if this Python is too old, else None."""
    if tuple(version_info[:2]) < MIN_PYTHON:
        return "This project needs Python %d.%d or newer; you have %d.%d. Install a newer Python from python.org and run again." % (
            MIN_PYTHON + tuple(version_info[:2]))
    return None


def venv_python(is_windows=None):
    windows = os.name == "nt" if is_windows is None else is_windows
    return VENV / ("Scripts/python.exe" if windows else "bin/python")


def requirements_hash(path=REQUIREMENTS):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def needs_install(stamp, wanted):
    """Install when the stamp is missing or was written for different requirements. The stamp is only written after pip succeeds,
    so an interrupted install is simply retried."""
    stamp = Path(stamp)
    return not stamp.exists() or stamp.read_text().strip() != wanted


def ensure_env(root=ROOT):
    """Create .env from .env.example when it is missing. True if it was created."""
    env, example = Path(root) / ".env", Path(root) / ".env.example"
    if env.exists() or not example.exists():
        return False
    shutil.copyfile(str(example), str(env))
    return True


def launch_command(py, argv):
    """The command that starts the app: the website, or with --terminal the terminal chat. Everything else is passed along."""
    module = "scripts.ask" if "--terminal" in argv else "app.server"
    return [str(py), "-m", module] + [a for a in argv if a not in ("--setup-only", "--terminal")]


def fail(message):
    sys.stderr.write(message + "\n")
    sys.exit(1)


def main(argv):
    problem = check_python(sys.version_info)
    if problem:
        fail(problem)
    setup_only = "--setup-only" in argv

    py = venv_python()
    if not py.exists():
        print("Creating a private .venv (nothing is installed outside this folder) ...")
        venv.create(str(VENV), with_pip=True)
    wanted = requirements_hash()
    if needs_install(STAMP, wanted):
        print("Installing the pinned requirements (first run only) ...")
        done = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)])
        if done.returncode != 0:
            fail("Installing the requirements failed. Check your internet connection, then run python3 run.py again.")
        STAMP.write_text(wanted)
    if ensure_env():
        print("Created .env from .env.example. Paste your ANTHROPIC_API_KEY into .env, then run python3 run.py again.")
        return 0 if setup_only else 1
    if setup_only:
        print("Setup finished. Put your ANTHROPIC_API_KEY in .env, then run: python3 run.py")
        return 0
    os.chdir(str(ROOT))
    try:
        return subprocess.call(launch_command(py, argv))
    except KeyboardInterrupt:  # Ctrl+C is how the server is stopped
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
