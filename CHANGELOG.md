---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '13315246-d9de-4f59-b2ca-013db587a615'
  PropagateID: '13315246-d9de-4f59-b2ca-013db587a615'
  ReservedCode1: '91077164-869a-4d6f-a157-102273850e26'
  ReservedCode2: '91077164-869a-4d6f-a157-102273850e26'
---

# Changelog

本项目的所有重要变更记录在此文件中。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.14.0] - 2026-10-21

### 修复

- **带 `tools` 的请求没有流式体感**：早期实现为了拿到完整的 `[TOOL_CALL]...[/TOOL_CALL]` 标记，只要请求带 `tools` 就把整段正文缓冲到结束再解析。实测一句 89 字的回复只落成 **1 个 SSE 事件**，客户端要等模型全部说完才看到第一个字。而 dsh 一定会带 `tools`，这条路径覆盖了全部实际流量——「用 dsh 发消息，没有流式输出」，就是这个原因
  - 新增 `_StreamingTextSplitter`：正文照常增量下发，只压住末尾 `len("[TOOL_CALL]") - 1` 个可能被标记前缀占用的字符；完整标记一到齐立刻剥离并转成 `tool_calls` delta
  - 标记被拆到相邻增量块里也能识别（逐个偏移量有测试覆盖），不会泄漏到正文
  - 同一提示词（1403 字长回复）实测：带 `tools` 从 **1 块** 变为 **198 块**，首末块间隔占全程 59%；与不带 `tools` 的 348 块处于同一量级
  - 语义保持：`finish_reason` 仍是 `tool_calls`，正文在增量过程中先发出，`tool_calls` delta 紧随其后，`index` 跨整个响应连续编号；非法/残缺标记仍按旧实现原样回显

### 新增

- **单元测试**（`tests/test_streaming_splitter.py`）：19 个用例覆盖增量拼接无损、标记剥离、跨块标记、多标记编号、非法标记回显、切块方式无关性，以及与旧全量解析器的结果一致性。全套 56 个用例通过（`python -m unittest discover -s tests`）
- **README 新增「流式转发」小节**：说明带 `tools` 时的缓冲取舍与修复后的实测对比表

### 变更

- `VERSION` 同步至 1.14.0

## [1.13.0] - 2026-10-20

### 新增

- **README 补充「接入 dsh（DeepSeek Harness）」章节**：把 dsh 接入本代理的完整配置落成文档，避免每人重新摸索
  - 配置文件位置：`%USERPROFILE%\.dsh\profiles\<profile>\cordis.patch.yml`，`web` 与 `headless` 两个 profile 各一份，两份都要写
  - `llm-pi-ai` 的 `providers` 下新增 `teleagent-proxy` provider（`baseURL: http://127.0.0.1:8088/v1`），并列全星小辰 5 档：`chat-flagship` / `chat-flash` / `chat-pro`（上下文 934465、输出 65536），`chat-lite` / `chat-nano`（上下文 92350、输出 16384）。上下文取 super-agent 的 `safeContextLimit`（已扣除其自身 system prompt 开销），输出取 `limit.output`
  - 五档能力一致：仅文本输入输出、支持 tool call、不支持 `temperature` 调节与 reasoning，故**不声明** `reasoningEfforts`
  - `agent-default-model` 切到 `provider: teleagent-proxy` / `model: NewApi/chat-pro`
  - **环境变量坑**：dsh 的 `apiKeyEnv` 解析的是**进程环境变量**，不读 `~/.dsh/.credentials.yaml` 的 `refs:` 段，Key 必须设成用户级环境变量才生效
  - **补丁文件坑**：同一映射里出现重复的 `models:` 键时，dsh 把后一个当成新键，前一个模型列表随之丢失（合成配置里一个模型都不剩）；`web` profile 的 `ui-theme` 与 `permission` 两段属顶层条目，不可写进 `llm-pi-ai` 的 `config` 内
  - 验证命令：`dsh --profile web --dump-config`（合成配置应含 5 个 NewApi 模型）与 `dsh --profile headless "只回复四个字：代理链路通"`

### 变更

- `VERSION` 同步至 1.13.0

## [1.12.0] - 2026-10-20

### 新增

- **会话自动放行（全会话「全自动执行」）**：此前代理创建的 super-agent 会话不带任何 permission 规则，AI 一旦触发外部目录、命令执行等敏感操作就会发出权限确认事件——**无头客户端（dsh、定时任务、CI）无人应答，请求会一直挂到超时**（实测 200s 超时）。现在会话行为与在 TeleAgent 界面手工设成「全自动执行」一致
  - 新建会话时预置 10 类权限的 allow 规则（`bash` `edit` `read` `write` `glob` `grep` `webfetch` `task` `tool` `external_directory`），由 super-agent 随会话持久化
  - 既有会话在收到权限确认事件时立即以 `always` 回复，既解锁当前请求，又让 super-agent 把该规则持久化到会话
  - 默认开启，可在控制台「认证」面板切换，或用 `--no-auto-approve` 关闭；也可读写 `GET/POST /api/auto-approve`
  - 代理只认「创建时带规则」：`PATCH /session/<id>` 虽返回 200 但**不持久化** permission 字段（实测四种写法均无效），所以既有会话走「自动回复 always」而不是 PATCH

- **用户登录鉴权基座**（`user_auth.py`）：在 API Key 认证之外补齐「人访问控制台」这一层。纯标准库实现，零第三方依赖，且**不 import `openai_proxy.py`**，可被单元测试直接驱动
  - **账号库**：`users.json`（与 `auth.json` 同目录，运行期生成，禁止入库），基于 JSON 文件 + 原子写（先写临时文件再 `os.replace`）+ 线程锁
  - **口令存储**：PBKDF2-HMAC-SHA256，210,000 次迭代、随机盐、哈希串自描述（算法与迭代次数随哈希一并保存，便于后续提升迭代次数）。口令策略只约束长度（10–256），不做字符集规则
  - **登录会话**：`tap_sid` Cookie，8 小时有效期、滑动续期、每用户最多 5 个会话；**会话不落盘**，重启后需重新登录（更安全的默认）
  - **角色**：`admin` / `viewer`；用户状态 `enabled` / `disabled`，停用账号会连带吊销其既有会话
  - **登录模式三档**：`off`（默认，保持现网行为）/ `optional`（校验登录但本机来源 `127.0.0.1` 仍放行，便于灰度与回滚）/ `required`（全量强制登录）
  - **登录失败限流**：按「用户名 + 来源 IP」统计，5 次 / 300 秒窗口触发后锁定 60 秒
  - **CSRF**：双提交校验，请求头 `X-CSRF-Token` 必须与会话中的令牌一致
  - **防用户名枚举**：未知用户与错误口令返回同一提示
  - **统一错误码**：`invalid_credentials` / `locked_out` / `user_disabled` / `weak_password` / `invalid_username` / `user_exists` / `user_not_found` / `invalid_mode`
  - **命令行管理**：`--init-admin` / `--create-user` / `--role` / `--set-password` / `--disable-user` / `--enable-user` / `--delete-user` / `--list-users` / `--set-mode` / `--password-stdin`
- **单元测试**（`tests/test_user_auth.py`）：标准库 `unittest`，37 个用例覆盖口令哈希、账号库 CRUD、登录、会话生命周期、HTTP helper 与 CLI，全部通过（`python -m unittest discover -s tests -v`）
- **设计与实施文档**：`docs/adr-0001-user-login-auth-scheme.md`（架构决策记录）、`docs/user-login-api-contract.md`（前后端接口契约）、`docs/user-login-plan.md`（实施计划）
- **实施计划留档**（`.omx/`）：深访规格、PRD、测试规格、Architect/Critic 两轮评审记录、三泳道分工与基线验证脚本

### 修复

- **调用方识别抖动导致同一客户端分裂成两套会话**：会话标题的第二段取自反查到的调用进程名，识别失败时退化为「未知」，于是「外部\|Node服务\|…」与「外部\|…」成为两个不同的匹配 key，同一客户端被拆成两套互不相通的会话（历史会话里两种标题并存即为证据）。现在按来源 IP 记住最近一次成功识别的结果作为兜底，消除抖动
- **计划任务停止后 python 子进程变孤儿**：任务动作用 `.cmd` 转发时，`Stop-ScheduledTask` 只回收 cmd.exe，python.exe 继续存活并占着 8088；重启任务则出现两个监听者，Windows 的 `SO_REUSEADDR` 会把请求随机分发到两个实例。改为任务**直接托管 python 进程**，停止即回收

### 变更

- `VERSION` 同步至 1.12.0，`.gitignore` 增加 `users.json`
- 模块 docstring 与 README 的认证说明改为"默认不校验，可在控制台开启"，不再写死"不做校验"

> 本版交付的 `user_auth.py` 是**鉴权基座**，尚未接入 `openai_proxy.py` 的路由层——`AuthManager` 已提供 `login` / `logout` / `authenticate` / `set_mode` 等门面方法，路由接入由后续泳道完成。

## [1.11.0] - 2026-10-20

### 新增

- **API Key 认证（控制台可配置）**：此前代理完全不校验 `Authorization`，README 明确写着"随意填，不校验"。现在控制台新增「认证」面板，可随时开关并管理 Key，改动即时生效无需重启
  - **三档模式**：`off`（默认，保持旧行为）/ `partial`（只校验本代理签发的 `tap-` 前缀 Key，其它取值放行）/ `strict`（所有受保护路径必须携带有效 Key，否则 401）
    - `partial` 是过渡档：现有客户端配 `api_key="any"` 的用法不受影响，同时可先拿到按 Key 的用量归因，再切 `strict`
  - **端点分层**：数据面 `/v1/*` 校验 `Authorization: Bearer`（兼容 `x-api-key`）；管理面 `/api/*` 本机来源（`127.0.0.1` / `::1`）放行、非本机来源同数据面规则；`/console`、`/health`、`/favicon.ico` 永远放行
    - 管理面按来源分层而非给控制台加登录：单机场景下"绑哪个地址"是用户本来就要做的决定，而管理面若裸奔，局域网可直接改配置
    - 校验放在 `do_GET` / `do_POST` 路由分发**之前**统一执行，避免按前缀枚举时漏掉端点（vLLM 的 `--api-key` 只覆盖 `/v1` `/v2` `/inference` `/cohere`，`/invocations` 可无凭据完成同样的推理）
  - **密钥生成与存储**：只支持服务端生成（`tap-` + `secrets.token_urlsafe(32)`，256 位熵），不支持自定义——需分发给脚本和第三方客户端的 Key 应是高熵随机值
    - 存储在脚本同级的 `auth.json`，只落**加盐哈希** `sha256(salt || key)` 与无盐索引 `sha256(key)`；明文 Key **仅在创建时返回一次**，列表只显示前缀
    - 多 Key 校验先用无盐索引 O(1) 定位候选，再做带盐比对（`hmac.compare_digest`），两次 SHA-256，微秒级
    - 存哈希而非明文的额外理由：控制台本身可能对局域网可达，明文存储等于把密钥管理的入口变成密钥泄漏的入口
  - **Key 生命周期**：按 Key 停用、吊销、设置过期时间、限定可用模型范围（越权返回 403，区别于认证失败的 401）
  - **用量归因**：请求日志新增 `api_key_name` 字段，复用既有的来源追踪与 `logs/requests-YYYY-MM-DD.jsonl` 落盘
  - **管理接口**：`GET /api/auth/status`、`GET/POST /api/auth/keys`、`PATCH/DELETE /api/auth/keys/<id>`、`POST /api/auth/mode`
  - **错误体与 OpenAI 一致**：`{"error":{"message","type","param","code"}}` + `code: "invalid_api_key"`，OpenAI SDK 直接抛 `AuthenticationError`；401 表示认证失败，403 表示作用域不足
  - 认证在解析请求体**之前**完成，失败请求不消耗额度、不占用 super-agent 会话
  - `auth.json` 加入 `.gitignore`

### 变更

- 模块 docstring 与 README 的认证说明改为"默认不校验，可在控制台开启"，不再写死"不做校验"

## [1.10.0] - 2026-10-20

### 新增

- **Windows 平台支持**：此前仅支持 macOS，Windows 上无法启动（`pgrep` / `ps eww` 不存在）。本次完成适配并在 Windows 实机验证通过
  - **session key 提取（核心）**：macOS 用 `pgrep` + `ps eww` 读进程环境，Windows 无等价命令，改为遍历 `node.exe` / `TeleAgent.exe` 并直接读取目标进程的 PEB 环境块
    - 实现：纯标准库 ctypes——`CreateToolhelp32Snapshot` 枚举进程 → `NtQueryInformationProcess(ProcessBasicInformation)` 定位 PEB → 探测 `RTL_USER_PROCESS_PARAMETERS` 中 `Environment` 偏移 → `ReadProcessMemory` 读出 UTF-16LE 环境块 → 匹配 `SUPER_AGENT_LOCAL_SESSION_KEY=`；**无需管理员权限、无第三方依赖**
    - 关键发现：scheduler 源码中 `delete process.env[SESSION_KEY_ENV]` 在 Windows 上会真正 unset 掉 PEB 环境块里的变量（macOS 的 `ps eww` 读的是启动时快照，不受影响），因此 key 实际由 **im-service 进程**持有，而非 scheduler。实现按"扫描所有候选进程"而非硬编码 PID，TeleAgent 升级后仍可自适应
  - **调用方反查**：新增 `netstat -ano` 版实现替代 macOS 的 `lsof -i :8088`；配套 `_win_process_command_line()`（`ProcessCommandLineInformation`）取目标进程完整命令行
  - **启动脚本**：`start_proxy.cmd`——自动挑选可用解释器（优先 TeleAgent 自带 Python 3.12 运行时，其次系统 PATH 上的 python），启动前检查 4397 端口是否有 super-agent 在监听；文件为纯 ASCII，兼容任意 Windows 控制台代码页
  - **持久化**：`install-scheduled-task.ps1`——用「任务计划程序」替代 launchd plist（用户登录时自启 + 失败自动重启），支持 `-Uninstall` 卸载
  - **README**：新增「平台支持」对照表（macOS / Windows 的 key 获取方式与持久化方式）、按平台拆分的「前置条件」与「启动代理」命令、「Windows 专项说明」与「持久化运行（Windows 任务计划程序）」章节；签名机制章节补充 Windows 取 key 的实现说明与 im-service 进程持有 key 的原因
- **多平台静态常量**：`PLATFORM_LABEL` / `SESSION_KEY_SOURCE_LABEL`，控制台「运行平台」「Session Key 来源」按平台动态渲染，不再硬编码 macOS 文案

### 修复

- **多模态图片临时目录硬编码 `/tmp/reachy_vision`**：Windows 上会解析到当前盘符根目录，改为 `tempfile.gettempdir()`（macOS 行为不变）
- **`/api/status` 的 `listen` 字段硬编码 `0.0.0.0`**：无论实际绑定什么地址都显示 `0.0.0.0`，改为输出真实绑定地址——在只监听 `127.0.0.1` 时也能准确反映，避免误判代理的暴露范围

> macOS 行为保持不变，原有 `pgrep` + `ps eww` 取 key 路径原样保留。

## [1.9.10] - 2026-09-27

### 修复

- **会话复用只按标题第一段匹配，跨天不新建会话**：脚本/curl/AI工厂/机器人等来源的会话标题虽含日期（如「脚本|Python脚本|2026-09-27|07:12」），但请求永远复用同一个旧会话，"一天一个会话"的设计失效
  - 根因：`get_session_by_title()` 与 `get_or_create_session()` 的匹配/缓存 key 均取 `title.split("|", 1)[0]`（仅来源标签，如"脚本"），标题中的日期段（第三段）完全不参与匹配——注释里"时间变化仍复用"的前缀匹配设计，副作用是日期变化也被豁免；且第二段调用进程名同样不参与匹配，所有 Python 脚本共用一个会话，舆情分析与微信摘要等不同任务串在同一会话里
  - 修复：新增 `_session_match_key(title)`——去掉标题尾部 HH:MM 时间段后整体比较：「脚本|Python脚本|2026-09-27|07:12」→ key「脚本|Python脚本|2026-09-27」；`get_session_by_title()` 匹配与 `get_or_create_session()` 缓存 key 统一换用该函数
    - 同一天内时间变化 key 不变 → 继续复用（保留原设计意图）
    - 跨天日期变化 key 变化 → 不再命中 → 自动新建当天会话
    - 企微/QQ/密信等无日期段标题 → key 即完整标题，顺带修复不同用户/群可能串会话的隐患
  - 验证：函数级 11 个用例全过（含跨天不匹配/同日不同时间匹配/企微完整保留/空标题）；重启 8088 后实测——今日请求不再命中旧会话 ses_f321（其真实标题为更早日期、已被连续复用多天），自动新建 ses_f1ff4dd6（标题 2026-09-27），同日第二次请求正确复用；模拟今日 23:59 标题仍命中今日会话，昨日标题互不命中
  - 真实案例：2026-09-27 07:12 舆情批次请求标题已是「脚本|Python脚本|2026-09-27|07:12」，但仍落入 09-26 之前创建的 ses_f321b9fe（日志 requests-2026-09-26.jsonl 61 次 / 2026-09-27.jsonl 24 次全部同一会话）
- **identify_caller_process 万达云穿透误判**（随本版一并提交的既有改动）：UA 已明确标识调用方类型（python-requests/python-urllib/curl/node/axios）时短路，跳过 lsof+万达云 7892 端口穿透，避免穿透取得分更高的无关进程（如 AI工厂 Streamlit 105 分 > TeleAgent主程序 70 分）

### 变更

- 企微/QQ/密信会话匹配从"第一段前缀"收紧为完整标题（渠道标识+用户/群 ID），多用户/多群场景不再共享同一会话

## [1.9.9] - 2026-09-01

### 修复

- **question.asked 确认推送缺少问题描述**：AI 发起交互式问答（如"是否创建腾讯会议提醒？"）时，QQ/飞书收到确认通知只有"需要您确认操作"模板，看不到具体确认内容
  - 根因：`question.asked` 事件的问题正文不在 `description`/`prompt` 字段，而在 `tool.input.questions[]`（结构：`{header, question, options[]}`）；全局监听器 `GlobalConfirmationListener._handle_event` 和请求链路 `SSEListener`/`StreamingSSEListener` 的 question 分支只取 `description`/`prompt`，导致 desc 为空
  - 修复：新增共享函数 `_extract_question_desc(props)`，按优先级提取：`description`/`prompt` > `tool.input.questions[]`（header+question+options 拼装）> 兜底；三处 question 分支统一调用
  - 验证：单元测试通过（模拟真实事件结构提取出完整"确认创建会议提醒 | 是否按上述信息创建腾讯会议提醒？ | 选项: 确认创建；取消；修改时间"）；inject 端到端链路验证 pending 表 desc 完整
  - 真实案例：2026-09-01 17:06 QQ|私聊|李准 conf_id=que_05c3865be001ErdIhe0exwJmRU，日志 `[GLOBAL-CONF] desc=` 为空

## [1.9.8] - 2026-09-01

### 修复

- **密信/企微/QQ 等脚本被误判为「TeleAgent主程序」**：运行在 `~/.local/share/TeleAgent/TeleAgent的工作空间/` 下的脚本（wecom-bot/server.py 等）命令行路径含 "TeleAgent" 字样，被 `_friendly_caller_name` 的 `"teleagent" in cmd` 提前命中误判为主程序
  - 根因：`_friendly_caller_name` 中 TeleAgent 主程序判断（`"teleagent" in cmd_lower`）在 wecom-bot/QQ/密信/AI工厂 等具体应用判断**之前**；穿透评分同理（`"teleagent" in cmd` 评 70 分，早于 wecom/QQ/密信的 95 分）
  - 修复：
    - `_friendly_caller_name`：具体应用（wecom-bot/QQ/密信/AI工厂/Reachy Mini/面板测试/curl/Node）判断**前置**；主程序改为精确匹配特征 `super-agent-code/bin/teleagent`、`/applications/teleagent.app/contents/macos/teleagent`、`teleagent helper`、`opencowork`
    - `_penetrate_wandacloud_proxy` 评分：wecom/QQ/密信（95 分）提前到 teleagent（70 分）之前；super-agent 精确匹配 `super-agent-code/bin/teleagent`
  - 验证：wecom-bot/server.py 进程命令行识别为 "wecom-bot"（修复前为 "TeleAgent主程序"）；TeleAgent 主程序仍正确识别
- **真实案例**：2026-09-01 04:32 密信群聊记录（pid 71911，wecom-bot/server.py）被误标 caller="TeleAgent主程序"，修复后应为 "wecom-bot"

## [1.9.7] - 2026-08-31

### 修复

- **curl/脚本/Node 来源被 caller 覆盖为「子智能体」**：UA 已精确识别的来源标签不再被 lsof caller 反哺覆盖
  - 根因：`_GENERIC_SOURCE_TAGS` 包含了 `curl`/`脚本`/`Node`，万达云代理拦截后 lsof 只看到 TeleAgent主程序/万达云进程，将正确来源覆盖为「子智能体」
  - 修复：`_GENERIC_SOURCE_TAGS` 仅保留 `外部`/`子智能体`；UA 识别的标签不再参与 caller 反哺
  - 验证：curl 不传 session_title → source="curl"，标题 `curl|2026-08-31|20:00`（修复前为 `子智能体|TeleAgent主程序|星小辰-子智能体`）
- **面板日志显示旧记录**：`/api/logs` 返回 `disk_logs[-limit:]`，在按时间倒序的列表上取到的是**最旧**的 limit 条，导致面板看不到最新请求
  - 修复：改为 `[:limit]` 取最新记录；`date=YYYY-MM-DD` 参数同理
  - 验证：重启后面板返回的最新 3 条为 Reachy Mini 对话 07:54/07:53/07:52（修复前为最早 15 条旧记录）

## [1.9.6] - 2026-08-31

### 变更

- **会话标题格式调整**：按准哥要求统一为「来源|日期|时间」三段格式
  - Reachy Mini 对话：`Reachy Mini对话|2026-08-31|19:46`
  - Reachy Mini 预热：`Reachy Mini预热|2026-08-31|19:46`（原 `机器人预热|Reachy Mini|星小辰-子智能体`）
  - Reachy Mini 视觉：`Reachy Mini视觉|2026-08-31|19:46`（原 `机器人视觉|星小辰-子智能体`）
  - AI工厂：`AI工厂|2026-08-31|19:46`（原 `AI工厂|星小辰-子智能体`，第二段去掉基底换日期+时间）
  - 脚本：`脚本|Python脚本|2026-08-31|19:46`（原末段 `星小辰-子智能体` 换为日期+时间）
  - curl：`curl|2026-08-31|19:46`（原末段 `星小辰-子智能体` 换为日期+时间）
  - 企微/QQ/密信：保留原始业务标题不变
  - 子智能体/面板测试：保留原基底拼接方式不变

## [1.9.5] - 2026-08-31

### 新增

- **来源溯源体现到会话标题**：所有会话标题统一带来源标识，TeleAgent 会话名一眼可辨调用来源
  - 未传 `session_title` 时，自动按识别来源 + 调用进程拼接前缀，例如 `脚本|Python脚本|星小辰-子智能体`、`curl|星小辰-子智能体`、`机器人预热|Reachy Mini|星小辰-子智能体`、`子智能体|TeleAgent主程序|星小辰-子智能体`
  - 原始标题已带来源前缀（企微/QQ/密信等）时原样保留，避免重复拼接，不影响机器人按标题复用会话
  - 来源标签与调用方进程名相同时自动去重（如 `curl|星小辰-子智能体` 而非 `curl|curl|星小辰-子智能体`）
  - 新增 `build_source_session_title()` 函数，将来源识别逻辑（来源标签 + caller 进程名）前置到会话创建之前，与日志/面板的 source、caller 字段保持一致
- **caller 反哺来源标签**：当 session_title/UA 无法精确判定来源时，用 lsof 识别到的进程名反哺 source_tag
  - 新增 `_CALLER_SOURCE_MAP` 映射：Reachy Mini → 机器人、AI工厂 → AI工厂、机器人视觉 → 机器人视觉、wecom-bot → 企微、QQ适配器 → QQ、量子密信适配器 → 密信
  - 仅当 source_tag 是泛化标签（外部/子智能体/脚本/curl/Node）时才覆盖，避免误覆盖企微/QQ/密信等精确渠道
- **机器人标题识别**：识别 `星小辰机器人|时间` 格式的 session_title（Reachy Mini s2s 正常对话传入）为"机器人"来源
  - `星小辰机器人` 加入 `_SOURCE_PREFIXES`，避免在标题前重复拼接"机器人|"前缀
- **穿透评分调整**：万达云代理穿透时，应用进程（s2s/AI工厂/wecom-bot/QQ/密信）优先级高于 TeleAgent 框架进程
  - 原因：TeleAgent 主程序在 7892 上有持久 WebSocket 长连接（保活），并非每次发 8088 请求的进程
  - 新评分：s2s/Reachy Mini → 110、AI工厂 → 105、super-agent → 100、TeleAgent主程序 → 70（原 90 降低）
  - wecom-bot/QQ/密信适配器 → 95（原 60/50 提升）

## [1.9.4] - 2026-08-31

### 新增

- **Reachy Mini warmup 请求识别**：自动识别机器人 s2s 服务的预热请求并标注来源
  - 排查结论：Reachy Mini 的 speech-to-speech 服务每次启动/重启时，`ChatCompletionsApiModelHandler.warmup()` 会自动向 8088 发一条 `{"role":"user","content":"Hello"}` 请求预热 LLM 连接
  - 代码源头：`~/.config/TeleAgent/skills/reachy-mini-voice/patches/chat_completions_language_model.py` 第 271-282 行
  - 识别规则：prompt 为 "Hello" + User-Agent 含 "openai" + 无自定义 session_title（代理默认为"星小辰-子智能体"）
  - 日志中 source 显示为"机器人预热"，source_detail 显示"Reachy Mini s2s warmup"
  - 控制台日志页来源列将显示"机器人预热"标签，便于区分正常用户消息和机器人预热请求

## [1.9.3] - 2026-08-31

### 新增

- **万达云代理穿透**：当 lsof 识别到调用方是万达云（wandacloud）时，自动反查 7892 端口上的真实调用进程
  - 万达云作为系统代理（127.0.0.1:7892）转发 TeleAgent 的请求到 8088，导致 lsof 只能看到万达云而非真正的调用方
  - 新增 `_penetrate_wandacloud_proxy()` 函数：查 `lsof -i :7892` 找 ESTABLISHED 连接，排除万达云自身，按优先级评分（super-agent > TeleAgent > Electron Helper > wecom-bot > QQ/密信 > 其他）返回最高分候选
  - 穿透逻辑集成在 `identify_caller_process()` 末尾：当识别到万达云或未知进程时自动触发
  - 控制台"调用进程"列将显示 TeleAgent 主程序 / super-agent 等真实进程名，而非万达云

### 修复

- 删除 `_handle_chat_completions` 中的 DEBUG-HEADERS 临时调试日志
- 修复 `subprocess.run` 因非 UTF-8 进程名（如 `QQ\x20Hel`）导致 UnicodeDecodeError 的问题：所有 lsof/ps 调用添加 `errors='replace'`
- 修复 `_penetrate_wandacloud_proxy` 中 ESTABLISHED 状态检查错误：`(ESTABLISHED)` 标记在 lsof 输出的 `parts[9]` 而非 `parts[8]`，改为检查整行
- 修复万达云进程名中英文匹配：万达云 app 的进程名为中文"万达云"而非英文"wandacloud"，穿透条件和排除条件同时支持中英文

## [1.9.2] - 2026-08-31

### 新增

- **请求日志落盘持久化**：请求日志从"仅内存环形缓冲（重启即丢）"升级为 JSON Lines 落盘
  - 日志文件：`openai-proxy/logs/requests-YYYY-MM-DD.jsonl`（按天滚动，重启不丢）
  - 每次请求记录包含：时间戳、模型、流式/非流式、session_id/title、业务来源、UA、调用进程（caller/caller_pid/caller_cmd）、prompt 预览、响应预览、耗时、tokens、状态
  - 同一条请求以 `id` 去重覆盖：请求开始写入 `pending`，结束时覆盖为 `success/error/waiting_confirmation`，保证最终态完整
  - `/api/logs` 接口增强：支持 `?date=YYYY-MM-DD` 查询历史某天磁盘日志；未指定时优先返回当日磁盘日志（重启后依然可查）
- **工作空间 plist 副本修正**：`com.lizhun.openai-proxy.plist` 脚本路径从失效的 `~/scripts/openai_proxy.py` 修正为实际运行路径（与 `~/Library/LaunchAgents` 一致）

## [1.9.1] - 2026-08-31

### 新增

- **调用进程反查**：通过 lsof 反查 8088 端口的客户端连接，识别出具体是哪个进程在调用
  - 自动识别：TeleAgent主程序、wecom-bot、QQ适配器、量子密信适配器、AI工厂、Reachy Mini、机器人视觉、面板测试、curl、Python脚本、Node服务等
  - 日志新增字段：`caller`（进程友好名）、`caller_pid`（进程PID）、`caller_cmd`（命令行）
  - 控制台来源列下方显示调用进程名+PID，鼠标悬停看完整命令行
  - 2分钟缓存避免每次请求都跑 lsof

## [1.9.0] - 2026-08-31

### 新增

- **请求来源追踪**：日志记录和面板新增"来源"标识，一眼看出谁调的代理
  - 自动识别 6 种来源：企微、QQ、密信、子智能体、脚本/curl/Node、外部
  - 识别依据：session_title 前缀（企微/QQ/密信）+ User-Agent（python-requests/curl/node）
  - 日志条目新增字段：`source`（来源标签）、`source_detail`（会话标题）、`client_ip`（调用方IP）、`user_agent`
  - 控制台日志表格新增"来源"列，鼠标悬停显示会话标题和IP

## [1.8.1] - 2026-08-29

### 修复

- **会话复用时上下文双重累积导致 LLM 变慢/超时**
  - 问题：s2s 每次发 10 轮历史给 8088，8088 把全部 messages 拼成巨型 prompt 发给 TeleAgent，而 TeleAgent 会话自身也维护完整历史 → 越聊上下文越大，LLM 越来越慢，最终超时导致 TTS 生成了音频但 WebSocket 下发失败（`audio=0.00s`）
  - 修复：`send_prompt_async` 新增 `session_reused` 参数，会话复用时只发 system+tools 定义和最新一条用户消息，让 TeleAgent 自己维护上下文历史
  - 同时将 s2s 的 `chat_size` 从 10 减至 6，进一步降低单次请求体积

## [1.8.0] - 2026-08-29

### 新增

- **Tool Call 转发支持（function calling 桥接）**
  - `send_prompt_async` 新增 `tools` 参数：收到 OpenAI 格式的 `tools` 列表后，自动将工具描述注入到发给 TeleAgent 的 system prompt 中
  - LLM 通过 `[TOOL_CALL]{"name": "...", "arguments": {...}}[/TOOL_CALL]` 标记输出工具调用
  - 新增 `_build_tool_prompt()` 和 `_parse_tool_calls_from_text()` 辅助函数
  - **流式模式**：智能缓冲检测——前 11 字符（`[TOOL_CALL]` 长度）缓冲判断，确认是 tool call 则缓冲完整响应后解析为 OpenAI `tool_calls` delta + `finish_reason: "tool_calls"`；普通对话立即流式输出不受影响
  - **非流式模式**：直接从响应文本解析 tool_calls，返回标准 OpenAI 格式
  - 支持 `role: "tool"` 消息（工具返回结果作为 `[tool_result]` 注入对话上下文）
  - 让 s2s / 机器人能通过标准 OpenAI function calling 协议调用 robot_vision 等工具

## [1.7.0] - 2026-08-29

### 新增

- **常驻全局确认监听器（多轮确认支持）**
  - 新增 `GlobalConfirmationListener` 后台线程：常驻连接 super-agent 的 `/global/event` 事件流，捕获**所有会话**的 `permission.asked` / `question.asked` 事件并登记到待确认表
  - 不依赖任何 chat/completions 请求的 SSE 连接——即使一次请求的连接在第一次确认后关闭，后续轮次确认（AI 确认后继续执行又触发新敏感操作）也能被捕获
  - 断线自动重连（5 秒间隔）
- **session_id → 会话标题关联映射**
  - 新增 `_session_title_map`：登记确认事件时自动补全会话标题，机器人侧轮询 `/api/permission/pending` 时可据此反查推送地址
  - 按会话标题前缀匹配（含 `|` 的标题按 `|` 前部分匹配，时间变化仍复用会话）
- **`POST /api/permission/inject` 测试接口（本地测试专用）**
  - 用于验证 8088 → 机器人轮询 → QQ 推送完整链路，不依赖 AI 是否弹确认
  - 仅允许本机（127.0.0.1 / ::1）调用，局域网/外网访问返回 403

### 修复

- **待确认登记幂等化（双通道去重）**
  - 同一 conf_id 可能被全局监听器与请求链路 SSE 双通道捕获，旧代码会重复登记、重复触发回调
  - 修复：`register_pending_confirmation` 已存在时仅补全缺失字段（title/session_id/description/tool/type），不刷新 time、不重复触发 `on_confirmation`，返回 `is_new=False` 供调用方判断
  - 避免机器人侧重复推送通知、重复 reply 导致 404

## [1.6.2] - 2026-08-29

### 修复

- **permission.asked 事件字段解析错误（根因修复）**
  - super-agent 的 `permission.asked` 事件结构为 `{id, sessionID, permission, patterns, always, tool}`
  - 旧代码用 `props.get("permissionID")` 取权限 ID，实际字段名是 `id` → 永远取到空值 → 不进入处理分支 → `on_confirmation` 回调不被调用
  - 旧代码用 `props.get("description")` 取描述，实际不存在此字段 → confirmation chunk 的 description 为空 → 机器人通知消息无内容
  - 旧代码用 `props.get("tool")` 取工具名，实际是 dict `{messageID, callID}` → 下游解析异常
  - 修复：
    - ID 字段：优先取 `props.get("id")`，兼容 `permissionID`/`permissionId`/`permission_id`
    - 描述：从 `permission` + `patterns` 字段自动拼装人类可读描述（如"权限类型: external_directory | 路径: /usr/local/*"）
    - 工具：tool 为 dict 时提取 `callID`，为字符串时直接使用
  - 同步修复 `question.asked` 事件的相同问题（ID 字段名 + tool 类型）

## [1.6.1] - 2026-08-29

### 修复

- **StreamingSSEListener 缺少权限确认事件处理（严重 Bug）**
  - `StreamingSSEListener._handle_event` 覆写父类时遗漏了 `permission.asked` 和 `question.asked` 事件分支
  - 导致流式请求中 AI 弹出权限确认/问题确认时，`on_confirmation` 回调永远不会被调用
  - 确认信号无法注入 SSE 流 → 机器人侧（企微/QQ/量子密信）收不到 confirmation chunk → 用户在聊天里永远看不到"请回复确认/拒绝"通知
  - 修复：在 `_handle_event` 中补上 `permission.asked` 和 `question.asked` 的完整处理逻辑（与父类 `SSEListener` 一致）

## [1.6.0] - 2026-08-19

### 新增

- 会话按标题复用：`POST /v1/chat/completions` 请求带 `session_title` 时，若 super-agent 已存在同名会话则复用其 session_id，不再每次新建
- 新增 `get_or_create_session()` / `get_session_by_title()`：按标题精确匹配 + 同目录过滤 + 取最新更新会话 + 本地 120 秒缓存 + 同名并发创建互斥
- 请求日志新增 `session_title` / `session_reused` 字段，便于排查会话复用情况

### 变更

- 会话标题语义调整：机器人端（企微/QQ）不再在标题中带时间戳，改为稳定标识（私聊=userid/openid，群聊=chatid/group_openid），同一用户/同一群固定一个会话，对话上下文可跨消息延续

## [1.5.1] - 2026-08-18

### 新增

- 项目内备份最新版「OpenAI 代理管理器」技能（`skills/openai-proxy-manager/`）：含 SKILL.md 与 `scripts/proxy_model.py`（默认模型 status/set/list 管理脚本）

## [1.5.0] - 2026-08-18

### 新增

- 新增动态默认模型管理：代理启动后可通过 Web 控制台修改默认模型，立即生效，影响所有未显式指定 `model` 字段的 API 请求
- 新增后端接口 `GET /api/default-model`（获取当前默认模型）与 `POST /api/default-model`（修改默认模型）
- Web 控制台「系统」页新增「默认模型设置」卡片：下拉选择模型、保存设置、刷新状态
- 模型列表自动同步：面板每 30 秒自动刷新模型列表，TeleAgent 新增 Provider/模型配置后最多 30 秒自动出现在面板；下拉框重建时保留用户当前选中项

### 变更

- `/api/models`（管理面板接口）只返回 TeleAgent 中已配置成功的 Provider（`source=config`），未配置密钥的内置模型目录（`source=custom`）不再显示；OpenAI 兼容接口 `/v1/models` 行为不变
- README 更新：模型说明由"224 个模型 / 19 个 Provider"改为"仅展示已配置的 Provider/模型"，补充默认模型设置与自动同步说明，新增 `/api/default-model` 端点文档

### 修复

- SSE 流式响应结束后主动关闭连接（`close_connection = True`），避免客户端 fetch 因等不到 EOF 而挂起

## 历史版本

以下为 git 历史提交中未单独记录 CHANGELOG 的版本演进（仓库初始化至 v1.5.0 之前）：

- 稳定性增强：`sa_request` 认证失败自动刷新 session key 重试；`create_session` 失败自动重试
- 支持 `session_title` 自定义会话标题；SSE 超时调整到 600 秒（适配企微机器人群聊调用场景）
- 使用 Homebrew Python 3.11 解决 launchd TCC 权限问题
- 新增 skill manager、launchd 配置，更新路径
- 初始版本：TeleAgent OpenAI-Compatible Proxy with web console