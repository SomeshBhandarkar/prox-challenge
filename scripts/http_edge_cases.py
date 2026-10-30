"""Real-HTTP edge cases against a RUNNING server (not the in-process test client): odd paths, odd bodies, odd headers, many conversations at once.

    .venv/bin/python -m scripts.dev_server --port 8135 &        (canned answers: no key, no cost)
    .venv/bin/python -m scripts.http_edge_cases http://localhost:8135

It also works against the real app (python3 run.py --no-open --port 8000), where every question costs money, so use --no-questions there.
Prints PASS/FAIL lines and exits with 1 if anything failed. The server must still be healthy at the end.
"""
import argparse
import base64
import http.client
import json
import socket
import sys
import threading
import time
from urllib.parse import urlparse

SECRETS = ("ANTHROPIC_API_KEY", "sk-ant", "def create_app", "import uvicorn", "SESSION_BUDGET", "# Prox challenge")
fails = 0
total = 0


def check(name, ok, detail=""):
    global fails, total
    total += 1
    fails += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + name + (f"   [{str(detail)[:200]}]" if detail else ""), flush=True)


JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 40 + b"\xff\xd9").decode()   # starts like a real JPEG


def raw(host, port, request: bytes, wait=3.0):
    """Send exact bytes (so nothing tidies an odd path) and return (status, headers, body)."""
    data = b""
    with socket.create_connection((host, port), timeout=wait) as s:
        try:
            s.sendall(request)
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > 2_000_000:
                    break
        except socket.timeout:
            pass
        except (ConnectionResetError, BrokenPipeError):
            pass   # the server hung up on us: a refusal (status 0 below)
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError):
        status = 0
    headers = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
    return status, headers, body


def request(host, port, method, path, body=None, headers=None, timeout=10):
    c = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        c.close()


def chat(host, port, message, session_id=None, read_all=True, timeout=30):
    """POST /api/chat and return (status, list of (event, data))."""
    c = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        c.request("POST", "/api/chat", body=json.dumps({"message": message, "session_id": session_id}), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        if r.status != 200:
            return r.status, [("http", r.read()[:200].decode("utf-8", "replace"))]
        events, name, data = [], "message", []
        for line in r.read().decode("utf-8", "replace").split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif not line.strip() and data:
                try:
                    events.append((name, json.loads("\n".join(data))))
                except ValueError:
                    events.append((name, "unparsable"))
                name, data = "message", []
        return 200, events
    finally:
        c.close()


def healthy(host, port):
    try:
        s, _, b = request(host, port, "GET", "/api/health")
        return s == 200 and json.loads(b).get("ok") is True
    except Exception:  # noqa: BLE001
        return False


def main():
    global fails
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="for example http://localhost:8135")
    ap.add_argument("--no-questions", action="store_true", help="skip everything that asks a question (those cost money on the real app)")
    a = ap.parse_args()
    u = urlparse(a.base)
    host, port = u.hostname, u.port or 80
    if not healthy(host, port):
        print("the server is not answering /api/health")
        return 2

    # ---------------- paths
    print("--- odd paths (sent as exact bytes, so nothing normalises them)")
    paths = ["/static/../app/server.py", "/static/%2e%2e/app/server.py", "/static/..%2fapp/server.py", "/static/%2e%2e%2f%2e%2e%2f.env",
             "/static/..\\..\\.env", "/static/%00.js", "/static//etc/passwd", "/static/....//....//.env", "/.env", "/CLAUDE.md", "/app/server.py",
             "/run.py", "/knowledge/data/caveats.json", "/figures/../../.env", "/figures/%2e%2e%2f.env.png", "/figures/nope.png", "/figures/.png",
             "/pages/0.jpg", "/pages/49.jpg", "/pages/-1.jpg", "/pages/abc.jpg", "/pages/1.jpg/../../.env", "/embed/../../etc/passwd",
             "/embed/doesnotexist", "/static/", "/static", "//", "/%", "/%zz", "/" + "a" * 5000, "/static/" + "a" * 300, "/static/" + "a/" * 400 + "b.js"]
    for p in paths:
        try:
            status, _, body = raw(host, port, f"GET {p} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("latin-1", "replace"))
        except OSError as e:
            check(f"path {p[:50]!r}", True, f"connection closed ({e.__class__.__name__}): acceptable")
            continue
        leaked = [s for s in SECRETS if s.encode() in body]
        check(f"path {p[:50]!r} is refused and leaks nothing", status in (301, 307, 308, 400, 404, 405, 414, 422) and not leaked, f"status {status} leaked {leaked}")
    check("the server is still healthy after the odd paths", healthy(host, port))

    # ---------------- methods and headers
    print("--- methods, headers")
    s, _, _ = request(host, port, "GET", "/api/chat")
    check("GET /api/chat is refused (it is a POST endpoint)", s == 405, s)
    s, _, _ = request(host, port, "POST", "/")
    check("POST / is refused", s == 405, s)
    s, h, _ = request(host, port, "OPTIONS", "/api/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    check("a cross-origin preflight gets no CORS permission", "access-control-allow-origin" not in h, f"{s} {h.get('access-control-allow-origin')}")
    s, h, _ = request(host, port, "POST", "/api/chat", body=json.dumps({"message": "hi"}), headers={"Content-Type": "text/plain", "Origin": "https://evil.example"})
    check("a cross-site text/plain post is refused", 400 <= s < 500 and "access-control-allow-origin" not in h, s)
    status, _, _ = raw(host, port, (f"GET / HTTP/1.1\r\nHost: {host}\r\nX-Big: " + "a" * 200000 + "\r\nConnection: close\r\n\r\n").encode())
    check("a 200 KB header is refused or closed, not accepted", status in (0, 400, 413, 431), status)
    status, _, _ = raw(host, port, f"GET / HTTP/1.1\r\nHost: {host}\r\n{chr(10).join(f'X-{i}: 1' for i in range(300))}\r\nConnection: close\r\n\r\n".replace("\n", "\r\n").encode())
    check("300 extra headers do not crash it", status in (0, 200, 400, 431), status)
    status, _, _ = raw(host, port, b"NOTHTTP\r\n\r\n")
    check("garbage that is not HTTP is refused", status in (0, 400), status)
    check("the server is still healthy after the odd requests", healthy(host, port))

    # ---------------- bodies
    print("--- odd bodies on /api/chat (all must be clean 4xx, never 500)")
    J = {"Content-Type": "application/json"}
    bodies = {
        "empty body": b"", "not json": b"{nope", "a json list": b"[1,2,3]", "json null": b"null", "message is a number": b'{"message": 5}',
        "message is a list": b'{"message": ["a"]}', "empty message": b'{"message": ""}', "whitespace message": b'{"message": "   "}',
        "message of 2001 characters": json.dumps({"message": "x" * 2001}).encode(), "invalid UTF-8": b'{"message": "\xff\xfe\xfd"}',
        "5 MB body": b'{"message": "' + b"x" * 5_000_000 + b'"}', "deeply nested json": b'{"message": ' + b"[" * 5000 + b"]" * 5000 + b"}",
        "session id is a huge string": json.dumps({"message": "hi", "session_id": "s" * 100000}).encode(),
        "session id is a number": b'{"message": "hi", "session_id": 123}', "session id is an object": b'{"message": "hi", "session_id": {"a": 1}}',
        # photos: every one of these is refused before anything could reach the model
        "photo is a string": b'{"message": "hi", "image": "abc"}',
        "photo labelled as HTML": json.dumps({"message": "hi", "image": {"media_type": "text/html", "data": JPEG_B64}}).encode(),
        "photo labelled SVG (can carry script)": json.dumps({"message": "hi", "image": {"media_type": "image/svg+xml", "data": JPEG_B64}}).encode(),
        "photo whose bytes are not what its label says": json.dumps({"message": "hi", "image": {"media_type": "image/png", "data": JPEG_B64}}).encode(),
        "photo that is not base64": json.dumps({"message": "hi", "image": {"media_type": "image/jpeg", "data": "***not base64***"}}).encode(),
        "photo of 5 MB": json.dumps({"message": "hi", "image": {"media_type": "image/jpeg", "data": base64.b64encode(b"\xff\xd8\xff" + b"0" * 5_000_000).decode()}}).encode(),
        "photo of 30 MB of text": json.dumps({"message": "hi", "image": {"media_type": "image/jpeg", "data": "A" * 30_000_000}}).encode(),
    }
    for name, body in bodies.items():
        try:
            s, _, _ = request(host, port, "POST", "/api/chat", body=body, headers=J, timeout=20)
        except (OSError, http.client.HTTPException) as e:
            check(f"body: {name}", True, f"connection closed ({e.__class__.__name__}): acceptable")
            continue
        check(f"body: {name} -> clean 4xx", 400 <= s < 500, s)
    check("the server is still healthy after the odd bodies", healthy(host, port))

    if a.no_questions:
        print(f"\n{'ALL ' + str(total) + ' CHECKS PASSED' if not fails else str(fails) + ' of ' + str(total) + ' CHECKS FAILED'}")
        return 1 if fails else 0

    # ---------------- conversations
    print("--- conversations (these send real questions: free on the demo server)")
    status, body_text = None, ""
    try:
        s_, _, body = request(host, port, "POST", "/api/chat", body=json.dumps({"message": "what is wrong with this weld?", "image": {"media_type": "image/jpeg", "data": JPEG_B64}}), headers=J, timeout=30)
        status, body_text = s_, body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    except (OSError, http.client.HTTPException) as e:
        body_text = str(e)
    check("a real-looking photo with a question is accepted and answered", status == 200 and "event: done" in body_text and JPEG_B64 not in body_text, status)
    status, ev = chat(host, port, "duty cycle please")
    names = [n for n, _ in ev]
    check("one question streams session -> status -> text -> show -> done", status == 200 and names[0] == "session" and names[-1] == "done" and "text" in names and "show" in names, names)
    sid = ev[0][1]["session_id"] if ev else None
    status2, ev2 = chat(host, port, "figure please", session_id=sid)
    check("a second question resumes the same conversation", status2 == 200 and ev2[0][1].get("resumed") is True and ev2[0][1]["session_id"] == sid)
    status3, ev3 = chat(host, port, "hello", session_id="forgotten-id")
    check("a conversation id the server does not know starts fresh (resumed: false)", status3 == 200 and ev3[0][1].get("resumed") is False)

    results = {}

    def ask_slow(key, sid_):
        results[key] = chat(host, port, "slow one", session_id=sid_, timeout=30)[0]

    _, evs = chat(host, port, "hi")
    sid2 = evs[0][1]["session_id"]
    t1 = threading.Thread(target=ask_slow, args=("a", sid2))
    t1.start()
    time.sleep(0.6)
    t2 = threading.Thread(target=ask_slow, args=("b", sid2))
    t2.start()
    t1.join(); t2.join()
    check("two questions at once on one conversation: one 200 and one 409", sorted(results.values()) == [200, 409], results)

    results.clear()
    threads = [threading.Thread(target=lambda i=i: results.__setitem__(i, chat(host, port, "duty cycle please", timeout=60)[0])) for i in range(14)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    codes = sorted(results.values())
    check("14 conversations at once: every one is 200 or a clean 503, never 500", all(c in (200, 503) for c in codes) and codes.count(200) >= 10, codes)
    check("the server is still healthy after 14 at once", healthy(host, port))

    s, _, b = request(host, port, "POST", "/api/reset", body=json.dumps({"session_id": "never-existed"}), headers=J)
    check("resetting a conversation that does not exist is harmless", s in (200, 204, 404), s)
    s, _, _ = request(host, port, "POST", "/api/reset", body=b"garbage", headers=J)
    check("a garbage reset body is a clean 4xx", 400 <= s < 500, s)

    # a client that drops the connection mid-answer
    sock = socket.create_connection((host, port), timeout=5)
    body = json.dumps({"message": "slow one", "session_id": None}).encode()
    sock.sendall(f"POST /api/chat HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
    sock.recv(200)
    sock.close()
    time.sleep(4)
    check("a client that hangs up mid-answer does not hurt the server", healthy(host, port))

    print(f"\n{'ALL ' + str(total) + ' CHECKS PASSED' if not fails else str(fails) + ' of ' + str(total) + ' CHECKS FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
