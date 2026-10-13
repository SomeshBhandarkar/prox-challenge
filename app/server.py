"""The website's server: the chat (server-sent events), the manual pictures, and the sandboxed frames for widgets and drawings.

    .venv/bin/python -m app.server            (python3 run.py does this for you)

How a question travels: the page POSTs to /api/chat; this file hands it to that conversation's agent, and streams back events:
  session (the conversation id) | status (what the agent is doing) | text (a piece of the answer) |
  show (a picture, widget or drawing to display) | error | done.
Widgets and drawings are never sent through the stream: they are stored under a random token and served at /embed/<token>, so the
page can put them in a frame with sandbox="allow-scripts" (no access to the page, cookies or network).
"""
import argparse
import asyncio
import json
import os
import re
import secrets
import socket
import threading
import time
import webbrowser
from collections import OrderedDict
from contextlib import asynccontextmanager

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock, ToolUseBlock
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders

from app.agent import make_options, require_api_key, resolve_model
from app.knowledge import ROOT
from app.show import PREFIX, render_show
from app.tools.figures import BY_ID, DEFAULT_PDF, FIGURES_DIR, pdf_of

WEB = ROOT / "web"
PAGES_DIR = ROOT / "knowledge" / "pages"
MANUAL_PAGES = 48
MAX_QUESTION_CHARS = 2000  # a pasted wall of text would cost real money
MAX_SESSIONS = 10          # each conversation runs its own Claude process
IDLE_SECONDS = 30 * 60
MAX_EMBEDS = 200
DEFAULT_SESSION_BUDGET_USD = 1.00  # per conversation; set SESSION_BUDGET_USD in .env to change it
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# Widgets and drawings come from our own tools and from the model. Whatever they contain, this keeps them in a box.
EMBED_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
             "font-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")

STATUS = {
    "duty_cycle": "Checking the duty cycle data",
    "polarity": "Looking up which cable goes where",
    "view_manual_page": "Reading a page of the manual",
    "show_figure": "Finding the picture in the manual",
    "show_polarity_diagram": "Drawing the cable diagram",
    "show_duty_cycle_calculator": "Building the duty cycle calculator",
    "show_troubleshooting_flowchart": "Building the troubleshooting flowchart",
    "show_setup_guide": "Putting the setup sheet together",
    "create_artifact": "Drawing a custom diagram",
}
STOPPED = {
    "error_max_budget_usd": "This conversation reached its spending limit. Start a new chat to keep going.",
    "error_max_turns": "That took too many steps and I had to stop. Try asking in smaller pieces.",
}
HINTS = {
    "authentication_failed": "The API key was refused. Check ANTHROPIC_API_KEY in .env, then restart.",
    "billing_error": "The Anthropic account has no credit left. Check the billing page for this API key.",
    "rate_limit": "Anthropic is rate limiting this key. Wait a moment and try again.",
}


# ---------- what goes over the wire ----------
def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Embeds:
    """The most recent widgets and drawings, by random token. Old ones fall out so memory stays small."""

    def __init__(self, limit: int = MAX_EMBEDS):
        self.limit, self.items = limit, OrderedDict()

    def add(self, html: str) -> str:
        token = secrets.token_urlsafe(16)
        self.items[token] = html
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return token

    def get(self, token: str) -> str | None:
        html = self.items.get(token)
        if html is not None:
            self.items.move_to_end(token)
        return html


def public(shown: dict, embeds: Embeds) -> dict:
    """What the page needs to display one shown item. HTML stays on the server; the page gets a link to a sandboxed frame."""
    kind = shown["kind"]
    if kind == "figure":
        f = BY_ID.get(shown["id"], {})
        page = f.get("page") if f and pdf_of(f) == DEFAULT_PDF else None
        return {"kind": "figure", "id": shown["id"], "caption": shown["caption"], "source": shown["source"],
                "url": shown["url"], "manual_page": page}
    if kind in ("widget", "artifact"):
        out = {"kind": kind, "tool": shown["tool"], "title": shown["title"], "embed": "/embed/" + embeds.add(shown["html"])}
        if kind == "artifact":
            out["identifier"] = shown["identifier"]
        return out
    detail = str(shown["message"])  # written for the model, so the page shows a short plain sentence and keeps this only for debugging
    return {"kind": "error", "tool": shown["tool"], "message": "I couldn't show a picture there." if shown["tool"] == "show_figure" else "I couldn't draw that one.",
            "detail": detail if len(detail) <= 200 else detail[:197] + "..."}


def events_for(message, embeds: Embeds, seen: set | None = None) -> list[tuple[str, dict]]:
    """Turn one SDK message into zero or more (event, data) pairs for the page.
    `seen` holds what this answer already showed, so the same picture or widget is never shown twice in one answer."""
    seen = set() if seen is None else seen
    out: list[tuple[str, dict]] = []
    if isinstance(message, AssistantMessage):
        if message.error:
            out.append(("error", {"message": HINTS.get(message.error, f"The assistant reported a problem ({message.error})."),
                                  "code": str(message.error)}))
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                out.append(("text", {"text": block.text.strip()}))
            elif isinstance(block, ToolUseBlock) and isinstance(block.name, str) and block.name.startswith(PREFIX):
                shown = render_show(block.name, block.input)
                if shown is not None and shown.get("silent"):
                    continue  # a refused placeholder: nothing for the person to see
                key = (block.name, json.dumps(block.input, sort_keys=True, default=str))
                if shown is not None and key in seen:
                    continue  # the same call again in this answer
                seen.add(key)
                out.append(("status", {"text": STATUS.get(block.name[len(PREFIX):], "Working on it")}))
                if shown is not None:
                    out.append(("show", public(shown, embeds)))
    elif isinstance(message, ResultMessage):
        if message.is_error or message.subtype != "success":
            out.append(("error", {"message": STOPPED.get(message.subtype, "Something went wrong while answering."),
                                  "code": message.subtype, "fatal": message.subtype == "error_max_budget_usd"}))
        out.append(("done", {"ok": not message.is_error and message.subtype == "success", "cost_usd": message.total_cost_usd}))
    return out


# ---------- one conversation = one worker task ----------
class Session:
    """One conversation. All calls to the SDK client happen inside one background task: the client must be opened and closed by the
    same task, and every web request runs in a different one. Requests hand their question to the worker through a queue."""

    def __init__(self, sid: str, client_factory, options_factory, embeds: Embeds, clock=time.monotonic):
        self.id, self.client_factory, self.options_factory, self.embeds, self.clock = sid, client_factory, options_factory, embeds, clock
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.pending = 0       # questions handed over and not yet finished (0 or 1)
        self.closing = False   # no new questions; the worker stops after the current one
        self.dead = False      # the worker has stopped
        self.last_used = clock()
        self.task = asyncio.get_running_loop().create_task(self._run())

    @property
    def busy(self) -> bool:
        return self.pending > 0

    def submit(self, message: str) -> asyncio.Queue | None:
        """Hand a question to the worker. Returns the queue its events arrive on (None marks the end), or None if still answering."""
        if self.pending or self.closing or self.dead:
            return None
        self.pending += 1
        self.last_used = self.clock()
        out: asyncio.Queue = asyncio.Queue()
        self.inbox.put_nowait((message, out))
        return out

    def close(self) -> None:
        if not self.closing:
            self.closing = True
            self.inbox.put_nowait(None)

    async def _answer(self, client, message: str, out: asyncio.Queue) -> None:
        sent_error, seen = False, set()
        try:
            await client.query(message)
            async for sdk_message in client.receive_response():
                for event, data in events_for(sdk_message, self.embeds, seen):
                    if event == "error":
                        if sent_error and not data.get("fatal"):
                            continue  # one explanation per answer is enough
                        sent_error = True
                        if data.get("fatal"):
                            self.closing = True  # the spending limit stays used up: this conversation is over
                    out.put_nowait((event, data))
        except Exception as e:  # noqa: BLE001
            self.closing = True  # after a failure the conversation state is unknown: start clean next time
            out.put_nowait(("error", {"message": f"Something went wrong talking to Claude ({type(e).__name__}). Check the terminal "
                                                 "where the server is running.", "code": "exception", "fatal": True}))
            out.put_nowait(("done", {"ok": False, "cost_usd": None}))

    async def _run(self) -> None:
        try:
            async with self.client_factory(options=self.options_factory()) as client:
                while True:
                    job = await self.inbox.get()
                    if job is None:
                        return
                    message, out = job
                    try:
                        await self._answer(client, message, out)
                    finally:
                        out.put_nowait(None)
                        self.pending -= 1
                        self.last_used = self.clock()
                    if self.closing:
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  (could not start the agent, or it died)
            self.closing = True
            reason = HINTS["authentication_failed"] if "uthentic" in str(e) else (
                f"Could not start the assistant ({type(e).__name__}). Check ANTHROPIC_API_KEY in .env and the terminal where the server runs.")
            while not self.inbox.empty():
                job = self.inbox.get_nowait()
                if job is not None:
                    _, out = job
                    out.put_nowait(("error", {"message": reason, "code": "start_failed", "fatal": True}))
                    out.put_nowait(("done", {"ok": False, "cost_usd": None}))
                    out.put_nowait(None)
                    self.pending -= 1
        finally:
            self.dead = True


class Sessions:
    """All open conversations: idle ones expire, and there is a cap so a stray script cannot start unlimited Claude processes."""

    def __init__(self, client_factory, options_factory, embeds: Embeds, limit: int = MAX_SESSIONS, idle: float = IDLE_SECONDS, clock=time.monotonic):
        self.client_factory, self.options_factory, self.embeds = client_factory, options_factory, embeds
        self.limit, self.idle, self.clock = limit, idle, clock
        self.items: OrderedDict[str, Session] = OrderedDict()

    def sweep(self) -> None:
        now = self.clock()
        for sid, s in list(self.items.items()):
            if s.dead or (not s.busy and now - s.last_used > self.idle):
                s.close()
                del self.items[sid]

    def get_or_create(self, sid) -> Session | None:
        """The conversation with this id, or a fresh one (also when the id is unknown or expired). None when every slot is busy."""
        self.sweep()
        s = self.items.get(sid) if isinstance(sid, str) else None
        if s is not None and not s.closing:
            self.items.move_to_end(sid)
            return s
        if s is not None:
            self.items.pop(sid, None)
        while len(self.items) >= self.limit:
            oldest_idle = next((k for k, v in self.items.items() if not v.busy), None)
            if oldest_idle is None:
                return None
            self.items.pop(oldest_idle).close()
        new = Session(secrets.token_urlsafe(9), self.client_factory, self.options_factory, self.embeds, self.clock)
        self.items[new.id] = new
        return new

    def drop(self, sid) -> bool:
        s = self.items.pop(sid, None) if isinstance(sid, str) else None
        if s is not None:
            s.close()
        return s is not None

    async def close_all(self) -> None:
        sessions = list(self.items.values())
        self.items.clear()
        for s in sessions:
            s.close()
        if sessions:
            await asyncio.wait([s.task for s in sessions], timeout=5)
            for s in sessions:
                if not s.task.done():
                    s.task.cancel()


# ---------- the web app ----------
class SafeHeaders:
    """Adds two harmless headers to every response. A plain ASGI middleware, so streamed answers are never held back."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def add_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
            await send(message)

        await self.app(scope, receive, add_headers)


class ChatIn(BaseModel):
    message: str = Field(max_length=MAX_QUESTION_CHARS)
    session_id: str | None = Field(default=None, max_length=64)


class ResetIn(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def session_budget(environ=os.environ) -> float:
    raw = str(environ.get("SESSION_BUDGET_USD", "")).strip()
    if not raw:
        return DEFAULT_SESSION_BUDGET_USD
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not value > 0 or value == float("inf"):
        raise SystemExit(f'SESSION_BUDGET_USD in .env must be a positive number of dollars, like 1.00 (it is "{raw[:30]}").')
    return value


def create_app(client_factory=ClaudeSDKClient, options_factory=None, model: str | None = None, budget: float | None = None,
               limit: int = MAX_SESSIONS, idle: float = IDLE_SECONDS, clock=time.monotonic) -> FastAPI:
    model_id = resolve_model(model)
    cap = session_budget() if budget is None else budget
    options_factory = options_factory or (lambda: make_options(model_id, cap))
    embeds = Embeds()
    sessions = Sessions(client_factory, options_factory, embeds, limit, idle, clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await sessions.close_all()

    app = FastAPI(title="Vulcan OmniPro 220 assistant", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.sessions, app.state.embeds, app.state.model = sessions, embeds, model_id

    app.add_middleware(SafeHeaders)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return _error(422, f"Send a message of 1 to {MAX_QUESTION_CHARS} characters.")

    @app.get("/")
    async def index():
        page = WEB / "index.html"
        if not page.is_file():
            return _error(404, "The page is missing (web/index.html).")
        return FileResponse(page, media_type="text/html", headers={"Content-Security-Policy": PAGE_CSP, "X-Frame-Options": "DENY",
                                                                    "Cache-Control": "no-cache"})

    @app.get("/static/{name:path}")
    async def static(name: str):
        root = (WEB / "static").resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return _error(404, "No such file.")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    async def health():
        try:
            require_api_key()
            key = True
        except SystemExit:
            key = False
        return {"ok": True, "model": model_id, "key": key}

    @app.get("/figures/{figure_id}.png")
    async def figure(figure_id: str):
        if not re.fullmatch(r"[a-z0-9-]+", figure_id) or figure_id not in BY_ID or not (FIGURES_DIR / f"{figure_id}.png").is_file():
            return _error(404, "No such picture.")
        return FileResponse(FIGURES_DIR / f"{figure_id}.png", media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/pages/{number}.jpg")
    async def manual_page(number: str):
        if not re.fullmatch(r"\d{1,2}", number) or not 1 <= int(number) <= MANUAL_PAGES:
            return _error(404, "The manual has pages 1 to 48.")
        path = PAGES_DIR / f"page-{int(number):02d}.jpg"
        if not path.is_file():
            return _error(404, "No such page.")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/embed/{token}")
    async def embed(token: str):
        html = embeds.get(token) if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token) else None
        if html is None:
            return _error(404, "That drawing is no longer available. Ask again to redraw it.")
        return HTMLResponse(html, headers={"Content-Security-Policy": EMBED_CSP, "Cache-Control": "no-store"})

    @app.post("/api/chat")
    async def chat(body: ChatIn):
        message = body.message.strip()
        if not message:
            return _error(422, f"Send a message of 1 to {MAX_QUESTION_CHARS} characters.")
        session = sessions.get_or_create(body.session_id)
        if session is None:
            return _error(503, "The server is busy with other conversations. Try again in a moment.")
        out = session.submit(message)
        if out is None:
            return _error(409, "Still answering the last question. Wait for it to finish.")

        async def stream():
            yield sse("session", {"session_id": session.id, "resumed": session.id == body.session_id})
            while True:
                item = await out.get()
                if item is None:
                    return
                yield sse(*item)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/reset")
    async def reset(body: ResetIn):
        return {"ok": True, "closed": sessions.drop(body.session_id)}

    return app


# ---------- starting it ----------
def find_free_port(host: str, start: int, tries: int = 20) -> int:
    """The first port from `start` that nothing is using, so a busy 8000 never stops the app from starting."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"No free port between {start} and {start + tries - 1}. Set APP_PORT in .env to another number.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="app.server", description="Run the Vulcan OmniPro 220 assistant website.")
    p.add_argument("--model", default=None, help="haiku, sonnet or opus (default: MODEL in .env, then opus)")
    p.add_argument("--host", default=os.environ.get("APP_HOST", "").strip() or "127.0.0.1")
    p.add_argument("--port", type=int, default=None, help="default: APP_PORT in .env, then 8000 (the next free port is used if busy)")
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = p.parse_args(argv)
    try:
        args.model_id = resolve_model(args.model)
    except ValueError as e:
        p.error(str(e))
    if args.port is None:
        raw = os.environ.get("APP_PORT", "").strip() or "8000"
        if not raw.isdigit():
            p.error(f'APP_PORT in .env must be a number, like 8000 (it is "{raw[:20]}")')
        args.port = int(raw)
    if not 1 <= args.port <= 65535:
        p.error("the port must be between 1 and 65535")
    return args


def main(argv: list[str] | None = None) -> None:
    import sys
    import uvicorn

    args = parse_args(sys.argv[1:] if argv is None else argv)
    require_api_key()
    cap = session_budget()
    port = find_free_port(args.host, args.port)
    url = f"http://{'localhost' if args.host in LOCAL_HOSTS else args.host}:{port}"
    print(f"Vulcan OmniPro 220 assistant ({args.model_id}, up to ${cap:.2f} per conversation) is at {url}", flush=True)
    if args.host not in LOCAL_HOSTS:
        print(f"WARNING: {args.host} makes this page reachable from other machines, and every visitor spends YOUR API key.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(create_app(model=args.model_id, budget=cap), host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
