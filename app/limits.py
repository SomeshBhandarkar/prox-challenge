"""Protections for a PUBLIC copy of the site, where every visitor spends the owner's API key. All of them are off unless switched on in .env,
so a person running the app locally with their own key is never limited.

    DAILY_BUDGET_USD=3      all visitors together may spend this much per UTC day; after that the site says so until midnight UTC
    RATE_LIMIT_PER_HOUR=20  one visitor (one address) may ask this many questions per hour
    TRUST_PROXY=on          the site sits behind a hosting proxy: read the visitor's address from X-Forwarded-For (exactly one proxy in front)
    MAX_CONVERSATIONS=4     open conversations at once (each one is a Claude process that uses memory; small hosts need a low number)

The spending cap counts what the SDK reports for each answer plus a flat allowance for the fact-checker, which has its own small bill.
It lives in memory: a restart starts the day again, so ALSO set a monthly spend limit on the key in the Anthropic Console (the real hard stop).
"""
import math
import os
import time
from collections import OrderedDict, deque

FACT_CHECKER_ALLOWANCE_USD = 0.01   # per answer, when the fact-checker is on (it costs about half a cent; this leaves room for a second look)
MAX_TRACKED_VISITORS = 5000         # memory bound for the rate limiter
DAY = 86400


def _positive(raw: str, name: str, whole: bool = False):
    """A positive number from .env, or None when the setting is empty. A bad value stops the start-up with a clear sentence."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not (value > 0) or math.isinf(value) or (whole and value != int(value)):
        kind = "a whole number" if whole else "a positive number"
        raise SystemExit(f'{name} in .env must be {kind}, like {"20" if whole else "3.00"} (it is "{raw[:30]}").')
    return int(value) if whole else value


class DailyBudget:
    """One spending cap shared by every visitor, counted per UTC day."""

    def __init__(self, limit_usd: float, clock=time.time):
        self.limit, self.clock = float(limit_usd), clock
        self.day, self.spent = int(clock() // DAY), 0.0

    def _roll(self) -> None:
        today = int(self.clock() // DAY)
        if today != self.day:
            self.day, self.spent = today, 0.0

    def add(self, usd) -> None:
        if isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd <= 0:
            return
        self._roll()
        self.spent += usd

    def exhausted(self) -> bool:
        self._roll()
        return self.spent >= self.limit

    def seconds_until_reset(self) -> int:
        return int(DAY - self.clock() % DAY)


class RateLimiter:
    """At most `per_hour` questions per visitor in any rolling hour."""

    def __init__(self, per_hour: int, clock=time.time):
        self.per_hour, self.clock = int(per_hour), clock
        self.seen: OrderedDict[str, deque] = OrderedDict()

    def _recent(self, key: str) -> deque:
        now, q = self.clock(), self.seen.get(key)
        if q is None:
            return deque()
        while q and now - q[0] >= 3600:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """0 when this visitor may ask now, else the seconds until the oldest question of the hour falls out of the window."""
        q = self._recent(key)
        if len(q) < self.per_hour:
            return 0
        return max(1, int(math.ceil(3600 - (self.clock() - q[0]))))

    def record(self, key: str) -> None:
        q = self._recent(key)
        q.append(self.clock())
        self.seen[key] = q
        self.seen.move_to_end(key)
        while len(self.seen) > MAX_TRACKED_VISITORS:
            self.seen.popitem(last=False)


def visitor_address(scope: dict, trust_proxy: bool) -> str:
    """Who is asking. Behind a hosting proxy the real address is the LAST entry of X-Forwarded-For (the one the proxy itself added; earlier
    entries can be written by the visitor), so only trust it when TRUST_PROXY is on."""
    if trust_proxy:
        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-for":
                last = value.decode("latin-1").split(",")[-1].strip()
                if last:
                    return last[:64]
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def minutes_text(seconds: int) -> str:
    minutes = max(1, int(math.ceil(seconds / 60)))
    return "a minute" if minutes == 1 else f"{minutes} minutes"


class Limits:
    """The settings from .env, ready to use. `Limits()` with nothing set protects nothing."""

    def __init__(self, daily_budget_usd=None, per_hour=None, trust_proxy: bool = False, max_conversations=None, clock=time.time):
        self.budget = DailyBudget(daily_budget_usd, clock) if daily_budget_usd else None
        self.limiter = RateLimiter(per_hour, clock) if per_hour else None
        self.trust_proxy, self.max_conversations = trust_proxy, max_conversations

    @classmethod
    def from_env(cls, environ=os.environ, clock=time.time) -> "Limits":
        return cls(_positive(environ.get("DAILY_BUDGET_USD"), "DAILY_BUDGET_USD"), _positive(environ.get("RATE_LIMIT_PER_HOUR"), "RATE_LIMIT_PER_HOUR", whole=True),
                   str(environ.get("TRUST_PROXY", "")).strip().lower() in ("on", "1", "true", "yes"),
                   _positive(environ.get("MAX_CONVERSATIONS"), "MAX_CONVERSATIONS", whole=True), clock)

    @property
    def active(self) -> bool:
        return bool(self.budget or self.limiter)

    def describe(self) -> str:
        parts = []
        if self.budget:
            parts.append(f"${self.budget.limit:.2f} per day for all visitors")
        if self.limiter:
            parts.append(f"{self.limiter.per_hour} questions per hour per visitor")
        return ", ".join(parts)

    def refusal(self, scope: dict):
        """None if the question may go ahead, else (status, message, retry_after_seconds)."""
        if self.budget and self.budget.exhausted():
            wait = self.budget.seconds_until_reset()
            return (503, "This demo has reached its spending limit for today and starts again at midnight UTC. "
                         "To keep going now, run it yourself with your own API key (see the README).", wait)
        if self.limiter:
            wait = self.limiter.retry_after(visitor_address(scope, self.trust_proxy))
            if wait:
                return (429, f"That is a lot of questions in an hour. Please try again in about {minutes_text(wait)}.", wait)
        return None

    def accepted(self, scope: dict) -> None:
        """Call once a question has really been handed to the assistant."""
        if self.limiter:
            self.limiter.record(visitor_address(scope, self.trust_proxy))

    def spent(self, usd, checked: bool = False) -> None:
        """Call with the cost of one finished answer (and whether the fact-checker also ran)."""
        if self.budget:
            self.budget.add((usd or 0) + (FACT_CHECKER_ALLOWANCE_USD if checked else 0))
