# Lane 划分 — team `user-login`

| 字段 | 值 |
| --- | --- |
| team | `user-login` |
| 源头 | `.omx/plans/prd-proxy-user-login.md` (v2, Critic APPROVE) + `.omx/plans/test-spec-proxy-user-login.md` (v2) |
| 人数 | 3（与用户"3 个人并行开发"一致） |
| lane 数 | 3（skill 建议 2–4 条，Mavis 有并发上限） |
| 并行前提 | **PRD §2 的模块契约已冻结** —— 三条 lane 只按契约写，不互相协商签名 |
| 合并顺序 | A → B → C（C 依赖 A/B 的契约，但三者可**同时开工**） |

## 0. 所有权矩阵（互斥，零重叠）

| lane | 独占文件 | 禁止触碰 |
| --- | --- | --- |
| **A** `auth-user-store` | `auth_users.py`、`tests/test_auth_users.py` | `openai_proxy.py`、`auth_session.py`、`tests/test_*` 其他文件、README/CHANGELOG |
| **B** `auth-session-guard` | `auth_session.py`、`tests/test_auth_session.py` | `openai_proxy.py`、`auth_users.py`、其他测试文件、README/CHANGELOG |
| **C** `auth-console-integration` | `openai_proxy.py`、`tests/test_decide_auth.py`、`tests/test_login_flow.py`、`README.md`、`CHANGELOG.md`、`VERSION`、`.gitignore` | `auth_users.py`、`auth_session.py`（**只读依赖，不得修改**） |

> **共享改动收敛**：凡需同时动 `openai_proxy.py` 与其它文件的，一律由 **Lane C** 串行收口（A/B 不得改主文件）。

## 1. Lane A — `auth-user-store`（账号存储与口令）

- **目标**：交付 PRD §2 中 `auth_users.py` 的**全部**契约（函数签名逐字对齐）。
- **输入产物**：`.omx/plans/prd-proxy-user-login.md` §2（`auth_users.py` 契约块）、§3（数据格式）、§4（引导流程）、§7（安全细则）。
- **允许触碰**：`auth_users.py`、`tests/test_auth_users.py`。
- **验收方式**：`tests/test_auth_users.py` 用例 **U-1..U-19 全绿**（含 `set_password(create_missing=...)` 三态、公开视图不含 salt/hash、落盘无明文、`login_enabled` 热加载）。
- **关键约束**：PBKDF2-HMAC-SHA256 200k + 16B 盐（`hashlib.pbkdf2_hmac`）；`hmac.compare_digest`；原子写（tmp + `os.replace`）；失败一律返回 `None` 而非抛错（防用户名枚举）；**不引入第三方依赖**。
- **交付物**：`auth_users.py`、`tests/test_auth_users.py`、lane 报告（命令 + 输出）。

## 2. Lane B — `auth-session-guard`（会话与登录限流）

- **目标**：交付 PRD §2 中 `auth_session.py` 的**全部**契约。
- **输入产物**：PRD §2（`auth_session.py` 契约块）、§7（Cookie 属性、限流阈值）。
- **允许触碰**：`auth_session.py`、`tests/test_auth_session.py`。
- **验收方式**：`tests/test_auth_session.py` 用例 **S-1..S-15 全绿**（Cookie 属性含 `HttpOnly`/`SameSite=Lax`、会话过期、销毁即失效、限流锁定与解锁、20 线程并发冒烟）。
- **关键约束**：会话**只存内存**（P3）；令牌 `secrets.token_urlsafe(32)`；`threading.Lock` 保护两张表（R-3）；不落盘。
- **交付物**：`auth_session.py`、`tests/test_auth_session.py`、lane 报告。

## 3. Lane C — `auth-console-integration`（控制台接入、接线与发布）

- **目标**：把 A/B 的能力接进服务，并把功能交付到"可发布"状态。
- **输入产物**：PRD §1（判定表）、§2（`openai_proxy.py` 契约 + `_decide_auth`）、§4（引导流程）、§5（登录日志 schema）、§6（回退路径）、§7（安全细则）。
- **允许触碰**：`openai_proxy.py`、`tests/test_decide_auth.py`、`tests/test_login_flow.py`、`README.md`、`CHANGELOG.md`、`VERSION`、`.gitignore`。
- **验收方式**：`tests/test_decide_auth.py` **D-1..D-9** 全绿（含 **D-5 非本机无凭据 → 拒绝**）；`tests/test_login_flow.py` **E-1..E-19** 全绿（E-17 允许显式 skip，但必须记录）；`py_compile` 通过。
- **关键约束**：
  - `_decide_auth` 必须是**纯函数**（无全局状态、无 IO）→ 否则 D-1..D-9 无法单测；
  - `/v1/*` 语义**完全不变**（P2）；`/api/*` 本机免鉴权**保留**；
  - 复用既有 `_auth_is_local`（`openai_proxy.py:334`）的"本机"定义，**不要另起一套**（Architect T-5）；
  - 状态变更端点要求 `Content-Type: application/json`（CSRF，T-1）；
  - 登录事件日志按 PRD §5 **白名单**构造；
  - `.gitignore` 补 `auth.json`、`auth_users.json`；
  - `VERSION` → `1.11.0`；CHANGELOG 按 Keep a Changelog 格式新增条目；README 补鉴权章节与恢复步骤。
- **交付物**：上列全部文件 + lane 报告。

## 4. 跨 lane 接口约定（冻结，任何改动须回 PRD 走复审）

```
auth_users.UserStore.authenticate(username, password) -> dict|None
auth_users.UserStore.has_users() -> bool            # 自举态判定
auth_users.UserStore.is_login_enabled() -> bool
auth_session.SessionStore.create(username, role) -> str
auth_session.SessionStore.get(token) -> dict|None
auth_session.SessionStore.destroy(token) -> bool
auth_session.parse_cookies(header) -> dict
auth_session.build_session_cookie(token, max_age=...) -> str
auth_session.LoginGuard.is_locked(ident) -> bool
```

## 5. 统一验证与收尾（主会话职责，非 lane）

1. 三条 lane 全部终止后，**主会话自己再跑一次全量验证**（不只信 lane 自述）：
   `py_compile` → `unittest discover -s tests` → `git status` 密钥未跟踪。
2. 跨 lane 集成点核对：`openai_proxy.py` 调用的 A/B 符号与契约**逐字一致**；`_decide_auth` 的入参与调用点一致。
3. 线上安全核对：`PID 26124` 未被打断；线上 `8088` 未被测试占用。
4. 汇总 lane 交付物路径、验证证据、遗留风险 → `.omx/team/user-login/report.md`。
5. 发布动作见 `.omx/team/user-login/report.md` 的"上线检查清单"（含 8 条 ODL 与监听地址）。

## 6. 失败处理

- lane 失败 → 先补上下文重试一次；仍失败则缩小该 lane 范围或标 cancelled，**不得拖住整体**。
- 发现两条 lane 写同一文件 → 立即停掉冲突那条，串行重做（本设计已通过所有权矩阵排除）。
- 需要中途改需求 → **停掉所有 lane**，更新 spec/PRD 后重新划分，不让新旧计划混跑。
