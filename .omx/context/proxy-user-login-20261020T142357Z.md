# 上下文快照 — proxy-user-login

| 字段 | 值 |
| --- | --- |
| slug | `proxy-user-login` |
| 时间戳 (UTC) | 20261020T142357Z |
| 工作区 | `C:\WorkSpaces\github\teleagent-openai-proxy` |
| 链路 | deep-interview → ralplan → team → merge/release |
| 类型 | brownfield |
| 采集方式 | 只读探查（read/grep/bash + git 只读命令） |

---

## 1. 任务陈述

用户原话：**"我们这个项目要加一个用户登录功能。鉴权方案我还没定，用 JWT 还是 session 也没想好。现在有 3 个人可以并行开发，帮我把这件事从需求澄清一直推进到代码合并上线。"**

拆解为三个可交付子目标：

1. **需求澄清** — 把"加一个用户登录功能"变成可验收的规格（用户显式声明方案未定，属于典型的"意图含糊、缺验收标准"）。
2. **并行推进** — 3 人可并行的 lane 切分（文件所有权互斥）。
3. **代码合并上线** — 合并进 `main` 并让线上实例生效。

## 2. 期望结果（从用户表述推断）

- 有一个**被用户认可**的鉴权方案（不是代理替用户拍板的）。
- 3 条**互不重叠**的 lane，可由 3 个人同时开工，不需要额外仲裁。
- 代码进 `main`，线上实例（计划任务 / 手工进程）跑上新代码。
- 需求不清的地方**先问清楚再动手**，不要假设。

## 3. 用户所述方案

- "鉴权方案我还没定" → **用户明确把方案选择权留空**。这是需求缺口，不是让我自行决定。
- "用 JWT 还是 session 也没想好" → 用户已经把候选收敛到 2 个：JWT / 服务端 session。
- "3 个人可以并行开发" → 暗示切面天然可分（但具体切法未知）。
- "从需求澄清一直推进到代码合并上线" → 全链路授权，包含发布动作。

## 4. 意图假设（标注为假设，非用户确认）

| # | 假设 | 依据 | 若错的代价 |
| --- | --- | --- | --- |
| A1 | "用户"指**控制台的人类操作者**，不是调用 `/v1` 的程序 | 仓库只有 Web 控制台是"人"的入口；`/v1` 侧已有 API Key 机制 | 方案要整体重做（给 SDK 客户端做账号体系） |
| A2 | 动机是**当前实例在局域网裸奔** | 实测监听 `0.0.0.0:8088`，且 `auth.json` 的 `mode` 为 `off` | 动机若是"多租户配额"，则范围扩大一档 |
| A3 | 登录只保护**控制台 + 管理面 `/api/*`**，`/v1/*` 维持现状 | 现有 API Key 体系已覆盖 `/v1`，README 也把 `/v1` 的鉴权写死在 Key 上 | 若 `/v1` 也要按用户计量，需再做一版（绑定 user_id） |
| A4 | "上线"= 本机服务（计划任务/手工进程）跑到新代码 | 该项目是本地代理，README 记录的是 launchd / 任务计划程序，不是云部署 | 若指真正的云上服务，本仓库不是发布载体 |

## 5. 已知事实 / 证据（可回溯）

| # | 事实 | 证据 |
| --- | --- | --- |
| F1 | 纯 Python 标准库实现，**零第三方依赖** | `README.md:269`「零依赖：纯 Python 标准库」；`openai_proxy.py:19-38` import 列表 |
| F2 | 主文件单文件 4000 行，`openai_proxy.py` | `openai_proxy.py` 共 4000 行 |
| F3 | **已有 API Key 鉴权体系**：`off/partial/strict` 三档模式 | `openai_proxy.py:193`（`AUTH_MODES`）、`:346-382`（`_auth_check`） |
| F4 | API Key 存储为加盐 SHA-256 + 无盐查找索引，前缀 `tap-`，服务端生成 | `openai_proxy.py:270-291`、`:203-247`、`auth.json` |
| F5 | `/console`、`/health`、`/favicon.ico` 永久豁免鉴权 | `openai_proxy.py:194`、`:349` |
| F6 | 管理面 `/api/*` 对**本机来源免鉴权**（控制台自举） | `openai_proxy.py:353-354`、`:334-336` |
| F7 | 控制台是内联在 `openai_proxy.py` 的 HTML 字符串 | `openai_proxy.py:3431`（`CONSOLE_HTML = r"""...`）、`:2765-2774`（`_serve_console`） |
| F8 | 路由入口统一在 `do_GET`/`do_POST`/`do_PATCH`/`do_DELETE` 顶部调用 `_auth_check` | `openai_proxy.py:2291-2356`、`:2532`、`:2544` |
| F9 | `auth.json` 当前 `mode: "off"`，且**未被 `.gitignore` 覆盖**（git 中为未跟踪文件） | `auth.json:3`；`git status` → `?? auth.json` |
| F10 | 工作区有**未提交改动**：`openai_proxy.py` +522 行（上一轮 API Key 鉴权实现） | `git diff --stat` → 1 file changed, 522 insertions |
| F11 | git 可用（不在 PATH，真实路径 `C:\Program Files\Git\cmd\git.exe`），远端 `origin` → `github.com/shangql/teleagent-openai-proxy`，分支 `main` | `git remote -v`、`git branch -a` |
| F12 | **线上实例正在跑**：`PID 26124`，`python.exe ... openai_proxy.py --host 0.0.0.0 --port 8088`，super-agent 在 `4397`（PID 24208） | `Get-NetTCPConnection` / `Get-CimInstance Win32_Process` |
| F13 | 计划任务 `TeleAgent OpenAI Proxy` 状态 `Ready`（未在跑），其 runner 指向 **本仓库**的 `openai_proxy.py`，参数 `--host 127.0.0.1 --port 8088` | `%LOCALAPPDATA%\TeleAgentOpenAIProxy\run-proxy.cmd` |
| F14 | 线上进程与计划任务参数不一致：线上是 `0.0.0.0`（局域网暴露），任务是 `127.0.0.1` | 同 F12/F13 |
| F15 | README 明确警告：代理**不校验 API Key**，`0.0.0.0` 会把能力暴露给整个局域网 | `README.md:84` |
| F16 | 无任何测试框架/测试目录/CI | 仓库无 `tests/`、无 `.github/` |
| F17 | 本机无独立 Python；可用解释器 = TeleAgent 自带 3.12 | `C:\Users\sql_h\.local\share\TeleAgent\runtimes\python\python.exe`（已验证存在） |
| F18 | 版本号 1.10.0，CHANGELOG 遵循 Keep a Changelog + SemVer | `VERSION`、��`CHANGELOG.md` 头部 |
| F19 | `openai_proxy_manager.py` 是 **macOS/launchd 专用**，Windows 侧管理靠计划任务 | `openai_proxy_manager.py:27,31` |

## 6. 约束

| # | 约束 | 来源 |
| --- | --- | --- |
| C1 | **不得引入第三方依赖**（纯标准库），否则打破 F1 的核心卖点 | `README.md:269` |
| C2 | 不破坏现有 `/v1` 调用方（本机机器人 `api_key="any"`） | `README.md:120-121`、`:134` |
| C3 | 不能打断正在运行的线上实例（PID 26124 在服务真实流量） | F12 |
| C4 | 产物落 `.omx/`，路径契约按 skill 约定 | skill `SKILL.md` 产物目录约定 |
| C5 | 平台双端（macOS + Windows）都要能跑 | `README.md:18-23` |
| C6 | 仓库规则面只有 README / CHANGELOG / skills/，**没有 AGENTS.md、没有 docs/、没有 ADR** | 目录清单 |

## 7. 未知项（用户才能回答）

| # | 未知项 | 为什么代理答不了 |
| --- | --- | --- |
| U1 | "用户"是谁：控制台人类操作者 / 调用 `/v1` 的程序 / 两者都要 | 仓库无用户体系，无从推断 |
| U2 | JWT 还是 session | 用户明说没想好；这是取舍题，须由用户接受代价 |
| U3 | 是否要**多用户**（多个账号 + 角色），还是单一管理员口令 | 无既有角色模型 |
| U4 | 是否要求**按用户计量/配额**（每人 token 上限、调用量统计） | 无既有配额设施 |
| U5 | 密码找回/重置的期望路径 | 仓库无邮件/邮件依赖 |
| U6 | 是否允许**关闭本机免鉴权**（`/api/*` 本机直连放行，F6） | 会打断本机机器人对 `/api/permission/reply` 的调用 |
| U7 | 会话是否需要跨重启保留 | 取决于是否愿意把令牌落盘 |

## 8. 决策边界

**可自行决定（不需回头问用户）**

- 模块切分、文件命名、函数签名（只要对外契约稳定）。
- 口令哈希算法选择（标准库内）：PBKDF2-HMAC-SHA256。
- 会话令牌的存储形态（内存 vs 落盘）、TTL 数值、Cookie 属性。
- 引导（bootstrap）流程的具体交互。
- 测试形态与目录结构。
- 提交信息、CHANGELOG/VERSION/README 的写法。

**必须问用户（不可替用户拍板）**

- U1 用户的定义、U2 鉴权方案、U3 是否多用户/角色、U4 是否按用户计量、U5 找回路径、U6 是否收紧本机免鉴权。

**处置原则（本会话的硬约束）**

> 本会话是**被委派的子会话**，按合同**不得直接向终端用户提问**，且当前工具集**没有 `ask_user` / `task` 子智能体**（`mcp_invoke` 的 `tool_search` 亦不可用）。
> 因此：**不伪造用户答案**。所有必须问用户的问题转写为 **Open Decision Ledger（ODL）**，每条给出「问题原文 + 证据推导的推荐默认 + 若用户改选的影响 + 证伪条件」，并**显式标注为待用户确认**；推荐默认只作为**可回滚的默认实现**落地。

## 9. 可能的代码触点

| 触点 | 位置 | 计划中的改动性质 |
| --- | --- | --- |
| 鉴权入口 | `openai_proxy.py:339`（`_auth_check`） | 扩展为"会话 or API Key"双凭证判定 |
| 路由分发 | `openai_proxy.py:2291-2356` | 新增 `/login`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/me` |
| 控制台出口 | `openai_proxy.py:2765`（`_serve_console`） | 未登录 → 302 `/login` |
| CLI | `openai_proxy.py:4391`（`main`） | 新增 `--reset-password` |
| 新模块 | `auth_users.py` / `auth_session.py`（新建） | 用户存储 / 会话与限流 |
| 测试 | `tests/`（新建） | stdlib `unittest` |
| 发布 | `VERSION`、`CHANGELOG.md`、`README.md`、`.gitignore` | 版本 1.11.0 + 文档 + 密钥不入库 |

## 10. 已检查的文档 / 规则面

- `README.md`（全文）— 特性、平台矩阵、API 端点表、技术细节、鉴权现状。
- `CHANGELOG.md`（头部）— 版本与条目格式。
- `skills/openai-proxy-manager/SKILL.md` — 管理面技能说明（macOS 口径）。
- `install-scheduled-task.ps1` — Windows 持久化安装口径。
- `openai_proxy_manager.py`（grep）— 管理脚本口径。
- `auth.json`、`VERSION`、`.gitignore`。
- 仓库内**无** `AGENTS.md` / `CONTEXT.md` / `docs/` / ADR（已用 glob 确认）。

## 11. 术语冲突（Terminologist 预判）

| 术语 | 冲突点 |
| --- | --- |
| "session" | 仓库里 `session` 指的是 **super-agent 会话**（`create_session` / `/api/sessions`），与"登录会话"同名不同物 → 本项目一律用 **login session / 登录会话**，代码里用 `login_session` |
| "auth" | 仓库 `auth.json` / `_auth_*` 指的是 **API Key 鉴权**；新增的账号体系须另起名 `user` / `login`，避免 `auth` 一词二义 |
| "用户" | 可能指"控制台人类"或"API 调用方" → 规格里拆成 **account（账号）** 与 **api key（机器凭证）** 两个概念 |
| "上线" | 该项目没有云环境，"上线" = 本机服务进程跑到新代码 + git `main` 合入 |
