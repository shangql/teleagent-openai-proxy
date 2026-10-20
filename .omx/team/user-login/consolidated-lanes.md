# 合并后的无冲突 Lane 计划（team `user-login`）

| 字段 | 值 |
| --- | --- |
| 团队 | `user-login`（3 人） |
| 计划来源 | 本次 OMX 链的 `docs` 等价物：`.omx/plans/prd-proxy-user-login.md` (v2) + 仓库内并行提交 `docs/user-login-plan.md` / `docs/user-login-api-contract.md` / `docs/adr-0001-user-login-auth-scheme.md` |
| 状态 | **A 泳道基座已合入 `main`（commit `7f12439`）；B / C 泳道尚未开工** |
| 本文件作用 | 把**两套并行的 lane 划分**合并成**一份区域级互斥**的执行计划，消除同文件写冲突 |

---

## 0. 为什么需要这份合并计划（实测到的冲突）

| 事实 | 证据 | 影响 |
| --- | --- | --- |
| 本会话按 `.omx/team/user-login/lanes.md` 划分 3 条 lane，其中 **Lane C 独占整个 `openai_proxy.py`** | `lanes.md` §0 所有权矩阵 | 与并行提交的区域归属表**直接冲突** |
| 并行提交的归属表把 `openai_proxy.py` **切成两块**：路由区（`_auth_check` / `do_GET` / `do_POST` / handler）归 A，`CONSOLE_HTML` 归 B | `docs/user-login-api-contract.md` §6（"文件与区域归属（防冲突表）"） | 两套划分叠加 = **同文件双写** |
| 两套方案实现了**同一件事**（账号存储 + 登录会话 + 限流）：本会话产出 `auth_users.py` / `auth_session.py`；并行提交产出 `user_auth.py` | 本会话 22:34–22:35 生成的 4 个文件 vs commit `7f12439` | 两套账号存储 + 两个 Cookie 名（`tap_ls` vs `tap_sid`）= **双重真相源** |
| 并行提交的实现**更完整且已合入**：含 CLI、CSRF 双提交、滑动续期、每用户会话上限、37 条单测 | `user_auth.py` 757 行；`python -m unittest tests.test_user_auth` → 37 passed | 采纳并行提交为基座 |

**处置（已执行）**：本会话的 4 个重复文件（`auth_users.py`、`auth_session.py`、`tests/test_auth_users.py`、`tests/test_auth_session.py`）已**可恢复删除**（移入回收站），避免第二套账号存储落地。**未修改**并行提交的任何文件。

## 1. 合并后的最终 lane 划分（区域级互斥）

> 规则：**同一文件的不同区域**也按所有权切开；任何 lane 需要越界 → 先改契约，再改代码。

| lane | 负责人 | 独占区域 | 产出 | 当前状态 |
| --- | --- | --- | --- | --- |
| **A** 后端接线 | 负责人 1 | `user_auth.py`（可加固，**签名不得变**）<br>`openai_proxy.py` 的 5 处集成点：import 区（≈19-40）、`_auth_check`（≈339-382）、`do_GET`/`do_POST`（≈2291-2356）、5 个新 handler、`===== 管理 API =====` 区块 | 后端增量（契约 §5 目标 ≤ 200 行） | ⬜ **未开工**（基座 `user_auth.py` 已合入，接线未做） |
| **B** 控制台前端 | 负责人 2 | `openai_proxy.py` 的 `CONSOLE_HTML` 常量（≈3431-4385）**仅此一处** | 登录遮罩 / 用户菜单 / 账号管理页 / 模式切换 UI | ⬜ **未开工** |
| **C** 测试 · CLI · 文档 | 负责人 3 | `tests/test_user_auth.py`、`tests/test_login_api.py`、`openai_proxy_manager.py`、`README.md`、`CHANGELOG.md`、`scripts/enable_login.ps1`、`scripts/rollback_login.ps1` | 契约级集成测试 + CLI 兼容 + 文档 + 上下线脚本 | ⬜ **未开工** |

**零重叠校验**：A 写 `openai_proxy.py` 的**路由区**，B 写同文件的**HTML 常量区**，C **完全不碰** `openai_proxy.py`。三者交集为空 ✅

### 1.1 唯一允许跨 lane 的接口

`docs/user-login-api-contract.md` §4 冻结的 `user_auth.py` 公开 API。**A 可加固实现，但不得改签名**；B、C 只按该契约写前端与测试。

### 1.2 合并顺序与分支

```
main
 └─ feature/login-contract     （契约 + user_auth.py + 37 单测）= commit 7f12439  ✅ 已合入
     ├─ feature/login-core         （A：后端接线）        → 第 2 个合
     ├─ feature/login-console      （B：前端）           → 第 3 个合（依赖 A 的端点形状）
     └─ feature/login-tests-docs   （C：测试/CLI/文档）   → 第 4 个合（需 A+B 合入后跑全量回归）
```

## 2. 各 lane 的验收标准（合并了本会话 PRD 的 AC 与仓库契约）

| lane | 验收（可断言） |
| --- | --- |
| **A** | ① 契约 §3.1/3.2/3.3 每个端点的**请求/响应/错误码逐条对上**（`invalid_credentials`/`locked_out`/`no_session`/`csrf_failed`/`user_exists`/`weak_password`…）；② 三档模式 `off/optional/required` 下 `/api/*` 行为符合契约 §2.3；③ **数据面 `/v1/*` 行为零变化**（`api_key="any"` 仍 200）；④ `/api/permission/*` 在 `required` 下可用 **API Key 兜底**；⑤ 最后一个 admin 不可删/降级（400）；⑥ 登录事件落审计日志（白名单字段，**不记口令/Cookie**）；⑦ `openai_proxy.py` 增量 ≤ 200 行且不触碰 `CONSOLE_HTML` |
| **B** | ① 未登录访问控制台只显示登录框；② 登录后各页功能与现状一致；③ 登出后立即回登录框；④ viewer 看不到账号管理页；⑤ 控制台**无 localStorage 令牌**；⑥ 401 自动弹登录框、403 `csrf_failed` 刷新重试 |
| **C** | ① `python -m unittest discover -s tests` 全绿；② 契约端点逐条覆盖（`tests/test_login_api.py`）；③ `openai_proxy_manager.py` 在三档模式下都能取到 `/api/status`（`required` 下先登录，带 Cookie）；④ README/CHANGELOG 与实现一致；⑤ 上下线脚本可执行 |

### 2.1 本会话额外要求的验收（两套计划都没写，但属高风险）

| # | 验收 | 理由 |
| --- | --- | --- |
| X-1 | **非本机来源**访问 `/api/status` 无凭据 → `401`（不能只测回环） | 登录的核心价值就是挡局域网；只测 127.0.0.1 等于没测 |
| X-2 | 会话 Cookie 属性实测为 `HttpOnly; SameSite=Lax; Path=/` | 契约 §2.1 已写死，须断言而非假设 |
| X-3 | 停用账号 → 其**所有现存会话立即失效** | 契约 §3.3 承诺 |
| X-4 | `users.json` / `auth.json` **既不被 git 跟踪，也不出现在 `git status`** | 明文哈希入库 = 凭据泄露 |
| X-5 | 改 `users.json` 的 `mode` 后**无需重启**即生效（运行期回滚） | 回滚必须分钟级 |
| X-6 | 上线前后**线上实例未被测试打断**（PID/启动时间不变） | 本次实测发现**同时有两个实例在监听 8088**，见 §4 |

## 3. 统一验证闸门（team 阶段「统一验证」的可执行实现）

脚本：`.omx/team/user-login/verify_base.ps1`（**ASCII-only**，规避 PS 5.1 的 ANSI 解析坑）

```powershell
powershell -ExecutionPolicy Bypass -File .omx\team\user-login\verify_base.ps1 -Port 18089
```

它做 11 项检查：`py_compile` → `unittest discover` → 密钥未被 git 跟踪 → **从副本目录**在备用端口起实例 → `/health`、`/v1/models`、`/api/status`、`/console` → 登录端点是否已接线 → **确认线上实例未被打断**。退出码 0 = 无 FAIL；`PENDING` = 该端点尚未由其 owner 接线（**不得**默认算通过）。

**每次合并后必跑**（对应仓库计划的"质量门禁"）。

## 4. 上线前的部署事实（本会话实测，必须进 runbook）

| # | 事实 | 证据 | 处置 |
| --- | --- | --- | --- |
| D-1 | **同时有两个代理实例在监听 8088**：`PID 25756` 绑 `127.0.0.1`（计划任务 runner 拉起）、`PID 26124` 绑 `0.0.0.0`（早前手工起的，**对整个局域网可达**） | `Get-NetTCPConnection -LocalPort 8088` | "重启服务"必须**指名道姓**：两个都重启，还是先杀掉 `0.0.0.0` 那个？否则会出现"重启了一个、流量在另一个" |
| D-2 | 计划任务 `TeleAgent OpenAI Proxy` 状态 `Ready`，runner 指向**本仓库**的 `openai_proxy.py`，参数 `--host 127.0.0.1 --port 8088` | `%LOCALAPPDATA%\TeleAgentOpenAIProxy\run-proxy.cmd` | 代码改完后，**重启计划任务即等于上线**（无需拷贝文件） |
| D-3 | `required` 模式对**局域网**生效 | `0.0.0.0` 实例存在 | 灰度必须 `optional` → `required`，与仓库计划 §7.1 一致 |
| D-4 | 回滚 = `python user_auth.py --set-mode off`，分钟级生效 | `user_auth.py` CLI | 值班同事必须抄到这条命令 |
| D-5 | 本会话**未重启、未终止**任何线上实例 | 验证全在副本目录 + 18089 端口完成（harness T11 PASS） | 上线重启需用户拍板时机（会打断在途请求） |

## 5. 与本会话 ODX 的关系

- 本会话 ODX 8 条（`specs/deep-interview-proxy-user-login.md` §ODL）与仓库计划的 11 条待澄清问题**高度重合**，且**关键结论独立收敛一致**：
  ① 鉴权方案 = **服务端会话 + Cookie**（非 JWT）；② 登录只保护**管理面**，`/v1/*` 行为不变；③ 双角色 `admin/viewer`；④ 不做邮件找回，改由 CLI/管理员重置；⑤ 会话 8 小时；⑥ 机器调用走 API Key 兜底。
  → 这是一次**独立交叉验证**：两条不同路径的分析得出同一结论，可信度显著提高。
- 差异点（本会话补充，仓库计划未覆盖）：① **歧义度量与就绪门**（最终歧义 0.143 / 阈值 0.20，但"人的判断"未满足）；② **决策边界**（哪些可自决、哪些必须问）；③ **ODL 的"证伪条件"**（方案要改的触发条件）；④ **暴露面优先于登录**（监听地址是主控制，登录是纵深防御）；⑤ **运行期回滚**与**双实例**的部署事实（D-1）。
