# AP 模块方案评审（对照本仓库现状）

**评审对象：** `backend/services/ap_manager/AP_Development_Plan.md` v1.0（2026-10-30）
**评审日期：** 2026-10-30
**评审方式：** 逐条核对方案第 15 节列出的 10 项"待确认事项"，全部落到代码/数据库实测

---

## 0. 结论

**方向可行，业务闭环设计（状态机 + 审核后关闭 + 审计 + 通知解耦）完全正确，可以直接采用。**

但方案是**脱离本仓库写的通用设计**，其中 **4 处假设与现状不符**，照原样开发会在第 1 天就卡住：

| # | 方案假设 | 项目实际 | 影响 |
|---|---|---|---|
| A | 复用现有「部门」主数据 | **没有部门数据**：`app.person` 的 `department/position/office` 三列实测**全部为空**（137 行，非空 0 行） | 部门下发、Department AP、部门绩效全部落不了地 |
| B | 复用现有「用户 + 邮箱」 | 登录身份只有门户 `username`（`jouwala` / `fe_fe_128` / `6000056629`），**没有邮箱、没有中文名**；`app.person` 只有 50/137 有 email，且按英文全名存，**与 username 无法 JOIN** | "派给谁 + 通知到谁"缺一张映射表 |
| C | 复用现有「角色/权限」 | 会话里 `role` 只有 `admin` / `viewer` 两个值（`portal_auth.py:446-462`），没有 AP Manager / Reviewer | 方案第 8 节的 6 个角色需自建 |
| D | 前端沿用 Tailwind + 原生 JS | 项目是 **React + Vite + antd**，且强制走统一组件 + 中英双语 + 三处登记 | 方案第 10 节的前端设计需整体重写 |

**评级：** 业务方案 9/10，落地可行性 6/10（缺口都在"人和组织"这一层，不在流程本身）。

**建议：** 首版砍掉"部门维度"和"统计分析"，先做「个人下发 → 确认 → 更新进度 → 提交 → 审核」这条最小闭环。缺口 A/B 用一张 `ap_user_profile` 表补上，不重建用户库。

---

## 1. 逐条核对（方案第 15 节）

| 方案待确认项 | 实测结论 | 出处 |
|---|---|---|
| 1. 后端框架 | **FastAPI**（不是 Flask/Django），路由集中在 `backend/routers/` | `backend/main.py:270-352` |
| 2. 数据库与用户/部门/角色表 | **PG 为主**（`MY_APP_DB_MODE=pg`），schema = `app`，68 张表。**无用户表、无部门表、无角色表**；`portal_sessions` 只有 `username/role/allowed_groups/allowed_cards` | `backend/.env`；`app.portal_sessions` |
| 3. 页面路由与导航 | `frontend/src/App.tsx` 菜单数组 + `i18n.tsx` + `pages/helpContent.ts`，**新增页面必须三处同步** | `AGENTS.md` 第三节 1 |
| 4. 登录态如何传给 API | 会话 Cookie（`sid`）→ 中间件校验 → `current_user()` 返回 `{username, role, allowedGroups, allowedCards}`；本机回环放行 | `backend/main.py:369-390`；`portal_auth.py:509-520` |
| 5. 邮件服务 | **双通道已就绪**：126 邮箱 SMTP（`send_status_email`）+ Exchange EWS（`send_ews_status_email`），另有 EWS 故障自动补发任务。**但没有通用 outbox/重试队列** | `services/email_notifier.py:146,225`；`services/email_recovery.py` |
| 6. 附件上传/存储/下载 | **已有完整可复制的实现**：`issue_reports` + `db/attachments/fb_<id>/`，5 个/10MB 限制、可执行文件黑名单、inline 预览 | `routers/feedback.py:1-20,49-62` |
| 7. 用户是否有部门负责人/经理字段 | `app.person` 有 `region_leader / sub_region_leader / sub_center_leader / circle_leader / position` 列，但**实测全为空**。真正可用的是 `app.flm_team_information`（30 人，含 Position / Base location / County / eFlow Acount） | 实测 SQL |
| 8. 是否关联 Ticket/Site/Region | 可关联，字段现成：`eflow_tt`（TT 号）、`master_site_db`（site id）、`person.managed_regions`（区域） | — |
| 9. 多级审核/SLA | 项目无任何审批流引擎，需自建；建议首版单级 | — |
| 10. SLA/升级/周期提醒 | 有现成调度底座（`task_registry.TASK_SPECS` + worker 分组），可加 1 个提醒任务 | `task_registry.py:179`；`worker_watchdog.py:283` |

---

## 2. 四个阻塞项与解法

### A. 没有部门主数据 → 首版不做"部门下发"

方案 2.2 / 4.3 / 11 的部门维度建立在"有部门表"之上，实际没有。三条可选路径：

1. **（推荐）首版只做个人下发**，`target_type` 字段保留 `USER`，`DEPARTMENT` 先不实现 —— 表结构不动，只不开放入口，后续加不返工。
2. 用 `app.flm_team_information` 的 `Base location`（如 `Monrovia POOL (Team1)`）+ `County` 当"准部门" —— 只覆盖 30 个现场人员，办公室人员没有。
3. 新建 `ap_departments` 表，手工维护部门与成员 —— 需要业务方提供一份组织架构清单，这是**唯一能真正支撑部门看板的路**，但要额外数据源。

> 注意：`app.person.department` 是**空的**，不要假设它可用。若后续 CMDB 导出补上该列，只需把 `ap_user_profile.department` 的取值来源换成 `person`，接口不变。

### B. 身份桥：门户 username ↔ 人

这是整个模块的地基。实测存在一条**可用链路**：

```
门户登录 username（如 fe_fe_128）
   ↓ 小写直接对应
app.flm_team_information."unnamed_5"（eFlow Acount，30 人）
   ↓ 同行取出
"unnamed_3"=姓名  "unnamed_4"=职位  "unnamed_2"=Base location  "unnamed_1"=County
   ↓ 姓名经 normalize_person_name() 归一
app.person（email 50/137、managed_regions、leavestatus）
```

实测命中：会话中的 `fe_fe_128` → `Luogon Justin`。**现场人员这条路是通的**；但办公室账号（`admin` / `jouwala` / `k-toure` / `6000056629`）不在 FLM 花名册里，必须人工建档。

**解法：** 新增一张 `ap_user_profile`，以 **门户 username 为主键**（不是新用户库，是身份扩展）：

| 列 | 说明 |
|---|---|
| `username` | PK，门户登录名（小写） |
| `display_name` | 显示名，首次登录时按上面链路自动预填，可人工改 |
| `email` | 通知邮箱，自动预填 `person.email`，为空则不发邮件 |
| `department` / `team` / `position` | 组织信息，首版仅用于展示与筛选 |
| `ap_role` | `AP_MANAGER` / `REVIEWER` / `MEMBER`（方案第 8 节的 6 个角色收敛为 3 个，Admin 复用现有 `role=admin`） |
| `is_active` | 离职/停用（可参考 `person.leavestatus`） |

**关键：** 首次访问 AP 页面时若 `ap_user_profile` 无记录 → 自动建档（用 username 兜底显示名），**绝不能因为没建档就 403**，否则新用户第一次点进来就是死路。这与项目"首次访问惰性建表"的既有写法一致（`routers/feedback.py:15`）。

### C. 权限模型要自建，且必须后端校验

`role` 只有 admin/viewer，`require_protected`（`backend/security.py`）是"本机放行"语义，**不适合 AP**——它保护的是"只有本机能改配置"，而 AP 是"任何登录用户按关系授权"。

必须实现一个 `ap_permission.can(user, ap, action)`，判定依据：
- 创建人 → 编辑/下发/取消
- 指派人（`ap_assignees`）→ 确认/进度/提交
- `reviewer_username` → 审核（且校验 `status == PENDING_REVIEW`）
- `role == admin` → 兜底

> 方案 8.1 的判断是对的：**前端隐藏按钮不算鉴权**。这一点在项目里尤其重要，因为门户反代下所有请求都来自本机回环，`require_protected` 会自动放行（`security.py` 顶部注释），**只有会话身份可用**。

### D. 前端按项目规范重写，不是 Tailwind

| 方案第 10 节 | 项目实际要求 |
|---|---|
| Tailwind + 原生 JS | React + Vite + antd；卡片必须 `components/cards` 的 `CardBase/StatCard` |
| 自写弹窗 | `components/DraggableClickModal` |
| 自写导出 | `utils/excelReport.ts` 的 `exportReport/exportAoaReport` |
| 中文字面量 | `t('key')`，`i18n.tsx` **中英两处**都要加 |
| 新页面直接加路由 | `App.tsx` 菜单 + `i18n.tsx` 中英 + `docs/manual/11-feature-guide.md` + `helpContent.ts` 的 `PAGE_DOCS`(zh/en) / `PAGE_LIST` / `NAV_KEY_MAP` |

从 `pages/_TemplatePage.tsx` 复制骨架，自动获得统一风格。漏登记 `PAGE_LIST` 页面**不会显示**（这是项目踩过的坑，`AGENTS.md` 第三节 1）。

---

## 3. 可直接复用的现成能力（省 40% 工作量）

| 能力 | 复用对象 | 说明 |
|---|---|---|
| 附件上传/下载/预览 | `routers/feedback.py` 全流程 | 连黑名单、大小限制、路径穿越防护、inline 预览都齐了，改前缀即可 |
| 邮件发送 | `services/email_notifier.send_status_email` / `send_ews_status_email` | 不要新写 SMTP 客户端 |
| 邮件失败不阻断业务 | 项目既有约定 | 通知失败只记日志（`email_notifier.py` 顶部设计原则），与方案 9.3 一致 |
| 定时提醒任务 | `task_registry.TASK_SPECS` | 加 1 条即可，但**必须显式分到 worker 组**，否则队列 pending 卡死 |
| 表读写双模 | `backend/database.get_raw_connection` + `dialect_helpers` | 别写裸 `sqlite3.connect` |
| 列表/分页/筛选 | `routers/feedback.py` 的查询写法 | 与 Settings 页风格一致 |
| 页面骨架 | `pages/_TemplatePage.tsx` | 可编译骨架 |

---

## 4. 方案里需要修正的技术细节

1. **状态枚举不要带空格。** 方案用 `In Progress` / `Pending Review` 作状态值，落库、拼 URL、做 i18n key 全是坑。改 `IN_PROGRESS` / `PENDING_REVIEW`，展示层再翻译。
2. **路由注册顺序有坑。** `GET /api/ap/analytics` 必须**注册在** `GET /api/ap/{id}` **之前**，否则 `analytics` 会被当成 `id` 解析，直接 422。
3. **`POST /{id}/update` 与 `PUT /{id}` 语义重叠。** 建议前者改名 `/progress`（只改进度+说明），后者才是改任务字段，避免前端混用。
4. **`progress` 归属要定死。** 方案 5.1 把 `progress` 放主表，但 `ALL_REQUIRED` 多执行人时"主表进度"没有定义。建议：个人进度存 `ap_assignees.progress`，主表 `progress` 为聚合值（取 min 或加权），且**由后端算，不接受前端直接写**。
5. **时间口径别改成 UTC。** 方案 12.2 要求存 UTC，但本项目所有表都是 **naive 本地时间**（如 `_sync_time = 2026-07-28T15:00:05`），前端 `datetime.ts` 统一格式化。AP 单独用 UTC 会导致"AP 页面时间和别的页面差 8 小时"。**沿用现状，AP 内保持单一口径。**
6. **`Overdue` 不做状态是对的**（方案 3 的判断正确），但实现上建议**查询时算**（`due_at < now() AND status NOT IN (COMPLETED, CANCELLED)`），首版不建定时任务维护标记 —— 少一个会静默失效的定时任务。
7. **并发控制要分方言。** PG 用 `SELECT ... FOR UPDATE`，SQLite 无行锁。`dialect_helpers` 目前没有行锁封装，需新增；或者用"乐观锁"（`UPDATE ... WHERE id=? AND status=?`，受影响行数=0 即冲突）——后者双模通用，**推荐**。
8. **AP 编号别用 count+1。** 并发下会重号。用 PG sequence 或 `AP-YYYYMMDD-<序列>` + 唯一索引 + 冲突重试。
9. **附件下载必须校验权限。** `feedback.py` 的现状是"内网不做额外鉴权"（其 docstring 明说），但 AP 凭证涉及整改证据，必须按 `ap_permission` 过滤（方案 8.1 这点是对的，别照抄 feedback）。

---

## 5. 建议的首版范围（MVP）

**做：**
- 表 6 张：`ap_user_profile` / `ap_tasks` / `ap_assignees` / `ap_updates` / `ap_reviews` / `ap_history`（附件元数据用 JSON 列，照 `issue_reports.attachments`；通知先用 `ap_notifications` 记录发送结果，不做 outbox 重试队列）
- 接口约 12 个：创建/列表/详情/编辑/下发/确认/进度/附件/提交/审核通过/审核退回/我的统计
- 页面 2 个：**AP 下发与管理**（列表 + 新建/编辑 + 详情抽屉）、**我的 AP**（确认/进度/附件/提交）；审核动作并入详情，不单独开审核中心
- 通知：邮件（有 email 的人）+ 页面内"待我处理"角标
- 逾期：查询时计算 + 列表红色标记

**暂缓（第二期）：**
- 部门下发、Department AP 页、部门绩效
- Analytics 页与 9 个指标
- 多执行人 `ALL_REQUIRED`、模板、多级审核、SLA 升级、独立通知中心
- 独立审核中心页（首版并入详情）

**为什么这么砍：** 用户的原话是"给用户下发 AP，用户收到后可以更新完成情况"。这条主链路只需 6 张表、2 个页面；部门与统计是"管理增强"，但它们依赖缺失的组织主数据（缺口 A），强行做会变成假数据看板。

---

## 6. 分期（对齐方案第 13 节，按现实调整）

| 期 | 内容 | 交付 |
|---|---|---|
| P1 | `ap_user_profile` + 身份预填链路 + `ap_tasks/ap_assignees` + 创建/列表/详情/下发 | 能建单、能派给具体人、对方能看到 |
| P2 | 确认 / 进度 / 附件 / 提交 / 审核通过·退回 / `ap_history` | 完整闭环 |
| P3 | 邮件通知 + 到期提醒任务（登记 `TASK_SPECS` + 分组） | 邮件推动流转 |
| P4 | 部门维度（待组织数据到位）+ Analytics + 模板 | 管理视角 |

**验收：** 方案第 14 节 AT-01 ~ AT-16 全部保留，但 AT-03（部门下发）、AT-16（ALL_REQUIRED）随范围后移。**AT-11（执行人直接调接口改 Completed 必须被拒）和 AT-12（越权访问）必须做**，这是整个模块的信任基础。

---

## 7. 待决策

1. **部门维度首版做不做？** 做 → 需要业务方给一份组织架构清单（或确认用 FLM 的 Base location 当准部门）；不做 → 只开个人下发，表结构预留。
2. **通知渠道：** 只有邮件够吗？现场人员不一定看邮箱，项目已有 WhatsApp 推送通道（`whatsapp_outbox` / `tt_alert_whatsapp`），要不要一并接？
3. **谁能下发 AP？** 首版建议收敛为 `role=admin` 或 `ap_role=AP_MANAGER` 白名单，避免"人人可派活"。

---

## 8. 实施结果（2026-10-30，首版已上线）

吉祥在评审后定了三件事，首版按此落地：

| 待决策项 | 决定 | 实现 |
|---|---|---|
| 组织架构 | **参考 Escalation Matrix** | `org.py::ORG_SEED`（4 级 / 21 人）→ `ap_org_people`，首次访问种入 |
| 通知渠道 | **邮件 + WhatsApp 群**，群名可自定义，先用 `lbr_assistant` 测试 | `notify.py`：邮件（多收件人）+ Baileys 文本通道（3 秒合并窗口批量投递） |
| 谁能创建 AP | **admin 或 AP_MANAGER 白名单** | `permissions.effective_role()`；`ap_user_profile.ap_role` |

**与评审建议的差异**：原建议"首版砍掉部门维度"仍成立 —— Escalation Matrix 提供的是
**岗位 + 汇报链**，不是部门，所以首版做的是"按岗位/按人下发 + 逐级上报关系"，
Department AP / 部门绩效依旧后置。

**交付物**

| 文件 | 作用 |
|---|---|
| `backend/services/ap_manager/store.py` | 6 张表（惰性建表，双模）、状态机常量、AP 编号、时间归一 |
| `backend/services/ap_manager/org.py` | Escalation Matrix 种子 + 四级身份匹配 |
| `backend/services/ap_manager/permissions.py` | 权限唯一判定（含"账号/姓名/显示名"三套别名） |
| `backend/services/ap_manager/notify.py` | 邮件 + WhatsApp 群（批量合并，失败不影响业务） |
| `backend/routers/ap.py` | 14 个端点，状态转换全部后端校验 + 乐观锁 |
| `frontend/src/pages/ApCenter.tsx` | 三页签工作台 + 详情抽屉 + 新建弹窗 |
| `docs/manual/11-feature-guide.md` §39 | 实现细节与踩坑记录 |

**验证**：`TMP/t_ap_flow.py` 覆盖方案第 14 节 AT-01~AT-16（含 AT-11 执行人不能自关、
AT-12 越权、AT-14 重复提交、AT-15 逾期不改状态），全部通过；`TMP/t_ap_page.py`
用 Playwright 验证页面渲染、详情抽屉、新建弹窗，无 i18n 漏键、无 JS 报错。

**上线时踩到并修掉的两个 PG-only 问题**（sqlite 测不出来）：
1. `COALESCE(due_at, '9999')` 在 PG 的 TIMESTAMP 列上直接抛 `InvalidDatetimeFormat`
   → 兜底值改 `'9999-12-31 00:00:00'`。
2. PG 读出的时间列是 `datetime`（序列化成带 `T` 的 ISO 串），与字符串比较混用会让
   逾期判定在"同一天"出错 → 统一过 `store.normalize_ts()` 输出 `YYYY-MM-DD HH:MM:SS`。
