# 验证记录

此文件只记录实际执行过的检查，不将 CLI 夹具测试当作真实模型演示。

## 自动化

- Python 接口与生命周期回归：17 项通过，原始输出见 `integration-tests.txt`。
- JavaScript 语法：`node --check static/app.js` 通过。
- 覆盖会话互斥、两个任务并发上限、取消、失败状态、重启恢复、会话持久化、上传重名、ZIP、路径越界、符号链接、跨站请求、DNS rebinding、HTML 预览隔离、协议字段过滤和 SSE 内容一致性。

## 已完成的真实运行

2026-11-27 13:42（Asia/Shanghai）：通过应用 HTTP API 启动真实 Codex CLI 与模型 `linext-5.3-luna`。

任务实际运行 Python 命令，创建 `artifacts/hello.txt` 并读回 `Hello from Agent Desk`；命令退出码为 0，CLI 发出 `turn.completed`，应用记录为 `completed`。

## Docker 实际运行

[GitHub Actions 运行 45948044953](https://github.com/enenf/talkingdata/actions/runs/45948044953) 在 Linux 上实际完成构建并启动容器，结果为 success。对应提交为 `9abc931c15b2da18ae4922b56dcdea30a089f53c`。

通过项目：Docker build、HTTP 健康检查、容器内非 root 用户检查、`codex --version`、创建会话、重启容器后读取同一会话。原始状态在 `ci-run.json`，关键输出在 `ci-container-log.txt`。CI 不接收考试模型密钥，真实模型任务在本机原生应用完成。

## 完整真实演示与独立复核

`real-demo/manifest.json` 记录两会话的模型、时间、真实任务状态和全部导出文件 SHA256。原始执行事件保留，公开证据中的本机目录前缀替换为 `[DATA_DIR]` / `[HOME]`。

- 代码会话：先完成离线费用分摊网页；追加逐人分配与重置时触及 600 秒上限，明确标记 failed，已写出的文件保留；随后在同一会话继续定向修复，最终 completed。浏览器实测额外发现 `id=reset` 遮蔽原生 `form.reset` 的命名冲突，经同一会话再追加反馈修复；真实预览中已验证输入、逐人明细和重置恢复。没有把超时任务改写为成功。
- 销售会话：上传虚构 `sales.csv`，生成报告与汇总；追加负责人行动摘要，两轮均 completed，并与代码会话并行运行。
- 独立计算器检查：17 项通过，含 100 元 / 3 人、0 元 / 2 人、10.01 元 / 2 人、无效金额/人数、超大金额、重置、余数文案及 1000 组总金额守恒。可运行 `node scripts/verify_demo_calculator.cjs evidence/real-demo/code/artifacts/index.html`，原始输出在 `independent-calculator-check.txt`。
- 独立销售复算：收入 72,000，成本 45,000，毛利 27,000，毛利率 37.5%；总计、渠道明细及两份文档的关键数字一致。见 `independent-sales-check.json`。
- 真实工具环境检查：实际执行 Python 断言，确认 shell 无 `MODEL_API_KEY` / `WORKBENCH_MODEL_KEY`，且 Python、Node、apply_patch 在 PATH 中可用，退出码 0。见 `environment-check.json`。
- 工作台浏览器检查：会话切换与恢复、执行记录、Markdown 表格、文件预览、HTML 隔离预览及生成网页交互，见本目录截图。

本机 Docker CLI 和 Colima 已安装，虚拟机镜像因网络缓慢仍在下载；不将本机容器运行标为通过。Docker 的已完成实际构建/启动证据来自上面的 Linux CI。
