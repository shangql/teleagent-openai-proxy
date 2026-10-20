# Architect 评审 — proxy-user-login（r2 · 复审）

| 字段 | 值 |
| --- | --- |
| 角色 | Architect（只读复审） |
| 评审对象 | `.omx/plans/prd-proxy-user-login.md` (**v2**)、`.omx/plans/test-spec-proxy-user-login.md` (**v2**) |
| 独立性声明 | ⚠️ 同 r1：本环境无 `task` 子智能体，Architect 与 Critic 由同一执行体分角色完成，**评审独立性未达成**；补偿手段 = 逐条行号级证据 + 复审只认"v2 文本里的具体机制"，不认"已处理"的口头声明。 |
| 结论 | **PASS（复审通过，同意进入 Critic 复评）** |

## 1. r1 要求逐条核对

| r1 要求 | v2 的落点（可点击定位） | 判定 |
| --- | --- | --- |
| **V-1** P3 被"打印引导口令"打破 | PRD v2 §4「引导与口令流程」：服务**不生成、不打印**口令；无账号→自举态；口令由 `--set-password` 由用户自设；§7 安全细则同口径；§0 原则 P3 措辞强化为"服务永不打印、永不落盘明文" | ✅ 已修。且比 r1 建议更进一步：**连"一次性随机口令"都不存在**，从根上消除了 `proxy.out.log` 明文面（`install-scheduled-task.ps1:62-63`） |
| **V-2** 运行期缺无损回退 | PRD v2 §6 三条回退路径；§2 契约新增 `set_login_enabled()` / `reload_if_changed()`；`UserStore.is_login_enabled()` 进入契约 | ✅ 已修，热加载路径明确（mtime） |
| **T-1** CSRF 面 | PRD v2 §1 判定表 + §7「CSRF：状态变更端点要求 `Content-Type: application/json`」；测试规格 E-16 | ✅ 已修 |
| **T-2** Cookie host-scoped | PRD v2 §8 R-9；README 由 Lane C 更新 | ✅ 已修（文档项） |
| **T-3** 两种凭证材料 | PRD v2 §8 R-10（职责边界 + 判定统一在 `_decide_auth`） | ✅ 已修 |
| **S-1** JWT 否决理由排序 | PRD v2 §0 方案 B：「v2 结论：否决理由排序 = ①零依赖下不手写 HS256（主因）→ ②职责重叠 → ③撤销（加分项，非否决项）」 | ✅ 已修 |
| **S-3** 登录只是纵深防御 | PRD v2 §8 **R-8** + pre-mortem PM-2；"监听地址"进入发布检查清单一等公民 | ✅ 已修 |
| **C-1** AC-13 无用例且不可构造 | PRD v2 §2 新增 `_decide_auth(path, client_ip, has_session, api_key_record, login_enabled)` 纯函数契约；测试规格新增 `tests/test_decide_auth.py`（D-1..D-9，含 **D-5 非本机无凭据 → 不放行**）+ E-17 非回环 E2E（带显式 skip 条件） | ✅ 已修，且**解法优于 r1 建议**：纯函数注入 client IP，不依赖网络拓扑，可确定性断言 |
| **C-2** 登录事件日志 schema 未定义 | PRD v2 §5 白名单 schema（`event/result/username/client_ip/ts/path`）+ 明令禁记口令/Cookie/令牌；测试规格 E-12 断言"键集合 ⊆ 白名单" | ✅ 已修 |
| **C-3** CLI 语义歧义 | PRD v2 §2 契约：`set_password(username, new_password, create_missing=True)`；§4 流程；CLI 统一 `--set-password`，`--reset-password` 为别名；测试规格 U-13/U-14/U-15 覆盖三种语义 | ✅ 已修 |
| **C-4** 备选方案不公平 | PRD v2 §0 新增**方案 C′** 与**三方案成本矩阵**（含 C′ 列）；C′ 的权衡被显式交回用户（ODL-1/ODL-3） | ✅ 已修 |
| **C-5** 运行期回退不可执行 | PRD v2 §6 + AC-15 + 测试规格 U-17/U-18、E-15 | ✅ 已修 |

**r1 的 13 条要求：13/13 已修。**

## 2. v2 是否引入新的原则违反（复审职责）

| 检查 | 结论 | 依据 |
| --- | --- | --- |
| P1 零依赖 | ✅ 未引入 | 契约只用 `hashlib.pbkdf2_hmac` / `hmac.compare_digest` / `secrets.token_urlsafe` / `mtime` 比较 |
| P2 不打断既有调用方 | ✅ 保持 | 判定表把 `/v1/*` 单列，语义"完全不变"；`/api/*` 本机来源仍放行 |
| P3 凭据不落明文 | ✅ 强化 | 服务不再打印任何口令；日志用白名单字典构造 |
| P4 一处判定 | ✅ 强化 | `_decide_auth` 是唯一判定点，且**纯函数**（无全局状态、无 IO）→ 可单测 |
| P5 可回滚 | ✅ 强化 | 运行期（热加载）/ 启动期（`--no-login`）/ 彻底（删文件）三条，且前两条**不删用户数据** |

**无新违反。** 唯一新增的面是 `login_enabled` 字段引入了一个"可被外部改写的配置"——但它只影响**是否强制登录**，且方向是"更松"，不存在"更严到把人锁死"的路径；且 `has_users()==False` 时本就不拦人。**不存在新的锁死路径。**

## 3. 剩余张力（不阻断，但必须带入执行）

| # | 张力 | 处置 |
| --- | --- | --- |
| T-4 | `login_enabled` 由**文件外部改写**触发热加载，意味着任何能写该文件的人都能关掉登录 | 文件在脚本同目录，权限 0600；本机威胁模型下可接受 → 记入风险 R-4 邻接项 |
| T-5 | `_decide_auth` 把"是否本机"简化为 `client_ip in 127.0.0.1/::1/::ffff:127.0.0.1`，与现有 `_auth_is_local`（`:334`）重复实现 | 实现时**复用**现有 `_auth_is_local` 语义，避免两套"本机"定义漂移 |
| T-6 | 用户自助设口令意味着**弱口令由用户自己负责**（代理无法强制复杂度） | `MIN_PASSWORD_LENGTH=8` 是底线；README 提示；不追求强复杂度策略（单机工具，过度策略反成负担） |

## 4. 结论

**PASS** —— 同意进入 Critic 复评。

残余提醒（不属 Architect 裁决范围，交 Critic 与上线清单处理）：
1. 8 条 ODL 仍未获用户确认（规格为"部分澄清的 brief"）→ **上线前必须逐条过**。
2. 评审独立性未达成（无子智能体）→ 该事实必须写进最终交付说明，不得声称"经独立第三方评审通过"。
3. 线上实例（PID 26124）重启属显式动作，需用户拍板时机。
