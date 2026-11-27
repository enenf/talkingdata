#!/usr/bin/env python3
"""Deterministic subprocess fixture for lifecycle tests; NEVER used by the app demo."""
import json
import sys
import time
import subprocess
from pathlib import Path


def emit(obj):
    print(json.dumps(obj), flush=True)


prompt = sys.stdin.read()
workspace = Path(sys.argv[sys.argv.index("-C") + 1])
emit({"type": "thread.started", "thread_id": "test-thread"})
emit({"type": "item.completed", "item": {"type": "agent_message", "text": "Fixture progress update."}})
if "FAIL_RUN" in prompt:
    emit({"type": "error", "message": "fixture provider failure"})
    sys.exit(1)
if "SLEEP_RUN" in prompt:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    (workspace / "artifacts" / "child.pid").write_text(str(child.pid))
    time.sleep(30)
path = workspace / "artifacts" / "result.txt"
path.write_text("Test result, not a real model response.\n" + prompt[-100:])
emit({"type": "item.completed", "item": {"type": "command_execution", "command": "fixture validation", "aggregated_output": "fixture passed", "status": "completed", "exit_code": 0}})
emit({"type": "item.completed", "item": {"type": "agent_message", "text": "Fixture task completed."}})
emit({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
