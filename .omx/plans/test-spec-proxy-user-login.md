# 测试规格 — proxy-user-login · **v2**

| 字段 | 值 |
| --- | --- |
| slug | `proxy-user-login` |
| 版本 | v2（回应 Critic C-1/C-2/C-3/C-5、Architect V-2/T-1） |
| 运行环境 | Windows + TeleAgent 自带 Python 3.12（`%USERPROFILE%\.local\share\TeleAgent\runtimes\python\python.exe`） |
| 框架 | **stdlib `unittest`**（零第三方，遵守 P1） |
| 隔离原则 | 所有 HTTP 用例在**脚本副本目录 + 随机高位端口**执行，绝不触碰线上 `8088` / `PID 26124` |

## 0. 执行命令

```powershell
$py = "$env:USERPROFILE\.local\share\TeleAgent\runtimes\python\python.exe"
& $py -m unittest discover -s tests -v
& $py -m py_compile auth_users.py auth_session.py openai_proxy.py
```

**通过判据**：全量退出码 `0`；`py_compile` 退出码 `0`；失败用例逐条可归因（不接受 flaky）。

## 1. 层次与映射（v2）

| 层 | 文件 | 目标 | 覆盖 AC |
| --- | --- | --- | --- |
| 单元 L1 | `tests/test_auth_users.py` | 口令哈希、账号 CRUD、**自举态**、**`login_enabled` 热加载** | AC-6, AC-15 |
| 单元 L1 | `tests/test_auth_session.py` | Cookie、会话生命周期、限流 | AC-4, AC-7 |
| **单元 L1（v2 新增）** | `tests/test_decide_auth.py` | **纯判定函数**，注入 client IP / session / key | **AC-1, AC-13** |
| 集成/E2E L2 | `tests/test_login_flow.py` | 真实 HTTP 路由、接线、CSRF、审计日志、运行期回退 | AC-1..AC-5, AC-7..AC-9, AC-12, AC-14..AC-16 |
| 回归 | 命令行 | 语法门 + 全量 + 密钥未跟踪 | AC-10, AC-11 |

## 2. 用例清单

### L1 — `tests/test_auth_users.py`（Lane A）

| ID | 用例 | 断言 | AC |
| --- | --- | --- | --- |
| U-1 | `hash_password` 随机盐 | 两次 salt/hash 不同 | — |
| U-2 | 正向校验 | `verify_password(pwd, rec) is True` | — |
| U-3 | 错误口令 | `False` | — |
| U-4 | 空口令被拒 | 抛错/返回 False | — |
| U-5 | 短口令（<8）被拒 | 同上 | — |
| U-6 | 用户名唯一 | 重复创建报错 | — |
| U-7 | `authenticate` 成功返回记录 / 失败返回 None | — | — |
| U-8 | 不存在用户与错口令返回**同样的 None** | 防用户名枚举 | — |
| U-9 | `list_users` 公开视图无 salt/hash | 键集合断言 | AC-6 |
| U-10 | 落盘文件无明文口令 | 全文子串断言 | AC-6 |
| U-11 | `set_disabled(True)` 后 `authenticate` 失败 | — | — |
| U-12 | `has_users()` 空库为 False（自举态） | — | — |
| U-13 | `set_password` 对**不存在的用户**且 `create_missing=True` → 创建成功 | C-3 语义 | — |
| U-14 | `set_password` 对**已存在的用户** → 轮换，新口令可登录、旧口令不可 | C-3 语义 | — |
| U-15 | `set_password(create_missing=False)` 对不存在用户 → 返回 None | C-3 语义 | — |
| U-16 | 存储字段含 `algo/iterations/salt/hash` | 字段齐全 | — |
| **U-17（v2）** | `set_login_enabled(False)` → `is_login_enabled()` 为 False，文件已落盘 | — | AC-15 |
| **U-18（v2）** | `reload_if_changed()`：外部改文件后返回 True 且状态更新 | mtime 热加载 | AC-15 |
| **U-19（v2）** | `reload_if_changed()`：文件未变时返回 False | 避免每次请求都重载 | — |

### L1 — `tests/test_auth_session.py`（Lane B）

| ID | 用例 | 断言 | AC |
| --- | --- | --- | --- |
| S-1 | `parse_cookies` 解析 `a=1; b=2` | 正确 | — |
| S-2 | `parse_cookies(None)`/空串 → `{}`，不抛 | — | — |
| S-3 | 容忍空格与空段 | `"a=1;;  b = 2"` | — |
| S-4 | `build_session_cookie` 属性 | 含 `HttpOnly`、`SameSite=Lax`、`Path=/`、`Max-Age=` | AC-4 |
| S-5 | `clear_session_cookie` | `Max-Age=0` | AC-5 |
| S-6 | `create` 令牌长度 ≥ 32 且互不相同 | — | — |
| S-7 | `get` 命中有效会话 | 含 username/role | — |
| S-8 | 无效 token → None | — | — |
| S-9 | 过期会话（注入假 clock）→ None | — | — |
| S-10 | `destroy` 后立即失效 | — | AC-5 |
| S-11 | `purge_expired` 计数正确 | — | — |
| S-12 | 失败达阈值 → `is_locked` 为真 | — | AC-7 |
| S-13 | `record_success` 解锁 | — | AC-7 |
| S-14 | 不同来源互不影响 | — | — |
| S-15 | 20 线程并发 create/get/destroy 不抛 | — | R-3 |

### L1 — `tests/test_decide_auth.py`（**v2 新增，Lane C**，回应 Critic C-1）

直接 import `openai_proxy` 的 `_decide_auth`，**注入 client IP**，不依赖网络拓扑。

| ID | 用例 | 断言 | AC |
| --- | --- | --- | --- |
| D-1 | `/v1/models` + 无 key + `mode=off` → 放行 | `(True, ...)` | AC-8 |
| D-2 | `/console` + 无会话 → 不放行（需 302） | `(False, "login_required")` | AC-1 |
| D-3 | `/console` + 有会话 → 放行 | `(True, ...)` | AC-2 |
| D-4 | `/api/status` + client_ip=127.0.0.1 → 放行（本机免鉴权保留） | `(True, "local")` | AC-9 |
| **D-5** | **`/api/status` + client_ip=192.168.1.50 + 无会话无 key → 不放行** | `(False, "unauthorized")` | **AC-13** |
| **D-6** | **`/api/status` + 非本机 + 有会话 → 放行** | `(True, "session")` | AC-13 |
| **D-7** | **`/api/status` + 非本机 + 有 API Key → 放行** | `(True, "api_key")` | AC-13 |
| D-8 | `/login`、`/api/auth/login`、`/health` → 放行 | 豁免 | — |
| D-9 | `/api/status` + 本机 + `login_enabled=False` → 放行 | — | AC-14/15 |

### L2/E2E — `tests/test_login_flow.py`（Lane C，真实 HTTP）

**夹具**：把 `openai_proxy.py` + `auth_users.py` + `auth_session.py` 复制到 `tempfile.mkdtemp()`（隔离 `auth.json` / `auth_users.json` / `logs/`）；以 `--host 127.0.0.1 --port <随机高位端口>` 起子进程；`setUpClass` 轮询 `/health` 等待就绪；`tearDownClass` 终止子进程。

| ID | 用例 | 断言 | AC |
| --- | --- | --- | --- |
| E-1 | 未登录 `GET /console` | 302 + Location 含 `/login` | AC-1 |
| E-2 | 未登录 `GET /api/status`（本机） | 200 | AC-9 |
| E-3 | `POST /api/auth/login` 错口令 | 401；响应体不区分"用户不存在/口令错" | AC-3 |
| E-4 | `POST /api/auth/login` 正确口令 | 200 + Set-Cookie 含 `HttpOnly`、`SameSite=Lax` | AC-4 |
| E-5 | 带会话 `GET /console` | 200，含控制台标志串 | AC-2 |
| E-6 | 带会话 `GET /api/auth/me` | 200，username 正确 | AC-2 |
| E-7 | `POST /api/auth/logout` 后复用旧 Cookie | `/console` → 302 | AC-5 |
| E-8 | `GET /login` | 200，含登录表单 | — |
| E-9 | 同 IP 连错 5 次后第 6 次 | 429 | AC-7 |
| E-10 | `mode=off` 时 `GET /v1/models` | 200 | AC-8 |
| E-11 | `mode=strict` + 有效 `tap-` key → 200；无 key → 401 | P2 不变 | AC-8 |
| E-12 | 登录成功/失败写入请求日志 | 日志出现 login 事件；**entry 键集合 ⊆ 白名单**，无 password/cookie | AC-12 |
| E-13 | `auth_users.json` 无明文口令 | 全文断言 | AC-6 |
| E-14 | `--no-login` 启动 | `/console` 直接 200 | AC-14 |
| **E-15（v2）** | 外部把 `login_enabled` 改 false → **下一次请求**免登录（无需重启） | `/console` 变 200 | **AC-15** |
| **E-16（v2）** | 状态变更端点（`POST /api/default-model`）不带 `Content-Type: application/json` | 拒绝（400/415） | **AC-16** |
| **E-17（v2）** | 用**非回环地址**访问 `/api/status`（无凭据） | 401 | **AC-13** |
| **E-18（v2）** | 自举态：仓库无 `auth_users.json` 时启动 | `/console` 直接 200（不拦人） | PM-1 |
| E-19 | `--set-password admin`（`--password-stdin`）后重启 | `/console` → 302（登录已启用），可用该口令登录 | C-3 / PM-3 |

> E-17 若取不到非回环地址（`socket.gethostbyname(socket.gethostname())` 失败或仍是回环）→ `self.skipTest(...)` 并在报告中**显式标注该用例未执行**（不得默认视为通过）。

### 回归（命令行）

| ID | 用例 | 断言 | AC |
| --- | --- | --- | --- |
| G-1 | `py_compile` 三个改动文件 | 退出码 0 | AC-11 |
| G-2 | `unittest discover` | 退出码 0 | AC-10 |
| G-3 | `git status --porcelain` | `auth.json` / `auth_users.json` **不在输出中** | R-4 |

## 3. 非功能验证

| 项 | 方法 | 判据 |
| --- | --- | --- |
| 不打断线上 | 测试端口 ≠ 8088；测试前后比对线上 PID/启动时间 | 线上进程未变 |
| 跨平台 | 只用 `os/json/hashlib/secrets/hmac/threading/http.cookies/urllib` | 无 POSIX-only 调用 |
| 依赖 | 解析改动文件的 import 列表 | 无第三方包 |
| 并发 | S-15 + E2E 并发登录 10 次 | 无异常，Cookie 互不串号 |

## 4. 退出判据

功能类 AC 全通过 **且** 回归通过 **且** G-3 通过 → 方可进入"合入 `main` + 重启线上实例"。任一 AC 失败 → 回炉对应 lane，不允许带病上线。

## 5. 已知不测项

- 跨进程/多实例会话共享（单机部署，不成立）。
- TLS / `Secure` Cookie 场景（本地 HTTP，见 ODL 风险 R-6）。
- 真实模型调用质量（E-10/E-11 只验证鉴权判定与可达性）。
- **E-17 在无可用非回环地址时被 skip**——必须显式记录，不得默算通过。
