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


## 九之三、2026-09-30 `Network Benchmark View` 一行装两个数据源（3 张 Ookla + 3 张 Meta）

**背景。** `Network Benchmark View` 行是 2026-10-01 加的，当时只有 3 张卡（下载 / 上传 / 时延），
数据来自 `/api/bm-speedtest/overview`（my_app `?page=bm_speedtest` 竞对分析）。
`.qc-grid` 是 `repeat(6, minmax(0,1fr))`，3 张卡只占半行、右侧留空。
用户要求「参考 my_app `?page=bm_meta` 的数据，在同一行再补 3 张卡」，
信息面覆盖 Orange·Speed / MTN·Speed / 综合评分与胜场 / 区间范围(Orange) / 区间范围(MTN) / BP。

**决策一：6 张卡挤一行，而不是另起一行。**
另一行会让「橙色 vs MTN」这个对比语义被拆成上下两段、还要再写一个重复的标题；
补齐到 6 张后，一个 `.qc-grid` 正好排满一行，两组卡同宽同高（实测 1680/1400px 下
6 张卡高度逐张相等 = 168.4px，卡头同一 y、页脚底边同一 y）。

**决策二：按「一个指标一张卡、卡里并排两家」分组，不按「一家一张卡」。**
沿用原 3 张 Ookla 卡的分组逻辑：同一指标的对比必须在同一张卡内完成，
否则用户要在两张卡之间来回看。BP 是**网络侧 KPI、不属于任何一家**
（`bm_meta_caliber` 把 9 个指标分成 `BRAND_METRICS` 与 `NETWORK_METRICS`），
所以它单独一张、卡内没有品牌行、**不挂领先方徽章** —— 塞进任何一边都是口径错误。

**决策三：两组卡共用同一个窗口对象（最近 30 天），但文案与来源标识各写各的。**
- 窗口：`loadKpi` 里 `recentWindow(30)` 只算一次，两路请求**共用返回的同一个对象**。
  各算一次会在跨午夜或先后差一秒时得到差一天的窗口，而它们印在同一个标题底下、
  页脚还各自写着「统计窗口 30 天」——差一天就是两个窗口，读者无法判断哪张卡能跟哪张卡比。
- 文案：**不复用 `kpi.bf.*`**。那套第一句就是「Speedtest by Ookla」，
  套到 Meta 卡上就是假话。新增 `kpi.mm.*`（zh/en 双字典），卡名照抄 my_app 的 `bmm.*`
  （同一件事在两个门户不能有两个名字）。
- 行标题 tooltip 换用新增的 `kpi.bf.subBoth`：`kpi.bf.sub` 只说得清左 3 张，
  挂在整行标题上会让人以为 6 张都是 Ookla 的数。

**⚠️ 两个数据源的数不可直接比。** 一份是 Ookla Speedtest 测试库（`bm_speedtest`），
一份是 Excel 导入的**静态快照**（`meta_data` 表）。实测差异：
- 窗口内 Ookla 有 1,047 次测试，Meta 只有 23 天有数据（`data_max_date=2026-09-23`，
  而窗口取「最近 30 天」到 2026-10-01）—— 所以 Meta 卡的页脚第二格专门写「覆盖 23 天」，
  不写清楚读者会以为大数字覆盖了 30 天；
- 同一窗口下 Meta 的 Orange 速率 14.1 Mbps、MTN 14.3 Mbps（**MTN 略高**），
  而 Ookla 那组下载速率 Orange 93.0 / MTN 72.7 Mbps（**Orange 大幅领先**）。
  两组结论方向相反，正因为样本与测量方式不同 —— 这也是行标题 tooltip 必须点明
  「数字不可直接对比」的原因。

**两个易读错的点，都进了 tooltip（不靠用户自己悟）：**
1. **综合评分是相对分**（更强的一方恒为 100，另一方按比值折算），不是绝对分；
2. **「区间」是逐日值的 min~max**，与大数字（区间均值）不是同一个统计量，两者不必相等。
   另外「领先 x / y 天」的分母是 `paired_days`（两家都有数据的天数），
   两家的 x 相加**可能小于 y**，差额是打平的天数（实测该窗口 `ties=1`、
   两家各领先 11 天、y=22，卡面看着像"两家平分"）—— 平局天数在卡级与行级
   tooltip 里都单独说了一句（my_app 那边是把平局单列一行的，这张卡没有那个位置）。

**实现要点（`v1/olbrportal/assets/`，本次只改 v1 一份）：**
- `olbr-data.js`：新增 `KPI_META` 规格表（`key/kind/name/unit/digits/page`）与 `kpi.mm.*` 双语文案；
  `SPEED_BRANDS` 改名为 `BENCH_BRANDS`（两组卡共用同一对品牌与顺序）；
- `olbr.js`：`state.kpi.meta` 独立存（与 `speed` 分开，任一路失败不擦掉另一组）；
  `loadKpi` 的并行计数 `left` 从 3 改到 **4**（漏改会永远停在骨架屏且不报错）；
  `speedWindow`/`speedDays` 改名 `recentWindow`/`windowDays`（两组共用）；
  新增 `metaCardHtml()`；
- `olbr.css`：新增页脚第三格的两套来源标识样式（见下条）；
- Meta 卡带 `has-foot`：BP 卡只有一行，靠它把页脚沉到卡底，与同排 5 张卡页脚落在同一条基线
  （Ookla 卡内容天然更高，不靠这个类）。

**页脚第三格：按数据源分两种标识（2026-09-30 第二轮，用户要求）。**
用户给了 Meta/Facebook 的参考图，并指出 BP 其实不属于 Meta 报告那组指标。于是：
- **速率 / 综合评分**两张卡 → 放 **Meta 标识**（`META_LOGO`，内联 SVG）；
- **BP** 卡 → 纯文字徽章「**网络侧 KPI**」（`kpi.mm.srcNet`）。
  沿用 my_app 对同一组 7 个指标的既有叫法（`bmm.sec.network`），
  两个门户对同一组指标只有一个名字 —— 用户在 Radio 与「网络侧 KPI」之间选了这个。
  ⚠️ **绝不能用 Ookla 或 Meta 的标识去标一份不属于它们的数据**，那既是对商标的错误使用，
  也会让用户把不同的数当成同一个来源。
- 来源 tooltip 也随之分成两句（`kpi.mm.tipSrc` / `kpi.mm.tipSrcNet`）：
  否则会出现「徽章写网络侧 KPI、悬停说 Meta 报告」的自相矛盾。
- ⚠️ 一个**口径事实**：BP 与速率其实在**同一张 `meta_data` 表、同一个 `/api/bm-meta/overview`**
  接口里（门户只能从这里取到它）。所以「网络侧 KPI」标的是**指标分组/来源系统**
  （Radio 侧 FDD 计数器），不是"门户换了另一个接口取数"—— 这句话写进了 tooltip。

**Meta 标识为什么是内联 SVG、而不是把参考图裁一张 PNG**（与 `OOKLA_LOGO` 完全同一条理由）：
根 `.gitignore` 忽略 `*.png`，新加的图不会被跟踪、换台机器拉下来就丢；
且参考图把浅色底烤进了像素，深色主题下会是一块白斑。
圆标路径取自 **Simple Icons（CC0）的 `facebook.svg`**（24×24 原样内联 + `scale(1.375)`
放大到参考图实测的 33px），路径把 f **挖空**，所以下面垫了一个白圆 ——
不垫的话 f 会露出卡片底色，深色主题下 f 直接变成深色。圆盘用 Meta 品牌蓝 `#0866FF` 固定值
（商标的组成部分，不跟主题走），字标 `Meta` 走 `currentColor`（主题墨色）。
⚠️ 这不是 Meta 官方矢量资产，与 Ookla 那段同一口径：**对外分发/商用前应换成官方 SVG**，
替换 `d` 的值即可，两个文件都不用动。
字号 18.6 是「大写高 = 参考图实测 13」反推的，`textLength=45` 锁成本机实测自然宽，
换字体时只调字距、不拉伸字形，整块外框比例不变。

**顺带改掉的一个窄屏缺陷。** `Meta` 组「综合评分与胜场」的英文名照抄 my_app 的
`bmm.card.scores = "Composite score and wins"`，在 420px 视口下（可用宽 147px）实测 159px，
而 `.bf-hd b` 当时是 `white-space: nowrap` → 只能显示成 `Composite score and …`。
这块 CSS 上面本来就立过口径：「窄屏多占一行高度是可接受的代价，而"卡名显示不全"不是」，
所以把它改成 `white-space: normal`（按需折行，`text-overflow: ellipsis` 随之删掉，
`overflow: hidden` 留作兜底）。实测折出来的那一行落在同排最高的 Ookla 卡
（420px 下 219.5px）之内，**栅格行高不变**，六张卡的顶/底基线仍齐。

**验证（本次实测）：** `npm run lint:shells` / `npm run lint` / `npm run build` 全绿；
Playwright 实测 **7 个视口 × 中英两种语言 = 14 种组合**，均为 6 张卡、
`scrollWidth > clientWidth` 的溢出元素 **0 个**、页面无 `kpi.mm.*` 键名泄漏；
1680/1400px 下 6 张卡高度逐张相等（168.4px）、顶/底基线同一；
两块标识同高（Ookla 106×27.4px、Meta 72×27.5px），深浅两套主题下字标自动切换
（`#172143` ↔ `#ccd9f0`）。标识形状另做了像素级核对：把圆盘转成 ASCII 图与用户给的
参考图逐行比对，f 的「顶部右钩 + 中横杠 + 竖笔贯穿盘底」结构一致，宽度差约 3%
（在 33px 的参考尺寸下属抗锯齿测量噪声）。


## 九之三补、2026-10-01 六张卡的走势图横向对齐（同一行内）

**背景。** 2026-10-01 给这一行六张卡都加了走势图（`benchSpark` / `metaSpark`，
双线 Orange/MTN，BP 单线）之后，用户反馈：
「同一行卡片里面的线图的横坐标没有对齐，左边 3 个对齐了右边的有办法对齐吗」，
追问后澄清为「**右边的 3 个横坐标太偏上了**」。

**排查结论：不是横向错位，是纵向错位。** 这一点值得记下来，因为它推翻了两轮错误假设：
- 先怀疑栅格间距不一致 → 实测六张卡 pitch 完全均匀（247.4px），排除；
- 再怀疑 SVG 盒子或内容盒左右边缘不同 → 实测六张卡的
  `.qc-spark-wrap` 相对卡片内容盒偏移**都是 0**，排除；
- 最终按「线底相对卡顶的偏移」量，才看到真相：左三张 120.2px，
  右三张 **86.7 / 107.5 / 62.5px**，最大差 57.7px。**是图的高度位置不齐。**

**根因有三层，每层都要治，少一层就仍然不齐：**

1. **图没有"沉底"机制。** 卡片是 flex column，页脚靠 `.qc-card.has-foot` 的
   `margin-top: auto` 沉到卡底，**但图没有** —— 它是 `.bf-rows` 之后的流内元素，
   位置由"上面有多少内容"决定。→ 给 `.qc-card--bf .bf-spark-wrap` 也加 `margin-top: auto`。
2. **页脚自己也在抢 auto。** 第一层改完后 Speed 卡出现「图 19.25px + 页脚 19.25px」——
   两个 `auto` 把富余空间**平分**了。`.qc-card.has-foot .qc-ext { margin-top: auto }`
   与 `.qc-card--bf .qc-ext` 同特异性（0,2,0），靠源码顺序定胜负，has-foot 那条在后面
   所以赢了。→ 用 `.qc-card.qc-card--bf.has-foot .qc-ext`（提到 0,3,0）把页脚压回固定 5px，
   富余量**全部交给图上方那一个 auto**。
3. **"图例有无"与"折行"都会改变块高。**
   - BP 是单线卡、没有图例，整块比另外五张矮 14.4px → 在 `metaSpark` 里补一个
     **空的** `.bf-spark-lg` 占位（同时把它的 wrapper 类名从 `qc-spark-wrap` 改成
     `qc-spark-wrap bf-spark-wrap` —— 早先漏了这个类，它压根没参与对齐规则）；
   - 窄断点下**卡头折行**（420px 档「Speed」两行 vs「Latency」一行，差 31.4px）、
     **数据区折行**（`.bf-row` 右列 P50/P90 折行，35.5px×2 vs 18.8px×2）、
     **页脚折行**（`.qc-ext` 在 560px 以下换行，82.5px vs 51.1px）——
     三者都会把图顶偏。→ 分别锁 `min-height`：卡头 42px、数据区 74px、
     页脚 82.5px（都只在 ≤1200px / ≤560px 的断点内生效，宽屏不锁、不浪费留白）。

**验证（实测，探针 `TMP/_probe_bf_vert.cjs`）：**
中英两种语言 × 6 个视口（1600 / 1200 / 900 / 760 / 560 / 430px），
**每一行内部六张卡的「线底相对卡顶偏移」最大差 = 0.0px**；
结构量（`TMP/_probe_bf_css.cjs`）六张卡的「卡头/数据区/图/页脚」四段高度逐项相等。
`npm run lint:shells` / `npm run lint` 退出码 0，三个既有探针
（render / color / spark）全部 PASS。

**⚠️ 留给维护者的两个坑（都已在 CSS 注释里就地写明）：**
- 三个 `min-height`（42 / 74 / 82.5px）是**实测值**，不是公式算的。
  它们依赖 `--fs-sm` / `--fs-2xs` / `.bf-row` 行高 / `.qc-ext` 内边距。
  **改这些字号或内边距后必须回来重测** —— 探针会直接打印每张卡的四段实高，
  照着重填即可（本次实测就吃过一次亏：先按 `calc(字号 × 行高 × 2)` 算出 37.5px，
  而真正折行后的卡头是 42px，锁了个偏小的值等于没锁）。
- 「横坐标对齐」在本行有两层含义，别混淆：
  **纵向**（图在同一水平线）已由上面解决；**横向**（同一天落在同一像素列）
  则取决于各卡的天数是否相同 —— 实测 Ookla 三张各 25 天、Meta 三张各 24 天，
  每张图把各自的天数拉伸铺满整宽，所以**同一天在左右两组里落的位置本来就不同**。
  这是"两个数据源窗口长度不同"的必然结果，不是排版缺陷；
  若要消除，需要统一窗口或改成按真实日期定位的横轴（属功能变更，未做）。


## 九之四、2026-09-30 `/v1/olbrportal/` 样式系统：字号令牌化 + 顶栏 rem 澄清 + 系统主题跟随

**背景。** 用户要求评估 `/v1/olbrportal/` 页面的字体大小与格式、使之统一专业。
评估发现该页的颜色/间距/圆角/阴影早已令牌化（`:root` / `html.dark` 双档），
**唯独字号没有**：全文件散落着 18 个不同 px 值、出现在 160+ 处声明里，
相邻档位只差 0.5px（10/10.5/11/11.5/12/12.5/13/13.5 八档挤在 3.5px 内），
同种语义在不同组件里各写一个值（三张表格的表头分别是 11 / 12 / 12.5px、
正文 12.5 / 13 / 13.5px）。这正是「看起来不够统一」的首要根因。

**决策一：把字号提升为令牌，18 档收成 7 档。**（`v1/olbrportal/assets/olbr.css`）
在 `:root` 新增 `--fs-2xs/xs/sm/md/lg/xl/num`（10/11.5/12.5/14/16/18/24px）、
行高 `--lh-solid/tight/base`、字距 `--ls-tight/base/wide`，全量替换散落像素。
归并口径（原值 → 新档）：
`9.5/10/10.5→--fs-2xs`、`11/11.5→--fs-xs`、`12/12.5/13→--fs-sm`、
`13.5/14→--fs-md`、`15/16→--fs-lg`、`17/18→--fs-xl`、`21/24→--fs-num`。
**图标字号故意不进字阶**（跟图标视觉重量、不跟文字层级），另立
`--icon-xs/sm/md/lg`（12/13/15/18px），值与原文件逐一相等，零视觉变化。

**决策二：面板标题拉开层级。** `.p-t` 15→`--fs-lg`(16)、`.esc-t` 14→16、
`.band-k` 保持 `--fs-xl`(18)。L1 面板标题现在真正与正文分档；原先 15px 卡在
14 与 16 之间，既不与正文成档也不与标题成档。冗余字重 800 并为 700
（全页仅 2 处 800，与其余标题的 700 在 16px 下无视觉差异）。

**决策三：六个入口卡「1.5 倍放大」保持不变，字号取整。**
`.v6-grid` 的 `--v6-k: 1.5` **不动**（那是用户 2026-09-25 的明确需求）。
只把字号从 `calc(base × k)` 的非整值（17.25 / 18.75）换成 1.5 倍后的整数
（15 / 17 / 19 / 21），落在干净的 2px 网格上、六卡内部各行基线重新对齐。
差异 ≤0.25px，肉眼不可辨。

**决策四：三张表格口径统一。** v1 的升级机制表（`table.grid`）、用户管理表
（`.um-table`）改为表头 `--fs-xs`(11.5)、正文 `--fs-sm`(12.5)；
下钻弹窗表（`.qc-table`，在**两门户共用**的 `MsPortal/assets/qcDrill.css` 里）
同步改为表头 11.5 / 正文 12.5 —— 于是三表同档，且两个门户的弹窗表格也一致。
⚠️ 改共享文件同时影响 `/MsPortal/`，这是**有意**的（两门户弹窗本就要求逐类一致）。

**决策五：顶栏 rem 的诚实化（仅注释，零行为变化）。**
`v1/olbrportal/assets/masthead.css` 原注释称「portal.js 改 html font-size 会连带
缩放顶栏」—— 经核实该逻辑在 `MsPortal/assets/portal.js:1167`，而 v1 **刻意不
加载 portal.js**，olbr.js 也没有任何根字号逻辑。故 rem 在 v1 等效 px（根字号恒
16px）。已在文件头注明真相与两条出路（要么在 olbr.js 补缩放，要么换回 px），
当前保持 rem 不动。

**决策六：系统主题跟随（`prefers-color-scheme`），v1 与 v2 同步。**
原逻辑：只有 `localStorage['olbr.theme']==='dark'` 才加 `.dark` 类，否则一律浅色 ——
系统是深色的用户首帧会被闪白。新逻辑：
**用户显式选择优先；未选择时跟随系统**。改了三处（v1/v2 各三处）：
- `index.html` 首帧脚本：读不到 `olbr.theme` 时用
  `matchMedia('(prefers-color-scheme: dark)')` 决定是否加 `.dark`；
- `assets/olbr.js`：新增 `detectTheme()` / `hasThemeChoice()`，
  `state.theme` 改用 `detectTheme()`（与首帧脚本同一套规则，首帧正常时读类即可）；
- `assets/olbr.js` 顶栏绑定处：新增 `matchMedia('change')` 监听 ——
  **仅在用户无显式选择时**跟随系统实时切换（已选择则永不覆盖），
  并保留 `addListener` 走 Safari<14 回退、`matchMedia` 缺失时静默跳过。
六种场景（无选择/选深/选浅 × 系统深/浅）已用脚本逐一验证，判定全部正确。

**决策七：死规则清单化（不删除）。** 复核了 olbr.css 里所有标「无命中」的规则，
逐条对 index.html / olbr.js / olbr-data.js 核实：`.qc-lv-*`、`.qc-ico`、
`.qc-card--lg/--sm`、`.stage`/`.vcol`/`.l0-col`/`.view-1`/`.tabs-v`/`.tabv`/
`.subs-v`/`.subv`、旧 `.drawer`/`.dr-*` 在 v1 **确无命中**
（其中 `.subs-v/.subv` 的渲染函数 `subLocatorHtml`/`subManageHtml` 在 v1 已
**定义但无调用**；在 v0 `/olbrportal/` 仍由 `renderViews()` 调用，是活的）。
**判定：保留**——它们不执行、不影响性能，删掉反而破坏与 v0 的类名对照约定；
已在文件头加一段「无命中规则清单」集中登记，取代原先散落各处的警示注释。

**验证。** `npx tsc -p v1/olbrportal/tsconfig.json` 与 v2 同款、`node --check`
（两个 olbr.js + 两段内联脚本）全部通过；CSS 花括号/圆括号平衡、`var(--*)`
无悬空引用；图标令牌 13 处映射值与旧值逐一相等。**未触碰**：`olbr-data.js`（纯数据）、
`server/`。回滚备份名：`olbr.css_bak_20260930_*`、`masthead.css_bak_20260930_*`、
`qcDrill.css_bak_20260930_*`。

**遗留（未做，需单独评审）：** `docs/TODO.md` 里可登记两件 —— ① 若确定两门户
不再需要类名对照，删除上述死规则（属改结构）；② v1 顶栏 rem 是改回 px 还是在
olbr.js 落地字号缩放（当前保持现状）。


## 九之五、2026-09-30 跨壳语言传递：出链统一带 `?lang=`

**现象。** 用户在 `/v1/olbrportal/` 选英文、本页确实是英文，但点进看板（下级页）
有时是中文，且「网内其他电脑」更常出现。

**根因。** 语言选择有**四套互不相通的 localStorage 键**，每一层各自为政：

| 层 | 存的键 | 键缺失时的兜底 |
| --- | --- | --- |
| `/v1/olbrportal/`、`/olbrportal/` | `olbr.lang`（`v1/olbrportal/assets/olbr.js:109`，写在 `:5658`） | 浏览器语言 |
| `/MsPortal/` 首页 | `msportal.lang.v1`（`MsPortal/assets/portal.js:22`） | 浏览器语言 |
| `/MsPortal/viewer.html`（卡片落点，由 `vlink()` 生成） | 正文只认 `msportal.lang.v1`（改前 `viewer.js:38-47`） | 浏览器语言 |
| `/myapp/`（地图栏、报告文件、KPI 卡） | `app-locale`（`Task/my_app/frontend/src/i18n.tsx:7159`） | 浏览器语言 |

出链从来不带语言（改前全仓库 `olbr.js` 搜 `lang=` 零命中），所以下一层只能退到
`navigator.language`：中文 Windows 返回 `zh-CN` → 下级页画中文，英文系统的机器就正常，
这正是「有时候」和「别的电脑更多」的来源。叠加一条：只要那台机器在 `/MsPortal/`
里点过一次语言，`msportal.lang.v1` 就**永久压住**门户的 `olbr.lang`，而查看器本身
没有语言按钮（按钮只在 `MsPortal/index.html:187-188`），用户在查看器里改不回来。
另有一处自相矛盾：`MsPortal/viewer.html` 的首帧脚本认 `olbr.lang` 兜底、`viewer.js` 不认，
同一页 `<html lang>` 与正文语言不同 —— 违反该文件自己写的「两处必须同口径」。

**对照事实：主题当年是做对的。** 门户给 my_app 的 iframe 带 `&theme=dark`
（`v1/olbrportal/assets/olbr.js:2202`），并在设 src 前写同一个键 `myapp-theme`
（`:3678`），my_app 与门户共用该键（`Task/my_app/frontend/src/theme.ts:231` 注释明确）。
语言这一维度缺的就是同一套动作。

**决策。** 沿用主题那条路：**导航时把来源语言显式交给下一层**，而不是让下一层去猜
多个键谁优先。判定链统一为

```
?lang=  >  本站点键  >  olbr.lang  >  浏览器语言
```

`?lang=` 命中就顺手写回本站点键（口径同 `MsPortal/assets/portal.js:7085 applyDeepLink`），
书签与下次直接访问也跟着这次选择走，用户仍可在子站内自己改回来。

**落点。** 出链侧新增 `langVal()/langQs()` 两个小函数，覆盖 `/myapp/`（KPI 卡、
`qcOpenBoard` 下钻、地图 `mapItems().src`、报告文件 `emailSrc()`）与
`/MsPortal/`（`vlink()`、分组 `.p-x`、管理门户入口）：
`v1/olbrportal/assets/olbr.js`（9 处）、`v2/olbrportal/assets/olbr.js`（6 处）、
`olbrportal/assets/olbr.js`（6 处）、`MsPortal/assets/portal.js`（4 处，它自己也是
`/myapp/` 的上游）。接收侧 4 处判定同改：`MsPortal/assets/viewer.js`、
`MsPortal/viewer.html` 首帧、`MsPortal/assets/portal.js` 的 `detectLang`、
`MsPortal/index.html` 首帧，外加 `Task/my_app/frontend/src/i18n.tsx` 的 `detectLocale`。
内嵌 iframe 的重建判据一并加上语言（`dataset.lang`），否则切语言时 iframe 会停在旧语言 ——
`emailSrc()` 原来只比 `dataset.theme` 就是同一个道理。

> ⚠️ 2026-10-01 追记：上面 `v2/olbrportal/assets/olbr.js` 的 6 处**已不在磁盘上**。
> v2 那份是 09-28 复制出来的并行副本，实测自 09-30 起停更（它的未提交改动与
> `/olbrportal/` 的逐行相同，是 v1 改动的回填复制，无独有内容），已整目录移入
> `_quarantine_20261001_v2_olbrportal\`。本条保留原样不改写，是因为它记的是
> **09-30 当时实际改过哪些文件**这一历史事实；只是其中的 v2 路径已失效，
> 后来者不要按它去找文件。现存两份壳（`v1/olbrportal/`、`olbrportal/`）口径不变。

**验证。** `npm run lint:shells`（v1/v2 两份 tsconfig）通过；my_app 前端
`npx tsc --noEmit` 通过；5 个被改 JS 全部 `node --check` 通过。真机（`192.168.100.20`）
在**故意留下脏键** `msportal.lang.v1='zh'` 的情况下从门户点进
`/MsPortal/viewer.html?no=52&gid=CXO View&lang=en`：正文 0 个中日韩字符、
标题 `CXO View · MS Portal`、`msportal.lang.v1` 被纠正为 `en`。地图 iframe 的 src
实测为 `/myapp/?page=gis&mwembed=1&lang=en`。

**⚠️ 尚未生效的一半。** `/myapp/` 由 `Task\_fe_dist\` 的**构建产物**提供
（`vite.config.ts:51` 的 `outDir`），`i18n.tsx` 的改动要 `cd Task\my_app\frontend ; npm run build`
才上线；在那之前门户里嵌入的地图/报告文件块仍按浏览器语言走。**未提交**本次改动。

**回滚。** 全部是纯文本改动，`git checkout -- <文件>` 即可；这些文件本次改动前工作区是干净的。


## 九之六、2026-10-01 `/v1/olbrportal/` 样式复查整改（第二轮）

**背景。** 九之四落地后，收到一份基于「JS 提取全页计算样式」的复查报告。
按惯例**逐条核验**后方才动手 —— 该报告整体质量高（主动纠正了自己上一版的
一条误判：表格 `td` 并非 700，只有级别格 `.lv` 加粗，已复核属实），
但仍有 3 条经不起核验，故**未照单全改**。记录如下，供后人参考「怎么核」。

**核验不成立、故不改的 3 条：**
1. 「顶栏等宽字体栈两套→一套」被列入"已修复"，但顶栏 `rem` 字号仍是**独立字阶**
   （标题 22px / 角色 10.4px）—— 这是**特性**（masthead.css 是 MsPortal 顶栏的
   同步副本，需两边一起改），不是缺陷，保持原样。
2. 「单位文字已统一 11px/400」**不成立**：实测 `.qc-unit`/`.qc-val em` 是
   **11.5px/600**、`.qc-ttl i`/`.bf-hd i` 是 **11px/400** —— 并未统一。
   （该报告"已修复"表与"剩余问题"表**自相矛盾**：前者说单位已统一，后者说
   11/11.5 混用。核验以代码为准。）
3. 「数字小数位已规范化」**不是本轮修复**：`digits` spec（速率1/评分1/BP2/延迟0）
   一直在 `olbr-data.js` 数据层，与样式改动无关。

**本轮实际落地（用户拍板，仅核验成立项）：**
- **小字归并**：`--fs-2xs` 由 11px 提到 **11.5px**，与 `--fs-xs` **同值**
  （此前 11 / 11.5 并存，只差 0.5px 人眼难辨，且造成"同一张 KPI 卡里
  `.qc-asof` 11px、`.qc-sub` 11.5px"的不一致）。取 11.5 而非 11 是因其对中文更友好。
  **保留两个令牌名**（同值）是刻意的：语义上仍是两类、将来可各调，且避免改 21 处引用。
  ⚠️ `.v6-grid` 作用域内的 `--fs-2xs:15px` 是独立定义，**不受**本次影响。
- **标题行高统一**：`.p-t` / `.esc-t` / `.v6-t` 补上 `line-height: var(--lh-tight)`。
  此前它们不写、继承 body 的 `--lh-base`(1.5)，而分区标题 `.band-k` 是 1.25 ——
  同类标题两种口径。现在全页标题行高只有一个真相源。（复查建议"统一为 1.3"，
  但那是个新数；用既有令牌 `--lh-tight`(1.25) 更符合"单一真相源"原则。）
- 另于同日早先已按同一份复查落地（见上一轮改动）：`.v6-t` 21→16px（纠层级倒挂）、
  `.aux-h` 12.5→14px（纠层级倒挂）、`.band-k` 行高 1.0→1.25、
  masthead 等宽栈补 `"Cascadia Mono"`、KPI 卡名加 `title` 属性
  （英文长名截断时的悬停兜底）。

**未采纳的复查建议及理由：**
- 「把英文第三卡名 `Valid Throughput of Video Download` 缩短为 `Video Download Throughput`」
  —— 数据层多处强调"同一内容在两个门户不该有两名"，`en` 名很可能与 my_app 页面一致，
  缩短会造成两门户同名卡叫法不一；且悬停 `title` 已兜底，**保持原名**。
- 「统一卡片 padding（10 vs 9）」—— 富卡/页脚卡的 `padding-bottom:9px` 是
  **跨行页脚对齐**（代码注释：'两排页脚要在同一条线上'），拉平会**破坏**该对齐。

**验证。** `olbr.css` 花括号/圆括号平衡；`node --check olbr.js`、
`tsc -p v1/olbrportal` 通过。回滚备份：`v1/olbrportal/assets/olbr.css_bak_20261001_082749_小字归并前`。

**同日追加复查（第三轮，独立取证）。** 直接重扫全文件裸字号，发现并修掉两处**新隐患**：
- **`.v6-t`（六视图卡标题）是字面 `16px`、未走令牌** —— 这是上一轮"纠倒挂"时留下的。
  与 `--fs-lg` 恰好同值，但绕过令牌；将来调 `--fs-lg` 它不跟随，会**制造新的分叉**
  （正是本轮要消灭的那类问题）。已改为 `var(--fs-lg)`，视觉零变化。
  （它取的是 `:root` 的 16px —— `.v6-grid` 只覆盖 `2xs/xs/sm/md` 四个，
   不覆盖 `lg`，所以"卡标题不随六卡 1.5 倍放大"的意图仍成立。）
- **`.sub-x`（子分组删除按钮 × 号）用 `font-size:11px` 而非 `--icon-*`** ——
  属上轮图标令牌化的漏网。但它是**死规则**（`.subv/.subs-v` 在 v1 无调用），
  且 `--icon-*` 无 11px 档、硬套 12px 会让 × 变大 —— 故**只加注释、不改值**。

复查后全文件剩余 13 处裸字号，**全部有据可查**：4 处死类
（`.qc-ico`/`.ic-ico`/`.ic-go`/`.c-ico`）、4 处有意特例（`.qc-num` 36、
`.qc-card--lg/sm` 26/21、`.bf-val` 15、`.v6-sub` 10）、3 处单点图标
（`.q > i` 16、`.tab i` 14、`.sub-x` 11），均在代码内注明理由。
`--ls-base`(0) 引用 0 次属正常（0 是默认值，无需显式引用）。

**同步到 `DESIGN.md`**：其"手写静态壳的字号体系"节更新为当前真实值
（`--fs-2xs` 10→**11.5px** 与 `--fs-xs` 同值），并补上**行高令牌表**
（`--lh-solid/tight/base`）、**字距令牌**、**层级方向不可倒挂**、
以及 `.v6-t` 不随六卡放大、顶栏独立字阶等口径。


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
