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
| API Key | `any`（随意填写） |
| 模型名 | `NewApi/chat-pro` |

已验证可接入：OpenAI Python SDK、LangChain、Cursor、Continue、ChatBox、NextChat 等。

## Web 控制台

访问 `http://127.0.0.1:8088/console` 即可使用：

- **仪表盘**：实时统计（请求数/Token/错误率）、服务状态、模型调用统计
- **模型管理**：浏览 TeleAgent 中已配置成功的模型（按 Provider 分组），新增配置自动同步
- **默认模型设置**：在「系统」页修改默认模型，保存后立即生效
- **请求日志**：查看最近 200 条请求的时间/模型/状态/耗时/Token
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

## 技术细节

- **零依赖**：纯 Python 标准库（`http.server`, `hmac`, `json`, `threading`），无第三方包
- **跨平台**：macOS 与 Windows 共用同一份业务代码；平台差异集中在 session key 提取与调用方反查两处（Windows 分支基于 `ctypes`）
- **线程安全**：每个请求独立线程处理，SSE 监听器在子线程运行
- **会话隔离**：每次 API 请求创建独立的 super-agent 会话
- **日志环形缓冲**：保留最近 200 条请求日志
- **Token 统计**：从 SSE 事件中提取输入/输出/推理/缓存 token

## License

MIT