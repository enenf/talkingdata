# 验证记录

此文件只记录实际执行过的检查，不将 CLI 夹具测试当作真实模型演示。

## 自动化

- Python 接口与生命周期回归：14 项通过，原始输出见 `integration-tests.txt`。
- JavaScript 语法：`node --check static/app.js` 通过。
- 覆盖会话互斥、两个任务并发上限、取消、失败状态、重启恢复、会话持久化、上传重名、ZIP、路径越界、符号链接、跨站请求、DNS rebinding、HTML 预览隔离、协议字段过滤和 SSE 内容一致性。

## 已完成的真实运行

2026-11-27 13:42（Asia/Shanghai）：通过应用 HTTP API 启动真实 Codex CLI 与模型 `linext-5.3-luna`。

任务实际运行 Python 命令，创建 `artifacts/hello.txt` 并读回 `Hello from Agent Desk`；命令退出码为 0，CLI 发出 `turn.completed`，应用记录为 `completed`。

## 正在收集的证据

- 完整代码开发、文件分析、后续交流及并行会话演示。
- Docker 构建和运行；本机初始未安装 Docker，已安装 CLI 和 Colima，虚拟机镜像下载中。

最终结果将在实际完成后更新，未完成项不会标记为通过。
