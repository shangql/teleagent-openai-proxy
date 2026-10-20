# PRD — proxy-user-login（控制台登录 / 身份边界）· **v2**

| 字段 | 值 |
| --- | --- |
| slug | `proxy-user-login` |
| 版本 | **v2**（v1 经 Architect r1 + Critic r1 评审后修订） |
| 模式 | `ralplan --deliberate`（认证/安全属高风险） |
| 上游 | `.omx/specs/deep-interview-proxy-user-login.md`（**部分澄清的 brief**，ODL-1..8 未决） |
| 下游 | `.omx/team/user-login/lanes.md` |
| 状态 | 已按 C-1..C-5、V-1、V-2、T-1..T-3、S-1、S-3 修订，待 Architect r2 + Critic r2 复审 |

## 修订记录（v1 → v2）

| 来源 | 要求 | v2 的处置 |
| --- | --- | --- |
| Architect V-1 | P3 被"打印引导口令"打破（`install-scheduled-task.ps1:62-63` 把 stdout 重定向到文件） | **引导模型重做**：服务**不再生成也不再打印**口令；无账号时进入"自举态"（不强制登录）；口令由运维用 CLI 显式设置。见 §4 |
| Architect V-2 | 运行期缺无损回退 | 新增 `auth_users.json` 顶层 `login_enabled` 字段 + **mtime 热加载**，改字段即回退，无需重启。见 §6 |
| Architect T-1 | CSRF 面 | 状态变更端点强制 `Content-Type: application/json`；新增 CSRF 用例 |
| Architect T-2/T-3 | Cookie host-scoped、两种凭证材料 | 写入风险表与 README 边界说明 |
| Architect S-1 | JWT 否决理由排序不当 | 否决理由重排：主因=零依赖下不手写 HS256；撤销降为加分项 |
| Architect S-3 | 登录只是纵深防御一层 | "监听地址"升为发布检查清单一等公民 |
| Critic C-1 | AC-13 无用例且不可构造 | 新增**可注入 client IP 的纯判定函数** `_decide_auth(...)` + 单元用例 + 非回环 E2E（可 skip） |
| Critic C-2 | 登录事件日志结构未定义 | 定义登录事件 entry schema（字段白名单 + 禁记口令/Cookie） |
| Critic C-3 | CLI 语义歧义 | 统一为 `--set-password <username>`（存在则轮换，不存在则创建），`--reset-password` 保留为别名 |
| Critic C-4 | 备选方案不公平 | 新增方案 **C′**（复用 `tap-` key + 审计字段）与三方案成本矩阵 |
| Critic C-5 | 运行期回退不可执行 | 同 Architect V-2 |

---

## 0. RALPLAN-DR 摘要（v2）

### 原则（5 条，v2 不变）

- **P1 零依赖不可破**：`README.md:269`「纯 Python 标准库」是产品卖点，任何第三方包一律否决。
- **P2 不打断既有调用方**：`/v1` 三档鉴权与本机机器人 `/api/*` 调用路径**行为不变**（`openai_proxy.py:193`、`:353`）。
- **P3 凭据不落明文**：口令只存加盐哈希；会话令牌只存内存；**服务永不打印、永不落盘任何明文口令**（v2 强化）。
- **P4 一处判定**：鉴权判定收敛到单一纯函数 `_decide_auth(...)`（可注入 client IP → 可单测）。
- **P5 可回滚**：运行期与启动期**各有一条**无损回退路径。

### 决策驱动 top 3

| # | 驱动 | 证据 |
| --- | --- | --- |
| D1 | **不能把用户锁在门外** | 线上实例在 `0.0.0.0` 且 `mode=off`；本地桌面代理的"自己进不去"比"被绕过"更致命 |
| D2 | **局域网暴露面** | `PID 26124` 监听 `0.0.0.0:8088`；`/api/*` 本机免鉴权；README 自述该风险（`README.md:84`） |
| D3 | **零依赖 + 单文件架构** | `README.md:269`、F1/F2 —— 所有实现必须落在标准库内 |

### 可行方案（v2：补 C′，重排 B 的理由）

#### 方案 A：服务端会话（Server-side Session）— **推荐**

账号存 `auth_users.json`（PBKDF2 加盐哈希）；登录成功在**内存**建会话，浏览器拿 `HttpOnly` Cookie。

| 取舍轴 | 评估 |
| --- | --- |
| 撤销（登出即失效） | ✅ O(1)，服务端删条目 —— **加分项**（v1 把主因放错位置，v2 降级） |
| 令牌泄露面 | ✅ 令牌不落盘、重启即失效、磁盘无痕 —— **v2 的主胜点** |
| 携带性 | ❌ Cookie host-scoped（T-2）—— 本场景不需要跨 host，故不构成否决 |
| 运维成本 | 需新增 2 个模块 + 登录页 + 口令哈希 ≈ 400~600 行 |

#### 方案 B：JWT（HS256 自签）

| 取舍轴 | 评估 |
| --- | --- |
| 携带性 / 跨 host | ✅ 唯一真实优势 —— 但本场景无此需求 |
| 撤销 | ❌ 需 denylist，denylist 即状态 → "无状态"优势归零（故撤销在本场景**不是决定性因素**） |
| 实现风险 | ❌ **主否决理由**：无 PyJWT（P1）→ 手写 HS256/base64url/时间窗校验 = 自造密码学边界，风险与收益不成比例 |
| 职责重叠 | ❌ 与既有 `tap-` 可撤销机器凭证重叠 |

**v2 结论**：否决理由排序 = ①零依赖下不手写 HS256（主因）→ ②与 `tap-` 体系职责重叠 → ③撤销体验（加分项，非否决项）。

#### 方案 C：把控制台并入 strict 模式（人类也用 `tap-` key）

零新代码，但**不满足需求本体**（无口令、无身份、无"谁登录了"、无登出）→ AC-1..AC-5 直接不成立。

#### 方案 C′（v2 新增，回应 Critic C-4）：复用 `tap-` key + 审计字段，不引入口令哈希

给 key 增加 `owner`（人名）字段，登录页让用户选一个 key → 记审计。改动 ≈ key 结构加 1 字段 + 一个选择页。

#### 三方案成本矩阵（v2 新增）

| 维度 | A 会话 | B JWT | C strict | C′ key+owner |
| --- | --- | --- | --- | --- |
| 新增代码量 | ~500 行 | ~300 行（+自造密码学） | ~5 行 | ~80 行 |
| 新增持久化存储 | 1 个（`auth_users.json`） | 0（+denylist 则 1） | 0 | 0 |
| 明文口令风险 | 无（哈希） | 无（哈希或外部 IdP） | 无 | **无口令** |
| 满足"用户登录"本体（AC-1..AC-5） | ✅ | ✅ | ❌ | ⚠️ 部分（无口令/登出） |
| 撤销 | ✅ | ❌ | ✅ | ✅ |
| 携带性 | ❌ | ✅ | ✅ | ✅ |
| 真实身份（谁是人） | ✅ | ✅ | ❌ | ⚠️ 弱（key 归属是自述） |
| P1 零依赖风险 | 低 | **高**（自造 HS256） | 无 | 无 |

**决策**：**采纳 A**。C′ 的价值在于**成本对照**（它证明"不引入口令哈希"确实省 400 行），因此把 C′ 连同 ODL-1/ODL-3 一并交给用户确认——若用户实际只要"知道是谁在用"而非"用户登录"，C′ 是更省的选项。

### pre-mortem（`--deliberate` 必填，3 场景，v2 修订）

| # | 场景 | 根因 | 预防措施（v2 落点） |
| --- | --- | --- | --- |
| PM-1 | 上线后用户打不开控制台，机器人也大面积报错 | 登录态误伤本机免鉴权路径，机器人 `permission/reply` 断链；且用户没记口令 | P2 + 保留本机免鉴权（`:353` 语义不变）；**v2：服务不打印口令 → 改用 `--set-password` 由用户自己设**；`login_enabled=false` 运行期回退；上线清单第一项=真实机器人回环 |
| PM-2 | 局域网里有人拿到控制台，改默认模型、翻走请求日志 | 只保护了页面，`/api/*` 非本机访问仍匿名 | P4 统一判定 + **v2：`_decide_auth` 可单测 + AC-13 有真实用例（C-1）**；上线清单要求实测"非本机来源访问 `/api/status` → 401" |
| PM-3 | 上线半年后没人能登进系统 | 会话不落盘 + 口令只有哈希 + 没有找回路径 | **v2 变化：口令由用户自己设置（用户记得住）**；`--set-password` 轮换；`login_enabled=false` 一键回退；README 写清恢复步骤；**自举态**：无账号时根本不拦人 |

### 扩展测试计划（`--deliberate` 必填）

| 层 | 覆盖 | 载体 |
| --- | --- | --- |
| 单元 L1 | 口令哈希、账号 CRUD、引导态、`login_enabled` 热加载、纯判定函数（注入 client IP）、会话生命周期、限流 | `tests/test_auth_users.py`、`tests/test_auth_session.py`、`tests/test_decide_auth.py` |
| 集成 L2 | 真实 HTTP 路由、鉴权接线、与 `/v1` 的隔离、CSRF 防护 | `tests/test_login_flow.py` |
| E2E | AC-1..AC-14 全部走真实 HTTP；副本目录 + 随机高位端口；非回环用例（取不到地址则显式 skip） | 同上 |
| 可观测性 | 登录事件 entry schema（白名单字段）+ 禁记口令/Cookie | 同上 |
| 回归 | `py_compile` + `unittest discover` + `git status` 密钥未跟踪 | 命令行 |

---

## 1. 架构（v2）

```
浏览器 ──POST /api/auth/login (JSON)──▶ ┌──────────── openai_proxy.py (Lane C) ────────────┐
        ◀─Set-Cookie: tap_ls=…           │ _decide_auth(path, client_ip, has_session,       │
        ──GET /console──────────────────▶│              api_key_record, login_enabled)      │
                                          │   ↑ 纯函数，可注入 client_ip → 可单测（P4/C-1）  │
                                          └───┬──────────────┬──────────────┬───────────────┘
                                              │              │              │
                                     auth_users.py   auth_session.py   auth.json
                                     (Lane A)         (Lane B)         (机器凭证, v1 既有)
```

**判定表（`_decide_auth`，v2 冻结）**

| 路径类别 | 本机来源 | 有效登录会话 | 有效 API Key | 结果 |
| --- | --- | --- | --- | --- |
| `/v1/*` | — | 否 | 按 `off/partial/strict` 既有三档 | **完全不变**（P2） |
| `/console` | — | 是 | — | 放行 200 |
| `/console` | — | 否 | — | **302 → `/login`** |
| `/api/*` | 是 | — | — | 放行（保留本机免鉴权，P2） |
| `/api/*` | 否 | 是 | — | 放行 |
| `/api/*` | 否 | 否 | 是 | 放行 |
| `/api/*` | 否 | 否 | 否 | **401**（AC-13 / PM-2） |
| `/login`、`/api/auth/*`、`/health`、`/favicon.ico` | — | — | — | 豁免 |

> 注意：`/console` **不**走本机免鉴权（那会让登录失去意义），但 `/api/*` 走——两者不对称是**刻意**的，且与现有 `:353` 语义一致。

## 2. 模块契约（**lane 并行的冻结接口 · v2**）

### `auth_users.py`（Lane A 独占）

```python
AUTH_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_users.json")
PBKDF2_ITERATIONS = 200_000
ROLES = ("admin", "viewer")
MIN_PASSWORD_LENGTH = 8

def hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS) -> dict
    # {"algo": "pbkdf2_sha256", "iterations": int, "salt": hex, "hash": hex}
def verify_password(password, record: dict) -> bool      # hmac.compare_digest

class UserStore:
    def __init__(self, path=AUTH_USERS_FILE)
    def reload_if_changed(self) -> bool        # 按 mtime 热加载；无变化返回 False
    def is_login_enabled(self) -> bool          # 顶层 login_enabled（默认 True）
    def set_login_enabled(self, enabled: bool) -> bool   # 运行期回退入口
    def list_users(self) -> list[dict]         # 公开视图：不含 salt/hash
    def get_user(self, username) -> dict|None
    def create_user(self, username, password, role="admin") -> dict
    def authenticate(self, username, password) -> dict|None   # 失败返回 None（不区分原因）
    def set_password(self, username, new_password, create_missing=True) -> dict|None
        # C-3：存在则轮换，不存在则创建（create_missing 控制）；返回用户公开视图
    def set_disabled(self, username, disabled: bool) -> bool
    def delete_user(self, username) -> bool
    def count(self) -> int
    def has_users(self) -> bool                # 自举态判定：False ⇒ 不强制登录
```

### `auth_session.py`（Lane B 独占）

```python
SESSION_COOKIE_NAME = "tap_ls"
SESSION_TTL_SECONDS = 8 * 3600
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 300

def parse_cookies(header: str|None) -> dict[str, str]
def build_session_cookie(token, max_age=SESSION_TTL_SECONDS) -> str   # HttpOnly; SameSite=Lax; Path=/
def clear_session_cookie() -> str

class SessionStore:
    def __init__(self, ttl=SESSION_TTL_SECONDS)
    def create(self, username, role) -> str
    def get(self, token) -> dict|None           # 过期自动清理
    def destroy(self, token) -> bool
    def purge_expired(self) -> int
    def count(self) -> int

class LoginGuard:
    def __init__(self, threshold=LOGIN_MAX_FAILURES, window=LOGIN_LOCK_SECONDS)
    def is_locked(self, ident) -> bool
    def retry_after(self, ident) -> int
    def record_failure(self, ident) -> int
    def record_success(self, ident) -> None
```

### `openai_proxy.py`（**Lane C 独占**，唯一允许改主文件与文档的 lane）

```python
def _decide_auth(path, client_ip, has_session, api_key_record, login_enabled) -> tuple[bool, str]
    # 纯函数：返回 (是否放行, 原因码)。不读文件、不看全局状态 → 可直接单测（C-1）
```
新增端点：`GET /login`、`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`。
新增 CLI：`--set-password <username>`（**存在则轮换 / 不存在则创建**，C-3）、`--password-stdin`、`--reset-password`（别名）、`--no-login`。
改动点：`_auth_check`（`:339`）改为调用 `_decide_auth`；`do_GET`（`:2291`）/`do_POST`（`:2329`）加路由；`_serve_console`（`:2765`）未登录 302。

## 3. 数据格式（v2）

```jsonc
// auth_users.json
{ "version": 1,
  "login_enabled": true,          // v2：运行期回退开关（热加载）
  "users": [
    { "username": "admin", "role": "admin", "status": "enabled",
      "password": { "algo": "pbkdf2_sha256", "iterations": 200000,
                    "salt": "<hex16B>", "hash": "<hex>" },
      "created_at": 1792505946, "last_login_at": null }
  ] }
```

- 原子写（tmp + `os.replace`），与 `_auth_save`（`:231`）同风格；文件权限尽力 `0600`。
- `.gitignore` 补 `auth.json`、`auth_users.json`（**当前 `auth.json` 未被忽略，是现存泄露风险**）。

## 4. 引导与口令流程（v2 重做，回应 V-1 / C-3）

```
首次启动，auth_users.json 不存在
   └─ has_users() == False  → 自举态：登录不强制（行为与上线前一致），横幅提示"尚未启用登录"
运维执行：python openai_proxy.py --set-password admin
   └─ 交互输入（或 --password-stdin 从管道读）→ 写加盐哈希 → 明文不落盘、不打印
下次启动：has_users() == True → 强制登录（/console 302 → /login）
忘记口令：python openai_proxy.py --set-password admin   （同一条命令轮换）
紧急回退：把 auth_users.json 的 login_enabled 改成 false → 热加载，下一次请求即免登录
```

- **服务永不生成、打印、落盘明文口令**（P3 v2）。
- 用户自助设口令 = "用户记得住"，直接降低 PM-3 概率。
- `--password-stdin` 供脚本/自动化使用，避免口令进入 shell 历史。

## 5. 登录事件日志 schema（v2 新增，回应 C-2）

写入现有请求日志（`log_request`，`:165` → `log_request_to_disk`），entry **字段白名单**：

```jsonc
{ "event": "login",
  "result": "success | failure | lockout",
  "username": "<用户输入，截断 64 字符>",
  "client_ip": "127.0.0.1",
  "ts": 1792505946.12,
  "path": "/api/auth/login" }
```

**禁止字段**：口令、Cookie 值、会话令牌、`Authorization` 头。构造 entry 时用显式白名单字典实现（不是"先取全部再删几个"）。

## 6. 回退路径（v2 新增，回应 V-2 / C-5）

| 场景 | 动作 | 生效 |
| --- | --- | --- |
| 运行期紧急回退 | 改 `auth_users.json` 的 `login_enabled` 为 `false` | **热加载，下一次请求生效**（`reload_if_changed()` 按 mtime 判断） |
| 启动期回退 | `python openai_proxy.py --no-login` | 启动即生效 |
| 彻底回退 | 删除 `auth_users.json` | 自举态（不拦人） |

三条路径都**不需要删除用户数据**、不需要停服务（运行期那条）。

## 7. 安全细则（v2）

| 项 | 取值 | 理由 |
| --- | --- | --- |
| 口令哈希 | PBKDF2-HMAC-SHA256, 200k, 16B 随机盐 | 标准库内；`scrypt` 在 Windows 受内存策略影响 |
| 口令强度 | 长度 ≥ 8（`MIN_PASSWORD_LENGTH`），拒绝空口令 | — |
| 比较 | `hmac.compare_digest` | 恒定时间 |
| 会话令牌 | `secrets.token_urlsafe(32)` | 256 位熵 |
| Cookie | `HttpOnly; SameSite=Lax; Path=/; Max-Age=28800` | 无 `Secure`（本地 HTTP），见 R-6 |
| CSRF | 状态变更端点要求 `Content-Type: application/json` | 跨站表单无法伪造该 Content-Type（T-1） |
| 登录失败 | 同 IP 5 次 → 锁 300s → `429` | 最小暴力破解防护 |
| 错误信息 | 统一"用户名或口令错误" | 防用户名枚举 |
| 日志 | 白名单字段；禁记口令/Cookie | P3 |

## 8. 风险与缓解（v2）

| # | 风险 | 缓解 | 残余 |
| --- | --- | --- | --- |
| R-1 | 登录上线把用户自己锁在外面 | 自举态 + `--set-password` 轮换 + `login_enabled=false` 热回退（P5） | 首次上线当天需人盯 |
| R-2 | 影响本机机器人 | 保留本机 `/api/*` 本机免鉴权；AC-9 断言 | 机器人换机需重评（ODL-6） |
| R-3 | 内存会话竞态 | `threading.Lock` | 无 |
| R-4 | `auth*.json` 误入 git | `.gitignore` 补齐 + 上线前 `git status` 核对 | 历史未提交过 `auth.json`（当前未跟踪） |
| R-5 | 线上实例被打断 | 验证走副本目录 + 备用端口；线上重启为显式动作 | 需用户确认重启时机 |
| R-6 | 会话令牌无 `Secure` 标志 | 明确文档：仅限本机/LAN HTTP | 若上公网必须先上 TLS |
| R-7 | 8 条 ODL 未获用户确认 | 实现走推荐默认且可一行回滚；上线清单逐条过 | **上线前必须过** |
| **R-8（v2 新）** | **即使启用登录，暴露面未收窄时风险仍显著**（实例跑 `0.0.0.0`；本机免鉴权路径仍开放） | **发布检查清单把"监听地址"提升为一等公民**（Architect S-3）；登录定位为**纵深防御的一层**，不是主控制 | ODL-8 未决 |
| **R-9（v2 新）** | **Cookie host-scoped**：在 `127.0.0.1` 登录 ≠ 在 LAN IP 登录（T-2） | README 写明；登录页显示当前访问地址 | 用户困惑，非安全缺陷 |
| **R-10（v2 新）** | **两种凭证材料并存**：`auth_users.json`（人）与 `auth.json`（机器） | 职责边界写死：前者管人（口令哈希/角色/审计），后者管机器（`tap-` key）；判定统一在 `_decide_auth` | 将来有人混用 → 靠代码评审拦截 |

## 9. 验收（承接规格 AC-1..AC-12，新增 AC-13..AC-16）

| ID | 判据 |
| --- | --- |
| AC-1..AC-5 | 同规格（302 / 200 / 401 / Set-Cookie / 登出失效） |
| AC-6 | `auth_users.json` 无明文口令 |
| AC-7 | 5 次失败 → 第 6 次 429 |
| AC-8 | `/v1` 行为不变（`mode=off` 200） |
| AC-9 | 本机 `/api/status` 仍 200 |
| AC-10 | `unittest discover` 全绿 |
| AC-11 | `py_compile` 通过 |
| AC-12 | 登录事件写入请求日志，且 **entry 只含白名单字段**（无 password/cookie） |
| AC-13 | 非本机来源访问 `/api/*` 无凭据 → 401（**有真实用例**，C-1） |
| AC-14 | `--no-login` 启动 → `/console` 直接 200 |
| **AC-15（v2）** | 运行期把 `login_enabled` 改为 `false` → **下一次请求**即免登录（热加载，C-5/V-2） |
| **AC-16（v2）** | 状态变更端点缺 `Content-Type: application/json` → 拒绝（CSRF，T-1） |

## 10. 与团队切面的关系

本 PRD 冻结第 2 节契约 → 3 条 lane 互斥所有权并行开工（详见 `.omx/team/user-login/lanes.md`）。
本 PRD 为 **v2**，待 Architect r2 + Critic r2 复审通过后方可执行。
