#!/usr/bin/env python3
"""Single-user cloud workbench, Python standard library only."""
import base64
import io
import json
import mimetypes
import os
import re
import signal
import sqlite3
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, quote

import agent
import transport

ROOT = Path(__file__).resolve().parent


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip("\"'"))


load_env()
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
MAX_UPLOAD = 10 * 1024 * 1024
MAX_FILES_TOTAL = 100 * 1024 * 1024
ACTIVE = {}
LOCK = threading.RLock()
STOPPING = threading.Event()
BRIDGE_TOKEN = uuid.uuid4().hex + uuid.uuid4().hex


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def db():
    conn = sqlite3.connect(DATA / "workbench.sqlite", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT REFERENCES sessions(id),role TEXT,content TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),status TEXT,started_at TEXT,finished_at TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT REFERENCES sessions(id),run_id TEXT REFERENCES runs(id),payload TEXT,created_at TEXT);
        CREATE INDEX IF NOT EXISTS events_session ON events(session_id,id);
        """)
        pending = c.execute("SELECT id,session_id FROM runs WHERE status='running'").fetchall()
        for r in pending:
            err = "服务重启导致任务中断；已保留会话和文件，可发送消息继续。"
            c.execute("UPDATE runs SET status='interrupted',finished_at=?,error=? WHERE id=?", (now(), err, r["id"]))
            c.execute("INSERT INTO events(session_id,run_id,payload,created_at) VALUES(?,?,?,?)",
                      (r["session_id"], r["id"], json.dumps({"kind": "done", "status": "interrupted", "text": err}, ensure_ascii=False), now()))


def workspace(sid):
    if not re.fullmatch(r"[a-f0-9]{32}", sid):
        raise ValueError("无效会话")
    with db() as c:
        if not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
            raise FileNotFoundError("会话不存在")
    return DATA / "sessions" / sid / "workspace"


def checked_file(root, rel, must_exist=True):
    if not rel or "\x00" in rel or "\\" in rel:
        raise ValueError("无效文件路径")
    raw = Path(rel)
    if raw.is_absolute() or any(part in ("..", ".") for part in raw.parts):
        raise ValueError("禁止访问工作区外的文件")
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("不允许访问符号链接")
    target = current.resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("禁止访问工作区外的文件")
    if must_exist and not target.is_file():
        raise FileNotFoundError("文件不存在")
    return target


def file_list(root):
    files = []
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__") and not (Path(folder) / d).is_symlink()]
        for name in names:
            p = Path(folder) / name
            if p.is_symlink() or name.startswith("."):
                continue
            files.append({"path": p.relative_to(root).as_posix(), "size": p.stat().st_size})
            if len(files) >= 1000:
                return sorted(files, key=lambda f: f["path"])
    return sorted(files, key=lambda f: f["path"])


def emit(sid, rid, payload):
    with db() as c:
        c.execute("INSERT INTO events(session_id,run_id,payload,created_at) VALUES(?,?,?,?)",
                  (sid, rid, json.dumps(payload, ensure_ascii=False), now()))


def end_process(proc):
    if proc is not None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        # Also reap tools that outlive the CLI leader.
        def kill():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        timer = threading.Timer(2, kill)
        timer.daemon = True
        timer.start()


def worker(sid, rid, state):
    proc = None
    answers = []
    error = ""
    status = "failed"
    timer = None
    try:
        with db() as c:
            messages = [dict(r) for r in c.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id", (sid,))]
        ws = workspace(sid)
        emit(sid, rid, {"kind": "status", "text": "正在连接模型并准备独立工作区…"})
        with LOCK:
            if state["stop"]:
                raise RuntimeError("任务已取消")
            compat = os.environ.get("MODEL_COMPAT_MODE", "1") == "1"
            bridge = "http://127.0.0.1:" + os.environ.get("APP_PORT", "8080") + "/__model/v1"
            proc = agent.launch(ws, DATA / "sessions" / sid / "control", messages,
                                bridge if compat else None, BRIDGE_TOKEN if compat else None)
            state["process"] = proc
        def timeout():
            with LOCK:
                state["stop"] = "timeout"
                end_process(proc)
        timer = threading.Timer(int(os.environ.get("RUN_TIMEOUT_SECONDS", "600")), timeout)
        timer.daemon = True
        timer.start()
        n = 0
        failed_event = False
        completed = False
        for line in proc.stdout:
            n += 1
            if n > 4000 or len(line) > 1000000:
                state["stop"] = "limit"
                end_process(proc)
                break
            event = agent.normalize(line)
            if event:
                if event["kind"] == "answer":
                    answers.append(event["text"])
                if event["kind"] == "error":
                    error = event["text"]
                    failed_event = True
                if event["kind"] == "usage":
                    completed = True
                emit(sid, rid, event)
        code = proc.wait()
        if state["stop"]:
            status = "cancelled" if state["stop"] == "cancelled" else "failed"
            error = {"cancelled": "任务已停止。已生成文件仍可下载，发送新消息可继续。", "timeout": "任务超时，已停止执行。请拆分任务后继续。", "limit": "执行日志超过安全上限，任务已停止。"}.get(state["stop"], "任务已停止")
        elif code != 0 or failed_event or not completed or not answers:
            error = error or f"Codex 未正常完成（退出码 {code}）；请检查模型配置与运行日志后重试。"
        else:
            status = "completed"
    except Exception as exc:
        error = agent.redact(str(exc))
        if state["stop"] == "cancelled":
            status = "cancelled"
    finally:
        if timer:
            timer.cancel()
        end_process(proc)
        if proc:
            proc.wait()
        with LOCK:
            with db() as c:
                if answers:
                    c.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                              (sid, "assistant", "\n\n".join(answers), now()))
                c.execute("UPDATE runs SET status=?,finished_at=?,error=? WHERE id=?", (status, now(), error, rid))
                c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now(), sid))
            emit(sid, rid, {"kind": "done", "status": status, "text": error or "任务完成，成果已保存。"})
            ACTIVE.pop(sid, None)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass  # No credentials or user prompts in access logs.

    def send(self, status=200, body=None, mime="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        body = body or b""
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        # Prevent cross-origin mutation and DNS-rebinding against a local service.
        host = self.headers.get("Host", "")
        if host.split(":")[0] not in ("127.0.0.1", "localhost", os.environ.get("APP_ALLOWED_HOST", "")):
            self.send(403, {"error": "Host 不允许访问"})
            return False
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != host:
            self.send(403, {"error": "禁止跨站请求"})
            return False
        if self.path == "/health" or self.path == "/" or self.path.startswith("/static/"):
            return True
        token = os.environ.get("APP_TOKEN", "")
        if token:
            import hmac
            cookies = self.headers.get("Cookie", "")
            supplied = next((c.strip()[len("workbench_token="):] for c in cookies.split(";") if c.strip().startswith("workbench_token=")), "")
            if not hmac.compare_digest(token, unquote(supplied)):
                self.send(401, {"error": "请先输入访问密码"})
                return False
        return True

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_UPLOAD * 2:
            raise ValueError("请求过大或为空")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            if self.path == "/__model/v1/responses" and method == "POST":
                import hmac
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + BRIDGE_TOKEN):
                    return self.send(403, {"error": "Internal model transport"})
                body = self.body()
                try:
                    upstream = transport.open_response(body, agent.settings())
                except transport.urllib.error.HTTPError as e:
                    return self.send(e.code, agent.redact(e.read().decode()), "application/json")
                with upstream:
                    buffered = "application/json" in upstream.headers.get("Content-Type", "")
                    result = json.load(upstream) if buffered else None
                    self.send_response(upstream.status)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if buffered:
                        for chunk in transport.as_sse(result):
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    else:
                        while True:
                            chunk = upstream.read1(8192)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    self.close_connection = True
                return
            if self.path == "/api/login" and method == "POST":
                import hmac
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    return self.send(403, {"error": "禁止跨站请求"})
                token = str(self.body().get("token", ""))
                if not hmac.compare_digest(os.environ.get("APP_TOKEN", ""), token):
                    return self.send(401, {"error": "密码不正确"})
                return self.send(200, {"ok": True}, headers={"Set-Cookie": "workbench_token=" + quote(token, safe="") + "; HttpOnly; SameSite=Strict; Path=/"})
            if not self.allowed():
                return
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if method == "GET" and path == "/health":
                return self.send(200, {"ok": True})
            if method == "GET" and (path == "/" or path.startswith("/static/")):
                asset = "index.html" if path == "/" else path[len("/static/"):]
                target = checked_file(ROOT / "static", asset)
                return self.send(200, target.read_bytes(), mimetypes.guess_type(str(target))[0] or "text/plain",
                                 {"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            if path == "/api/config" and method == "GET":
                with LOCK:
                    active_count = len(ACTIVE)
                return self.send(200, {**agent.readiness(), "active": active_count, "max_parallel": 2, "upload_limit": MAX_UPLOAD})
            if path == "/api/sessions":
                if method == "GET":
                    with db() as c:
                        rows = c.execute("SELECT s.*, (SELECT status FROM runs WHERE session_id=s.id ORDER BY rowid DESC LIMIT 1) status FROM sessions s ORDER BY updated_at DESC,rowid DESC").fetchall()
                    return self.send(200, [dict(r) for r in rows])
                title = str(self.body().get("title", "新会话")).strip()[:80] or "新会话"
                sid = uuid.uuid4().hex
                ws = DATA / "sessions" / sid / "workspace"
                (ws / "uploads").mkdir(parents=True)
                (ws / "artifacts").mkdir()
                with db() as c:
                    c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (sid, title, now(), now()))
                return self.send(201, {"id": sid, "title": title})
            match = re.fullmatch(r"/api/sessions/([a-f0-9]{32})(?:/(.*))?", path)
            if not match:
                return self.send(404, {"error": "接口不存在"})
            sid, action = match.groups()
            ws = workspace(sid)
            if not action and method == "GET":
                with db() as c:
                    session = dict(c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
                    session["messages"] = [dict(r) for r in c.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (sid,))]
                    session["runs"] = [dict(r) for r in c.execute("SELECT * FROM runs WHERE session_id=? ORDER BY rowid", (sid,))]
                    session["events"] = [dict(r) for r in c.execute("SELECT * FROM events WHERE session_id=? ORDER BY id", (sid,))]
                for e in session["events"]:
                    e["payload"] = json.loads(e["payload"])
                session["files"] = file_list(ws)
                return self.send(200, session)
            if action == "rename" and method == "POST":
                title = str(self.body().get("title", "")).strip()[:80]
                if not title:
                    raise ValueError("会话名称不能为空")
                with db() as c:
                    c.execute("UPDATE sessions SET title=?,updated_at=? WHERE id=?", (title, now(), sid))
                return self.send(200, {"ok": True})
            if action == "messages" and method == "POST":
                content = str(self.body().get("content", "")).strip()
                if not content or len(content) > 20000:
                    raise ValueError("消息需为 1-20000 个字符")
                if not agent.readiness()["ready"]:
                    return self.send(503, {"error": "请先配置模型 API 和 Codex CLI", **agent.readiness()})
                with LOCK:
                    if sid in ACTIVE:
                        return self.send(409, {"error": "当前会话已有运行中的任务"})
                    if len(ACTIVE) >= 2:
                        return self.send(429, {"error": "已有两个任务在运行，请稍后发送"})
                    rid = uuid.uuid4().hex
                    state = {"process": None, "stop": None}
                    with db() as c:
                        c.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)", (sid, "user", content, now()))
                        c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (rid, sid, "running", now(), None, None))
                        c.execute("UPDATE sessions SET updated_at=?,title=CASE WHEN title='新会话' THEN ? ELSE title END WHERE id=?", (now(), content[:32], sid))
                    ACTIVE[sid] = state
                    threading.Thread(target=worker, args=(sid, rid, state), daemon=True).start()
                return self.send(202, {"run_id": rid})
            if action == "cancel" and method == "POST":
                with LOCK:
                    state = ACTIVE.get(sid)
                    if state:
                        state["stop"] = "cancelled"
                        end_process(state["process"])
                return self.send(200, {"ok": True})
            if action == "upload" and method == "POST":
                body = self.body()
                name = str(body.get("name", ""))
                if not re.fullmatch(r"[^/\\\x00-\x1f]{1,160}", name) or name.startswith("."):
                    raise ValueError("文件名无效")
                data = base64.b64decode(body.get("data", ""), validate=True)
                if len(data) > MAX_UPLOAD:
                    raise ValueError("单文件不能超过 10 MB")
                with LOCK:
                    if sid in ACTIVE:
                        return self.send(409, {"error": "请在当前任务完成后上传文件"})
                    if sum(f["size"] for f in file_list(ws)) + len(data) > MAX_FILES_TOTAL:
                        raise ValueError("工作区文件超过 100 MB 上传额度")
                    dest = checked_file(ws, "uploads/" + name, must_exist=False)
                    if dest.exists():
                        return self.send(409, {"error": "同名文件已存在，请重命名后上传"})
                    with dest.open("xb") as f:
                        f.write(data)
                return self.send(201, {"path": "uploads/" + name, "size": len(data)})
            if action == "files" and method == "GET":
                return self.send(200, file_list(ws))
            if action == "bundle" and method == "GET":
                files = file_list(ws)
                if sum(f["size"] for f in files) > MAX_FILES_TOTAL:
                    raise ValueError("文件总量过大，请逐个下载")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in files:
                        p = checked_file(ws, f["path"])
                        z.write(p, f["path"])
                return self.send(200, buf.getvalue(), "application/zip", {"Content-Disposition": 'attachment; filename="workspace.zip"'})
            if action in ("file", "preview") and method == "GET":
                rel = query.get("path", [""])[0]
                p = checked_file(ws, rel)
                if p.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("文件过大，暂不支持浏览器获取")
                mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                headers = {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(p.name)}
                if action == "preview":
                    headers = {"Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"}
                    if p.suffix.lower() not in (".html", ".htm"):
                        mime = "text/plain; charset=utf-8"
                return self.send(200, p.read_bytes(), mime, headers)
            if action == "events" and method == "GET":
                last = max(int(query.get("after", ["0"])[0]), int(self.headers.get("Last-Event-ID", "0")))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline and not STOPPING.is_set():
                    with db() as c:
                        rows = c.execute("SELECT * FROM events WHERE session_id=? AND id>? ORDER BY id LIMIT 200", (sid, last)).fetchall()
                    for row in rows:
                        last = row["id"]
                        payload = {"id": last, "run_id": row["run_id"], "created_at": row["created_at"], "payload": json.loads(row["payload"])}
                        self.wfile.write((f"id: {last}\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode())
                    if not rows:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    STOPPING.wait(0.5)
                self.close_connection = True
                return
            return self.send(404, {"error": "接口不存在"})
        except FileNotFoundError as e:
            self.send(404, {"error": str(e)})
        except (ValueError, TypeError, KeyError) as e:
            self.send(400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self.send(500, {"error": agent.redact(str(e))})


def serve():
    init()
    server = ThreadingHTTPServer((os.environ.get("APP_HOST", "127.0.0.1"), int(os.environ.get("APP_PORT", "8080"))), Handler)
    server.daemon_threads = True
    def stop(*_):
        STOPPING.set()
        with LOCK:
            for state in ACTIVE.values():
                state["stop"] = "cancelled"
                end_process(state["process"])
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Agent Desk listening on http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    serve()
