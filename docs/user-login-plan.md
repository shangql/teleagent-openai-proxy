# 用户登录功能 —— 实施计划（v1.12.0）

- 制定日期：2026-10-20
- 目标：给控制台加「用户登录」（账号 / 口令 / 登录会话 / 管理员），**不改动数据面 `/v1/*` 的任何行为**
- 配套文档：决策 `docs/adr-0001-user-login-auth-scheme.md`｜契约 `docs/user-login-api-contract.md`
- 核心实现：`user_auth.py`（已落地，35 条单测通过）

> **与 v1.11.0 的关系**：v1.11.0 是并行的**API Key 三档鉴权**（`auth.json`），本功能是**另一层**。
> 两者配置文件、接口前缀、模式开关全部分开，互不影响；本功能不修改 v1.11.0 的任何一行代码。
>
> **术语**：本仓库里 "session" 指 super-agent 会话；「登录会话」另称 login session，代码里用
> `LoginSessionStore` / `tap_sid`，避免二义。

---

## 1. 需求澄清（需求方未拍板项 → 本计划的默认答案）

需求方只说了「加用户登录，JWT 还是 session 没想好，3 个人并行」。以下 11 个问题会实质影响设计，
我**不阻塞等待**，而是逐条给出默认答案继续推进；需求方若不认同，改动点已在「怎么改回去」列明。

| # | 待澄清问题 | **默认答案（本计划据此实施）** | 若答案不同，怎么改 | 影响面 |
|---|-----------|---------------------------|------------------|--------|
| 1 | JWT 还是 session？ | **服务端会话 + Cookie**（理由见 ADR） | 换 `JwtProvider`，半天内可切，契约不变 | 契约级，但已被接口隔离 |
| 2 | 登录保护哪些端点？ | 只保护**管理面**（`/console` + `/api/*`）；数据面 `/v1/*` 继续用 API Key | 要覆盖数据面，需给 Key 增加 `owner` 概念，工作量 ×2 | 高 |
| 3 | 登录是否影响机器客户端（机器人、CLI、SDK）？ | **不影响**；`/api/permission/*` 允许 API Key 兜底 | 若要求机器也走会话，需引入服务账号 | 中 |
| 4 | 角色模型？ | 二角色：`admin`（可管账号）/ `viewer`（只读控制台） | 加角色只需在 `ROLES` 加值 + 契约补一行 | 低 |
| 5 | 首次部署怎么建管理员？ | CLI 命令 `python user_auth.py --init-admin admin`（不依赖代理进程） | 改为首次访问网页自助注册，需加「仅当无用户时开放注册」逻辑 | 低 |
| 6 | 口令策略？ | 仅长度 ≥ 10；PBKDF2-HMAC-SHA256 210k 次加盐 | 改 `MIN_PASSWORD_LENGTH` / `DEFAULT_PBKDF2_ITERATIONS` | 低 |
| 7 | 要不要「忘记密码 / 邮箱验证」？ | **不做**（本地部署无邮件服务），改由管理员重置 | 需引入邮件服务依赖 | 中 |
| 8 | 多租户 / 组织？ | **不做**，单租户 | 需给用户加 org 字段并全链路透传 | 高 |
| 9 | 会话有效期？ | 8 小时，滑动续期 | 改 `DEFAULT_SESSION_TTL` | 低 |
| 10 | 忘记登录怎么办（可用性风险）？ | 三档模式 `off → optional → required` 灰度，`optional` 保留本机放行 | —— | 低 |
| 11 | 现有 `openai_proxy_manager.py`（无凭据调 `/api/status`）怎么办？ | `off`/`optional` 下不动；`required` 下由 C 泳道加「先登录」 | —— | 低 |

> **需要需求方确认的只有 3 条**（其余均可后补，不阻塞开发）：
> ① 第 2 条的保护范围（建议维持「只管管理面」）；② 第 4 条角色是否够用；③ 第 5 条建管理员的方式是否符合运维习惯。

## 2. 范围

**v1.11.0 做**

- 账号体系：增删改查、角色、停用/启用、改口令、最后一个管理员保护
- 登录：口令校验、失败限流锁定、错误文案防用户枚举
- 会话：签发 / 校验 / 续期 / 吊销，Cookie 属性正确
- 管理面鉴权接入：`_auth_check` 按登录模式放行或拦截
- 控制台：登录遮罩、当前用户信息、登出、账号管理页（admin）
- 三档模式灰度与一键回滚

**v1.11.0 不做（记入后续）**

- 忘记密码 / 邮件验证 / SSO / OAuth / 双因素
- 用户维度配额与用量统计（`/v1/*` 仍以 Key 计量）
- 审计日志（登录成功/失败事件持久化）
- 多实例共享会话（需换掉 `SessionStore` 实现）

## 3. 三条并行泳道

**共同前提**：三条分支都从「契约基线提交」拉出，**契约已冻结**（见 `docs/user-login-api-contract.md`）。
依赖关系：A ← B（前端要对着后端端点写）、C 全程可并行（最后合）。

### 泳道 A —— 后端核心与鉴权接线（负责人 1）

| 项 | 内容 |
|----|------|
| 已有 | `user_auth.py`（账号 / 会话 / 限流 / CSRF / Cookie 工具）已落地并通过 35 条单测 |
| 待做 | ① 按契约第 5 节在 `openai_proxy.py` 的 5 处集成点接线；② 实现 5 个新 handler；③ 登录模式接入 `_auth_check`；④ `required` 模式下 `/api/permission/*` 的 API Key 兜底；⑤ 账号管理端点的「最后一个管理员」保护；⑥ 加固：会话表定期清理、登录接口限流参数可配 |
| 产出 | `openai_proxy.py` 的最小增量 + `user_auth.py` 的加固 + 路由级自测 |
| 验收 | 契约第 3 节每个端点：请求/响应/错误码逐条对上；`off/optional/required` 三种模式下 `/api/*` 行为符合第 2.3 节；数据面 `/v1/*` 行为零变化；`openai_proxy.py` 增量 ≤ 200 行且不触碰 `CONSOLE_HTML` |
| 风险 | 与需求方未提交的 `openai_proxy.py` WIP（API Key 鉴权，522 行）**同一文件** → 合并前必须先与 WIP 提交合流，见第 4 节 |

### 泳道 B —— 控制台前端（负责人 2）

| 项 | 内容 |
|----|------|
| 待做 | ① `CONSOLE_HTML` 内加登录遮罩层（未登录时遮住全部内容并弹出登录框）；② 统一 `apiFetch()` 包装：带 `X-CSRF-Token`、401 自动弹登录框、403 `csrf_failed` 刷新重试；③ 顶栏加当前用户名 + 登出按钮；④ 新增「账号管理」页（仅 admin 可见）：列表 / 新建 / 改口令 / 停用 / 删除；⑤ 登录模式切换 UI（调用 `/api/auth/login-mode`）；⑥ 登录失败 / 锁定倒计时 / 表单校验提示 |
| 产出 | `openai_proxy.py` 中 `CONSOLE_HTML` 常量的增量（**仅此一处**） |
| 验收 | 未登录访问控制台 → 只显示登录框；登录后所有页面功能与现状一致；登出后立即回到登录框；viewer 看不到账号管理页；控制台无 localStorage 里的令牌 |
| 依赖 | 对着契约第 3 节写；A 的端点未上线前用 mock 响应联调（契约里给了完整 JSON 样例） |

### 泳道 C —— 测试、CLI 兼容与文档（负责人 3）

| 项 | 内容 |
|----|------|
| 待做 | ① 扩展 `tests/test_user_auth.py`（边界：并发登录、会话表清理、模式切换并发）；② 新增 `tests/test_login_api.py`（起真实 `ThreadingHTTPServer`，用 `http.client` 打契约端点，逐条断言契约）；③ 改造 `openai_proxy_manager.py`：`required` 模式下先登录（`--user` / `--password` / 环境变量 `TAP_LOGIN_USER`、`TAP_LOGIN_PASSWORD`），带 Cookie 调 `/api/status`；④ `README.md` 增「用户登录」章节；⑤ `CHANGELOG.md` 写 v1.11.0 条目；⑥ 上线脚本 `scripts/enable_login.ps1`（建管理员 + 设模式）与回滚脚本 `scripts/rollback_login.ps1` |
| 产出 | 测试、CLI 改造、文档、上下线脚本 |
| 验收 | `python -m unittest discover -s tests` 全绿；契约端点逐条覆盖；`openai_proxy_manager.py` 在三档模式下都能取到状态；README/CHANGELOG 与实现一致 |
| 依赖 | 无（可第一天就开工） |

### 工作量与排期（建议）

| 泳道 | D1 | D2 | D3 | D4 |
|------|----|----|----|----|
| A | 接线 + 登录/登出/me | 账号管理端点 + 模式接入 | 加固 + 自测 | 修 bug、配合联调 |
| B | apiFetch 包装 + 登录遮罩 | 用户菜单 + 登出 | 账号管理页 + 模式 UI | 联调 + 视觉打磨 |
| C | 契约级集成测试 | manager CLI 改造 | 文档 + 上下线脚本 | 全量回归 + 演练 |

D4 三人合并 → 走第 4 节流程；D5 灰度上线。

## 4. 分支与合并策略

### 4.1 分支

| 分支 | 归属 | 从哪拉 |
|------|------|--------|
| `feature/login-contract` | 共同基线 | `main`（**先合入 main**） |
| `feature/login-core` | A | `feature/login-contract` |
| `feature/login-console` | B | `feature/login-contract` |
| `feature/login-tests-docs` | C | `feature/login-contract` |

### 4.2 合并顺序

```
main
 └─ feature/login-contract      （契约 + user_auth.py + 单测）→ 先合
     ├─ feature/login-core      （A：后端接线）          → 第 2 个合
     │   └─ feature/login-console  （B：前端）         → 第 3 个合（B 依赖 A 的端点形状）
     └─ feature/login-tests-docs（C：测试/CLI/文档）     → 第 4 个合（需 A+B 都已合入才能跑全量回归）
```

**合并规则**

1. 每个 PR 必须**只改归属表内的区域**；越界直接打回。
2. A 合入前，先把需求方**未提交的 `openai_proxy.py` WIP 单独提交**（如 `feat: API Key 三档鉴权`），
   否则 A 的增量会和 WIP 混在同一文件里，冲突无法自动解决。
3. 每次合并后跑一次全量单测 + 手工回归清单（第 5 节）。
4. 合并用 `--no-ff` 保留分支痕迹；冲突解决原则：**契约优先**——以 `docs/user-login-api-contract.md` 为准。

### 4.3 冲突高发区与预案

| 高发区 | 风险 | 预案 |
|--------|------|------|
| `openai_proxy.py` 的 `do_GET`/`do_POST` | A 独占，C 的 CLI 与 B 不碰 | 归属表已隔离 |
| `openai_proxy.py` 的 `CONSOLE_HTML` | B 独占，A 不碰 | 归属表已隔离 |
| `openai_proxy.py` 顶部 import 区 | A 加 1 行 import | 冲突面仅 1 行，手工可解 |
| 未提交的 API Key WIP | 与 A 的改动同文件 | 合并前先单独提交 WIP（4.2 规则 2） |

## 5. 质量门禁

**自动化**

```bash
python -m unittest discover -s tests -v     # 全部单测
```

**手工回归清单（每次合并后必跑）**

- [ ] 数据面：`curl /v1/models`、`curl -N /v1/chat/completions`（`api_key="any"`）行为与改动前一致
- [ ] 管理面：`/api/status`、`/api/models`、`/api/logs`、`/api/sessions`、`/api/stats` 返回正常
- [ ] 控制台：仪表盘 / 模型 / 日志 / 测试 / 会话 / 系统 / 认证 各页正常渲染
- [ ] 机器人链路：`/api/permission/pending` 可拉取、`/api/permission/reply` 可应答
- [ ] CLI：`python openai_proxy_manager.py` 正常
- [ ] 登录：登录 / 登出 / 会话过期 / 锁定倒计时 / 停用账号立即踢下线
- [ ] 三档模式：`off` → `optional` → `required` 逐档切换，行为符合契约 2.3

## 6. 登录页承载方式（一个待定的实现选择）

### 6.1 两种做法与取舍

| 做法 | 描述 | 优点 | 代价 |
|------|------|------|------|
| **A. 控制台内遮罩层（默认）** | `/console` 页面外壳照常加载，未登录时前端渲染登录遮罩；`/api/*` 返回 401 触发遮罩 | ① **不新增路由**，B 泳道只改 `CONSOLE_HTML` 一处，A/B 零冲突；② `optional` 模式下本机用户不受打扰（不会莫名被弹登录框）；③ 现有「永久豁免」白名单不用改 | 前端要多写遮罩层逻辑；浏览器地址栏不体现"在登录页" |
| B. 独立 `/login` 页 | 未登录访问 `/console` → 302 到 `/login` | 语义更直白；登录页可单独做品牌页 | ① A 要多一条路由 + B 要多一个 `LOGIN_HTML` 常量，**跨泳道耦合**（B 未合入时 A 的路由要有兜底）；② `optional` 模式下要额外判"本机是否放行"，否则本机用户被反复弹登录 |

**默认选 A**（冲突面最小）。若团队偏好 B：契约只需改一处（A 加路由 + B 加常量），
其余端点、错误码、角色模型、CSRF 规则**一字不改**。

## 7. 上线与回滚（Runbook）

### 7.1 上线步骤

```bash
# 1) 建管理员（不依赖代理进程）
python user_auth.py --init-admin admin

# 2) 灰度：先 optional（本机仍放行，外部访问开始要求登录）
python user_auth.py --set-mode optional
#    观察一个使用周期：机器人 / CLI / 外部访问是否正常

# 3) 终态：required
python user_auth.py --set-mode required
```

Windows 侧服务重启（**会让在途请求失败，必须择时并先通知使用者**）：

```powershell
Restart-ScheduledTask -TaskName "TeleAgent OpenAI Proxy"   # 计划任务方式
# 或手动重启：start_proxy.cmd
```

> ⚠️ **当前线上进程与计划任务参数不一致**：实测在跑的进程是 `--host 0.0.0.0`（局域网可达），
> 而计划任务 `TeleAgent OpenAI Proxy` 用的是 `--host 127.0.0.1` 且状态为 `Ready`（未在跑）。
> 上线前必须先确认「到底谁在服务流量」，否则会出现「重启了一个、流量在另一个」的情况。
> 另外 `0.0.0.0` 意味着登录功能一旦 `required`，是**对整个局域网**生效——灰度务必从 `optional` 起步。

### 7.2 回滚（分钟级，配置即生效）

```bash
python user_auth.py --set-mode off      # 立刻恢复改动前行为，无需改代码
# 极端情况：删掉 users.json 也能回到「无登录」状态
```

> 会话表在内存，重启即清空；回滚不需要考虑会话残留。

### 7.3 上线前检查

- [ ] `users.json` 已进 `.gitignore`（含口令哈希，绝不能入库）
- [ ] `auth.json` 同样已进 `.gitignore`（**当前仓库里它还是未跟踪状态，`git add -A` 会把它带进去**）
- [ ] 管理员口令已按 ≥ 10 位强口令设置，且不是复用其他系统的口令
- [ ] 代理监听地址确认：若监听 `0.0.0.0`，`required` 模式下才对全网生效——`optional` 只挡外部
- [ ] 回滚命令已抄写到值班同事手上

## 8. 现状风险（非本次功能引入，但上线前应处理）

| 风险 | 现状 | 建议 |
|------|------|------|
| `auth.json` 未被 git 忽略 | `git status` 显示为未跟踪文件，`git add -A` 会连同 Key 哈希一起提交到**公开仓库** | 本次一并加入 `.gitignore`（已处理） |
| `openai_proxy.py` 有 522 行未提交改动 | 需求方的 API Key 鉴权 WIP；与 A 泳道改同一文件 | 上线前先单独提交该 WIP |
| 仓库无 CI | 改动只能靠人工回归 | 建议后续加一个最小 CI：跑 `python -m unittest discover -s tests` |
| 控制台无鉴权白名单外的防护 | `/console` 页面外壳任何人可拉（页面本身不含敏感数据） | 保持现状即可，但**不要**把账号列表等信息渲染进静态 HTML |
