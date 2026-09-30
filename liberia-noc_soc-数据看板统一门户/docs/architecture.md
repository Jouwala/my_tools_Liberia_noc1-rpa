# 05 architecture.md —— 架构和数据流

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总纲：`D:\01_RPA\architecture.md`（全域拓扑与 my_app 内部架构见那里，本文不重复）

## 一、运行时拓扑

```
                      nginx  192.168.100.19:80
                             │
        ┌────────────────────┼────────────────────┐
        │ /myapp/            │ /api/              │ /uniplam/
        ▼                    ▼                    ▼
  my_app 前端          my_app 后端           本门户
  vite :7090           uvicorn :7038          :9267
  base=/myapp/         (FastAPI)              前端 + 门户后端 API
        │                                          │
        └──────── 看板页面 URL = 主机 + rel ────────┘
```

**开发端口 9267**（`npm run dev`）。7038 / 7090 已被 my_app 占用，**不可复用**。

## 二、`/uniplam` 前缀为什么是必须的

这是本项目最容易踩的架构坑，原文在 `src\config.ts` 顶部注释：

```
门户页面挂在 nginx 的 /uniplam/ 子路径下。
前端若请求绝对路径 /api/auth/login，会命中 nginx 的通用 location /api/
  → 打到 my_app 后端 7038
  → 7038 上 GET /api/auth/login 是 SPA 兜底静态页（仅允许 GET）
  → POST 被回成 405 Method Not Allowed
  → 这正是"其他电脑（走 80 端口 nginx）登录失败"的原因
```

修复方式：门户所有 API 请求带应用 base 前缀，即 `/uniplam/api/...`，天然落在 `location /uniplam/`（→ 9267 门户自身服务）里，与 my_app 的 `/api/` 彻底不冲突。

**代码里用 `PORTAL_API` 常量**（`src\config.ts` 导出）：

```ts
export const PORTAL_API = `${(import.meta.env.BASE_URL || '/').replace(/\/+$/, '')}/api`;
```

本地直连 `http://localhost:9267/uniplam/` 同样走这个前缀，行为一致。

## 三、配置优先级与"主机 + rel"模型

### 优先级

```
localStorage 覆盖  >  VITE_* 环境变量  >  src\config.ts 硬编码兜底
```

`src\config.ts` 是**单一真相源**。`EnvConfig` 三个字段：

| 字段 | 含义 |
| --- | --- |
| `finebiHost` | FineBI 决策平台主机 |
| `myappHost` | my_app 主机 |
| `myappApiBase` | my_app API 基址；留空=同源（`/api/...`），跨域时填完整基址 |

### 看板 URL 的组装

```
看板条目只存相对路径 rel  ──►  运行时 = 主机 + rel  ──►  完整 URL
```

这样做的收益：

- 换 IP/域名时**只改主机一处**（或界面上「环境配置」一键切换），全站生效；
- **已持久化到 localStorage 的旧数据也能自动跟随**——因为存的是 `rel` 不是绝对 URL。

这是本项目最重要的设计决策之一，改数据模型时不要退化成存绝对 URL。

## 四、数据流

### 流 1：加载看板目录

```
浏览器 → /uniplam/ → 门户前端 :9267
  ① 读内置初始数据 src\data\initialDashboards.ts
  ② 读门户后端 GET /uniplam/api/portal-default
  ③ 读 localStorage（键 liberia_noc_dashboards_v3）——【优先级最高】
  → 合并后渲染；每张卡 URL = 主机 + rel
```

> **本地优先**是有意为之（用户可自定义并导出），代价是改代码里的初值后用户看不到——需「恢复初始默认看板」或清缓存。

### 流 2：实时任务调度部件

```
TaskSyncWidget ──每 60s──► GET /uniplam/api/tasks
    → （同源部署）nginx → my_app :7038 /api/tasks
    → 成功：渲染任务列表（含 recent_runs 最近运行、耗时、成功与否）
    → 失败：降级为内置静态快照，【不白屏】
```

部件接口模型（`TaskSyncWidget.tsx`）：入参 `ApiTask`（`task_id`/`name_zh`/`name_en`/`category`/`current_cron`/`enabled`/`running`/`recent_runs`），内部归一为 `TaskItem`（`id`/`name`/`category`/`cron`/`enabled`/`running`/`lastSuccess`/`lastElapsed`）。

### 流 3：QC 指标与下钻

```
QC 卡片 ──► 门户后端 /uniplam/api/portal-qc/*
    │
    └─ 点击下钻 → GET /uniplam/api/portal-qc/detail
                     ?metric=<id>&page=<n>&size=50[&q=<搜索>]
                  → { total, rows, columns }
```

**两档刷新节奏**（用**墙上时钟**对齐，不是 interval 累加）：

| 档 | 网格 | 偏移 | 对应后端 |
| --- | --- | --- | --- |
| 全量 | 60 分钟 | +390 秒 | 每小时 `:06:30`，紧跟 `eflow_sync` 跑完 |
| 告警 | 5 分钟 | +30 秒 | `:00:30` / `:05:30` …，紧跟 `eflow_active_alarm` 每 5 分钟的同步 |

**为什么不用 interval 累加**：interval 从进页面那一刻起算，进页面时若是 `:07`，`:06` 已同步好的数据要再等 59 分钟才上屏。网格以「本地当天 0 点」为原点（而非 epoch），这样 `+05:30` 这类半小时时区也能对齐到本地的 `:06`。

## 五、状态管理

`src\App.tsx` 是**唯一状态中枢**（43KB）——看板数组、分组、鉴权、视图模式、搜索排序、所有弹窗开关、localStorage 持久化都在这里。组件通过 props 接收回调，**没有引入 Redux/Zustand 等状态库**。

新增弹窗必须同时改三处：

1. `App.tsx`：`useState` 开关 + 渲染组件 + 把回调传给 `Navbar`；
2. `Navbar.tsx`：`NavbarProps` 加回调 + 桌面端与移动端两个入口；
3. `i18n.tsx`：`zh` 与 `en` 两份字典加入口文案。

（`DesignGuideModal` 与本项目的 `DocsIndexModal` 都是这个模式，可作模板。）

## 六、请求竞态处理

异步请求用**序号作废**模式，避免过期响应写回界面。以 QC 下钻为例：

```ts
var seq = ++qcDrillSeq;
// ...fetch...
.then(function (data) {
  if (seq !== qcDrillSeq || state.qcDrill.metric !== d.metric) return;  // 过期响应，丢弃
  // ...
});
// 关闭弹窗时：qcDrillSeq++   ← 作废在途请求，避免关掉后又被写回
```

> 看到别的模块也用 `xxxSeq` 变量，是同一套约定。新增异步列表/弹窗时照做。

## 七、构建与部署

- 构建：`npm run build` → `dist/`
- 部署到 nginx 子路径时**必须**在 `vite.config.ts` 设 `base: '/portal/'` 后**重新构建**，否则静态资源 404。
- `vite.config.ts` 还负责把门户后端（`server\`）挂进 dev server。

## 八、鉴权架构

> **2026-09-25 重构**：原单文件 `server\auth.ts`（928 行，越过本项目 500 行红线，
> 混了类型/密码/状态/守卫/路由五类职责）已拆为 `server\auth\` 模块。设计与验收见
> `auth-module-design.md`。**行为零变化**，仅结构改变；同时修掉循环依赖与限流分桶缺陷（见下）。

| 文件 | 职责 |
| --- | --- |
| `server\auth\types.ts` | 类型、常量、纯函数（无 IO、无状态） |
| `server\auth\password.ts` | scrypt 加盐哈希与校验（N=16384,r=8,p=1） |
| `server\auth\store.ts` | `AuthStore`：用户 / 申请 / 会话 / 限流；导出 `getAuthStore` 单例 |
| `server\auth\guard.ts` | **鉴权决策唯一入口** `resolveCaller(req, store)`；含免登录旁路与 `DEV_ADMIN` |
| `server\auth\routes.ts` | HTTP 路由分发 + vite 插件挂载；`clientIp()` 取真实来源 IP |
| `server\auth\index.ts` | 对外出口（保留原 `./server/auth` 导入面） |
| `server\authDb.ts` | 鉴权持久化；**只依赖 `auth/types`**（依赖 `auth/index` 会形成环） |
| `server\authSwitch.ts` | 鉴权总开关 |
| `src\auth\AuthContext.tsx` | 前端鉴权上下文（`apiFetch` 自动注入 Bearer，401 自动回登录态） |
| `src\components\RequireAuth.tsx` | 前端鉴权门组件（新页面接入用） |
| `src\utils\groups.ts` | 分组 |

### 依赖方向（单向，无环）

```
types ← password ← store ← guard ← routes ← index
                     ↑
                  authDb（只取 types）
```

### 新页面接入鉴权（三种形态）

| 形态 | 接入方式 | 成本 |
| --- | --- | --- |
| 门户内新 React 页 | `<RequireAuth>` 包住 + `useAuth()` 取身份 + `apiFetch(PORTAL_API+...)`；照抄 `src\pages\_TemplatePage.tsx` | 低 |
| `MsPortal\` 静态壳 | 已各自实现（登录/`/me` 探针/用户管理）；再新增壳需照抄 `portal.js` 的验签流程 | 中 |
| 远程系统深链 | 已实现：门户 token → `?t=` → 对方回调门户 `/me` 验签 → 签自己的会话（见 `Task\my_app\backend\services\portal_auth.py`） | 低（复用） |

> **服务端才是强制点。** `allowedGroups` / `allowedCards` 目前只在前端
> `App.tsx` 过滤（显示层），服务端不拒答——见 `auth-module-design.md` 第五节 S4。

### 已知缺陷（已登记，未修）

| # | 缺陷 | 影响 |
| --- | --- | --- |
| S1 | 门户 token 经 URL query（`?t=`）传递 | 进入浏览器历史 / Referer / nginx access log；token 有 12h 滑动续期 |
| S2 | 门户会话仅存进程内存 | 门户重启即全员掉线（my_app 侧已用 SQLite 落盘解决） |
| S4 | 看板目录接口未登录可读 | 白名单是显示层规则，非强制边界 |

> **S3（登录限流全站共用 `127.0.0.1` 一个桶，可被单人锁死全站 60 秒）已于 2026-09-25 修复**：
> `server\auth\routes.ts` 的 `clientIp()` 在直连方为本机回环时改读 nginx 下发的
> `X-Real-IP`（`nginx.conf:364`），并保留 socket 地址作为不可信来源的回退，防伪造。

- 鉴权开关状态在 `auth-switch.json`，操作入口 `auth_switch.bat` / `auth_switch.py`，说明见 `D:\01_RPA\AUTH_SWITCH.md`。
- **`auth-data\` 含加盐密码哈希，已在 `.gitignore`，严禁入库。**

## 九、决策记录（事实上的 ADR）

> 本仓库没有独立 ADR 目录，重大决策按工作区总纲原则 8 记在这里，带日期与出处。

### 2026-09-26：`/v1/olbrportal/` 恢复「编辑分组」能力（编辑对象 = 六个入口卡）

**背景。** OLR 门户有两份手写静态壳：`olbrportal/`（原版）与 `v1/olbrportal/`（改版）。
`v1` 早前为了瘦身，删掉了 L1 分组面板 `#views`（依据是"上面六个 `#views6` 入口卡已经覆盖了
CXO/SP/MS/FLM/FO/BO"）。问题在于**编辑入口是挂在这些卡片容器上的**：
`onEditClick` 只委托在 `#views` 与 `#l0` 上，容器一删，两处委托都失去落点
（`$('#views')` 返回 `null`，绑定时会直接抛错），于是作者顺手把编辑也一并关掉 ——
`setEditing()` 里写成 `state.editing = false`（**忽略了自己的 `on` 参数**）、
`syncEditBtn()` 里写成 `b.hidden = true`。结果顶栏按钮点开只剩一条横幅，底下没有可编辑对象。

**决策（含一次返工）。** 第一版按"完整还原"把 `#views` 面板整块搬了回来，
含 `renderViews()`/`viewsShell()` 与一份宽屏分栏 CSS。**这一版被否掉并已删除**：
用户要的不是第二个页签面板，而是**让页面上已有的六张入口卡本身可编辑**，
并明确要求"不要增加 `#views6` 之外的卡片"。删掉 `#views` 也对 —— 六个入口卡已经覆盖了
同样的六个分组，再铺一层页签是同一批内容的第二份入口。

最终做法：**编辑对象 = `#views6` 六列里的行条目**（`renderViews6()` 内），
只读态保持纯链接，编辑态把行升级成 `a.card.is-ed` 并补按钮。
`#views` 面板、`renderViews()`、`viewsShell()`、`#l0` 一律**不恢复**。

**为什么是"挂载"而不是"重写"。** 编辑机制在 `v1` 里几乎逐字节存活：
`putCatalog`/`commit`/`rollback` 共 70 行完全相同；九个 `sub*` 辅助函数与五个卡片函数
除 `OTHER` → `DATA.OTHER` 一个词外完全一致；**`bindEdit()` 整块（拖拽三件套 + 编辑开关 +
Esc + 点外关闭）也一直都在**——它只是选不到对象：`cardOf()` 找的是 `a.card.is-ed`，
而 `#views6` 当时渲染的是裸 `a.v6-row`。所以本次改动量很小：

| 位置 | 改动 |
| --- | --- |
| `renderViews6()` | 编辑态渲染 `a.card.v6-row.is-ed` + `draggable` + `data-gid/data-no`，补 `edBtns()` 与列头工具；只读态分支原样保留 |
| `setEditing()` | 一行还原：`state.editing = !!on && !!state.catalogEditable` |
| `syncEditBtn()` | 一行还原：`b.hidden = !state.catalogEditable` |
| `bind()` | `#views6` 的 click 委托改为「先判 `v6-toggle`，其余交给 `onEditClick`」 |
| `addGroup()` | 不再写 `state.viewTab`（那是 L1 面板的选中态，本页没有面板） |
| `olbr.css` | 新增 `.v6-row.is-ed` 一组（竖排 + 释放 ellipsis）与列头折行；`.v6-list` 下的拖拽落点高亮 |

**三处与 `olbrportal/` 的有意分歧**（每处都写进了代码注释）：

1. **六列是固定名单**（`V6_GROUPS`），不是"目录里所有分组"。新建分组仍会写进共享目录
   （`/olbrportal/` 与 `MsPortal` 看得到），但本页**不会**长出新的一列 ——
   这正是用户"不要增加 `#views6` 之外的卡片"的要求。`grp-add` 按钮因此只出现在最后一列。
2. **本页没有子分组条**，所以 `bindEdit()` 里 `data-drop-sub` 那两支（拖到子分组归类）
   在本页恒不触发（`subOf()` 找不到 `.subv[data-drop-sub]`）；跨列拖拽也**不支持**，
   改归属走卡片的「分组」浮层。行内拖拽只在同列内排序。
3. **列头补了一颗「重置顺序」**（`data-act="rst-order"`）。原版这颗按钮挂在 L1 面板的
   `panelHead` 上，本页没有面板 —— 不补的话一旦拖过顺序就再也回不去默认排序。
   口径与原版一致：写 `order[gid] = []`（显式空数组，不是删键），且只在该列真有自定义顺序时出现。

**验证。** `npm run lint:shells`、`npm run lint`、`npm run check:clean` 全通过；
`TMP\_verify_v1_editgrp2.cjs` 35 项断言全绿（只读态不动 / 编辑态 41 行全部可编辑 /
看板改名 / 改归属 / 拖拽排序 / 重置顺序 / 分组改名并回显到列标题 / 新建分组不多列 / 退出编辑，
每步都做「改 → API 读回 → 复原」，末尾与跑前快照逐字段对账并自动回写）；
`TMP\_probe_v1_editgeom2.cjs` 12 项全绿（92 颗按钮零尺寸 0、被裁剪 0、两颗按钮不重叠、
标题省略仍在、只读态仍是单行 flex）。

**一次值得记录的排查。** 探针曾报"分组改名保存成功，但列标题不变"。
真因不是前端没重绘（`commit()` 里 `renderCatalog()` → `renderViews6()` 一直在跑），
而是**中英文是两个独立字段**（`groups[].zh` / `.en`），而当时页面处于英文模式，
只改了 `zh`，`gName()` 读的却是 `en` —— 页面行为完全正确，是探针只写了一个字段。
教训：分组名/看板名的「改名」验证必须把 `zh` 与 `en` 一起写、一起还原。

**已知遗留（未修，登记在案）**：

- **PUT 是整份替换**，`items`/`subGroups`/`order`/`groups`/`tabLabels` 必须每次都整体回传，
  漏一个键就会被后端 `_normalize_catalog` 抹掉。探针里已把这条列为回归项。
- **无 ETag / 无版本号，后写覆盖先写**。两人同时编辑时后者静默赢，
  前端只有 `state.saving` 挡并发自提交，挡不住跨用户。要真正解决需给目录加版本号与冲突提示。
- **删分组/删子分组/删看板走原生 `confirm()`**，无头验证时必须先桩掉，否则阻塞渲染进程。
- **本页删不了分组。** `delGroup()` 的入口挂在 L1 面板的 `panelHead` 上，本页没有面板，
  所以 `#views6` 只提供「改名 / 新建 / 重置顺序」。要删分组请走 `/olbrportal/` 或 `MsPortal`。
- **跨列拖拽不支持**（见上面分歧 2），改归属要用卡片的「分组」浮层。

### 2026-09-26（续）：`/v1/olbrportal/` 增加「删除看板」与「新增看板」

**背景。** 上一条做完后，`#views6` 的行条目只能改名 / 改归属 / 拖排序 ——
**动不了条目本身**：既不能把某个看板从目录里去掉，也不能往某一列加一张新的。
用户在实测中直接点了这两个需求（"MS View 里面可以删除 NUR dashboard"、
"新增一个 dashboard 到 MS VIEW 卡片"），并确认了语义与新增方式：

| 决定 | 选定口径 |
| --- | --- |
| 删除 | **两颗按钮都要**：「移出本列」（可逆）+「删除看板」（不可逆，二次确认） |
| 新增 | **先选一个现有看板当模板再改**（只填名字与链接，其余字段继承） |

**为什么必须给两颗删除按钮。** 本项目**没有「不属于任何分组」的看板**这种状态 ——
空 `groups` 的条目在页签视图里是看不见的（`delGroup()` 里那段"无家可归"保护讲的就是这个）。
而 `NUR Dashboard`(no=1) 恰好只属于 `["MS View"]` 一个分组，无脑"移出本列"等于把它弄丢。
所以「移出本列」在**只剩一个分组时直接拒绝**，并指路到真正能删它的那颗按钮。

**新增为什么不直接开表单。** 一条看板有 20 个字段，从零填没人愿意填。
改成两步：先选模板（55 条要能搜，`#grpPop` 复用为选模板浮层），再填名字与链接。
模板继承 `icon`/`platform`/`descZh`/`descEn`/`owner`/`dept`/`tags`/`status`/`freq`，
但**链接刻意留空、名字加"副本"后缀** —— 照抄链接会造出一张指向同一页面的重复看板，
这正是最该避免的误操作。

**实现要点（都在代码注释里复述过）**：

| 位置 | 改动 |
| --- | --- |
| `dropItemFromGroup()` | 新增。摘一个分组归属 + `withSubOf(c, gid, '')` 清子分组映射；只剩一组时拒绝 |
| `deleteItem()` | 新增。二次确认（`confirm` 写清看板名 + "所有人可见、无法撤销"）；**顺手把该 no 从所有 `order[gid]` 摘掉**，否则留下悬挂编号 |
| `addItemFromTemplate()` | 新增。`no = max(no)+1`（**不回收旧编号**）；`groups=[本列]`；`clicks=0`；删掉模板的 `subOf`/`boSub`/`qc`/`custom` |
| `edBtns()` | 行尾补 `item-drop` 与 `item-del` 两颗（仅在有 gid 时） |
| `renderViews6()` 列头 | 补 `item-add`（**每列一颗**，与只出现一次的 `grp-add` 不同） |
| `openTplPick()` / `paintTplPick()` / `bindTplPick()` | 新增。选模板两步流 |
| `FORMS.itemadd` | 新增 kind，字段 `itemZh`/`itemEn`/`itemUrl`（**不叫 zh/en**，否则 `submitForm` 分不清该走 `renameItem` 还是新增） |
| `olbr.css` | `.ct--del`（危险色，**必须排在 `.ct:hover` 之后**，同权重后者胜）、`.gp-search`/`.gp-tpl`（**含 `min-width: 0`，见坑 5**）、`.gf-back`/`.gf-note` |

**五个只有踩过才知道的坑**：

1. **`#editBtn` 是开关不是"进入"按钮。** `?edit=1` 深链已经把页面开进编辑态，
   探针里再点一下就把它**关掉**了 —— 后续所有 `[data-act="item-del"]` 查到 0 颗，
   表现成"删除没反应"。产品没问题，是探针点了反向。（`_verify_v1_itemadddel.cjs` 里已注释）
2. **`state.tplPick` 会被 `openForm()` 里的 `closeGrp()` 清掉**，而 `closeGrp()`
   现在同时清 `grpFor` 与 `tplPick`。目标列必须在选模板那一步就存进 **`state.addGid`**，
   到 `submitForm` 再读 `tplPick.gid` 只会拿到 `null`，新看板会**静默落到第一列**。
3. **URL 必须过 `^https?://` 白名单。** 这个 `url` 直接进 `<a href>`，
   而目录是所有门户共用的 —— 放行 `javascript:`/`data:` 等于给自己开一个 XSS 口子。
4. **`order` 里的悬挂编号。** 删掉条目却不摘 `order[gid]` 里的 `no`，
   会留下一个指向不存在看板的编号。
5. **grid/flex 子项必须补 `min-width: 0`。** `.gp-list` 是 grid，
   `.gp-tpl` 作为子项默认 `min-width: auto`，会被**最长模板名的最小内容宽度**撑开 ——
   实测那一行量出 439px 塞在 298px 的列表里横向溢出，而 `width: 100%` 完全管不住。
   更阴的是**浮层自身 `scrollWidth === clientWidth`**，页面上不报任何错，
   只有逐个子项量宽度才看得出来。所以验收探针里专门加了一条 B2 尺寸断言。

**验证。** `TMP\_verify_v1_itemadddel.cjs` **37 项断言全绿**（A1 按钮齐全且只读态没有 /
A2 唯一分组被拒 / A3 多分组移出并复原 / A4 删除真落盘且二次确认写清看板名与不可撤销 /
A5 `order` 悬挂编号被摘 / B1 每列一颗新增 / B2 选模板+搜索过滤 55→2 **+ 模板行不横向溢出** /
B3 预填副本名、链接留空、标注模板来源 / B4 新 no 唯一、只属本列、clicks=0、图标继承、不照抄 `subOf`/`qc` /
B5 `javascript:` 被拒 / B6 换模板带回已填值），
末尾与跑前快照逐字段对账并自动回写。
回归：`_verify_v1_editgrp2.cjs` 36/36、`_probe_v1_editgeom2.cjs` 12/12、`_probe_v1_dragvis.cjs` 9/9。
另实测四档视口（1700/1440/1280/1024）选模板浮层都不横向溢出、不出屏。

**回归中修掉的两处探针陈旧断言**（都不是产品故障，值得记下来）：

- `_probe_v1_editgeom2.cjs` 报 `offscreen: 126` —— 那是**纵向折页**（41 行本来就超出视口），
  有意义的判据是 `clipped === 0`，仍为 0。另实测三档视口（1680/1440/1280）按钮都放得下，
  富余 239–389px，四颗按钮不会挤出列宽。
- `_verify_v1_editgrp2.cjs` 的"入口卡列标题跟着变"失败 —— 真因是**列标题结构变了**：
  做成可点链接后名字落在 `.v6-t-top > span`，不再是 `.v6-t` 的直接文本节点，
  取 `firstChild.nodeValue` 会把 `<small>` 说明连起来
  （"BO View·测Back Office Expert Support"）。改成取那颗 span 后 36/36。
  页面渲染一直是对的。

### 2026-09-26（再续）：`/v1/olbrportal/` 可编辑「看板链接」

**背景。** 上面两轮做完后，条目能改名 / 改归属 / 拖排序 / 增删，**唯独链接改不了** ——
想换一张看板点开去哪个页面，只能手改服务端 `portal_catalog.json`。
用户实测时直接提出：把 `viewer.html?no=13&gid=FLM%20View` 换成打开 `/myapp/?page=v1_ttwo`。

**先澄清一层间接（这正是需求看起来别扭的原因）。** 卡片点下去地址栏显示
`/MsPortal/viewer.html?no=13&gid=FLM%20View`，但那是**查看器**地址，不是看板的真实地址 ——
`vlink()` 在 `olbr.js:273` 把所有卡片的 href 都硬编码成这个形式，**它根本不读 `it.url`**。
真实地址由查看器按 `no` 查共享目录、读 `item.url` 后塞进 iframe：

```
卡片 → /MsPortal/viewer.html?no=13  →  viewer.js 按 no 查目录  →  item.url  →  iframe.src
```

所以「替换看板链接」= **改目录里那条的 `url`**。这一层间接是有意保留的：
查看器还负责鉴权、主题同步（写 `localStorage['myapp-theme']`）与点击计数，绕开它会丢功能。

**决策。** 把 `url` 并入已有的「改名字」表单，按钮文案从「改名字」改为「编辑」——
而不是新加第五颗行内按钮。理由：一个看板的"名字 + 链接"本就属于同一件事，
行内按钮已经从 2 颗长到 4 颗，再长一颗的边际价值低于新增的视觉噪声。

| 位置 | 改动 |
| --- | --- |
| `FORMS.title` | 字段 `['zh','en']` → `['zh','en','itemUrl']` |
| `openForm` 的 `title` 分支 | 预填 `itemUrl: it.url`（**不是空框**——改链接通常只动其中一段，空框容易被整串覆盖掉带 token 的查询串） |
| `submitForm` | `renameItem(id, v.zh, v.en, vi.itemUrl)` |
| `renameItem` | 加 `url` 参数：非空 + `http(s)` 校验，写 `c.url` |
| `isHttpUrl()` | **新抽出的单一判定**，新增与改名共用（原先正则内联在 `addItemFromTemplate` 里，两处复制必然分叉） |
| `edit.title` | 「改名字 / Rename」→「编辑 / Edit」；`edit.titleTip`、`edit.titleOk` 同步改口径 |

**字段名为什么复用 `itemUrl` 而不另起 `url`：** `submitForm` 已经在收集 `vi.itemUrl`，
i18n 的 `edit.f.itemUrl` / `edit.fph.itemUrl` 也已存在 —— 复用省掉一套重复定义，
语义上"这个条目的链接"在新增与编辑两处本就同一件事。

**两个容易搞反的实施细节**：

1. **校验不留后门。** 一律要求非空且 `http(s)`，不写「只有链接变了才校验」那种判断 ——
   实测目录 54 条全部是 `http(s)`，放宽只会让非法值有路可走。
   这层校验是**安全边界**：`url` 会进 iframe 的 `src` 与「新标签打开」的 `<a href>`。
2. **查看器会丢掉主机名。** `viewer.js` 的 `embedSrc()` 是
   `location.origin + u.pathname + (u.search || '')` —— 只保留路径与查询串。
   所以对内嵌的 my_app 卡片，写 `localhost` 还是 `192.168.100.20` 都能打开
   （谁访问用谁的主机）；主机名只在「新标签打开」那颗按钮上才起作用。
   这一点值得写进文档：否则很容易得出"必须写某个固定 IP"的错误结论。
3. **`url` 必须整串原样写回，尤其是 `&t=`。** 目录 54 条里有 21 条的 url 带
   `&t=<门户token>`，那是 myapp 的**免登录凭据**（`api.ts:457` 的 `readPortalToken()`：
   `?t=` → 同源 `localStorage['liberia_noc_auth_v1']` → 探测）。
   表单是**整串覆盖** url 的（prefill `it.url` → 提交原样写回），
   所以一旦哪天在预填或提交环节顺手 trim/重建查询串，就会**静默**抹掉一批看板的免登录能力，
   而且页面上完全看不出来。为此在探针里加了 D 组专门盯这条（只改名字 → 链接逐字节不变）。

### 一次"本机测试骗了自己"的教训（鉴权：回环放行 vs 局域网 401）

回答用户「改链接时那串 `t=` 能不能不填」时，我第一版结论是**错的**，值得完整记下。

当时我在**服务器本机**用 `http://localhost/myapp/?page=gis`（去掉 `t=`）跑了一个全新
Chrome profile —— 无 Cookie、无 localStorage，等价于"从没登录过门户的人"。结果是：
页面渲染出真实数据（827 个站点、实时时间戳），**401 响应数 0**。
于是得出结论"token 可以不填"。

**但 `/api/auth/mode` 明明返回 `authEnabled: true` / `mode: "enforced"`** —— 这两件事对不上，
于是继续查，真相是：

| 请求 `/api/auth/me` 的来源 | 结果 |
| --- | --- |
| `127.0.0.1:7038` | `200 {"user":{"username":"local","role":"admin"}}` |
| `localhost` | `200` 同上 |
| `192.168.100.20` | **`401`** |
| `192.168.100.19` | **`401`** |

**后端对回环来源自动信任成 `local` 管理员。** 我在服务器本机上测，等于自己给自己开后门；
真实用户从自己电脑访问门户，来源是局域网，走的是 401 那条路。

改用局域网地址重测（`TMP\_diag_myapp_lan_token.cjs`），两种深链都落到登录门：

- 带 `t=`：`/api/auth/portal-login` → 401，同样 `Sign in required`
- 不带 `t=`：`/api/auth/me` → 401 `未登录：请通过统一门户登录`

**正确结论**：
`t=` 是"没登录过门户的浏览器"**唯一**的免登录入口，**不该建议用户删**；
但**用户也不需要输入它** —— 编辑表单预填的就是当前整串，只改 `page=` 那段即可。
（另外那时目录里现存的 token **已经失效**了，所以带它也是 401；真正让人能用的是
同源 `localStorage` 回落 —— 这一点让"带不带 token 都打得开"在**已登录门户的人**身上同样成立，
正好是这个坑最迷惑人的地方。）

> 教训升格：**凡是要验证"鉴权 / 免登录 / 权限"的行为，绝不能用 `localhost` 或 `127.0.0.1`。**
> 本仓库至少有 myapp 后端与门户目录 API（`is_privileged()` 同样认回环）两处对回环放行。
> 本机验证只会得到一个偏乐观的假结论。先跑 `TMP\_diag_myapp_auth.cjs` 确认来源差异。

**验证。** `TMP\_verify_v1_itemadddel.cjs` 扩到 **50 项断言全绿**，新增的 C / D 两组：
C1 表单三字段 / 链接预填当前值 / `maxlength=512` / 按钮已改叫 Edit；
C2 改链接落盘且**同表单里名字未被改坏**；C3 `javascript:` 被拒；C4 空链接被拒；
**D1–D4 带 token 的链接写入后原样预填、只改名字后逐字节不变**（守住上面第 3 条）。
回归：`_verify_v1_editgrp2.cjs` 36/36、`_probe_v1_editgeom2.cjs` 12/12、`_probe_v1_dragvis.cjs` 9/9。

**一次由共享数据引出的探针整改（这次真正学到的教训）。** 跑验收时探针整片失败，
报 `no=1` 的 `titleZh` 是 `undefined` —— 一查，**NUR Dashboard(no=1) 已被人在页面上真的删掉了**
（证据：`order['MS View']` 从 `[65,71,70,4,1,5,64,68]` 变成 `[65,71,70,4,5,64,68]`，
编号 `1` 被**干净摘除**、没有留悬挂编号，正是 `deleteItem()` 的行为；
同一时段 `order` 还多出一个 `SP View: [53,54,34]`，说明有人在页面上拖过顺序）。
**产品没有任何问题，是探针把 `no=1` 写死当靶子了。**

于是把三处写死的 fixture 全改成动态取：A2 的"只属于一个分组"的靶子、
选模板浮层的模板（连同名字一起读出来再断言预填）、
以及 B4 断言"图标继承模板"时改为先读模板的 icon 再比对，
而不是断言一个写死的 `'dashboard'`（模板一换那条就变成假绿）。
另把"模板行不横向溢出"的尺寸断言**移到搜索过滤之前**——
撑破布局的正是名字最长的那几条，放在过滤后只剩 1 行，等于没测。

> 教训升格：**共享目录上的探针，任何依赖具体编号或具体名称的断言都会过期。**
> 上一轮已经因为写死 `no=11` 记过一次，这轮又因为写死 `no=1` 复发 ——
> 凡是"取一条满足某条件的条目"都要现查（`find` 谓词），并且断言要绑定**读出来的那个值**。


## 九之二、2026-09-30 直接改目录文件「新增一张 MS View 卡」（BP Cells Report）

**背景。** my_app 新增了 BP 报告页（`?page=bp_report`，页面名 **BP Cells Report**），
要求挂进门户 **MS View**。上节讲的是**在页面上**用「选模板 → 填名字/链接」新增；
本次是**直接改目录文件**（脚本方式），因为同一次改动还要同时更新四处真源、
且要写较长的中英文描述（表单里填不进去）。

**四处真源，与 `scripts/migrate_finebi_to_myapp.py` 头部列的前四处一致：**

| # | 文件 | 角色 |
| --- | --- | --- |
| 1 | `Task\my_app\backend\data\portal_catalog.json` | **线上真源**（`GET /api/portal-catalog` 实时读盘） |
| 2 | `MsPortal\assets\data.js` | MsPortal 内置兜底 |
| 3 | `portal-default.json` | uniplam 服务端全局目录 |
| 4 | `src\data\initialDashboards.ts` | uniplam 内置兜底 |

**为什么改 1 就等于改线上、不需要重启门户：** `v1\olbrportal\assets\olbr.js:7` 写明
`GET/PUT /api/portal-catalog → 服务端全局目录（有则覆盖内置，无则用内置）`；
实测该端点与磁盘 `portal_catalog.json` **逐字段一致**（58 条 vs 58 条，无单边差异），
`PUT` 走的是同一份文件的整体替换。所以落盘即生效，刷新即见。

**三条必须遵守的既有约定：**

1. **`no` 取 `max(no)+1`，不回收旧编号** —— 同 `addItemFromTemplate()`（见上节实现要点表）。
   `no` 是卡片锚点与 localStorage 分组归属键，复用会串卡。本次新卡为 **`no=79`**。
2. **url 不带 `&t=` 令牌** —— `migrate_finebi_to_myapp.py:89-90` 的原话：
   「不带 &t= 令牌（viewer.js 用门户 token 换会话 Cookie）」。
   目录里 `no=70/71/76` 那几条带着令牌是历史遗留（令牌会过期，且写进版本库违反
   `AGENTS.md` 四.2 的「绝不写敏感值」）。新条目一律不带。
3. **`order[gid]` 与 `groups` 要同时维护** —— `deleteItem()` 会顺手把该 no 从所有
   `order[gid]` 摘掉（见上节），新增同理要 append，否则卡片有归属却不进分组显示顺序。

**⚠️ 四个文件里 `initialDashboards.ts` 的 schema 与其他三处完全不同，不能照抄字段名。**
它是 `DashboardItem`（`src\types\dashboard.ts:35`）：用
`title` / `description` / `category`（**中文分组规范名**，本次用 `MS 运维管理`，
与 `portal-default.json` 的 `groupLabels` 口径一致，而**不是** `MS View`）/
`iconName` / `updateFrequency` / `department` / `themeColor` / `isFavorite` / `isPinned` /
`clickCount`，没有 `no` / `groups` / `titleZh` / `titleEn` / `icon`。
照抄 catalog 的字段名会直接 `tsc` 报错。

**icon 键两个体系也不通用：** 线上目录用 `olbr-data.js:831` 的 `PH` 表键
（本次 `chart-line`，该键确实在表中；写错会**静默退回方块图标**、不报错），
`initialDashboards.ts` 用 `AVAILABLE_ICONS` 里的组件名（本次 `AlertTriangle`）。

**验证（本次实测）：**
- `GET /api/portal-catalog` 返回 59 条、含 `no=79 BP Cells Report`、`groups=["MS View"]`，
  `order['MS View']` 末尾为 79；
- `MsPortal\assets\data.js` 用 `node` 造 `window` 后 `eval` 解析通过，
  且 `stats` 的 `total/online/beta/myapp/finebi/external/groups` **逐项按实际条目重算后一致**
  （`total` 55→56、`online` 53→54、`myapp` 51→52）——
  该 `stats` 是文件自述，不消费但仍要准；
- `portal-default.json` 用 `JSON.parse` 通过，新条目 `platform=custom` + `rel='/myapp/?page=bp_report'`
  （`rel` 必须一起给：运行时 `resolveUrl()` 优先用 `rel` 拼地址）；
- 门户 `npm run lint`（`tsc --noEmit`）全绿。

**⚠️ 并发写风险（本次真的遇到了）。** 改完几分钟后复查，发现目录里多了一条
`no=80 Speedtest 基准报告`、且 `no=5/64/68` 已从 MS View 移走 —— **有人同时在页面上编辑目录**。
本次因为只做「append 一条 + append 一个 order 编号」而未受影响，磁盘与线上始终逐字段一致
（59 vs 59）。这与上节结尾那条教训同源：

> **共享目录上不存在"我先读一遍、待会儿再整体写回"的安全操作。**
> 能 append 就不要整体重写；非重写不可时，写完必须立刻复查线上与磁盘是否仍然一致
> （本次的复查命令：比对 `GET /api/portal-catalog` 与磁盘文件的 `items` 编号集合，
> 两边都应为空集）。

一次性脚本落在 `Task\my_app\TMP\_add_bp_card.py`（幂等：已存在同 url 则跳过对应文件）。


## 十、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 全域拓扑与 my_app 架构 | `D:\01_RPA\architecture.md` |
| my_app 内部架构 | `Task\my_app\docs\manual\02-architecture.md` |
| 配置项与优先级原文 | `src\config.ts` 顶部注释 |
| 组件 API | `component-api.md` |
| 开发与部署 | `development.md` / `README.md` |
| 鉴权开关 | `D:\01_RPA\AUTH_SWITCH.md` |

> **工具负责整理，人与 AI 负责协作执行。**
