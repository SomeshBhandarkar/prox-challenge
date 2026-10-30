"""The protections for a public copy of the site (app/limits.py): off by default, exact when on, and wired into the real server."""
import dataclasses

import pytest
from claude_agent_sdk import ResultMessage
from starlette.testclient import TestClient

from app import limits as L
from app import server as S
from scripts.dev_server import DemoClient


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------- the daily spending cap ----------
def test_the_daily_budget_runs_out_and_starts_again_at_midnight_utc():
    clock = Clock(2 * L.DAY + 100)
    b = L.DailyBudget(1.00, clock)
    b.add(0.60)
    assert not b.exhausted()
    b.add(0.40)
    assert b.exhausted() and b.spent == pytest.approx(1.0)
    clock.t = 3 * L.DAY + 1
    assert not b.exhausted() and b.spent == 0.0


@pytest.mark.parametrize("junk", [None, True, "0.5", float("nan"), float("inf"), -1, 0, [1]])
def test_the_budget_ignores_amounts_that_are_not_real_spending(junk):
    b = L.DailyBudget(1.0, Clock())
    b.add(junk)
    assert b.spent == 0.0


def test_seconds_until_reset_is_exact():
    assert L.DailyBudget(1, Clock(5 * L.DAY + L.DAY - 60)).seconds_until_reset() == 60


# ---------- the per-visitor rate limit ----------
def test_a_visitor_gets_exactly_the_hourly_number_and_then_waits_for_the_oldest_to_age_out():
    clock = Clock()
    r = L.RateLimiter(3, clock)
    for _ in range(3):
        assert r.retry_after("a") == 0
        r.record("a")
        clock.t += 10
    assert r.retry_after("a") == 3600 - 30          # the first question was 30 s ago
    assert r.retry_after("b") == 0                  # someone else is not affected
    clock.t += 3600 - 30
    assert r.retry_after("a") == 0                  # the first has aged out


def test_the_rate_limiter_forgets_old_visitors_so_memory_stays_bounded(monkeypatch):
    monkeypatch.setattr(L, "MAX_TRACKED_VISITORS", 5)
    r = L.RateLimiter(2, Clock())
    for n in range(20):
        r.record(f"ip{n}")
    assert len(r.seen) == 5 and "ip19" in r.seen and "ip0" not in r.seen


# ---------- who is asking ----------
def scope(client_ip="9.9.9.9", xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return {"headers": headers, "client": (client_ip, 1234)}


def test_the_visitor_address_ignores_forwarded_headers_unless_a_proxy_is_trusted():
    assert L.visitor_address(scope(xff="1.2.3.4"), trust_proxy=False) == "9.9.9.9"
    assert L.visitor_address(scope(), trust_proxy=True) == "9.9.9.9"
    assert L.visitor_address({"headers": []}, trust_proxy=False) == "unknown"


def test_behind_a_proxy_the_LAST_forwarded_address_counts_because_earlier_ones_can_be_faked_by_the_visitor():
    assert L.visitor_address(scope(xff="6.6.6.6, 7.7.7.7"), trust_proxy=True) == "7.7.7.7"
    assert L.visitor_address(scope(xff="  "), trust_proxy=True) == "9.9.9.9"
    assert len(L.visitor_address(scope(xff="x" * 500), trust_proxy=True)) == 64


# ---------- the settings from .env ----------
def test_nothing_is_limited_when_nothing_is_set():
    lim = L.Limits.from_env({})
    assert not lim.active and lim.refusal(scope()) is None and lim.max_conversations is None


def test_the_settings_are_read_and_described():
    lim = L.Limits.from_env({"DAILY_BUDGET_USD": "3", "RATE_LIMIT_PER_HOUR": "20", "TRUST_PROXY": "on", "MAX_CONVERSATIONS": "4"})
    assert lim.active and lim.trust_proxy and lim.max_conversations == 4
    assert lim.describe() == "$3.00 per day for all visitors, 20 questions per hour per visitor"


@pytest.mark.parametrize("name, value", [("DAILY_BUDGET_USD", "abc"), ("DAILY_BUDGET_USD", "0"), ("DAILY_BUDGET_USD", "-2"), ("DAILY_BUDGET_USD", "nan"),
                                         ("DAILY_BUDGET_USD", "inf"), ("RATE_LIMIT_PER_HOUR", "2.5"), ("RATE_LIMIT_PER_HOUR", "0"), ("MAX_CONVERSATIONS", "many")])
def test_a_bad_setting_stops_the_start_with_a_sentence_naming_it(name, value):
    with pytest.raises(SystemExit) as e:
        L.Limits.from_env({name: value})
    assert name in str(e.value)


def test_refusals_say_what_happened_and_when_to_come_back():
    clock = Clock(7 * L.DAY + 3600)
    lim = L.Limits(daily_budget_usd=1, per_hour=1, clock=clock)
    assert lim.refusal(scope()) is None
    lim.accepted(scope())
    status, text, wait = lim.refusal(scope())
    assert status == 429 and "lot of questions" in text and 3590 <= wait <= 3600 and "about 60 minutes" in text
    lim.spent(2.0)
    status, text, wait = lim.refusal(scope("5.5.5.5"))
    assert status == 503 and "midnight UTC" in text and "your own API key" in text and wait == L.DAY - 3600


def test_the_fact_checkers_allowance_is_added_only_when_it_ran():
    lim = L.Limits(daily_budget_usd=10)
    lim.spent(0.05, checked=False)
    lim.spent(0.05, checked=True)
    assert lim.budget.spent == pytest.approx(0.10 + L.FACT_CHECKER_ALLOWANCE_USD)


# ---------- wired into the real server ----------
class Costly(DemoClient):
    """The pretend agent, but each conversation reports a growing running total, like the real SDK."""
    total = 0.0

    async def receive_response(self):
        async for m in super().receive_response():
            if isinstance(m, ResultMessage):
                Costly.total += 0.30
                m = dataclasses.replace(m, total_cost_usd=Costly.total)
            yield m


def app_with(limits, judge=None):
    Costly.total = 0.0
    app = S.create_app(client_factory=Costly, options_factory=lambda: None, model="haiku", guard_text=False, limits=limits, judge=judge)
    return TestClient(app)


def test_a_server_without_limits_never_refuses():
    with app_with(None) as c:
        for _ in range(5):
            assert c.post("/api/chat", json={"message": "hello"}).status_code == 200


def test_the_rate_limit_refuses_with_429_retry_after_and_a_sentence_the_page_shows():
    with app_with(L.Limits(per_hour=2)) as c:
        assert [c.post("/api/chat", json={"message": "hi"}).status_code for _ in range(2)] == [200, 200]
        r = c.post("/api/chat", json={"message": "hi"})
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0 and "lot of questions" in r.json()["error"]


def test_the_rate_limit_is_per_visitor_when_a_proxy_is_trusted():
    with app_with(L.Limits(per_hour=1, trust_proxy=True)) as c:
        def ask(ip):
            return c.post("/api/chat", json={"message": "hi"}, headers={"X-Forwarded-For": f"1.1.1.1, {ip}"}).status_code
        assert ask("10.0.0.1") == 200 and ask("10.0.0.1") == 429 and ask("10.0.0.2") == 200


def test_a_forged_forwarded_header_does_not_dodge_the_limit_without_a_trusted_proxy():
    with app_with(L.Limits(per_hour=1, trust_proxy=False)) as c:
        first = c.post("/api/chat", json={"message": "hi"}, headers={"X-Forwarded-For": "8.8.8.8"})
        second = c.post("/api/chat", json={"message": "hi"}, headers={"X-Forwarded-For": "9.9.9.9"})
        assert (first.status_code, second.status_code) == (200, 429)


def test_a_refused_or_busy_question_does_not_use_up_the_visitors_allowance():
    with app_with(L.Limits(per_hour=2)) as c:
        assert c.post("/api/chat", json={"message": "   "}).status_code == 422
        assert c.post("/api/chat", json={"message": "x" * 5000}).status_code == 422
        assert [c.post("/api/chat", json={"message": "hi"}).status_code for _ in range(2)] == [200, 200]


def test_the_daily_budget_counts_the_change_in_the_running_total_and_then_closes_the_site():
    lim = L.Limits(daily_budget_usd=0.50)
    with app_with(lim) as c:
        first = c.post("/api/chat", json={"message": "hi"})
        sid = first.text.split('"session_id": "')[1].split('"')[0]
        assert first.status_code == 200 and lim.budget.spent == pytest.approx(0.30)
        # a second answer in the SAME conversation: the SDK now reports 0.60 in total, so only 0.30 is new (not 0.60)
        assert c.post("/api/chat", json={"message": "again", "session_id": sid}).status_code == 200
        assert lim.budget.spent == pytest.approx(0.60) and lim.budget.exhausted()
        r = c.post("/api/chat", json={"message": "one more"})
        assert r.status_code == 503 and "spending limit" in r.json()["error"] and int(r.headers["retry-after"]) > 0
        assert c.get("/api/health").status_code == 200            # the rest of the site keeps working
        assert c.get("/figures/rating-label.png").status_code == 200


def test_the_cost_is_counted_even_when_the_visitor_closes_the_connection_before_the_answer_ends():
    lim = L.Limits(daily_budget_usd=5)
    with app_with(lim) as c:
        with c.stream("POST", "/api/chat", json={"message": "hi"}) as r:
            next(r.iter_lines())          # read only the first line, then walk away
        for _ in range(100):               # the worker finishes the answer by itself
            if lim.budget.spent:
                break
            c.get("/api/health")
        assert lim.budget.spent == pytest.approx(0.30)


def test_the_fact_checker_allowance_is_added_to_each_checked_answer_on_the_server():
    lim = L.Limits(daily_budget_usd=5)

    async def judge(answer, question):
        return []
    with app_with(lim, judge=judge) as c:
        c.post("/api/chat", json={"message": "hi"})
    assert lim.budget.spent == pytest.approx(0.30 + L.FACT_CHECKER_ALLOWANCE_USD)


def test_the_conversation_cap_comes_from_the_settings():
    app = S.create_app(client_factory=Costly, options_factory=lambda: None, model="haiku", guard_text=False, limit=2)
    assert app.state.sessions.limit == 2 and app.state.limits.active is False


# ---------- starting it ----------
def test_the_port_is_read_from_the_hosting_services_PORT_variable_when_APP_PORT_is_not_set(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.setenv("PORT", "10000")
    assert S.parse_args([]).port == 10000
    monkeypatch.setenv("APP_PORT", "8123")
    assert S.parse_args([]).port == 8123
    monkeypatch.delenv("APP_PORT")
    monkeypatch.setenv("PORT", "abc")
    with pytest.raises(SystemExit):
        S.parse_args([])
