import pytest

from app.agent import (DEFAULT_BUDGET_USD, DEFAULT_MODEL, KEY_PLACEHOLDER, MAX_TURNS, MODELS, make_options, require_api_key,
                       resolve_model)
from app.agent_tools import TOOL_NAMES
from app.knowledge import ROOT
from app.prompt import build_system_prompt


@pytest.fixture(autouse=True)
def no_model_env(monkeypatch):
    monkeypatch.delenv("MODEL", raising=False)


# ---------- the lock-down ----------
def test_the_options_are_locked_down():
    o = make_options()
    assert o.tools == [] and o.setting_sources == []  # no built-in tools, no local Claude settings
    assert o.allowed_tools == TOOL_NAMES and len(TOOL_NAMES) == 9
    assert list(o.mcp_servers) == ["welder"]
    assert not o.env  # an env override would replace the whole environment and drop the API key
    assert o.max_turns == MAX_TURNS == 8 and o.max_budget_usd == DEFAULT_BUDGET_USD == 0.5
    assert o.permission_mode in (None, "default")  # nothing is bypassed


def test_the_system_prompt_is_the_whole_briefing():
    o = make_options()
    assert o.system_prompt == build_system_prompt()
    assert "=====PAGE 1=====" in o.system_prompt and "THE MANUAL DOES NOT SAY" in o.system_prompt


def test_every_tool_the_agent_can_use_is_ours():
    assert all(name.startswith("mcp__welder__") for name in make_options().allowed_tools)


# ---------- choosing the model ----------
def test_the_default_is_opus():
    assert DEFAULT_MODEL == "opus" and make_options().model == "claude-opus-5-5"


@pytest.mark.parametrize("given, expected", [("haiku", "claude-haiku-5-5"), ("Sonnet", "claude-sonnet-5-5"), (" OPUS ", "claude-opus-5-5"),
                                             ("claude-haiku-5-5", "claude-haiku-5-5"), ("claude-fable-5-1", "claude-fable-5-1")])
def test_aliases_and_full_ids(given, expected):
    assert resolve_model(given) == expected
    assert make_options(given).model == expected


def test_the_aliases_point_at_real_model_ids():
    assert set(MODELS) == {"haiku", "sonnet", "opus"} and all(v.startswith("claude-") for v in MODELS.values())


def test_the_argument_beats_the_env_setting_and_the_env_beats_the_default(monkeypatch):
    monkeypatch.setenv("MODEL", "haiku")
    assert resolve_model() == "claude-haiku-5-5"
    assert resolve_model("sonnet") == "claude-sonnet-5-5"


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_model_falls_back_to_the_default(monkeypatch, blank):
    monkeypatch.setenv("MODEL", blank)
    assert resolve_model() == "claude-opus-5-5" and resolve_model(blank) == "claude-opus-5-5"


@pytest.mark.parametrize("bad", ["hiaku", "gpt-4", "opuss", "claude", "model", "x" * 5000, 5, [], True])
def test_a_typo_is_rejected_with_a_helpful_message_not_sent_to_the_api(bad):
    if isinstance(bad, str):
        with pytest.raises(ValueError, match="haiku, sonnet, opus"):
            resolve_model(bad)
    else:
        assert resolve_model(bad) == "claude-opus-5-5"  # a non-string argument counts as "not given"


def test_a_typo_in_the_env_setting_is_rejected_too(monkeypatch):
    monkeypatch.setenv("MODEL", "hiaku")
    with pytest.raises(ValueError, match="Unknown model"):
        make_options()


def test_the_error_never_echoes_a_huge_input():
    with pytest.raises(ValueError) as e:
        resolve_model("x" * 5000)
    assert len(str(e.value)) < 300


# ---------- the spend cap ----------
@pytest.mark.parametrize("bad", [0, -1, -0.01, float("nan"), float("inf"), True, False, None, "0.5", [], {}])
def test_a_bad_budget_is_rejected_so_the_cap_cannot_vanish(bad):
    with pytest.raises(ValueError, match="positive number"):
        make_options("haiku", bad)


@pytest.mark.parametrize("ok", [0.05, 1, 0.5, 2.5])
def test_a_normal_budget_is_kept(ok):
    assert make_options("haiku", ok).max_budget_usd == float(ok)


# ---------- the key ----------
def test_a_missing_blank_or_placeholder_key_gets_a_friendly_message(monkeypatch):
    for value in (None, "", "   ", KEY_PLACEHOLDER, f"  {KEY_PLACEHOLDER}  "):
        if value is None:
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        else:
            monkeypatch.setenv("ANTHROPIC_API_KEY", value)
        with pytest.raises(SystemExit) as e:
            require_api_key()
        assert "cp .env.example .env" in str(e.value)


def test_a_real_looking_key_passes_and_is_never_printed(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0000000000")
    require_api_key()
    options = make_options("haiku")
    assert "sk-ant-test" not in options.system_prompt
    assert "sk-ant-test" not in capsys.readouterr().out


def test_the_placeholder_matches_what_env_example_ships_with_and_every_other_setting_is_optional():
    from dotenv import dotenv_values
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert dict(dotenv_values(stream=__import__("io").StringIO(text))) == {"ANTHROPIC_API_KEY": KEY_PLACEHOLDER}  # nothing else is switched on
    for name in ("MODEL", "SESSION_BUDGET_USD", "APP_PORT"):
        assert f"# {name}=" in text, f"{name} should be documented as an optional, commented-out line"
