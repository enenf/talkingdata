"""Small Responses compatibility transport, not an agent implementation.

Codex still owns the planning/tool/execution loop. Some compatible providers fail
mid-stream on large tool arguments, so buffered mode converts a complete, real
Responses result to standard SSE events without changing its content.
"""
import json
import urllib.request
import urllib.error
import os

ALLOWED_TOOLS = {"exec_command", "write_stdin", "shell_command", "shell", "apply_patch", "view_image", "update_plan"}


def compatible_request(body, model):
    allowed = {"input", "instructions", "stream", "max_output_tokens"}
    result = {k: v for k, v in body.items() if k in allowed}
    result["model"] = model
    result["store"] = False
    result["tools"] = [t for t in body.get("tools", [])
                       if t.get("type") in ("function", "custom") and t.get("name") in ALLOWED_TOOLS]
    return result


def open_response(body, settings):
    body = compatible_request(body, settings["model"])
    if os.environ.get("MODEL_BUFFERED", "1") == "1":
        body["stream"] = False
    request = urllib.request.Request(settings["base"] + "/responses",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + settings["key"], "Content-Type": "application/json"})
    return urllib.request.urlopen(request, timeout=240)


def as_sse(response):
    """Standard event framing for a buffered response; content is never invented."""
    sequence = 0

    def event(kind, **fields):
        nonlocal sequence
        payload = {"type": kind, "sequence_number": sequence, **fields}
        sequence += 1
        return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()

    created = {**response, "output": [], "status": "in_progress"}
    yield event("response.created", response=created)
    for index, item in enumerate(response.get("output", [])):
        added = {**item, "status": "in_progress"}
        kind = item.get("type")
        if kind == "message":
            added["content"] = []
        elif kind == "function_call":
            added["arguments"] = ""
        elif kind == "custom_tool_call":
            added["input"] = ""
        yield event("response.output_item.added", output_index=index, item=added)
        common = {"item_id": item.get("id"), "output_index": index}
        if kind == "message":
            for content_index, part in enumerate(item.get("content", [])):
                fields = {**common, "content_index": content_index}
                if part.get("type") == "output_text":
                    yield event("response.content_part.added", **fields, part={"type": "output_text", "text": "", "annotations": []})
                    yield event("response.output_text.delta", **fields, delta=part.get("text", ""))
                    yield event("response.output_text.done", **fields, text=part.get("text", ""))
                    yield event("response.content_part.done", **fields, part=part)
        elif kind == "function_call":
            yield event("response.function_call_arguments.delta", **common, delta=item.get("arguments", ""))
            yield event("response.function_call_arguments.done", **common, arguments=item.get("arguments", ""))
        elif kind == "custom_tool_call":
            yield event("response.custom_tool_call_input.delta", **common, delta=item.get("input", ""))
            yield event("response.custom_tool_call_input.done", **common, input=item.get("input", ""))
        yield event("response.output_item.done", output_index=index, item=item)
    kind = "response.completed" if response.get("status") == "completed" else "response.failed"
    yield event(kind, response=response)
