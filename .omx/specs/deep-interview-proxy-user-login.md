# 需求规格 — 用户登录（控制台身份边界）

| 字段 | 值 |
| --- | --- |
| slug | `proxy-user-login` |
| 档位 | `--standard`（阈值 ≤ 0.20） |
| 轮数 | 5（R0 预检不计入提问轮） |
| 最终歧义 | **0.143** |
| 阈值 | 0.20 ✅ |
| 类型 | brownfield |
| 规格状态 | **CONDITIONAL — 条件可执行**（歧义达标，但未获用户判断，继承"部分澄清的 brief"） |
| 上下文快照 | `.omx/context/proxy-user-login-20261020T142357Z.md` |
| 访谈纪要 | `.omx/interviews/proxy-user-login-20261020T142357Z.md` |
| 开放决策 | ODL-1 … ODL-8（见纪要 §4；**上线前逐条确认**） |

---

## 0. 规格修订说明（后续链路回写，2026-10-20 22:47）

本规格在下游链路中被修订/取代的地方，以**下游产物为准**，此处只做指向，避免读者按过期描述实施：

| 位置 | 原描述 | 修订后 | 依据 |
| --- | --- | --- | --- |
| §4 范围内 **S3** | 引导流程"自动建 admin + 随机口令**打印一次**" | **服务永不生成/打印口令**；口令由运维用 CLI 显式设置（`python user_auth.py --init-admin admin` / `--set-password`）；无账号时代理处于**自举态**（不强制登录） | Architect r1 **V-1**：计划任务把 stdout 重定向到 `proxy.out.log`（`install-scheduled-task.ps1:62-63`），"打印口令"= 明文落盘，违反原则 P3。已由 PRD v2 §4 取代 |
| §5 范围外 | "JWT（方案层否决）" | 保持否决，但**否决理由重排**：主因=零依赖下不手写 HS256；撤销降为加分项 | Architect r1 **S-1**；PRD v2 §0 |
| §8 验收 | AC-1..AC-12 | 扩充为 **AC-1..AC-16**（新增：非本机来源 401、运行期回退、CSRF 防护、登录日志白名单） | Critic r1 **C-1/C-2/C-5**、Architect r1 **T-1/V-2**；PRD v2 §9 |
| §8 验收 AC-13 | 无对应用例、不可构造 | 抽 `_decide_auth(path, client_ip, …)` 纯函数 + 注入 client IP 单测 | Critic r1 **C-1** |

**并行提交的出现**：本规格产出后，仓库出现并行写入者提交的另一套实现（commit `29354cf` API Key 三档鉴权、commit `7f12439` 用户登录鉴权基座 + `docs/adr-0001-user-login-auth-scheme.md` / `docs/user-login-api-contract.md` / `docs/user-login-plan.md`）。经对比：

- **结论一致**：鉴权方案同为「服务端会话 + Cookie（非 JWT）」、只保护管理面、`/v1/*` 不变、双角色、不做邮件找回 —— 构成一次**独立交叉验证**；
- **实现更完整且已合入**：故以其为基座，本会话停止与其区域重叠的写入（详见 `.omx/team/user-login/report.md` §3）。

---

## 1. 清晰度分解表（brownfield 权重）

| 维度 | 权重 | 初值(R0) | 终值 | 提升来源 |
| --- | --- | --- | --- | --- |
| 意图清晰度 intent | 0.25 | 0.50 | 0.85 | Ontologist 重构：本质是"身份边界"不是"登录页" |
| 结果清晰度 outcome | 0.20 | 0.30 | 0.80 | R4 验收标准改为可当场演示的断言 |
| 范围清晰度 scope | 0.20 | 0.20 | 0.85 | R2 非目标清单 + Simplifier 砍范围 |
| 约束清晰度 constraints | 0.15 | 0.60 | 0.90 | R3 证据式确认（零依赖 / 不打断机器人） |
| 验收清晰度 success | 0.10 | 0.20 | 0.85 | R4 七条可断言判据 |
| 上下文清晰度 context | 0.10 | 0.90 | 0.95 | 预检探查（F1–F19 全部有 file:line 证据） |
| **加权合计** | | 0.425 | **0.8575** | |
| **歧义 = 1 − 合计** | | 0.575 | **0.1425** | ✅ ≤ 0.20 |

## 2. 意图（Ontologist 重述后的版本）

> **症状**：项目"没有登录功能"。
> **本质**：这台机器上**没有身份边界**——谁是人、谁是机器、谁能碰管理面、谁能看到请求日志，全靠"监听在哪个地址"这一条偶然事实决定。
> **本次要做**：把人这一侧的边界**建立起来**（账号 + 登录会话），并让控制台与管理面默认处在边界之内。

## 3. 期望结果

1. 控制台 `/console` 与管理面 `/api/*` 对**非本机来源**必须持有效凭据（登录会话或 API Key）。
2. 人类操作者用**账号 + 口令**登录，登录态为服务端会话（Cookie）。
3. `/v1/*` 的**行为完全不变**（现有机器人零改造）。
4. 账号凭据**不明文落盘**，会话令牌**不落盘**。
5. 3 条**互斥所有权**的 lane，可由 3 人并行开工。
6. 代码合入 `main`，本机服务跑到新代码，且有可回滚路径。

## 4. 范围内

| # | 项 | 说明 |
| --- | --- | --- |
| S1 | 账号存储 | `auth_users.json`：username / 加盐 PBKDF2 哈希 / role / status / created_at |
| S2 | 口令哈希 | `hashlib.pbkdf2_hmac('sha256', ..., 200000)` + 16B 随机盐，标准库 |
| S3 | 引导流程 | 无账号时首次启动自动建 `admin`，随机口令**只打印一次**（stdout），明文不落盘 |
| S4 | 登录会话 | 内存会话表；8h TTL；Cookie `HttpOnly; SameSite=Lax; Path=/`；不落盘 |
| S5 | 登录失败限流 | 同 IP 5 次失败 → 锁 5 分钟，第 6 次 `429` |
| S6 | HTTP 端点 | `GET /login`（登录页）、`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me` |
| S7 | 接入点 | `/console` 未登录 → `302 /login`；`/api/*` 本机免鉴权**保留**，会话为并行凭证 |
| S8 | CLI | `python openai_proxy.py --reset-password <username>` 重置口令 |
| S9 | 审计 | 登录成功/失败写入现有请求日志（复用 `log_request`） |
| S10 | 测试 | `tests/` 下 stdlib `unittest`，覆盖 A/B/E2E 三层 |
| S11 | 发布 | VERSION → 1.11.0、CHANGELOG 条目、README 鉴权章节、`.gitignore` 补 `auth*.json` |

## 5. 范围外 / 非目标

- ❌ JWT（方案层否决，理由见 PRD §3）
- ❌ 多角色细粒度权限（只 admin / viewer 两级）
- ❌ 按用户计量 / 配额 / 账单（→ v2 backlog）
- ❌ 自助注册（账号由管理员创建）
- ❌ 邮件 / 短信找回密码（破零依赖）
- ❌ 改 `/v1` 鉴权模型（三档模式保持不变）
- ❌ 改线上监听参数（`0.0.0.0` → `127.0.0.1` 属 ODL-8，用户决策，不擅自改）
- ❌ 第三方依赖、测试框架、CI（保持零依赖）

## 6. 决策边界

**代理可自行决定**：模块切分与命名、函数签名、口令哈希算法、会话存储与 TTL、Cookie 属性、bootstrap 交互、测试形态、提交与文档写法。

**必须用户拍板**（ODL-1..8）：用户定义、鉴权方案、是否多用户/角色、是否按用户计量、找回路径、是否收紧本机免鉴权、会话是否跨重启、监听地址是否收窄。

## 7. 约束

| # | 约束 | 验证方式 |
| --- | --- | --- |
| C1 | 零第三方依赖 | `py_compile` + 仅用标准库导入清单 |
| C2 | `/v1` 行为不变 | E2E：`/v1/models` 在 `mode=off` 下 200；`mode=strict` 下旧 key 仍通 |
| C3 | 不打断线上实例（PID 26124） | 所有验证在**副本目录 + 18089 端口**执行 |
| C4 | 产物落 `.omx/` | 目录清单核对 |
| C5 | macOS + Windows 双平台 | 仅用跨平台标准库 API（不碰 `ctypes`/`ps`） |
| C6 | 明文口令不落盘 | 断言 `auth_users.json` 全文无明文 |

## 8. 可测试验收标准（AC）

| ID | 判据 | 断言方式 |
| --- | --- | --- |
| AC-1 | `GET /console` 无会话 → `302`，Location `/login` | E2E HTTP |
| AC-2 | `GET /console` 带有效会话 → `200` 且含控制台 HTML | E2E HTTP |
| AC-3 | `POST /api/auth/login` 口令错误 → `401`，且不泄露"用户不存在/口令错误"的区分 | E2E HTTP |
| AC-4 | `POST /api/auth/login` 正确 → `200` + `Set-Cookie` 含 `HttpOnly` 与 `SameSite=Lax` | E2E HTTP |
| AC-5 | `POST /api/auth/logout` 后原 Cookie 失效 → `/console` 回到 `302` | E2E HTTP |
| AC-6 | `auth_users.json` 全文不含明文口令 | 单元：读文件断言 `password not in text` |
| AC-7 | 同 IP 连错 5 次 → 第 6 次 `429` | 单元 + E2E |
| AC-8 | `/v1/models` 在 `mode=off` 仍 `200`（机器人不受影响） | E2E HTTP |
| AC-9 | `/api/status` 本机来源仍 `200`（保留本机免鉴权） | E2E HTTP |
| AC-10 | `python -m unittest discover -s tests` 全绿 | 命令退出码 0 |
| AC-11 | `py_compile` 通过（改动过的全部 .py） | 命令退出码 0 |
| AC-12 | 登录成功/失败写入请求日志 | 断言日志中出现登录事件 |

## 9. 被暴露的假设及结论

| # | 假设 | 结论 |
| --- | --- | --- |
| A1 | 用户 = 控制台人类 | **保留为默认**（ODL-1），程序侧继续用 API Key |
| A2 | 动机 = 局域网暴露 | **证实**（F12/F14/F15）；但 Contrarian 指出"收窄监听地址"是更前置的控制 → 登录定位为纵深防御 |
| A3 | 登录只管控制台 + 管理面 | **保留为默认**（ODL-1/ODL-4） |
| A4 | "上线" = 本机服务跑新代码 | **证实**（F12/F13/F19） |

## 10. 压力测试结论

1. **机器人链路压测**：若登录开启后 `/api/*` 一律要求会话 → 本机企微机器人的 `/api/permission/reply` 断链。→ 结论：**保留本机免鉴权**（ODL-6），会话作为并行凭证而非替代凭证。
2. **锁死压测**：若启用登录但用户忘记口令且无重置路径 → 控制台永久锁死，代理成为砖。→ 结论：必须提供 CLI `--reset-password`（AC-8 之外的安全兜底，S8）。
3. **重启即失效压测**：若会话落盘以跨重启保留 → 会话令牌进入磁盘 = 新增泄露面。→ 结论：**不落盘**（ODL-7），接受"重启需重新登录"。
4. **首次启动压测**：无账号时若直接要求登录 → 无路可登。→ 结论：**引导模式**：账号表为空时不要求登录，且自动生成 admin（明文只打印一次）。
5. **依赖压测**：若用 PyJWT / bcrypt → 破坏 C1 零依赖。→ 结论：PBKDF2 + 手写 Cookie 解析。

## 11. 术语账本（强制统一，代码注释亦须遵守）

| 规范用词 | 含义 | 禁用/易混 |
| --- | --- | --- |
| `login session` / `登录会话` | 账号登录后的服务端会话 | 裸 `session`（仓库内 `session` = super-agent 会话） |
| `account` / `账号` | 人类登录身份 | `user`（易与 super-agent 用户混淆） |
| `api key` / `机器凭证` | `tap-` 开头的 OpenAI 兼容密钥 | `auth`（仓库 `auth.json`/`_auth_*` = API Key 鉴权） |
| `上线` | 本机服务进程跑到新代码 + `main` 合入 | 云部署（该项目无云载体） |

## 12. 场景压测结论（用具体场景逼边界）

| 场景 | 预期行为 | 覆盖 |
| --- | --- | --- |
| 同事从局域网 `http://<ip>:8088/console` | `302` → `/login` → 输账号口令 → 进控制台 | AC-1..AC-4 |
| 本机企微机器人 `POST /api/permission/reply` | `200`（不受登录影响） | AC-9 / 约束 C2 |
| Cursor / LangChain 带 `api_key="any"` 调 `/v1` | `200`（`mode=off` 不变） | AC-8 |
| 同一 IP 连续输错 5 次 | 第 6 次 `429`，`Retry-After` 提示 | AC-7 |
| 代理重启后浏览器还在 | `/console` → `302 /login`（会话不跨重启） | ODL-7 |
| 忘口令 | `python openai_proxy.py --reset-password admin` 恢复 | S8 |
| 首次启动（无 `auth_users.json`） | 自动建 admin + 打印一次性口令，控制台仍可直接进 | S3 |

## 13. 技术上下文（交给 ralplan 的输入）

- 单文件巨型服务（`openai_proxy.py`，4000 行）+ 2 个辅助脚本；鉴权入口统一在 `do_GET/do_POST/do_PATCH/do_DELETE` 顶部（`:2291`、`:2329`、`:2532`、`:2544`）。
- 现成的可复用件：`_auth_check`（`:339`）、`_auth_extract_token`（`:312`）、`log_request`（`:165`）、`_send_json`（`:2263`）、`_serve_console`（`:2765`）、`CONSOLE_HTML`（`:3431`）。
- 部署形态：Windows 计划任务（`install-scheduled-task.ps1`，runner 指向本仓库）+ macOS launchd；管理脚本 `openai_proxy_manager.py` 仅 macOS。
- 环境：无 git 在 PATH（真实路径 `C:\Program Files\Git\cmd\git.exe`）；Python 用 TeleAgent 自带 3.12。

## 14. 压缩纪要（5 轮要点）

R0 预检（brownfield、已有 API Key 鉴权、线上裸奔、零测试）→ R1 锁定"人 vs 程序"（人用账号，程序用 Key）→ R2 列非目标并砍掉角色/配额/注册/邮件找回 → R3 证据式确认"保留本机免鉴权、禁第三方依赖、不打断线上实例"→ R4 验收标准具体化为 12 条可断言 AC → R5 划分决策边界，剩余分歧收敛为 8 条 ODL。挑战：Contrarian（真问题是暴露面）、Terminologist（session/auth 双义）、Simplifier（砍到 MVP）、Ontologist（症状=缺登录，本质=缺身份边界）。

**交接**：→ `ralplan --deliberate`（认证/安全属高风险改动，强制 pre-mortem + 扩展测试计划）。本规格为**部分澄清的 brief**，8 条 ODL 必须随交接传递到发布检查清单。
