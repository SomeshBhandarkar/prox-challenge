"""Before you submit: what is still missing or risky? Free, local, and it never prints a secret.

    .venv/bin/python -m scripts.check_ready

Checks: (1) the README has no unfilled <PLACEHOLDER>; (2) every picture and file the README points at exists; (3) the real key from .env is in no file that
would be committed (compared by value; only the FILE NAME is printed); (4) no other key-shaped text is in such a file; (5) .env and CLAUDE.md are ignored by git;
(6) what git would still have to commit or push. Exit code 1 if anything in 1-5 fails.
"""
import re
import subprocess
import sys
from pathlib import Path

from app.knowledge import ROOT

PLACEHOLDER = re.compile(r"<([A-Z][A-Z0-9_]{3,})>")
KEY_SHAPED = re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")
LINK = re.compile(r"(?:!\[[^\]]*\]|\[[^\]]*\])\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"")
TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".html", ".js", ".mjs", ".css", ".yaml", ".yml", ".toml", ".sh", ".example", ".cfg", ".ini", ""}


def placeholders(text: str) -> list:
    """Unfilled markers such as <VIDEO_LINK>. (HTML tags are lower-case, so they never match.)"""
    return sorted(set(PLACEHOLDER.findall(text)))


def missing_links(text: str, base: Path) -> list:
    """Relative links and images in the README whose target file is not there."""
    out = []
    for m in LINK.finditer(text):
        target = (m.group(1) or m.group(2) or "").split("#")[0]
        if not target or re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
            continue
        if not (base / target).exists():
            out.append(target)
    return sorted(set(out))


def key_shaped(text: str) -> list:
    return KEY_SHAPED.findall(text)


def committable_files(root: Path = ROOT) -> list:
    """Files git would commit: tracked, plus untracked ones that are not ignored."""
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, text=True)
    return [root / line for line in r.stdout.splitlines() if line and (root / line).is_file()]


def env_key(root: Path = ROOT) -> str:
    try:
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("\"'")
                return "" if value in ("", "your-api-key-here") else value
    except OSError:
        pass
    return ""


def scan_for_keys(files: list, real_key: str) -> tuple[list, list]:
    """(files containing the real key, files containing some key-shaped text). Names only."""
    real, shaped = [], []
    for f in files:
        if f.suffix.lower() not in TEXT_SUFFIXES or f.stat().st_size > 5_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if real_key and real_key in text:
            real.append(f)
        if key_shaped(text):
            shaped.append(f)
    return real, shaped


def ignored(path: str, root: Path = ROOT) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=root).returncode == 0


def git_summary(root: Path = ROOT) -> list:
    def run(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True).stdout.strip()
    branch = run("rev-parse", "--abbrev-ref", "HEAD")
    changed = len([ln for ln in run("status", "--short").splitlines() if ln])
    ahead = run("rev-list", "--count", f"origin/{branch}..HEAD") if run("rev-parse", "--verify", "--quiet", f"origin/{branch}") else "?"
    return [f"branch {branch}: {changed} changed or new files not yet committed; {ahead} commit(s) not yet pushed to origin"]


def main() -> int:
    ok = True

    def report(passed: bool, text: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(("PASS  " if passed else "FAIL  ") + text + (f"\n        {detail}" if detail and not passed else ""))

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    left = placeholders(readme)
    report(not left, "README has no unfilled <PLACEHOLDER>", "still to fill: " + ", ".join(f"<{p}>" for p in left))
    gone = missing_links(readme, ROOT)
    report(not gone, "every picture and file the README points at exists", "missing: " + ", ".join(gone))
    files = committable_files()
    real, shaped = scan_for_keys(files, env_key())
    report(not real, "your real key is in no file that would be committed", "in: " + ", ".join(str(f.relative_to(ROOT)) for f in real))
    report(not shaped, "no key-shaped text in any file that would be committed", "in: " + ", ".join(str(f.relative_to(ROOT)) for f in shaped))
    report(ignored(".env"), ".env is ignored by git")
    report(ignored("CLAUDE.md"), "CLAUDE.md (private notes) is ignored by git")
    print("INFO  " + "\nINFO  ".join(git_summary()))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
