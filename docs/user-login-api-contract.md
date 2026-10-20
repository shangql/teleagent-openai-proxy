# 用户登录功能 —— 接口契约（冻结版 v1）

> **本文件是三条并行泳道之间的唯一约定。**
> 三条泳道的分支都从「契约基线提交」拉出，**任何对本文档的修改必须先改本文档、再改代码**，
> 否则会出现前端按 A 写、后端按 B 实现的对不上。

- 版本：v1（对应目标版本 **v1.12.0**）
- 冻结日期：2026-10-20
- 决策依据：`docs/adr-0001-user-login-auth-scheme.md`
- 实施计划：`docs/user-login-plan.md`
- 核心实现：`user_auth.py`（已落地并带 35 条单测）

> **与 v1.11.0 的关系**：v1.11.0 是**API Key 三档鉴权**（`auth.json` / `off|partial|strict`），
> 已由另一条并行线完成。本功能（用户登录）是**另一层**：账号 / 登录会话 / 角色，
> 两者**互不影响**，配置文件分开（`auth.json` vs `users.json`），接口前缀分开
> （`/api/auth/keys` vs `/api/auth/login`），模式开关分开（`/api/auth/mode` vs `/api/auth/login-mode`）。

---

## 1. 分层模型

| 层 | 面向谁 | 凭据 | 端点 |
|----|--------|------|------|
| 数据面 | 机器客户端（OpenAI SDK / curl / 机器人） | **API Key**（`Authorization: Bearer tap-xxx`，沿用现状） | `/v1/*` |
| 管理面 | 人（浏览器控制台） | **用户会话**（Cookie `tap_sid`），机器调用可用 API Key 兜底 | `/api/*` |
| 公共面 | 所有人 | 无 | `/health`、`/console`（页面外壳）、`/api/auth/login`、`/api/auth/me` |

**关键约束**：`/v1/*` 的行为**完全不变**（不引入用户概念），避免影响现有所有客户端。

## 2. 凭据与防护

### 2.1 会话 Cookie

| 项 | 值 |
|----|-----|
| Cookie 名 | `tap_sid` |
| 属性 | `HttpOnly; SameSite=Lax; Path=/; Max-Age=28800`（8 小时） |
| 载体 | 服务端会话，不透明随机串（`secrets.token_urlsafe(32)`，256 位） |
| 续期 | 滑动续期：每次通过校验即把到期时间顺延 8 小时 |
| 失效 | 登出、账号被停用、账号被删除、超过 TTL、进程重启 |

### 2.2 CSRF

变更类请求（`POST` / `PATCH` / `DELETE`）到 `/api/*`，除 `/api/auth/login` 外，必须带：

```
X-CSRF-Token: <csrf_token>
```

`csrf_token` 由 `POST /api/auth/login` 的响应体返回，并在 `GET /api/auth/me` 的响应体中返回。
前端存在**内存**变量里（不要写 localStorage）。

### 2.3 登录模式（三档，存 `users.json` 的 `mode` 字段）

| 模式 | 行为 | 用途 |
|------|------|------|
| `off` | 完全不校验登录（与现状一致） | 首次上线、紧急回滚 |
| `optional` | 校验登录，但**本机来源（127.0.0.1 / ::1）仍然放行** | 灰度期；保证本机 CLI 与机器人不受影响 |
| `required` | 管理面**全部**要求有效会话 | 终态 |

> 模式只影响**管理面**。数据面 `/v1/*` 永远走 API Key 规则，与本模式无关。

### 2.4 机器调用兜底

`/api/permission/*`（企微 / QQ / 机器人的确认回执接口）由**其他机器**调用，不能依赖浏览器 Cookie。
契约规定：这类端点接受 **「有效会话」或「有效 API Key」**二者之一，行为不变。

## 3. 端点契约

### 3.1 公共端点

#### `POST /api/auth/login`

请求：

```json
{"username": "admin", "password": "********"}
```

成功 `200`：

```json
{
  "user": {"id": "u_a1b2c3d4", "username": "admin", "role": "admin",
           "status": "enabled", "created_at": 1792505946,
           "updated_at": 1792505946, "last_login_at": 1792506000},
  "csrf_token": "…",
  "expires_at": 1792534800
}
```

同时下发 `Set-Cookie: tap_sid=…; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800`。

失败 `401`：

```json
{"error": {"message": "用户名或密码错误", "type": "invalid_request_error",
           "param": null, "code": "invalid_credentials"}}
```

#### `GET /api/auth/me`

- 有效会话 → `200 {"user": {...}, "csrf_token": "…", "mode": "optional", "expires_at": 1792534800}`
- 无会话 → `401 {"error": {"message": "未登录", "type": "invalid_request_error", "param": null, "code": "no_session"}}`

### 3.2 会话端点

#### `POST /api/auth/logout`

需 `X-CSRF-Token`。成功 `200 {"ok": true}`，并下发 `Set-Cookie: tap_sid=; Max-Age=0` 清 cookie。
会话不存在时也返回 `200 {"ok": true}`（幂等）。

### 3.3 账号管理端点（需 `admin` 角色）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/users` | 列出账号 → `{"users": [ ...用户视图... ]}` |
| `POST` | `/api/users` | 创建账号，body `{"username","password","role"}` → `201 {"user": {...}}` |
| `PATCH` | `/api/users/<username>` | 改口令 / 角色 / 状态，body 至少一个 `{"password"?,"role"?,"status"?}` → `200 {"user": {...}}` |
| `DELETE` | `/api/users/<username>` | 删除账号 → `200 {"ok": true}` |

**用户视图**（任何返回用户信息的地方都必须是这个形状，**绝不含口令哈希**）：

```json
{"id": "u_a1b2c3d4", "username": "admin", "role": "admin", "status": "enabled",
 "created_at": 1792505946, "updated_at": 1792505946, "last_login_at": 1792506000}
```

**管理操作约束**

- 不能删除或降级**最后一个** `admin` 账号 → `400 {"error": {"code": "invalid_request", "message": "至少需要保留一个管理员"}}`；
- 停用 / 删除账号时，该账号的**所有现存会话立即失效**（已由 `AuthManager.set_status/delete_user` 实现）。

### 3.4 登录模式管理端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/auth/status` | **沿用现有端点**，仅**增量**新增字段：`login_mode`、`login_enforced`、`user_count`（现有字段一个都不许删改） |
| `POST` | `/api/auth/login-mode` | 需 `admin` + CSRF，body `{"mode": "off|optional|required"}` → `{"mode": "optional"}` |

> ⚠️ 现有的 `POST /api/auth/mode` 是 **API Key 的三档模式**（off/partial/strict），**不是**登录模式，
> 两者名字相近极易混淆，**禁止复用该路径**。登录模式一律走 `/api/auth/login-mode`。

### 3.5 错误码总表

| code | HTTP | 含义 | 前端建议动作 |
|------|------|------|------------|
| `invalid_credentials` | 401 | 用户名或密码错误 | 提示「用户名或密码错误」 |
| `locked_out` | 429 | 失败次数过多被锁定 | 提示剩余秒数（`error.retry_after`） |
| `user_disabled` | 403 | 账号被停用 | 提示联系管理员 |
| `no_session` | 401 | 未登录或会话已过期 | 弹登录框 |
| `csrf_failed` | 403 | CSRF 令牌缺失或不匹配 | 刷新页面重试 |
| `user_exists` | 409 | 用户名已存在 | 表单内联报错 |
| `user_not_found` | 404 | 用户不存在 | 表单内联报错 |
| `weak_password` | 400 | 口令不合规（< 10 字符） | 表单内联报错 |
| `invalid_username` | 400 | 用户名不合规（3-32 位字母数字 `. _ -`） | 表单内联报错 |
| `invalid_mode` | 400 | 模式值非法 | 表单内联报错 |
| `invalid_role` | 400 | 角色值非法 | 表单内联报错 |
| `forbidden` | 403 | 角色不足（非 admin 访问管理端点） | 提示无权限 |

## 4. `user_auth.py` 公开 API（冻结，A 泳道不得随意改签名）

```python
# 错误
class AuthError(Exception):
    def __init__(self, code, message=None, retry_after=None)
    .code / .message / .retry_after / .to_dict() -> dict   # 直接可作为响应体

# 常量
SESSION_COOKIE_NAME = "tap_sid"
DEFAULT_SESSION_TTL = 8 * 3600
DEFAULT_PBKDF2_ITERATIONS = 210000
MIN_PASSWORD_LENGTH = 10
ROLES = ("admin", "viewer")
STATUS_ENABLED / STATUS_DISABLED
LOGIN_MODES = ("off", "optional", "required")
ERR_* （见 3.5 错误码表）
# 口令
hash_password(password, iterations=DEFAULT_PBKDF2_ITERATIONS) -> str
verify_password(password, stored) -> bool          # 任何异常输入都返回 False，不抛

# 门面
class AuthManager:
    __init__(users_path=USERS_FILE, session_ttl=DEFAULT_SESSION_TTL,
             clock=None, iterations=DEFAULT_PBKDF2_ITERATIONS)
    get_mode() -> str
    set_mode(mode) -> str
    is_login_enforced() -> bool
    list_users() -> list[dict]
    get_user(username) -> dict | None
    create_user(username, password, role="viewer") -> dict
    set_password(username, password) -> bool
    set_status(username, status) -> bool            # 停用时立即踢下线
    set_role(username, role) -> bool
    delete_user(username) -> bool
    login(username, password, client_ip="") -> (user_dict, session_dict)
        # 失败抛 AuthError（invalid_credentials / locked_out / user_disabled）
    logout(token) -> bool
    authenticate(token) -> user_dict | None
    session_info(token) -> dict | None

# 登录会话表（替换 JWT 时只动这一类）
class LoginSessionStore:
    __init__(ttl=DEFAULT_SESSION_TTL, clock=None, max_per_user=5, sliding=True)
    create(user_id, username, role) -> dict
    get(token) -> dict | None
    revoke(token) -> bool
    revoke_user(user_id) -> int
    purge_expired() -> int

# HTTP 辅助
parse_cookies(header_value) -> dict
build_set_cookie(name, value, max_age=None, path="/", http_only=True,
                 same_site="Lax", secure=False) -> str
check_csrf(session, headers) -> bool
```

## 5. `openai_proxy.py` 集成点（A 泳道独占，共 5 处）

| # | 位置 | 改动 | 行数级 |
|---|------|------|--------|
| 1 | 文件顶部 import 区（约 19-40 行） | `from user_auth import AuthManager, AuthError, SESSION_COOKIE_NAME, parse_cookies, build_set_cookie, check_csrf` | 1 行 |
| 2 | 模块级（`_auth_*` 区块之后，约 397 行） | `_login_manager = AuthManager()` 单例 | 1 行 |
| 3 | `_auth_check()`（约 339-382 行） | 增加「登录模式」判定：读取 `_login_manager.get_mode()`；`required` 时，管理面需要有效会话（会话 **或** API Key）；`off` / `optional` 保持现有行为 | 约 25 行 |
| 4 | `do_GET` / `do_POST`（约 2291-2356 行） | 新增 5 个路由分支：`/api/auth/me`、`/api/users`、`/api/users/<username>`、`/api/auth/login-mode`；`/api/auth/login`、`/api/auth/logout` 走 POST | 约 40 行 |
| 5 | 新增 3 个 handler 方法（紧随 2349 行之后的 `===== 管理 API =====` 区块内） | `_handle_auth_login`、`_handle_auth_logout`、`_handle_auth_me`、`_handle_api_users`、`_handle_api_user_update` | 约 120 行 |

**冻结要求**

- 路由分支的**路径字符串**必须与第 3 节完全一致（含大小写与连字符）；
- 错误响应体必须经 `AuthError.to_dict()` 产出，**不得**自造形状；
- 新增 handler 方法一律放在 `===== 管理 API =====` 区块内，**不得**插到 `do_GET`/`do_POST` 之前；
- 现有 `do_GET` / `do_POST` 的**既有分支顺序与行为一律不动**（只允许追加分支）。

## 6. 文件与区域归属（防冲突表）

| 区域 | 文件 | 归属 | 说明 |
|------|------|------|------|
| 账号 / 会话 / 限流核心 | `user_auth.py` | **A** | 已落地，A 负责按契约接线与加固 |
| 路由与 `_auth_check` | `openai_proxy.py:19-40, 339-382, 2255-2360` | **A** | 上表 5 处集成点 |
| 控制台 HTML（`CONSOLE_HTML`，约 3431-4385 行） | `openai_proxy.py` | **B** | 登录遮罩、用户菜单、账号管理页 |
| 集成测试 / CLI 登录 | `tests/test_user_auth.py`、`tests/test_login_api.py`、`openai_proxy_manager.py` | **C** | |
| 文档 | `README.md`、`CHANGELOG.md` | **C** | |

**规则**

1. 任何泳道**不得**修改归属表之外的区域；需要改别的区域 → 先在 PR 里提出，等契约变更。
2. B 泳道**不得**动 `do_GET` / `do_POST` / `_auth_check`；登录页**不新增路由**，
   改为在 `/console` 页面内用前端遮罩层承载（`/console` 本来就在免鉴权白名单里）。
   - 若团队更倾向**独立 `/login` 页面**（服务端未登录时 302 过去）：唯一改动是
     A 增加一条路由 + B 提供一个 `LOGIN_HTML` 常量，**其余契约一字不改**；
     两种做法的取舍见 `docs/user-login-plan.md` §6.1。
3. A 泳道**不得**改 `CONSOLE_HTML` 里的任何字符。
4. 三条泳道都**不得**改 `user_auth.py` 以外的公共文件（`openai_proxy_manager.py` 归 C）。

## 7. 兼容性约束（必须逐条验证）

| 现状 | 约束 |
|------|------|
| `openai_proxy_manager.py` 用 `urllib` 无凭据调 `/api/status` | `login.mode=off` / `optional` 下必须照常工作；`required` 下需改造为「先登录再带 Cookie」（C 泳道） |
| 企微 / QQ / 机器人调 `/api/permission/reply` | 这些是**机器**调用，必须在 `required` 模式下仍可用（API Key 兜底，见 2.4） |
| OpenAI SDK / Cursor / Continue 等用 `api_key="any"` | 数据面不受影响，行为完全不变 |
| 现有 `auth.json`（Key 三档模式） | 与 `users.json`（登录模式）**互不影响**，两套配置各自独立 |
| 现有 `/api/auth/status` 响应 | 只允许**增量**加字段，不得删改既有字段（控制台 B 泳道在用） |
