# 栖点 · Agent Desk

一个面向单用户的云端 Agent 助手工作台。把任务交给真实 **Codex CLI 0.162.1**，在浏览器中查看执行进度、上传材料、预览或下载成果，并在不同会话之间继续工作。

不是只生成聊天文本：服务端实际启动 `codex exec --json` 子进程，Codex 自己调用工具、执行命令并写文件。页面中的执行记录来自 CLI 的真实 JSONL 事件。

## 快速开始：Docker

前提：Docker Engine / Docker Desktop 和 Docker Compose v2，可访问 npm、Debian 镜像源及模型服务。支持 Linux amd64 / arm64。

```bash
git clone https://github.com/enenf/talkingdata.git
cd talkingdata
cp .env.example .env
# 编辑 .env，填写 MODEL_BASE_URL、MODEL_API_KEY、MODEL_NAME
docker compose up --build -d
```

打开 **http://127.0.0.1:8080**。默认只发布到本机回环地址，不需要公网部署。容器以非 root 的 `node` 用户运行，所有会话和成果保存在 `workspace-data` 命名卷中。

```bash
docker compose logs -f
docker compose down          # 停止，保留数据
docker compose up -d         # 恢复原会话
# docker compose down -v 会删除数据卷，请谨慎使用
```

没有 Compose 插件时，也可直接运行：

```bash
docker build -t agent-desk .
docker run -d --name agent-desk --init \
  -p 127.0.0.1:8080:8080 --env-file .env \
  -v agent-desk-data:/data --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 256 \
  --memory 2g --cpus 2 agent-desk
```

## 模型配置

`.env` 仅保存在服务端，被 Git 和 Docker 构建上下文排除。不要将凭据粘贴到对话、README 或公开仓库。

| 变量 | 含义 |
| --- | --- |
| `MODEL_BASE_URL` | 支持 Responses 的 API 基地址，以 `/v1` 等服务根路径结尾，不包含 `/responses` |
| `MODEL_API_KEY` | 模型服务密钥；必填 |
| `MODEL_NAME` | 服务实际提供的模型 ID；考试环境使用题面给出的 ID |
| `MODEL_WIRE_API` | `responses`；本项目固定的新版 Codex 不支持旧 `chat` 模式 |
| `MODEL_BUFFERED` | 默认 `1`，兼容模式下先收完整模型响应再输出标准 SSE；命令进度仍实时推送 |
| `MODEL_COMPAT_MODE` | 默认 `1`，开启下述服务端兼容传输；完整原生 Responses 服务可设为 `0` |
| `APP_TOKEN` | 可选工作台访问密码，通过 HttpOnly / SameSite Cookie 验证 |
| `RUN_TIMEOUT_SECONDS` | 单任务执行上限，默认 600 秒 |
| `DATA_DIR` | 持久化目录，原生启动默认 `./data`，Docker 为 `/data` |
| `CODEX_BIN` | 原生开发时指定 Codex 可执行文件；默认 `codex` |
| `APP_PORT` | 默认 8080 |
| `APP_ALLOWED_HOST` | 需要其他本机访问主机名时显式配置；默认仅 localhost / 127.0.0.1 |

配置变更后重新创建容器：`docker compose up -d --force-recreate`。考试临时凭据到期或交卷后会失效，复现时需换成新的有效凭据。

### 协议兼容的取舍

真实联调中，考试 API 拒绝命名空间工具以及 CLI 的部分可选请求字段。本项目关闭 Codex 多 Agent 扩展和内置搜索，启用 `exec_command` / `write_stdin`，并在 `transport.py` 中只转发标准 Responses 输入、标准客户端函数工具、模型名和流式参数，移除可选推理元数据等字段。

兼容层**不实现 Agent 循环**，不伪造工具调用，也不合成回答；工具执行仍由 Codex 完成，默认将上游完整响应转换为标准 SSE 事件，以避开考试服务在较长工具参数流上的中断；转换只重排传输事件，不改变模型内容。设置 `MODEL_BUFFERED=0` 可直接转发上游 SSE。`store=false`，不依赖上游会话存储。CLI 只拿到一个启动时随机生成的内部传输令牌，真实模型密钥由 Python 服务附加，不传给 CLI 的 shell 环境。

官方调用依据：[Codex 非交互模式](https://developers.openai.com/codex/noninteractive)、[高级配置](https://learn.chatgpt.com/docs/config-file/config-advanced)。

## 如何使用

1. 点击「新建会话」，输入具体任务。也可点击首页的代码开发或材料分析示例，把任务填入输入框后调整并发送。
2. 日常工作任务先「添加文件」。支持任意文件上传，单文件最大 10 MB；文本、CSV、Markdown 最容易直接处理。二进制文档需要 CLI 自行使用合适的解析工具。
3. 「执行记录」显示真实命令、输出、退出码、文件变更和用量。任务执行期间可切换其他会话；最多同时执行两个任务，同一会话只运行一个任务。
4. 完成后在「成果文件」中点文件名预览，点箭头下载，或打包下载工作区。HTML 预览支持内联交互脚本，但禁用网络与表单，并在 sandbox iframe 中运行。
5. 直接追加修改要求。新一轮执行会带上最近的对话以及同一个工作目录。关闭浏览器不会停止后台任务，重新打开后自动恢复最近会话。
6. 可以重命名、搜索会话，或点击「停止」结束当前进程组。超时、失败、服务重启会明确标记，不会将失败包装为成功。

窄屏下使用顶部「工作区」按钮查看文件和执行记录。

## 原生开发

应用本身没有第三方 Python 或前端运行依赖，Python 3.9+、Node 18+ 和 Codex CLI 即可。

```bash
npm install -g @openai/codex@0.162.1
cp .env.example .env
# 填写模型配置
python3 -B server.py
```

原生开发使用 Codex 的 `workspace-write` 沙箱。Docker 内由外部容器承担执行隔离，CLI 使用非交互自动执行模式。不要将宿主根目录、SSH 目录或 Docker socket 挂载给容器。

## 验证与演示

```bash
python3 -B -m unittest discover -s tests -v
node --check static/app.js
# 真实模型端到端演示：先启动并配置工作台
python3 -B scripts/demo.py
```

`tests/fake_codex.py` 仅用于可重复的接口和进程生命周期测试，不进入 Docker 镜像，也不用于真实演示。真实演示脚本通过应用 HTTP API 并行创建两个会话，上传虚构 CSV，分别完成网页开发、销售分析，再分别追加修改要求，导出完整对话、命令记录和文件 SHA256。

详细材料见 [演示说明](docs/DEMO.md)、[架构与取舍](docs/ARCHITECTURE.md)、[验证记录](evidence/VALIDATION.md)。[GitHub Actions](.github/workflows/verify.yml) 运行接口测试、JS 语法检查、Docker 构建、非 root 检查及容器重启后的会话持久化测试；CI 不使用模型密钥。

## 已知限制

- 这是本机或可信内网的**单用户**工作台。会话目录独立、HTTP 文件路径校验并拒绝符号链接，但所有 Agent 进程共享一个容器和 Unix 用户，目录不是针对恶意代码的强安全边界。多租户部署需要每任务独立容器、认证授权和出口控制。
- 默认不开放公网。访问密码是轻量门禁，不是完整账号系统；需要远程访问时应在可信反向代理后加 HTTPS 和成熟身份认证。
- 每轮重新启动 CLI，重放最近 24 条消息且最多 80,000 字符；文件一直保留。超长对话会遗忘较早内容，尚无自动摘要和原生线程压缩。
- 浏览器实时显示 CLI 项目级事件，不展示内部思考；助手文本在 CLI 完成对应消息项后出现，并非逐 token 打字。
- HTML 预览只适合自包含页面，外部图片、CDN、模块和相对资源被刻意禁用；复杂项目可打包下载后自行运行。文件大于 20 MB 不通过浏览器直接获取，打包总量限制 100 MB，文件列表最多 1000 项。Agent 写入仍需依靠容器磁盘资源约束。
- 上传不自动做 OCR 或安装 Office/PDF 解析依赖；当前演示使用文本 CSV。模型和其工具需要对实际材料内容进行验证，输出的业务判断仍需用户审阅。
- 取消会终止 CLI 进程组，已经发出的上游模型请求可能仍结算。不会回滚已经写出的文件。Docker 重启会保留数据并把未结束任务标记中断，不自动重新执行可能有副作用的任务。
- 未实现文件版本管理、删除会话、实时协作、任意 Web 服务托管或联网浏览器。网络依赖安装受运行环境限制。

## 目录

```text
server.py       HTTP API、SQLite 持久化、任务生命周期、SSE、文件访问
agent.py        Codex 配置、子进程启动、JSONL 事件归一化
transport.py    标准 Responses 兼容转发（不含 Agent 逻辑）
static/         无构建步骤的中文工作台界面
tests/          API 和生命周期自动化测试，使用显式 CLI 夹具
scripts/demo.py 真实应用端到端演示
docs/           演示与架构说明
evidence/       运行证据和虚构材料演示成果（不含凭据）
```
