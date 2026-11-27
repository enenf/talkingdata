#!/usr/bin/env python3
"""Run two real Agent tasks through the same HTTP API used by the browser.

Requires the running app and a configured real provider. No mock fallback.
Produces reproducible, synthetic-only evidence in evidence/real-demo/.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import zipfile
import io

CSV = """month,channel,revenue,cost,orders
2026-09,website,12000,7000,120
2026-09,marketplace,8000,6000,100
2026-10,website,15000,8000,140
2026-10,marketplace,9000,7000,110
2026-11,website,18000,9500,160
2026-11,marketplace,10000,7500,115
"""
CODE = """请直接开发一个简洁的离线中文费用分摊计算器（整个 HTML 控制在 100 行以内），保存为 artifacts/index.html（所有 CSS 和 JS 内联，不依赖外网）。输入总金额和人数，显示每人应付金额，处理零人数、负金额、无效输入。先完成一个简洁可用的版本。请用 Node 执行实际测试并保存测试结果为 artifacts/verification.txt；可以使用内置 vm 和简单的 DOM 桩对象测试脚本。不要检查应用列表或环境，不要使用浏览器、Playwright 或 Chrome，不要启动服务器。"""
CODE_FOLLOWUP = """继续改进刚才的计算器：金额精确到分，用整数分来计算，余数从第一人开始分配，确保合计与原金额完全一致。例如 100 元 3 人应为 33.34、33.33、33.33。列出每个人的金额，增加重置按钮。请实际运行验证 100元3人、0元2人、10.01元2人，以及无效输入，并更新 artifacts/verification.txt。保留同一个 artifacts/index.html。"""
REPORT = """请直接读取 uploads/sales.csv，这是一份虚构的销售数据。使用 Python 实际计算三个月及各渠道的收入、成本、毛利和毛利率，生成 artifacts/report.md（800 字以内）和 artifacts/summary.csv。在报告中给出可追溯的数字、增长趋势、数据局限和三条行动建议；不要把毛利称作净利润。请运行校验并说明总收入与总成本。不需要检查机器环境或应用列表。"""
REPORT_FOLLOWUP = """请基于刚才的计算结果，补充一份面向负责人的中文一页行动摘要，保存为 artifacts/executive-summary.md。包含三个关键数字、渠道优先级、未来两周行动和需要补充的数据。请复核总收入、总成本与毛利相等关系，不要虚构额外事实。"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--out", default="evidence/real-demo")
    parser.add_argument("--export-only", action="store_true", help="Re-export existing manifest sessions after additional review turns")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def request(path, body=None, raw=False):
        req = Request(args.base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as r:
            data = r.read()
            return data if raw else json.loads(data)

    config = request("/api/config")
    if not config["ready"]:
        raise RuntimeError("Real model/CLI not configured: " + str(config["missing"]))

    def turn(sid, text):
        request(f"/api/sessions/{sid}/messages", {"content": text})
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            d = request(f"/api/sessions/{sid}")
            if d["runs"][-1]["status"] != "running":
                print(d["title"], d["runs"][-1]["status"], flush=True)
                if d["runs"][-1]["status"] != "completed":
                    (out / f"failed-{sid}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))
                    raise RuntimeError(d["runs"][-1].get("error"))
                return d
            time.sleep(2)
        raise TimeoutError("demo run timed out")

    if args.export_only:
        manifest = json.loads((out / "manifest.json").read_text())
    else:
        code_id = request("/api/sessions", {"title": "费用分摊器 · 代码开发"})["id"]
        report_id = request("/api/sessions", {"title": "销售复盘 · 材料分析"})["id"]
        request(f"/api/sessions/{report_id}/upload", {"name": "sales.csv", "data": base64.b64encode(CSV.encode()).decode()})
        manifest = {"model": config["model"], "cli": config["cli"], "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sessions": {"code": code_id, "report": report_id}, "synthetic_input": True}
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(turn, code_id, CODE), pool.submit(turn, report_id, REPORT)]
            for f in futures:
                f.result()
            futures = [pool.submit(turn, code_id, CODE_FOLLOWUP), pool.submit(turn, report_id, REPORT_FOLLOWUP)]
            for f in futures:
                f.result()
    manifest["runs"] = {}
    for name, sid in manifest["sessions"].items():
        d = request(f"/api/sessions/{sid}")
        if any(r["status"] == "running" for r in d["runs"]):
            raise RuntimeError("Cannot export while a task is still running")
        manifest["runs"][name] = [{k: r[k] for k in ("id", "status", "started_at", "finished_at")} for r in d["runs"]]
        transcript = json.dumps(d, ensure_ascii=False, indent=2)
        transcript = transcript.replace(str(Path.cwd() / "data"), "[DATA_DIR]").replace(str(Path.home()), "[HOME]")
        (out / f"{name}-transcript.json").write_text(transcript)
        archive = request(f"/api/sessions/{sid}/bundle", raw=True)
        dest = out / name
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for info in z.infolist():
                path = (dest / info.filename).resolve()
                if not path.is_relative_to(dest.resolve()):
                    raise ValueError("Unsafe archive path")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(z.read(info))
    manifest["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest["sha256"] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Real demo evidence saved to", out, flush=True)


if __name__ == "__main__":
    main()
