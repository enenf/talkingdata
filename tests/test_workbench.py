import base64
import http.client
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import agent
import transport


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.temp.name)
        fixture = ROOT / "tests" / "fake_codex.py"
        fixture.chmod(0o755)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.env = {**os.environ, "APP_PORT": str(cls.port), "APP_HOST": "127.0.0.1", "DATA_DIR": str(cls.data), "CODEX_BIN": str(fixture), "MODEL_BASE_URL": "https://fixture.invalid/v1", "MODEL_API_KEY": "fixture-key", "MODEL_NAME": "fixture", "APP_TOKEN": ""}
        cls.start_server()

    @classmethod
    def start_server(cls):
        cls.proc = subprocess.Popen([sys.executable, "-B", "server.py"], cwd=ROOT, env=cls.env, stdout=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1):
                    return
            except (OSError, HTTPError):
                time.sleep(.05)
        raise RuntimeError("test server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.temp.cleanup()

    def req(self, path, data=None, headers=None):
        req = Request(f"http://127.0.0.1:{self.port}" + path, data=json.dumps(data).encode() if data is not None else None, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as e:
            response = e
        raw = response.read()
        return response.status, json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw, response.headers

    def create(self):
        code, s, _ = self.req("/api/sessions", {"title": "test"})
        self.assertEqual(code, 201)
        return s["id"]

    def detail(self, sid):
        return self.req(f"/api/sessions/{sid}")[1]

    def wait(self, sid):
        for _ in range(100):
            d = self.detail(sid)
            if d["runs"] and d["runs"][-1]["status"] != "running":
                return d
            time.sleep(.05)
        self.fail("run did not finish")

    def test_health_and_static(self):
        self.assertEqual(self.req("/health")[1], {"ok": True})
        self.assertIn("栖点".encode(), self.req("/")[1])
        self.assertIn("script-src 'self'", self.req("/")[2]["Content-Security-Policy"])

    def test_real_subprocess_lifecycle_and_follow_up(self):
        sid = self.create()
        self.assertEqual(self.req(f"/api/sessions/{sid}/messages", {"content": "first"})[0], 202)
        d = self.wait(sid)
        self.assertEqual(d["runs"][-1]["status"], "completed")
        self.assertEqual([m["role"] for m in d["messages"]], ["user", "assistant"])
        self.assertTrue(any(e["payload"]["kind"] == "command" for e in d["events"]))
        self.assertEqual(d["files"][0]["path"], "artifacts/result.txt")
        self.req(f"/api/sessions/{sid}/messages", {"content": "second"})
        d = self.wait(sid)
        self.assertEqual(len(d["messages"]), 4)
        self.assertEqual(len(d["runs"]), 2)

    def test_upload_download_isolation_and_zip(self):
        a, b = self.create(), self.create()
        body = {"name": "材料.csv", "data": base64.b64encode(b"a,b\n1,2\n").decode()}
        self.assertEqual(self.req(f"/api/sessions/{a}/upload", body)[0], 201)
        self.assertEqual(self.req(f"/api/sessions/{a}/upload", body)[0], 409)
        self.assertEqual(self.req(f"/api/sessions/{b}/file?path=uploads/missing.csv")[0], 404)
        bundle = self.req(f"/api/sessions/{a}/bundle")[1]
        with zipfile.ZipFile(io.BytesIO(bundle)) as z:
            self.assertEqual(z.read("uploads/材料.csv"), b"a,b\n1,2\n")

    def test_path_traversal_symlinks_and_invalid_uploads(self):
        sid = self.create()
        base = f"/api/sessions/{sid}"
        for rel in ["../workbench.sqlite", "/etc/passwd", "uploads/../../workbench.sqlite", "uploads%5cfile"]:
            self.assertEqual(self.req(base + "/file?path=" + rel)[0], 400)
        ws = self.data / "sessions" / sid / "workspace"
        (ws / "uploads" / "link.txt").symlink_to(self.data / "workbench.sqlite")
        self.assertEqual(self.req(base + "/file?path=uploads/link.txt")[0], 400)
        self.assertEqual(self.detail(sid)["files"], [])
        for name in ["../bad", ".env", "bad/name", "bad\\name", "bad\nname"]:
            self.assertEqual(self.req(base + "/upload", {"name": name, "data": "YQ=="})[0], 400)

    def test_cross_origin_and_dns_rebinding(self):
        self.assertEqual(self.req("/api/sessions", {}, {"Origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(self.req("/api/config", headers={"Host": "evil.invalid"})[0], 403)

    def test_concurrency_and_cancellation(self):
        a, b, c = self.create(), self.create(), self.create()
        try:
            self.assertEqual(self.req(f"/api/sessions/{a}/messages", {"content": "SLEEP_RUN"})[0], 202)
            self.assertEqual(self.req(f"/api/sessions/{a}/messages", {"content": "duplicate"})[0], 409)
            self.assertEqual(self.req(f"/api/sessions/{b}/messages", {"content": "SLEEP_RUN"})[0], 202)
            self.assertEqual(self.req(f"/api/sessions/{c}/messages", {"content": "over limit"})[0], 429)
            self.assertEqual(self.req(f"/api/sessions/{a}/upload", {"name": "x", "data": "YQ=="})[0], 409)
        finally:
            self.req(f"/api/sessions/{a}/cancel", {})
            self.req(f"/api/sessions/{b}/cancel", {})
        self.assertEqual(self.wait(a)["runs"][-1]["status"], "cancelled")
        self.assertEqual(self.wait(b)["runs"][-1]["status"], "cancelled")

    def test_provider_failure_is_not_success(self):
        sid = self.create()
        self.req(f"/api/sessions/{sid}/messages", {"content": "FAIL_RUN"})
        d = self.wait(sid)
        self.assertEqual(d["runs"][-1]["status"], "failed")
        self.assertIn("provider failure", d["runs"][-1]["error"])

    def test_preview_is_sandboxed(self):
        sid = self.create()
        self.req(f"/api/sessions/{sid}/upload", {"name": "test.html", "data": base64.b64encode(b"<script>alert(1)</script>").decode()})
        code, _, headers = self.req(f"/api/sessions/{sid}/preview?path=uploads/test.html")
        self.assertEqual(code, 200)
        self.assertIn("sandbox allow-scripts", headers["Content-Security-Policy"])
        self.assertIn("connect-src 'none'", headers["Content-Security-Policy"])

    def test_rename_and_missing_session(self):
        sid = self.create()
        self.assertEqual(self.req(f"/api/sessions/{sid}/rename", {"title": "Renamed"})[0], 200)
        self.assertEqual(self.detail(sid)["title"], "Renamed")
        self.assertEqual(self.req(f"/api/sessions/{'f'*32}")[0], 404)

    def test_restart_preserves_history_and_marks_interrupted(self):
        sid = self.create()
        self.req(f"/api/sessions/{sid}/messages", {"content": "SLEEP_RUN"})
        # Crash the server, then kill its fixture CLI process groups to avoid orphans.
        self.proc.kill()
        self.proc.wait()
        self.start_server()
        d = self.detail(sid)
        self.assertEqual(d["runs"][-1]["status"], "interrupted")
        self.assertEqual(d["messages"][-1]["content"], "SLEEP_RUN")
        self.assertEqual(d["events"][-1]["payload"]["status"], "interrupted")


class AdapterTests(unittest.TestCase):
    def test_jsonl_normalization(self):
        self.assertEqual(agent.normalize('{"type":"turn.completed","usage":{}}')["kind"], "usage")
        self.assertEqual(agent.normalize('{"type":"item.completed","item":{"type":"reasoning","text":"private"}}'), None)
        self.assertEqual(agent.normalize('a diagnostic line')["kind"], "log")

    def test_reconnect_is_not_a_terminal_failure(self):
        event = agent.normalize('{"type":"error","message":"Reconnecting... 1/1"}')
        self.assertEqual(event["kind"], "log")

    def test_transport_preserves_inputs_and_filters_unsupported_extensions(self):
        body = {"model": "wrong", "input": [{"role": "user", "content": "hello"}], "stream": True,
                "reasoning": {"summary": "auto"}, "client_metadata": {"test": True},
                "tools": [{"type": "function", "name": "exec_command", "parameters": {}},
                          {"type": "namespace", "name": "multi_agent"},
                          {"type": "function", "name": "create_goal"}]}
        result = transport.compatible_request(body, "configured-model")
        self.assertEqual(result["input"], body["input"])
        self.assertEqual(result["model"], "configured-model")
        self.assertFalse(result["store"])
        self.assertNotIn("reasoning", result)
        self.assertEqual([t["name"] for t in result["tools"]], ["exec_command"])

    def test_buffered_sse_preserves_tool_calls_and_model_text(self):
        response = {"id": "resp_test", "status": "completed", "usage": {"input_tokens": 5, "output_tokens": 7},
                    "output": [{"id": "msg1", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "Test reply", "annotations": []}]},
                               {"id": "fc1", "type": "function_call", "call_id": "call1", "name": "exec_command", "arguments": '{"cmd":"echo hello"}', "status": "completed"}]}
        events = [json.loads(chunk.decode()[6:]) for chunk in transport.as_sse(response)]
        self.assertEqual(events[-1]["type"], "response.completed")
        self.assertEqual(events[-1]["response"], response)
        done = [e["item"] for e in events if e["type"] == "response.output_item.done"]
        self.assertEqual(done, response["output"])
        self.assertEqual([e["sequence_number"] for e in events], list(range(len(events))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
