"""Shared test setup."""
import pytest

from app import artifacts


@pytest.fixture(autouse=True)
def drawings_are_not_content_checked_unless_a_test_asks(request, monkeypatch):
    """Most artifact tests use tiny placeholder drawings about something else (identifiers, titles, sandboxing). The manual-only content check
    of drawings has its own tests (marked `content_guard`); everywhere else it is switched off so those tests stay about one thing."""
    if "content_guard" not in request.keywords:
        monkeypatch.setattr(artifacts, "artifact_findings", lambda code: [])
