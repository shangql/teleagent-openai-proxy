---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'd90e64ea-64f4-49bb-acbf-8be5f9ac88cb'
  PropagateID: 'd90e64ea-64f4-49bb-acbf-8be5f9ac88cb'
  ReservedCode1: 'f5a009ce-34c5-4d59-8c67-b58a2ed012ff'
  ReservedCode2: 'f5a009ce-34c5-4d59-8c67-b58a2ed012ff'
---

# TeleAgent OpenAI-Compatible Proxy

将 [TeleAgent](https://teleagent.cn) 桌面应用的 super-agent API 转换为 **OpenAI 兼容接口**，任何支持 OpenAI API 的工具/SDK 均可直接接入。

## 平台支持

| 平台 | 状态 | session key 获取方式 | 持久化方式 |
|------|------|--------------------|-----------|
| macOS | ✅ 官方支持 | `pgrep` + `ps eww` 读进程环境 | launchd |
| Windows | ✅ 已适配（v1.10.0+） | 读取 TeleAgent 进程 PEB 环境块 | 任务计划程序 |

两个平台的 HTTP / HMAC / SSE 逻辑完全一致，Windows 侧纯标准库实现，**无需管理员权限、无需额外安装 Python**。

## 特性

- **OpenAI 兼容**：标准 `/v1/chat/completions` 和 `/v1/models` 端点
- **流式 & 非流式**：支持 SSE 流式输出和一次性返回
- **多轮对话**：通过 messages 数组传入完整历史
- **自动签名**：自动从运行中的 TeleAgent 进程获取 session key
- **模型管理**：只展示 TeleAgent 中已配置成功的 Provider 与模型（未配置密钥的内置模型目录自动隐藏），TeleAgent 新增配置后面板每 30 秒自动同步
- **默认模型可切换**：Web 控制台可动态修改默认模型，立即生效，影响所有未显式指定 `model` 的 API 请求
- **Web 控制台**：内置仪表盘、模型管理、请求日志、在线测试、会话管理
- **持久化运行**：macOS 用 launchd、Windows 用任务计划程序，均支持开机自启、崩溃自动重启
- **零依赖**：纯 Python 标准库实现，无需 pip install

## 快速开始

### 前置条件

**通用**

- **TeleAgent 桌面应用必须已启动**——其内置的 super-agent 服务监听 `127.0.0.1:4397`，代理需要与它通信才能完成签名与转发；未启动时代理会在启动阶段直接报错退出
- **Python 3.8+**

**macOS**

- 推荐 [Homebrew Python 3.11](https://brew.sh)，具备完整 TCC 权限

> **TCC 权限提示**：macOS 的 `~/Desktop`、`~/Documents`、`~/Downloads` 受 TCC 隐私保护。通过 `launchd` 持久化运行的服务需要使用已获得 TCC 授权的 Python 解释器（如 Homebrew 安装的 Python 3.11+），否则会遇到 `Operation not permitted` 错误。如果脚本放在 `/tmp` 或 `~/scripts` 等非受保护目录，则无此限制。

**Windows**

- **不需要管理员权限**，**不需要额外安装 Python**——TeleAgent 桌面应用自带 Python 3.12 运行时（`%USERPROFILE%\.local\share\TeleAgent\runtimes\python\python.exe`），`start_proxy.cmd` 会优先使用它
- 也可使用系统 Python 3.8+（需在 PATH 中）
- session key 的获取方式与 macOS 不同：macOS 用 `pgrep` + `ps eww` 读进程环境，Windows 没有等价命令，改为直接读取 TeleAgent 子进程的 PEB 环境块（纯标准库 ctypes 实现）。详见下方「Windows 专项说明」

### 启动代理

macOS / Linux：

```bash
python3 openai_proxy.py --port 8088 --host 0.0.0.0
```

Windows：

```bat
:: 自动挑选可用的 Python 解释器（优先 TeleAgent 自带运行时）
start_proxy.cmd
```

### Windows 专项说明

手动指定解释器与监听地址：

```bat
:: 优先使用 TeleAgent 自带的 Python 运行时（无需安装 Python）
"%USERPROFILE%\.local\share\TeleAgent\runtimes\python\python.exe" openai_proxy.py --host 127.0.0.1 --port 8088
```

注意事项：

- **监听地址**：建议用 `--host 127.0.0.1`。代理**不校验 API Key**，用 `0.0.0.0` 会把本机 TeleAgent 的调用能力暴露给整个局域网。
- **前置依赖**：TeleAgent 桌面应用必须已启动（super-agent 监听 `127.0.0.1:4397`），否则拿不到 session key，代理会在启动阶段直接报错退出。
- **Python**：不强制安装。TeleAgent 自带 Python 3.12 运行时，`start_proxy.cmd` 会优先使用它；也可用系统 Python 3.8+。
- **持久化**：用任务计划程序替代 launchd，见下方「持久化运行（Windows 任务计划程序）」。

### 调用示例

```bash
# 非流式
curl http://127.0.0.1:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "NewApi/chat-pro",
    "messages": [{"role": "user", "content": "你好"}]
  }'

# 流式
curl -N http://127.0.0.1:8088/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "NewApi/chat-pro",
    "messages": [{"role": "user", "content": "讲个笑话"}],
    "stream": true
  }'

# 获取模型列表
curl http://127.0.0.1:8088/v1/models
```

### 流式转发

`"stream": true` 时正文边生成边下发，**带 `tools` 的请求同样是真流式**。

这一点值得单独说明：super-agent 不发原生 `tool_calls`，而是把工具调用写成正文里的 `[TOOL_CALL]{...}[/TOOL_CALL]` 标记，由代理解析后转成 OpenAI 的 `tool_calls`。为了拿到完整标记，早期实现只要请求带 `tools` 就把整段正文缓冲到结束再解析——一句 89 字的回复只落成 1 个 SSE 事件，客户端要等模型全部说完才看到第一个字。而 dsh 这类客户端一定会带 `tools`，等于覆盖了全部实际流量。

现在改为「尾部压住」：正文照常增量发出，只压住末尾 `len("[TOOL_CALL]") - 1` 个可能被标记前缀占用的字符；完整标记一到齐就立刻剥离并转成 `tool_calls` delta，标记不会泄漏到正文里。

同一提示词（1403 字长回复）实测：

| 请求形态 | SSE 块数 | 首块 | 末块 | 首末块间隔占比 |
|---------|---------|------|------|--------------|
| 不带 `tools` | 348 | 2.73s | 8.12s | 66% |
| 带 `tools`（修复前） | 1 | 2.83s | 2.83s | 0% |
| 带 `tools`（修复后） | 198 | 2.48s | 6.06s | 59% |

`tools` 存在时仍保留的差异：工具调用前的那句对话文字（如「好的，我来看一下」）会实时流出，但它的收尾要等标记判定完成，所以最后几个字会随 `tool_calls` delta 一起到达。

### Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8088/v1",
    api_key="any"  # 随意填，不校验
)

resp = client.chat.completions.create(
    model="NewApi/chat-pro",
    messages=[{"role": "user", "content": "你好"}]
)
print(resp.choices[0].message.content)
```

## 接入第三方工具

| 配置项 | 值 |
|--------|-----|
| API Base URL | `http://127.0.0.1:8088/v1` |
| API Key | `any`（未开启认证时随意填） |
| 模型名 | `NewApi/chat-pro` |

已验证可接入：OpenAI Python SDK、LangChain、Cursor、Continue、ChatBox、NextChat 等。

### 接入 dsh（DeepSeek Harness）

dsh 的每个 profile 有一层独立补丁，代理配置写在这里：
`%USERPROFILE%\.dsh\profiles\<profile>\cordis.patch.yml`（`web` 与 `headless` 各一份，两份都要写，否则只有其中一个 profile 能用）。

**1) 在 `llm-pi-ai` 的 `providers` 下新增本机代理，并列全星小辰 5 档：**

```yaml
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      teleagent-proxy:
        displayName: TeleAgent 本地代理
        apiKeyEnv: TELEAGENT_PROXY_API_KEY
        api: openai-completions
        baseURL: http://127.0.0.1:8088/v1
        models:
          - id: NewApi/chat-flagship
            name: 星小辰 chat-flagship（旗舰）
            description: 星小辰 旗舰 档，934465 上下文 / 65536 输出
            contextWindow: 934465
            maxTokens: 65536
            input:
              - text
          - id: NewApi/chat-flash
            name: 星小辰 chat-flash（极速）
            description: 星小辰 极速 档，934465 上下文 / 65536 输出
            contextWindow: 934465
            maxTokens: 65536
            input:
              - text
          - id: NewApi/chat-pro
            name: 星小辰 chat-pro（智能）
            description: 星小辰 智能 档，934465 上下文 / 65536 输出
            contextWindow: 934465
            maxTokens: 65536
            input:
              - text
          - id: NewApi/chat-lite
            name: 星小辰 chat-lite（轻量）
            description: 星小辰 轻量 档，92350 上下文 / 16384 输出
            contextWindow: 92350
            maxTokens: 16384
            input:
              - text
          - id: NewApi/chat-nano
            name: 星小辰 chat-nano（轻速）
            description: 星小辰 轻速 档，92350 上下文 / 16384 输出
            contextWindow: 92350
            maxTokens: 16384
            input:
              - text
```

上下文取 super-agent 提供的 `safeContextLimit`（已扣除其自身 system prompt 开销，即实际可用窗口），最大输出取 `limit.output`。五档都只支持文本输入输出与 tool call，不支持 `temperature` 调节与 reasoning，因此**不要**声明 `reasoningEfforts`。

**2) 把默认模型切到代理：**

```yaml
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: teleagent-proxy
    model: NewApi/chat-pro
```

**3) 设用户级环境变量：**

dsh 的 `apiKeyEnv` 解析的是**进程环境变量**，不读 `~/.dsh/.credentials.yaml` 的 `refs:` 段，所以 Key 必须落到用户级环境变量里（代理默认 `auth=off`，填 `any` 即可；切到 `strict` 后换成控制台「认证」面板生成的 `tap-` 开头 Key）：

```powershell
[Environment]::SetEnvironmentVariable('TELEAGENT_PROXY_API_KEY', 'any', 'User')
```

**4) 验证：**

```powershell
dsh --profile web --dump-config        # 合成配置里应能看到 5 个 NewApi 模型
dsh --profile headless "只回复四个字：代理链路通"
```

> 改补丁文件时注意两点：一是同一个映射里**不能出现重复的 `models:` 键**，dsh 会把后一个当成新键，前一个模型列表随之丢失（合成配置里一个模型都不剩）；二是 `web` profile 里 `ui-theme` 与 `permission` 两段属于顶层条目，不要写进 `llm-pi-ai` 的 `config` 里。

## 认证（API Key）

控制台的「认证」面板可随时开关并管理 API Key，改动即时生效，无需重启。

### 三档模式

| 模式 | 校验行为 | 适用场景 |
|------|---------|---------|
| `off` | 不校验任何 Key（默认） | 纯本机个人使用，保持旧行为 |
| `partial` | 只校验本代理签发的 Key（`tap-` 前缀）；其它取值放行 | 多客户端已接入，先做用量归因再收紧 |
| `strict` | 所有受保护路径必须携带有效 Key，否则 401 | 局域网共享，需要真正的访问控制 |

`partial` 是过渡档：现有客户端配 `api_key="any"` 的用法不受影响，同时可以先拿到按 Key 的用量归因。

### 端点保护范围

- **数据面** `/v1/*`：`partial` / `strict` 下校验 `Authorization: Bearer <key>`（也兼容 `x-api-key` 头）
- **管理面** `/api/*`：本机来源（`127.0.0.1` / `::1`）放行，非本机来源按数据面规则校验
- **永远放行**：`/console`、`/health`、`/favicon.ico`

管理面按来源分层而不是给控制台加登录，是因为本项目是单机代理：默认只监听回环地址时本机浏览器改配置不受阻，一旦改成 `0.0.0.0`，管理面自动纳入 Key 校验。校验在路由分发之前统一执行，不会漏掉端点。

### 密钥的生成与存储

- 密钥**只支持服务端生成**（`tap-` + 43 字符随机串，256 位熵），不支持自定义——需要分发给脚本和第三方客户端的 Key 应当是高熵随机值
- 存储在脚本同级的 `auth.json`，只落**加盐哈希**（`sha256(salt || key)`）与无盐索引，明文 Key **仅在创建时返回一次**，之后列表只显示前缀
- 支持按 Key 停用、吊销、设置过期时间、限定可用模型（越权返回 403）
- 请求日志新增 `api_key_name` 字段，可按 Key 归因用量

### 切换到 strict 之前

`strict` 模式下现有客户端需要改用签发的 Key，否则会收到 401。响应体与 OpenAI 一致，OpenAI SDK 会直接抛出 `AuthenticationError`：

```json
{
  "error": {
    "message": "Incorrect API key provided: tap-7f3c…abcd",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

## 会话自动放行（全会话「全自动执行」）

TeleAgent 的会话权限以规则数组表达，在客户端界面把会话设成「全自动执行」，等价于给该会话预置一批 `allow` 规则。

代理创建的会话若不带规则，AI 一旦触发外部目录、命令执行等敏感操作就会发出权限确认事件——**无头客户端（dsh、定时任务、CI）无人应答，请求会一直挂到超时**。本项能力让代理侧会话与手工设成「全自动执行」的会话行为一致。

开启后代理会做两件事：

- **新建会话**时预置 10 类权限的 allow 规则（`bash` `edit` `read` `write` `glob` `grep` `webfetch` `task` `tool` `external_directory`）
- **既有会话**在收到权限确认事件时立即以 `always` 回复，既解锁当前请求，又让 TeleAgent 把该规则持久化到会话

默认开启，可在控制台「认证」面板切换，或用 `--no-auto-approve` 关闭：

```bash
python openai_proxy.py --no-auto-approve
```

也可通过接口读写：

```bash
curl http://127.0.0.1:8088/api/auto-approve
curl -X POST http://127.0.0.1:8088/api/auto-approve \
  -H "Content-Type: application/json" -d '{"enabled": false}'
```

> 关闭后敏感操作会重新需要人工确认，可通过 `GET /api/permission/pending` 查看待确认项、`POST /api/permission/reply` 应答。

## Web 控制台

访问 `http://127.0.0.1:8088/console` 即可使用：

- **仪表盘**：实时统计（请求数/Token/错误率）、服务状态、模型调用统计
- **模型管理**：浏览 TeleAgent 中已配置成功的模型（按 Provider 分组），新增配置自动同步
- **认证**：开关认证模式、生成与吊销 API Key、设置可用模型范围
- **默认模型设置**：在「系统」页修改默认模型，保存后立即生效
- **请求日志**：查看最近 200 条请求的时间/模型/状态/耗时/Token，并按 API Key 归因
- **在线测试**：直接在页面发送请求并查看响应
- **会话管理**：查看 super-agent 创建的会话列表
- **系统信息**：版本、签名机制、API 端点文档
- **使用说明**：内置完整使用文档，含代码示例和一键复制

## 持久化运行（Windows 任务计划程序）

Windows 上用「任务计划程序」替代 launchd，实现用户登录时自启 + 崩溃自动重启：

```powershell
# 注册计划任务（默认只监听 127.0.0.1:8088）
powershell -ExecutionPolicy Bypass -File install-scheduled-task.ps1

# 立即启动 / 停止 / 查看
Start-ScheduledTask -TaskName "TeleAgent OpenAI Proxy"
Stop-ScheduledTask  -TaskName "TeleAgent OpenAI Proxy"
Get-ScheduledTask  -TaskName "TeleAgent OpenAI Proxy" | Get-ScheduledTaskInfo

# 卸载
powershell -ExecutionPolicy Bypass -File install-scheduled-task.ps1 -Uninstall
```

> 任务在**用户登录时**触发（与 TeleAgent 桌面应用的启动时机一致），日志写入 `%LOCALAPPDATA%\TeleAgentOpenAIProxy\`。

## 持久化运行（macOS launchd）

```bash
# 创建 launchd 配置
cat > ~/Library/LaunchAgents/com.lizhun.openai-proxy.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lizhun.openai-proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/Cellar/python@3.11/3.11.15/Frameworks/Python.framework/Versions/3.11/bin/python3.11</string>
        <string>/Users/YOUR_USERNAME/scripts/openai_proxy.py</string>
        <string>--port</string>
        <string>8088</string>
        <string>--host</string>
        <string>0.0.0.0</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/openai-proxy.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/openai-proxy.log</string>
</dict>
</plist>
EOF

# 加载服务
launchctl load ~/Library/LaunchAgents/com.lizhun.openai-proxy.plist

# 查看状态
launchctl list | grep openai-proxy

# 重启服务
launchctl unload ~/Library/LaunchAgents/com.lizhun.openai-proxy.plist
launchctl load ~/Library/LaunchAgents/com.lizhun.openai-proxy.plist
```

## 工作原理

```
┌──────────────┐     OpenAI 格式      ┌───────────────┐     签名请求      ┌─────────────────┐
│  客户端/SDK   │ ──────────────────→ │  代理 (8088)   │ ──────────────→ │  super-agent     │
│  (curl/SDK)  │ ←────────────────── │  (Python)     │ ←────────────── │  (4397)          │
└──────────────┘    流式 SSE / JSON   └───────────────┘   SSE 事件流     └─────────────────┘
                                                                            │
                                                                    ┌───────┴───────┐
                                                                    │  TeleAgent     │
                                                                    │  桌面应用       │
                                                                    └───────────────┘
```

1. 客户端发送标准 OpenAI 格式请求到代理
2. 代理创建 super-agent 会话，启动 SSE 事件监听
3. 代理通过 `POST /session/{id}/prompt_async` 异步发送消息
4. 代理监听 `/global/event` SSE 事件流，收集 assistant 回复
5. 代理将回复转换为 OpenAI 格式返回（流式或非流式）

### 签名机制

代理自动从运行中的 TeleAgent 进程环境变量中提取 `SUPER_AGENT_LOCAL_SESSION_KEY`，使用 HMAC-SHA256 + base64url 生成签名头：

> - **macOS**：通过 `pgrep` + `ps eww` 读取进程环境
> - **Windows**：改为遍历 `node.exe` / `TeleAgent.exe` 并直接读取目标进程的 PEB 环境块（`NtQueryInformationProcess` + `ReadProcessMemory`，纯 ctypes 标准库实现，无需管理员权限）
>   - 注意：scheduler 启动后会在 JS 层 `delete process.env[SUPER_AGENT_LOCAL_SESSION_KEY]`，该操作在 Windows 上会真正 unset 掉 PEB 环境块中的变量（macOS 的 `ps eww` 读的是启动时快照，不受影响），因此 Windows 上 key 实际由 **im-service 进程**持有。实现按「扫描所有候选进程」而非硬编码 PID，TeleAgent 升级后仍可自适应

```
payload = "\n".join(["local-v1", method, path_with_query, timestamp_ms, nonce])
signature = HMAC-SHA256(session_key, payload).digest("base64url")
```

请求头：`X-SA-Sign-Version`, `X-SA-Timestamp`, `X-SA-Nonce`, `X-SA-Signature`

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 获取模型列表 (OpenAI 兼容) |
| POST | `/v1/chat/completions` | 聊天补全，支持 stream (OpenAI 兼容) |
| GET | `/health` | 健康检查 |
| GET | `/console` | Web 控制台页面 |
| GET | `/api/status` | 代理服务状态 |
| GET | `/api/models` | 详细模型列表（仅含 TeleAgent 已配置的 Provider/模型） |
| GET | `/api/default-model` | 获取当前默认模型 |
| POST | `/api/default-model` | 修改默认模型（立即生效） |
| GET | `/api/logs` | 请求日志 |
| GET | `/api/sessions` | super-agent 会话列表 |
| GET | `/api/stats` | 统计数据 |
| POST | `/api/test` | 在线测试接口 |
| GET | `/api/auth/status` | 认证模式、Key 数量、本次请求是否已认证 |
| GET | `/api/auth/keys` | API Key 列表（仅前缀） |
| POST | `/api/auth/keys` | 创建 API Key（完整 Key 仅此一次返回） |
| PATCH | `/api/auth/keys/<id>` | 改名、启停、设置可用模型与过期时间 |
| DELETE | `/api/auth/keys/<id>` | 吊销 API Key |
| POST | `/api/auth/mode` | 切换认证模式（`off` / `partial` / `strict`） |

## 技术细节

- **零依赖**：纯 Python 标准库（`http.server`, `hmac`, `json`, `threading`, `secrets`, `hashlib`），无第三方包
- **跨平台**：macOS 与 Windows 共用同一份业务代码；平台差异集中在 session key 提取与调用方反查两处（Windows 分支基于 `ctypes`）
- **认证分层**：校验在路由分发之前统一执行，管理面按来源分层，避免出现"部分端点受保护"的假安全感
- **密钥存储**：只落加盐哈希，明文仅创建时返回一次；多 Key 用无盐索引 O(1) 定位候选
- **线程安全**：每个请求独立线程处理，SSE 监听器在子线程运行
- **会话隔离**：每次 API 请求创建独立的 super-agent 会话
- **日志环形缓冲**：保留最近 200 条请求日志
- **Token 统计**：从 SSE 事件中提取输入/输出/推理/缓存 token

## License

MIT