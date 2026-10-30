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


## 九之七、2026-10-02 GIS Map 栏默认取景：第三次反转，改回「打开就大一号」

**背景。** 用户要求：「`/v1/olbrportal/` 的 GIS Map 两个地图能打开后要默认显示比当前
大一号的，类似鼠标点击了一下 + 号」。这一栏（`gis` + `mwRealTime` 两个页签）
的默认取景档位此前已经**反转过两次**，本次是第三次。

**需求演化（同一栏、同一位用户，三次取舍全部记录在案）：**

| 日期 | 需求原话 | 结果 |
| --- | --- | --- |
| 2026-09-22 | 「跟手动点一次加号一个效果」 | 在内层页全国取景基础上**再放大一级** |
| 2026-09-25 | 「打开不能是点一下减号的效果，并且要保持利比里亚居中」 | 回到内层页自己的全国 `fitBounds`（**不加一级**） |
| 2026-10-02 | 「两个地图能打开后要默认显示比当前大一号的，类似鼠标点击了一下 + 号」 | **改回放大一级**（本次） |
| 2026-10-02（同日复述） | 「实际上只要能做到居中，放大一级（zoom 8）是正好，7 的话有点小了」 | 确认 zoom 8 为**目标档位**；裁边可接受，**居中**才是判据 |

**改动。落点只有一个布尔** —— `v1\olbrportal\assets\olbr.js` 的
`MAP_DEFAULT_ZOOM_IN`：`false` → `true`。两条放大路径的代码一直都原样保留着，
所以本次**没有新增实现**，只是把开关拨回来。其余改动全是注释（把上面这段历史、
以及下面这条实测结论写进代码，免得第四次再来一遍）。

**两条放大路径各管一页，互不重叠**（这一点在 2026-09-29 的注释里写错过，已更正）：

| 页签 | 内层实现 | 有无 `fitAllSites` | 由谁放大 |
| --- | --- | --- | --- |
| `gis` | React 页（`GISMap.tsx`） | 无 | `zoomOnce`（挂载后延迟 1.8s） |
| `mwRealTime` | 静态页 `mw_real_time.html` | **有** | `refitLeaflet`（每次 `fitAllSites` 之后 +1） |

2026-09-29 那版注释写着「改 true 会让两级放大叠在已经正确的 zoom 7 上、直接裁边」，
判断依据是**当时的实现**（那时 `mwRealTime` 的 `zoomOnce` 会因暴露 `fitAllSites` 而早退，
只有 `refitLeaflet` 一条路）。现在 `zoomOnce` 对这类页早退的守卫仍在，
所以每页只放大**一次**，不存在叠加。

**⚠️ 曾以为的取舍，经用户 2026-10-02 复述后已澄清：zoom 8 只要居中就是「正好」，zoom 7 反而偏小。**

国土跨度 4.85°纬 × 4.40°经（`LB_BOUNDS`），而中列画布约 767×856：

| 档位 | 可视范围（实测） | 含入国土 |
| --- | --- | --- |
| zoom 7 | 约 9.66°纬 × 8.87°经 | 完整含入，但**四周留白过多、显得小** |
| zoom 8 | 约 4.83°纬 × 4.43°经 | 纬向 4.83° < 4.85°，只裁掉**极窄一条**南北边缘 |

2026-09-25 那次选的是「完整居中」，2026-10-02 用户明确：**「只要能做到居中，
放大一级（zoom 8）是正好，7 的话有点小了」** —— 即用户接受那点裁边，
认为 zoom 8 才是正确的观感。所以**裁边本身不是问题，居中才是判据**。

**居中实测（`TMP\_probe_v1_centered.cjs`，4 条断言全绿）：**

| 页签 | 量法 | 结果 |
| --- | --- | --- |
| `mwRealTime` | `window.__geoNodes`（649 个站点真实经纬）的包围盒中心 vs 国土中心 | 偏差 **1.6% 纬 / 0.2% 经** —— 几乎正中 |
| `gis` | 站点像素包围盒中心 vs 容器中心（该页无经纬入口） | 偏差 **9.8% 横 / 1.9% 纵** |

结论：**zoom 8 已经是居中的**，无需额外改取景逻辑。
**将来不要单凭"裁边了"就把开关改回 `false`** —— 用户已明确 zoom 7 偏小。
要改，先问清是哪一侧的需求变了。

> ⚠️ 该探针第一版曾把 `window.__geoNodes` 当数组用（`nodes.filter(...)`），
> 而它实际是**以站点 id 为键的对象**（无 `.length`），于是静默算出"中心 = 0,0"、
> 偏差 130%/215% 的假失败。现已两种形状都兼容，并用显式 `isFinite` 兜底
> （原先 `+x.toFixed()` 会把 NaN 静默变成 `null`，"全是 null 的坏数据"看着像正常返回）。

**实测验收（`TMP\_verify_v1_defaultzoom.cjs`，7 条断言全绿）：**

- `mwRealTime`：**不做任何操作**打开后，栅格瓦片级别 = **8**（内层全国档 7 +1，
  网络层证据）；再点一次 `-` 回到 7 → 证明 `refitLeaflet` 的重复 `apply` **不累加**
  （因为 `fitAllSites()` 内部是 `fitBounds(全国, animate:false)`，每轮都把 zoom
  重新压回 7，所以每轮「fit → +1」都收敛到同一个 8）。
- `gis`：打开态站点要素像素跨度 **752px**，「缩小一级」后 **376px**，比值 **2.00**
  —— 恰好一级；静置 12s 跨度不变 → 不会继续放大。
- 两页的 `.leaflet-control-zoom-in` 都在，所以走的是**内层页自己的 + 行为链**
  （maxZoom 与它自己的 `zoomend` 都由它管），不依赖任何地图实例挂载点。
- 截图留档：`TMP\_shot_defaultzoom_gis.png`、`TMP\_shot_defaultzoom_mwRealTime.png`。

**踩坑记录（写进探针，免得下次重踩）：** `gis` 页是**两段式加载** ——
1.1~3.1s 只有 104 个要素（跨度 376），4.0s 才补齐到 948 个（跨度 752）。
验收探针若只判「要素数 > 100」就返回，会把**过渡帧当最终态**，表现为
「immediate=376 / settled=752」的 B4 假失败（看上去像"还在继续放大"）。
⚠️ 而只要求「连续两次读数一致」**仍不够**：第一段本身能稳约 2s，探针循环间隔 1.5s，
两次采样可能都落在第一段里 —— 同一份探针会**时而全绿、时而 B4 假失败**（已复现）。
最终门控为「**连续 3 次**（≈4.5s）一致才算落定」，改后连续 3 轮复跑全绿。

**为什么不在 my_app 侧改默认 zoom：** `/myapp/` 是两个门户（`MsPortal` 与 `v1/olbrportal`）
共用的预编译产物，改它的默认取景等于把展示版的偏好推给 MsPortal，
还要连带重新发布一批与本次无关的源码。故仍在门户侧用「点内层页的 + 控件」实现。
**MsPortal 侧的 `MAP_DEFAULT_ZOOM_IN`（`MsPortal\assets\portal.js`）本次刻意未动** ——
用户只提了 `/v1/olbrportal/`。若哪天要求两边一致，那是**另一处独立改动**，
改完需各自实测（两边的放大实现不同：MsPortal 用注入 `<script>` 到内层作用域读 `leafMap`）。


## 九之八、2026-10-15 地图浮层「背景异常」：`MAP_STRIP_CSS` 白名单漏登记新浮层

**报障原话。**「MAINTENANCE ALERTS 图例，在 `https://localhost/myapp/?page=gis` 页面正常，
但是在 `https://localhost/v1/olbrportal/` 页面背景说明都异常，不匹配」。

**根因。** `v1\olbrportal\assets\olbr-data.js` 的 `MAP_STRIP_CSS` 里有一条
「地图卡片内与地图同级的小块贴底浮层」规则，用一个 `:not(...)` **白名单**把
地图自己的绝对定位浮层排除在外。2026-10-14 GIS 页新增
`.gis-rank-overlay`（区域排名条，右上角）时，**只登记了老的 `.gis-legend-overlay`**，
排名条没进白名单，于是被这条规则整套 `!important` 接管，三处同时被改坏：

| 属性 | 它自己（index.css） | 被注入规则覆盖成 | 后果 |
| --- | --- | --- | --- |
| `background` | `rgba(255,255,255,.78)`（浅）/ `rgba(10,20,40,.55)`（深） | `rgba(255,255,255,.88)` | **永远白底** —— 就是用户看到的"背景异常" |
| `z-index` | `1000` | `900` | 掉到 Leaflet 控件之下 |
| 定位 | `top:10px; right:196px` | `left:0;right:0;bottom:0` | 从「右上角小面板」拉成**左侧通高一条** `[0,10,189,842]`，盖住地图左缘 |

**修法。** 给白名单补上 `:not(.gis-rank-overlay)`（`olbr-data.js:1283`），
并在该处注释里写明「**这条排除表是白名单，GIS 页每新增一个地图同级浮层都必须登记**」。
孪生规则在 `MsPortal\assets\portal.js:3705`，同样只排除了图例 —— **本次未改**（用户只报了 v1 侧），
但已在两处注释里互相指认，将来要同步时不必再找。

**⚠️ 这类 bug 的识别特征（下次直接按这个查）：**
**直开永远正常，只有经门户内嵌才坏** —— 因为 `MAP_STRIP_CSS` 只在门户侧注入。
所以看到「同一页两种入口观感不同」，第一反应就该是去 `MAP_STRIP_CSS` 找
「哪条 `!important` 规则命中了它」。

**验收（两个探针，均已登记进 `development.md`）：**
- `TMP\_verify_v1_legendcss.cjs` —— 浅/深两主题各一遍，断言两个浮层的
  `background`/`z-index`/`position` 与直开一致、没被拉成通高、方位没跑。**14 条全绿**。
- `TMP\_verify_v1_themeclick.cjs` —— 真实路径（点顶栏 `#themeBtn`）复核主题切换后
  浮层跟着变。**6 条全绿**。

**探针自身踩的两个坑（已写进探针注释）：**
1. **第一版用 `?theme=dark` 设门户主题 —— 门户根本不认这个参数。**
   门户的主题来自 `localStorage['olbr.theme']` → 系统偏好（见 `olbr.js` 的 `detectTheme`），
   而直开 my_app **认** `?theme=`。于是探针让"门户保持浅色、直开是深色"，
   比出了 `rgba(255,255,255,.78)` vs `rgba(10,20,40,.55)` 的**假差异**，
   看上去像"深色主题也坏了"。现改为两侧各用各自真实的机制设主题，
   并加 `C0` 自检**先证明两侧主题一致**再比较 —— 否则后面的断言全是噪声。
2. **不能只测预置主题**：真实用户是点按钮切主题，走的是
   `setTheme()` → 重建 iframe `src`。若只预置 `localStorage` 再导航，
   就覆盖不到「切换后内层没跟上」这条路径，故另起 `_verify_v1_themeclick.cjs`。


## 九之九、2026-10-15 地图左移与「MAINTENANCE ALERTS 为什么没在最右边」

**需求。** 用户：「`/myapp/?page=gis` 这个页面已经是 8 了，所以不用再放大了，
但是要把地图向左平移，避免右边的图例遮挡地图」。

**做法。** 只在门户侧注入一条 CSS（`v1\olbrportal\assets\olbr-data.js` 的 `MAP_STRIP_CSS`）：

```
.leaflet-map-pane{margin-left:-160px!important}
```

用 `margin-left` 而不是 `transform`：Leaflet 每次拖拽/缩放都会重写
`.leaflet-map-pane` 的**行内 transform**，写在 transform 上的位移会被冲掉；
margin 不在它管辖范围内，实测拖拽后仍存活。

**⚠️ 方向是用户知情后的选择，但实测与直觉相反。** 排名条在**右侧**，
所以内容左移会把更多站点推到它下面：

| | 压在排名条上的站点 | 屏内可见站点 |
| --- | --- | --- |
| 不动 | 44 | 574 |
| **左移 160px**（用户选择） | **54（更糟）** | **193（丢掉 2/3）** |
| 右移 160px | 26 | 549 |

已把该结果告知用户，用户明确回复「就要左移，我知道会让出左边界」。
**故这是知情决定，不是 Bug**；后人不要因为「压住变多 / 左边出界」就擅自改成正数或删除。
可复跑 `TMP\_diag_v1_pandir.cjs` 复核。

**⚠️⚠️ 一次真实翻车：把浮层和地图一起平移。** 第一版顺手加了
`.gis-rank-overlay{transform:translateX(-160px)}`，理由是「地图左移了、浮层不跟着移会撞在一起」——
**那是想当然**。用户随即发现并追问「MAINTENANCE ALERTS 为什么没有在最右边」。

根因：排名条本来就靠 `index.css` 的 `right:196px` 定位，**那个 196 是专门为让开右上角
「图层」开关**（`right:56` + 宽 `132` + 8 间隙）算出来的，它相对右边缘的位置**本来就是对的**，
与地图往哪边移无关。把它一起左移 160px 的后果（实测 `TMP\_diag_v1_rankgap.cjs`）：

| | 排名条右缘距容器右边 |
| --- | --- |
| 含误加的 `translateX(-160px)` | **216px**（悬在中间） |
| 去掉该条 | **56px**（与直开一致） |

**结论：地图内容平移与浮层定位是两件事，不要耦合。**
同理图例（`.gis-legend-overlay`，左下角）也**不参与**平移 —— 它本来贴左边，跟着左移会直接出界。
两者都在「地图同级浮层」这一类里，但定位诉求相反，所以不能给 `.ant-card-body` 加统一位移。

**验收（5 个探针全绿）：** `_verify_v1_panleft.cjs`（8 条，含「排名条没被平移且仍贴右边」的回归守卫）、
`_verify_v1_legendcss.cjs`、`_verify_v1_themeclick.cjs`、`_verify_v1_defaultzoom.cjs`、`_probe_v1_centered.cjs`。

**⚠️ 平移污染了两个老探针的读数，已分别修正判据（都不是产品回归）：**
1. `_verify_v1_defaultzoom.cjs` 的 B3 原用「站点像素跨度比 ≈2」判缩放。跨度会被容器宽度
   **截顶**（容器仅 769px，缩小态跨度已 752 顶满），且平移后未裁剪跨度再被污染。
   改成用**屏内要素占比**（放大后屏内更少），该量与平移解耦。
2. `_probe_v1_centered.cjs` 的 C4 原断言「水平居中 <15%」，但平移后必然左偏
   （-20.7% ≈ 160/769）。拆成 C4a「偏移**等于**注入的平移量」+ C4b「扣掉平移后仍居中」——
   实测残余偏移 **0.1%**，既证明了平移生效，也证明了取景本身没有跑偏。
   另外该探针里读平移量必须**在采集循环内、gis 页还选着的时候**读：循环最后停在
   `mwRealTime`，循环结束后 gis 的 iframe 已被换掉，那时读只会得到 0。


## 九之十、2026-10-16 地图默认缩放改为「按页配置」

**需求。** 用户：「alarm 这个地图不要在点一次放大了」。
经确认范围后明确：**只关 Alarm，MW 保持放大**。

**⚠️ 先厘清一个容易搞混的对应关系：页签显示名 ≠ page 值。**

| 界面上的页签 | page 值 | 本次决定 |
| --- | --- | --- |
| **Alarm** | `gis` | **不再自动放大**（打开即内层默认档） |
| **MW** | `mwRealTime` | 保持自动放大（2026-10-02 的决定） |

改名发生在 2026-09-29（`olbr-data.js` 的 `'map.gis': 'Alarm'`），
键名与 page 值**刻意没跟着改**（键是内部标识，历史 `catalog.tabLabels` 记录才不会失配）。
所以看代码时「`gis` 就是 Alarm」，别去代码里找 `alarm` —— 那个 page 已于 2026-09-25 下线。

**改动。** 原先是一个全局布尔 `MAP_DEFAULT_ZOOM_IN`，两页共用，无法只关一页。
2026-10-16 改为按页配置（`v1\olbrportal\assets\olbr.js`）：

```js
var MAP_ZOOM_IN_BY_PAGE = { gis: false, mwRealTime: true };
function shouldZoomIn(page) { return MAP_ZOOM_IN_BY_PAGE[page] === true; }
```

未知页默认**不放大** —— 宁可不放大（用户看得见全境），也不要擅自改变他的视野。

两页本来就各走一条独立实现，所以只需各自查自己那一项：
`zoomOnce`（只服务 gis）查 `'gis'`；`refitLeaflet`（只服务 mwRealTime）查 `'mwRealTime'`。

**需求演变（四次，方向来回过，改前务必确认当前状态）：**

| 日期 | 用户要求 | 结果 |
| --- | --- | --- |
| 2026-09-22 | 跟手动点一次 `+` 一个效果 | 两页都放大 |
| 2026-09-25 | 别放大了 | 两页都不放大 |
| 2026-10-02 | 又改回「打开就大一号」 | 两页都放大 |
| **2026-10-16** | **「alarm 这个地图不要在点一次放大了」** | **只关 gis，MW 保持** |

**验收。** `TMP\_verify_v1_zoomperpage.cjs`（5 条，专属）：
MW 仍 `zoom 8` 且点一次 `-` 回到 7；Alarm 打开态跨度 **752**，与直开 `/myapp/?page=gis` 的 **752** 完全一致（ratio 1.000）——
即它回到的是内层页自己的默认档，没有任何自动放大。同时 `_verify_v1_panleft.cjs` 的平移守卫仍绿。

**⚠️ 三个探针的判据要跟着需求一起翻，不能只当它们是"读数不准"：**

1. `_verify_v1_defaultzoom.cjs`：原 A/B 两组都断言「打开即大一号」。B 组（gis）判据已**反转**为
   「屏内要素占比与『缩小一级』相当」= 未被放大。实测 openedRatio 0.966（vs 被放大时的 0.311）。
2. `_probe_v1_centered.cjs` 的 C4a：原来隐含假设「站点群自然中心恰在容器中心」，
   取消放大后该假设不成立（平移确实 -160px，但站点中心只挪 -84.5px，
   因为群的自然中心与容器中心本就不重合，两者**不是 1:1**）。
   **教训：平移量要直接读注入的 `margin-left`，不要用站点中心去反推** ——
   中心偏移是「取景 + 平移」的合成量，反推必然假失败。
3. 同一探针还试过「拿直开的自然偏移做对照」，同样错：两边**缩放级不同**
   （直开容器 1669px、门户 769px），**百分比偏移不可跨视口移植**，直开算出 68.3% 纯属宽视口产物。
   判据已改为按**像素**直接量平移量。


## 九之十一、2026-10-07 `#kpi` 两排卡改为「连体卡组 + 组头链接」

**背景（用户原话）。** 「`Network Benchmark View` 组件前 3 个卡片下钻都是打开相同的页面，
容易让人误解是 3 个不同的页面，有没有办法弄一个组之类的，从感观告诉人们点击会打开同一个页面」。

问题是真的：「同一组卡去同一个 `page`」这件事，改之前**只写在每张卡的 tooltip 里**，
不悬停就看不见；而同排卡的间距均匀、外观一致，读者无法从视觉上区分
"这 3 张是一组、那 2 张是另一组"。

用户从 4 个方案里选了 **A：连体卡组 + 组头链接**。

**决策一：一组 = 一个可见的整体（共享外框 + 组内不留栅格间距）。**
`.qc-grid` 仍是 6 列，但**组是它的直接子项**：组跨越 `N` 列（`N` = 成员卡数），
组内卡 `gap:0`、去掉各自的圆角与描边，只在相邻处留一条 `1px` 细缝；
圆角与描边记在组这一层。于是「组内是一个整体、组与组之间是两个东西」
靠**缝的宽窄差**表达（实测：组内缝 0px、组间距 8px），而不是靠间距大小去暗示。

**决策二：组头写组名 + 一个显式链接，且链接与卡片**同源**。**
组头 = 组名（= 目标看板的业务名）+ 右侧「打开完整看板 ↗」。
两者都取 `g.page` / `spec.page`，**渲染层不写死任何页面** ——
写死就会出现「组头去 A、点卡去 B」。

**决策三：`page` 与组成员都属于数据，`olbr-data.js` 是唯一真相源。**
新增 `KPI_GROUPS`（`rich`→`KPI_RICH`、`avail`→`KPI_AVAIL_ROWS`）与
`BF_GROUPS`（`speed`→`KPI_SPEED`、`meta`→`KPI_META`、`bp`→`KPI_META_BP`），
每组带 `id / name / page / items`。组表的成员直接**引用**原数组本身
（不是拷贝），所以表里增删卡时组自动跟着变。
⚠️ JS 的 `var` 前向引用得 `undefined`，所以组表必须声明在**成员数组之后**。

**决策四：BP 单独成组，目标页从 `bm_meta` 改为 `bp_report`。**
用户要求「单独成组 + 目标改 `bp_report`」。于是 `KPI_META` 缩到 2 项
（`speed` / `scores`），BP 移入新的 `KPI_META_BP`（`page: 'bp_report'`）。

⚠️ **这里有一个必须写下来的口径不一致（用户明确接受）：**
BP 卡的**数字**取自 `/api/bm-meta/overview`（`meta_data` 快照），
而它**点开的页** `bp_report` 是 RAN_UME 重算的「BP Cells Report」——
**两者不是同一份数据**。所以三处文案都刻意只说
「这些卡点下去都打开 X」/「打开 X 的完整看板」，**绝不说**「这些卡的数据来自 X」：
许下同源的承诺就是撒谎。`kpi.grp.tip` 的注释里记了这条。

**决策五：骨架屏与真实结构 1:1（本次连带修掉一个既有缺陷）。**
骨架分支原来输出了两个**平铺**的 `.qc-grid`，分组后必须也按
`KPI_GROUPS` / `BF_GROUPS` 渲染，否则数据到位那一刻会连"组头"一起凭空长出来。
遍历组表而不是写死 3 组：将来一组卡增减不会漏改骨架。

**连带修掉：骨架屏比真卡矮 129px。** 量骨架态时发现（`Fetch.enable` 把 kpi 四路请求
挂住即可停在骨架态；用 `setBlockedURLs` 是错的 —— 请求立刻失败、`loading` 翻 false，
走的其实是"真卡 + —"分支）：
- 旧骨架只往卡里丢几条 `.sk` 灰条，而 `.sk` 是**固定 12px 高的方块**，
  五条才 90px 上下；真卡的内部是一条有固定高度的链
  （富卡：标题 19 + 数值 25 + 日期 14 + 徽章 21 + 走势 26 + 页脚 51，
  加外边距 27 与内边距 19 = 203px）。
- 实测骨架 417px vs 真卡 546px，**数据到位整块往下弹 129px**（上排 82px、Benchmark 行 46px）。
  这是**改动前就存在**的缺陷（用 `_bak_20261007_094400_连体卡组前` 对照量到同样的 46px）。
- 修法：骨架**复用真卡的分段类名**（`.qc-ttl / .qc-val / .qc-asof / .qc-chips /
  .qc-spark / .bf-hd / .bf-rows / .qc-ext`），每段给等于真卡的显式高度。
  两处踩坑记在代码注释里：① 用裸 `.sk` 拿不到 `.qc-asof`(`margin-top:2px`) 与
  `.qc-spark`(`margin-top:8px`) 的边距，必须包一层真类名（差 10px）；
  ② 富卡**不能**挂 `has-foot`（那只给内容少的 Benchmark 卡用），
  多挂一个会让 `.qc-ext` 吃到 `margin-top:auto`、多出 6px。
  结果：**129px → 3px**（每组各 1px 的亚像素舍入）。

**断点（实测三个视口）。**
- `>1200px`：组按卡数横跨列（3/2/1），三组正好排满一行
  （749 + 8 + 497 + 8 + 244 = 1506 = 栅格宽），各卡宽 242~249px；
- `≤1200px`：整行收成 3 列，组改为**一组一整行**，1 张的 BP 组用
  `minmax(0, 50%)` 限宽，避免它突然拉成整行宽；
- `≤760px`：组内一律单列纵向堆叠，此时"左细缝"要翻成"上细缝"
  （`border-left:0; border-top:1px`），否则分隔线跑到左边、上下两卡粘在一起。

**悬停：反馈做在组上，不在卡上。** 逐卡 `translateY(-2px)`（原 `.qc-card:hover`）
在连体组里会让"连体"在鼠标下散架，恰好把"这是一个整体"说反了，
所以组内卡的抬升被关掉，改由 `.qc-group:hover` 给整组描边 + 阴影。

**改动文件（只改 v1 一份，`/v1/olbrportal/` 是 nginx alias 手写壳，无构建步骤）。**
- `v1/olbrportal/assets/olbr-data.js`：新增 `KPI_GROUPS` / `BF_GROUPS` / `KPI_META_BP`，
  `KPI_META` 缩到 2 项，新增 `kpi.grp.go / kpi.grp.tip / kpi.grp.one / kpi.grp.many /
  kpi.bp.board` 双语键，改写 `kpi.bf.subBoth`（原文说"6 张卡来自两个数据源"，
  分组后是**三个组、三个目标页**）；
- `v1/olbrportal/assets/olbr.js`：新增 `qcGroupHtml()` / `qcGroupCards()`，
  `renderKpi` 的两排与骨架分支都改成遍历组表，`metaCardHtml` 的
  「打开哪一页」按 `spec.kind` 取 `kpi.bp.board` 或 `kpi.mm.board`
  （原来对所有 Meta 卡写死 `kpi.mm.board`，BP 改目标页后就成了假话）；
- `v1/olbrportal/assets/olbr.css`：新增 `.qc-group / .qc-group-h / .qc-group-n /
  .qc-group-go / .qc-group-b` 与三个断点。

**验证。** 无头 chromium 实测 `1600 / 1100 / 700px` 三个视口 ×（数据态 / 骨架态）：
5 个组、卡数 3/3/3/2/1、组头链接可见且 `page` 与成员逐张一致；
组内缝 0px vs 组间距 8px；卡圆角 0px、组圆角 10px；
中英双语下每张卡 tooltip 的「打开 X」与它 `href` 的 `page` **逐条对齐**。
另修掉英文单复数（BP 组只有 1 张卡，原写 "(1 cards)"）。


## 九之十二、2026-10-22 地图「滚轮缩放锁」：默认锁定，工具条上一颗开关

**问题（用户原话）。** 「当用户鼠标下滑的时候容易出现在地图里面下滑」——
页面往下滚时，滚轮一旦划过内嵌地图就被 Leaflet 吃掉变成缩放地图，页面卡住不动。
`/v1/olbrportal/` 的地图在页面下方（实测 `#mapFrame.top≈1316`，视口高 1050），
用户滚到那一带就"陷进去"。

**方案选择：工具栏开关，而不是"点击激活"。** 两个候选：
- 方案三「点击激活」（嵌入时默认关滚轮，点一下地图才开，鼠标移出又收回）
  **本项目已经做过又删了**：my_app 的 `MapWheelZoomOnClick` 组件，2026-09-29 按用户
  要求整体撤销（`frontend/src/pages/GISMap.tsx:1157`、`PacketLossDashboard.tsx:604`、
  `olbr.js` 的 `mapSrc()` 注释都留了记录）。再上等于把同一个决定来回翻第二次。
  更要紧的是**语义撞车**：这两页的主交互就是「点站点弹窗 / 点链路下钻」，
  左键已被占用，再让它兼职"开启滚轮缩放"，用户点完弹窗回来发现滚轮又失灵，只会觉得坏了。
- **采用：方案二** —— 工具条上新增一颗「缩放锁」（`data-act="map-zoomlock"`），
  **默认锁定**（`scrollWheelZoom:false` 的等效效果），点一下解锁、再点锁回，
  选择持久化到 `olbr.mapwheellock`（`'1'` 锁 / `'0'` 放）。
  锁定态下滚轮永远滚页面；要精细看地图时自己解锁一次，之后一直有效。
  锁定的**只是滚轮**这个最容易误触的通道 —— 双击缩放、`+/-` 按钮、拖拽平移都不动。

**实现（`v1/olbrportal/assets/olbr.js` 的 `applyMapWheelLock`）两条路都要走：**
1. **实例路**：`map.scrollWheelZoom.disable()`。已知 gis（界面上叫 "Alarm"）**可能拿不到
   实例**（`findLeafletMap` 那条路在 PMTiles 页上没有挂载点），这条会静默失败；
2. **拦截路**：在内层 document 上挂 **capture 阶段**的 `wheel` 监听，
   `preventDefault` + `stopImmediatePropagation`，挡在 Leaflet 自己的处理器之前。
   不依赖实例，两页通用。

**三个不做就会静默失效的点**（都写进了代码注释）：
- **必须 `{ passive: false }`**。Chrome 把 document/window 上的 wheel/touch 监听默认当
  passive，passive 里调 `preventDefault` 会被忽略（控制台只留一行 warning），
  表现是"锁了但地图照样缩放"。
- **光拦不够，还要把滚动还给最外层门户窗口**。内层页被 `keepOnlyMap` 刷成
  `overflow:hidden`，拦掉滚轮只是"地图不缩放"，页面**不会**自己往下走；
  必须把 deltaY 转交给外层窗口的 `scrollBy`（见 `outerScrollWindow`）。
  MW 页是**三层**嵌套（门户 → React 壳 → `mw_real_time.html`），中间那层同样不可滚，
  所以要一路走到顶。
- **判"有没有缩放"不能看 tile 的 z 层级**：这两页用 PMTiles，瓦片 `src` 不是
  `/{z}/{x}/{y}.png`（实测 z 直方图恒为空）；且缩放动画结束后 `transform` 会**停在
  最后一帧**，"前后相等"既可能是没缩放也可能只是残留 —— 探针改用
  MutationObserver 数 `.leaflet-zoom-anim` 的出现**次数**（增量，不受残留影响）。

**为什么 `stripFrame` 的 0/1.4/3.4s 三拍还不够。** 这三个是**固定时刻**，
而 MW 三层嵌套各自还要跑 React 挂载与地图初始化：点「重新加载」之后，最内层 document
往往三拍都还没被创建出来。实测后果是**界面在说谎** —— 按钮显示"已锁定"，
内层 `data-olbr-wheel-lock` 仍是 `null`，地图照常缩放。
故另有 `sweepMapWheelLock()` 每 2 秒幂等重放一次开关状态（`boot()` 里启动，
解锁态自动空转）。两处都保留：`stripFrame` 那条负责"第一时间生效"，
定时那条负责"最终一定生效"。

**验证（`TMP/_probe_v1_wheellock.cjs`，7 项断言全绿，两页签各跑一遍）。**
真浏览器（CDP）发**真实滚轮**（页面里 `new WheelEvent` 不触发 Leaflet）：
① 锁定态：页面 `scrollY 1570→2077`、缩放动画 0 次；
② 解锁后：页面不动、缩放动画 2~3 次（`maxScale 1→8`，MW 到 64）；
③ 再锁回：回到①的行为；④ 刷新后开关仍锁定并生效；⑤ 点 Reload 后仍锁定并生效。
另外量了两态视觉与布局：按钮在工具条**最左**（顺序 `map-zoomlock → map-reload →
mapOpen`，2026-09-29「reload/openlink 放最右」那条继续成立），
锁定态中性色 / 解锁态 accent 底色（`rgba(14,116,144,.08)` + 描边加重），
窄屏（≤520px）自动收成纯图标（33px），沿用既有的 `.gb--t > span{display:none}`。
中英两态文案均实测（"缩放锁" / "Zoom lock"，切语言后 tooltip 跟着换）。

**不在本次范围。** `/olbrportal/`（MsPortal 的只读展示版，`nginx.conf:417` 另一条 location）
有同一套地图工具条，但**没有**加这把锁 —— 用户只提了 `/v1/olbrportal/`。
`MsPortal/assets/portal.js` 更是另一套实现（无 `data-act="map-*"`），无从镜像。
若要推广，三处都要各自改。


## 九之十三、2026-10-24 RAG 知识问答改经 `.20:9443` 反代（VPN 端口白名单问题）

**问题现象。** 同事在**登录 VPN 后**访问 `https://192.168.100.27:8443/`（Open WebUI 的
NOC 身份端口）稳定超时（`ERR_CONNECTION_TIMED_OUT`）；**不登 VPN** 或访问
`https://192.168.100.20/v3/olbrportal/` 正常。排查结论：**8443 不在 VPN/防火墙的
放行名单内**，不是证书、不是服务故障。

**排查中被排除的方向（都实测过，避免后人重走）。**

| 假设 | 证伪方式 | 结论 |
| --- | --- | --- |
| `.27` 服务挂了 | `curl -k https://192.168.100.27:8443/` → 200，18ms | 服务正常 |
| 网络不通 | `ping` 0% 丢包、`Test-NetConnection` `TcpTestSucceeded: True` | 三层网络通 |
| 证书链不完整 | `openssl s_client` 曾只下发 1 张；后 `.27` 补 fullchain 后为 2 张 | 是真实缺陷，但**不是超时主因** |
| 证书吊销检查 | `.20` 根证书已装进客户端 Root store | 同前，软失败不产生超时 |
| 浏览器缓存 | 换无痕窗口仍超时 | 排除 |

**关键判据。** 问题只出现在"登 VPN"这一条件下，且 `.20` 在同条件下可用 → 流量是否
进入 VPN 隧道由**端口白名单**决定，与目标主机的技术实现无关。

**方案。** 在 `.20` 的 nginx 上开独立端口 `9443`，反代到 `192.168.100.27:443`
（借道 `.20` 已放行的通道）。**不采用子路径**（如 `/rag/`）——Open WebUI **不支持
子路径部署**，实测会白屏；这是它没有 `WEBUI_URL` 式 base path 配置项的直接后果。

配置位置：`nginx\conf\portal_ports.conf` 末尾（与既有 8081-8088 网管门户同构），
**不是** `nginx.conf` 主文件——那里只 `include portal_ports.conf;`。

**三处必须与网管门户不同的写法（照抄 8081-8088 会坏）。**

1. **必须摘 `Alt-Svc`。** 上游 Caddy 下发 `Alt-Svc: h3=":443"`，浏览器学到 QUIC 直连后
   会**绕过反代直连 `.27`**，反代立即失效——且失败表现仍是"超时"，极难归因。
   网管门户没有这条是因为它们的上游不发 `Alt-Svc`。
2. **`Host` 用 `192.168.100.27` 而非 `$host`。** Open WebUI 用 Host 生成绝对跳转；
   若为 `192.168.100.20:9443`，登录后可能被导到反代外的地址。
3. **`proxy_buffering off`。** Open WebUI 逐 token 流式输出，不关缓冲会"攒齐才吐"。

**Cookie 为什么不需要 `proxy_cookie_domain`。** 上游 Cookie 形如
`token=...; Path=/; SameSite=lax`，**没有 `Domain` 属性**（host-only）。浏览器按
**当前访问 host**（`.20`）存储，行为天然正确。`proxy_cookie_domain` 只在上游**有**
domain 时才改写；此处保留该行是为防御上游未来改成带 domain（写了也无副作用，实测未触发）。

**安全约束（必读，防止后人误改）。** 上游 `/api/config` 返回
`"auth_trusted_header": true`，即 Open WebUI 认 `X-Forwarded-Email` 之类的**信任头**。
本反代**刻意不设置任何信任头**，只设 `X-Real-IP` / `X-Forwarded-For` / `X-Forwarded-Proto`。
**任何人若在此 location 内加 trusted header 做"免登录"，等于把 `.20:9443` 变成
未认证入口**，切勿。

**验证记录（2026-10-24）。**

- 本机：`https://192.168.100.20:9443/` → 200，32ms，11601 字节，与直连 `.27` 的
  Etag 一致（`94fe10f7...`）；WebSocket `/ws/socket.io/` → **101**；响应头中
  **无** `Alt-Svc`，`Via: 1.1 Caddy` 证明穿透成功。
- 同事端：**登录 VPN 状态下实测可访问**（本次方案成立的最终判据，见下条备注）。
- 80/443 未受影响。

**为什么仍保留 `.27` 直连。** 反代是"绕路"，不是根因修复。**长期正解是让网络管理员
把 `192.168.100.27:8443` 加入 VPN 白名单**，届时撤掉 9443 server 块、门户链接改回直连即可。
在那之前，9443 是可用方案；若将来 9443 也被策略收紧，**不要再换端口**（9543/9643 同理），
应回到白名单申请。

**回滚。** `cp conf\portal_ports.conf.bak_20261024_加RAG反代前 conf\portal_ports.conf`
然后 `cd D:\01_RPA\nginx-1.28.0 && .\nginx.exe -s reload`。

**遗留问题：`logs\nginx.pid` 被清空。** 本次重载时 `nginx.pid` 是 **0 字节**，导致
`-s reload` 报 `invalid PID number ""`。确认真实 master（worker 的父进程）后写回 pid
才成功。成因未查明，疑为此前某次 `-s stop` 或被计划任务拉起时未正确写入。**影响**：
`Nginx_EnsureRunning` 计划任务与手工 reload 都可能踩到。**待办**见门户 `TODO.md`。

## 九之十四、2026-10-27 `/v3/olbrportal/` 右下角问答挂件（复用 WhatsApp 机器人知识库）

**要什么。** 门户页面上直接问「告警码什么意思 / 这个单怎么样了 / 操作步骤」，答案与
WhatsApp 群里一致，不另建一套知识库、也不让浏览器直连模型。

**链路。** 浏览器（同源，带 `myapp_session`）
→ `POST /api/portal-qa/ask`（nginx `/api/` → `7038`，my_app 路由 `backend/routers/portal_qa.py`）
→ `127.0.0.1:9269`（whatsapp-kb-bot 的 `src/http-server.js`）
→ `src/answer.js:routeAnswer`（与群机器人**同一个**答题入口：查表 / 工单统计 / 单号分析 /
站点告警 / VMAX CCA / 知识库 RAG）。
9269 不常驻，由后端 `backend/services/portal_qa_ctl.py` 按需拉起（详见 my_app
`docs/manual/13-operations.md` 的「网页问答助手」一节）。

**两个文件，纯增量，不改 olbr.js。**
`assets/qa-assistant.css`（只用 `--surface/--line/--t1/--b/--grad` 令牌，深浅色随 `html.dark`）与
`assets/qa-assistant.js`（IIFE，自建 FAB + 面板）。在 `index.html` 里只加一行 `link`、一行 `script`，
`script` 排在 `assets/olbr.js` **之后**。它不读 `window.OLBR_DATA`、不碰 olbr.js 的 DOM，
靠两个 `MutationObserver` 跟随页面状态：

- `<html lang>` 变化 → 重刷挂件文案（中/英由页面语言开关驱动，自身不存语言偏好）；
- `#gate` 的 `hidden` 属性变化 → 登录门打开时隐藏 FAB 并收起面板（门户未登录时不该出现问答入口）。

**为什么不让浏览器直连 9269 / 直连 `.27`。** 9269 只绑回环；模型 key 不能下发到前端；
同源还省掉 CORS 与第二个鉴权口。`clientId` 由后端拼成 `用户名#页面id`，服务端每会话留 5 轮，
同名不同浏览器不串上下文。

**已知限制（2026-10-27 实测）。** OWU 侧的 `OPENWEBUI_API_KEY` 对 `/api/v1/models`、
`/api/v1/chat/completions` 返回 403/400，网页问答实际走的是「OWU 失败 → 本地 Ollama 同款 7b」
兜底；`.27` 的 Ollama 只常驻一个模型，7b 与 `bge-m3` 换载一次 7~30 秒，知识库类问题
单次 **60~90 秒**（规则通道毫秒级）。补一个具备模型权限的 key 后自动切回 OWU，无需改代码。

### 九之十五、2026-10-28 问答挂件换 3D 机器人徽章（**不铺背景**）

**要什么。** 用户提供素材「蓝色3D聊天机器人徽章.png」，要求问答助手的图标用它，
并且**不要背景** —— 徽章之外必须是真空透明，页面底色直接透出来。

**素材本身就是透明底，不需要抠图。** 实测原图 1254×1254 RGBA：四角 α=0、
最外 12px 环带 α 最大值 **1**、从边界洪水填充得到的背景连通区占全图 **42.1%**
（= 徽章之外的真空）。所以「不要背景」不是「把背景抠掉」，而是**别再由 CSS 补一块
底板** —— 原来那两块才是背景的真正来源：

| 位置 | 改前 | 改后 |
| --- | --- | --- |
| `.qa-fab` | `background: linear-gradient(145deg, #0b245e, #123b91, #087e9b)` 实心深蓝青圆盘 + 白色描边 | `background: transparent`，只留 1px 细描边 + 投影作浮标锚点 |
| `.qa-avatar`（面板标题栏头像） | `background: #fcfcfc` 实心白底板 | `background: transparent` |

> ⚠️ 头像那块白底板**当初是有用的**：旧图标 `logo-qa-share-*.png` 是**白底方图**，
> 不铺底就会露出方形白角。换成透明 alpha 切图后，铺底反而在浅色页面上多出一块
> 灰白色方块 —— 与「不要背景」直接冲突。故一并去掉（`qa-assistant.css:118-140`）。

**资产：换成 `logo-qa-badge*.png`，旧的 7 个 `logo-qa-*.png` 一并删除。**
旧的 `logo-qa-{112,168}.png` / `logo-qa-icon-*.png` / `logo-qa-share*.png` 自
`c49942ea` 起就只有 `logo-qa-share-*` 被引用，另外 5 个是**从未被任何文件引用的
死资产**（其中 `logo-qa-share.png` 单个 1.07MB）。按 AGENTS.md 原则 10「删除优于
兼容」全部删掉，不留兼容层。

**位图怎么来的（`scripts/make_qa_badge.py`，可复现）。** 位图是二进制，git 里看不出
「这张图抠过没有」，故把处理步骤写成脚本：素材原图在用户本机 Downloads（不入库），
跑一次脚本产出三档尺寸。

1. **裁掉四周留白**：按 α>8 取外接框（阈值取 8 而非 0，保住边缘抗锯齿羽化）；
2. **补成正方形**：徽章实测 1103×1123，不是正圆，不补会在 58px 圆钮里偏；
3. **预乘 alpha 缩放**（`RGBa` 缩放再转回 `RGBA`）：直接 `Image.resize` 会把全透明
   区域的**黑色**插值进半透明边缘，缩到 112px 时表现为机器人外一圈**灰黑描边**
   （浅色底上尤其明显）—— 这是必须走预乘的原因，不是可选优化。

产物 `logo-qa-badge.png`(256) / `-112.png` / `-168.png`，三档都是真透明 alpha。

**验收（2026-10-28 实测）。** 浏览器实测 `getComputedStyle`：
`.qa-fab` 的 `background-image: none`、`background-color: rgba(0,0,0,0)`、
`border-width: 0`；`.qa-avatar` 的 `background-color: rgba(0,0,0,0)`；
两处 `<img>` 的 `naturalWidth/naturalHeight` 均为 112（srcset 2x/3x 档位正确）。
浅色与深色两套主题各截图目视核对：徽章边缘无暗边、无白角、无方形底板。

**回归**：`node --check v3/olbrportal/assets/qa-assistant.js` +
`npx tsc -p v3/olbrportal/tsconfig.json` 均通过。`v3` 是**手写静态壳**（nginx 直接
alias 发出，无构建步骤），改完刷新即生效。

## 九之十五、2026-10-28 `/v3/olbrportal/` 柱状图分档：判定改回各指标自己的阈值

**起因。** 用户反馈「`/v3/olbrportal/` 页面卡片里面的柱状图的颜色好像没有根据图例要求
显示对应的颜色」。

**结论：问题不在"颜色没对上图例"，而在**分档规则本身错了**，且**页面上根本没有对应的图例**。
两处都要改。

**一、判定：2026-10-23 写死的绝对阈值是错的。** 当时六张卡按大数字套了同一把尺子
（`<5 绿 / <20 金 / >=20 红`）。但六个指标量级差三个数量级（PMT 存量 1,700、SPMS 存量 12），
同一把尺子必然判错。实测**六张卡错了四张**：

| 指标 | 存量 | 绝对阈值判定 | 正确判定（各指标自己的阈值） | 错在哪 |
| --- | --- | --- | --- | --- |
| `alarm` | 34 | 严重 | 严重（warn 10 / crit 30） | 对 |
| `tt` | 78 | 严重 | **关注**（warn 30 / crit 80） | 错升一级 |
| `wo` | 165 | 严重 | 严重（warn 50 / crit 150） | 对 |
| `cr` | 86 | 严重 | **正常**（warn 100 / crit 250） | 错升两级 |
| `pmt` | 1,700 | 严重 | **关注**（warn 1000 / crit 2000） | 错升一级 |
| `spms` | 12 | 关注 | **正常**（warn 150 / crit 400） | 错降一级 |

**修法**：改走 `DATA.QC_TARGETS` + `qcLevel()` —— 阈值表与 `/olbrportal/`(v0)、`/MsPortal`
**完全是同一份**（`assets/olbr-data.js` 的 `QC_TARGETS`，与 `MsPortal/assets/portal.js` 逐字对应）。
⚠️ 口径来源见 `MsPortal/QC面板展示优化建议_20260922.md` §4，那张表**本就标注「待业务确认」**
（首版默认值，依据只有实测量级 + NOC 常识）—— 业务目标值到位后改这一处即可，**四处同步**
（v0 / v1 / v2 / v3 各自的 `olbr-data.js` + `MsPortal/assets/portal.js`）。
⚠️ `qcLevel()` 此前在 v3 是**死代码**（v1 摘掉等级徽章后就没有调用点了），
本次把它接回来，与 MsPortal 走同一条判定 —— 同一个数字在两个门户上给出不同结论，
比样式不一致更糟。

**二、色值：从硬编码绝对色改取全站状态色令牌。** 原值 `#006400` / `#FFD700` / `#FF0000`
是纯绝对色，有两个问题：① 不跟浅/深两套主题走（深色底上的 `#006400` 对比度仅 2.11:1，
基本看不见）；② 与全站状态色不是一套（浅色 `--ok` 是 `#0a6a52`，与 `#006400` 是两个不同的绿）。
现在三档取 `var(--ok)` / `var(--warn)` / `var(--crit)`，与 v0 徽章、MsPortal 徽章、
页面其它状态色**完全同色**，深浅两套主题自动跟随。
⚠️ 仍然刻意**不动 `--qc-accent`**：那个变量还喂着卡片边框、内发光与 hover 光晕，
整卡换色不在需求里（用户点名的只有「数字和下面的柱状图」两处）。

**三、补回图例与阈值提示。** 用户说的"图例"当时**在页面上并不存在** ——
全页唯一的图例是 Benchmark 那两条基准线（Orange / MTN），与柱状图无关。
既然颜色又变得有含义，就必须给出对照：
  · 标题行加「分档图例：正常 / 关注 / 严重」三枚色点，色点**直接取同一组令牌**，
    所以图例里看到的就是柱子上的（若这里另写一套色值，就会重演"图例画的是 A、柱子是 B"）；
  · 卡片 tooltip 加回「分级阈值：关注 ≥ N · 严重 ≥ N」（v1 摘掉它的理由是"等级分档整个不显示了，
    再把阈值挂在悬浮里，等于让用户按一个屏幕上不存在的规则去读数字"—— 该前提已不成立）。

**验收（2026-10-28 实测）。** Playwright + `getComputedStyle` 实测：
  · 分档：v3 与 v0 与 MsPortal **三者逐卡一致**（crit/warn/crit/ok/warn/ok）；
  · 图例色点与柱子 `fill` **逐档完全相等**（浅色 `rgb(10,106,82)` / `rgb(124,94,7)` / `rgb(162,32,47)`，
    深色 `rgb(11,199,140)` / `rgb(246,207,0)` / `rgb(255,92,108)`）；
  · 英文界面图例渲染为 "Level legend / OK / Watch / Critical"；
  · 窄屏 760px 图例整块折行，**无横向溢出**，且不与心跳区重叠；
  · 页面 0 个 page error。

**回归**：`node --check`（olbr.js / olbr-data.js）+ `npx tsc -p v3/olbrportal/tsconfig.json`
+ `npm run lint` + `npm run build` 均通过。`v3` 是手写静态壳，**改完刷新即生效，无需构建**。
⚠️ 只改了 `v3`；`v1` / `v2` / `olbrportal`(v0) 的分档本就正确（走 `QC_TARGETS`），未动。

## 九之十六、2026-10-29 五个团队门户（FO/BO/FLM/SMC/CXO）：**一套资产 + 一张可见性矩阵**

**起因。** 用户要求以 `/v3/olbrportal/` 为样板，另开五个只显示各自团队应看内容的门户：
`/v3/fo_portal/`、`/v3/bo_portal/`、`/v3/flm_portal/`、`/v3/smc_portal/`、`/v3/cxo_portal/`。
内容清单来自 `C:\Users\ZTEEMS\Desktop\新看板设计.xlsx`（「各团队看板内容清单」表），
按「团队列打勾 = 该团队应看」翻译成机器可读的可见性矩阵。

**结论：可行，且上游 `/v3/olbrportal/` 一行未改。** 实现上做了三个关键取舍。

### 一、五个 URL 共用一套资产，而不是五份副本

`v3/team_portal/` 一份 HTML/CSS/JS，nginx 侧五个 `location ... alias` 到同一目录：

```
/v3/fo_portal/  ─┐
/v3/bo_portal/  ─┤
/v3/flm_portal/ ─┼─→ alias →  v3/team_portal/
/v3/smc_portal/ ─┤
/v3/cxo_portal/ ─┘
```

**为什么不是五份副本。** 五份副本意味着 HTML/CSS/JS 有五个真相源：上游 `olbr.js` 修一次 bug
要手工合并五遍，漏一处就有一个团队看到旧行为；门户改一次样式要改五处 CSS。
`v3/olbrportal/assets/olbr.js` 有 37 万字符，fork 一次就是两份真相源，
后续每次上游改动都要手工合并一遍，必然漂移。

**为什么共用不会串味。** 团队判定靠 URL 前缀（`team-scope.js` 的 `detectTeam()`），
五个 location 同源共用后端 API（`/api/portal-catalog`、`/api/portal-qc/*`、
`/api/email-reports/*`），所以各门户看到的是同一份目录、同一份数据，差异**只**在可见性矩阵。

⚠️ **目录深度必须与 `/v3/olbrportal/` 一致**（同样理由见 nginx 里 v3 那条 location），
否则 `index.html` 里 `assets/xxx.js` 相对路径会指向错误目录。

⚠️ 五个 location 均带 `Cache-Control: no-cache, no-store, must-revalidate` ——
矩阵或 scope 改完后刷新即生效，不需要清 nginx 缓存。

### 二、矩阵从 Excel 生成；`olbr.js` 用薄适配层，不 fork

```
scripts/gen_team_matrix.py  ──读 Excel──→  v3/team_portal/assets/team-matrix.js
                                          （window.OLBR_TEAM_MATRIX）
                                                ↓
                            assets/team-scope.js（window.OLBR_SCOPE 查询引擎）
                                                ↓
                            assets/olbr.js（team_portal 版）
                            渲染点：if (SCOPE && !SCOPE.ok('qc','alarm')) return '';
```

**矩阵生成脚本。** `scripts/gen_team_matrix.py` 解析 Excel，输出 `window.OLBR_TEAM_MATRIX`
（结构 `{域键: {子键: [有勾的团队id]}}`）。Excel 表头里的团队列名与内部 id 的对应在脚本内定义：
`ZTE FO Team → fo`、`ZTE BO Team → bo`、`ZTE FLM Team → flm`、`Orange SMC → smc`、`Orange CXO → cxo`。

**两个必须消解的歧义。**

  · **`SPMS` 在两个域里指两件不同的事。** Excel 的 QC 指标域有 `SPMS`（备件存量），
    Domain Dashboard 域也有 `SPMS`（视图分组）。按名字全局匹配就会张冠李戴 ——
    脚本内用 `DETAIL_BY_DOMAIN` **按域分别解析**才能唯一确定。
  · **全角/半角括号不一致。** Excel 里 `CXO View（ User/Traffic/Throughput）` 用全角，
    其它行用半角 `CXO View(User/Traffic/Throughput)`。脚本内做括号归一化后匹配。

**为什么矩阵是生成文件而不是手写 JS。** 矩阵是需求文档的机器可读形式：需求变了改 Excel 重跑脚本，
而不是在 JS 里手改一串团队 id。手改会在下次重跑时被静默覆盖 ——
这正是本仓库「不新增第二个真相源」的硬性约束。

**薄适配层。** `team-scope.js` 提供 `window.OLBR_SCOPE`（`ok(domain,sub)`、`subs(domain)`、
`ossSlots()`、`viewGroups()`、`mapPages()`、`qaTabs()`、`reportIds()`、`hasComplaint()` 等）。
`team_portal` 版的 `olbr.js` 里每个渲染点都是一行
`if (SCOPE && !SCOPE.ok('qc','alarm')) return '';` 形态 —— **一行判据，不 fork 逻辑**。

**矩阵缺项 = 不显示**，没有「默认全显」兜底 —— 缺一行就意味着那行没勾，不显示是唯一正确的行为。

**上游隔离。** `/v3/olbrportal/` 不引这三个文件，`window.OLBR_SCOPE` 为 null，
每个 `if (SCOPE && ...)` 都短路，上游那页行为**一行未变**
（`git status --porcelain v3/olbrportal/` 输出为空）。

### 三、Auto Report 与 Customer Complaint：两个不能靠矩阵过滤的特例

**Auto Report。** 上游那页的自动报表区是嵌入 my_app 的 iframe（不带过滤，渲染全部报告源），
无法按团队过滤；而 Excel 的 Auto-report 域是**逐条**勾选了要哪几种报告。
`assets/team-panels.js` 改为渲染一张**门户自绘表格**：查 `/api/email-reports/latest?limit=1`，
按 `source_id` 与 `SCOPE.reportIds()` 匹配过滤后再渲染，下载链接直连
`/api/email-reports/download/<source_id>/<name>`。
实测行数与 Excel 勾选数一致：FO 10 行、BO 3 行、FLM 8 行；
SMC / CXO 该域无勾选 → **整块消失**（矩阵 `report` 域对这两个团队为空）。
处置口径与其余各域一致：「这一域对这个团队完全无关」就不留空标题。

⚠️ **口径要如实说。** 这张表是**门户侧渲染**的，不是 my_app 页面截图；它复用同一个
`/api/email-reports/latest` 接口（同源、同一份数据），登录态由 Cookie 携带，
故受门户登录门保护 —— 与上游那块的行为一致。

**Customer Complaint。** 上游页面**没有**这一块（门户从未做过客户投诉入口），
它对应 my_app 的 `/myapp/?page=vmax_user_query`（VMAX CCA 投诉系统，按号码查用户与投诉根因）。
Excel 里是独立一行，故单独一块卡片式入口（`<a>` 跳页，不用 iframe ——
那是个需要输入号码的查询页，嵌进来只是个空表单，看不出能干什么）。
CXO 未勾选 → 不显示该块。

### 四、五个门户的实测可见范围（2026-10-29）

浏览器逐个打开实测，与 Excel 矩阵逐项对齐：

| 域 | FO | BO | FLM | SMC | CXO |
| --- | --- | --- | --- | --- | --- |
| QC 指标 | alarm/tt/wo/cr | alarm/cr | alarm/tt/wo/pmt/spms | alarm/tt/wo | 全部隐藏 |
| KPI | CXO 视图 + Availability | CXO 视图 + Availability | 仅 Availability | CXO 视图 + Availability | CXO 视图 + Availability |
| Benchmark | 隐藏 | 隐藏 | 隐藏 | Speedtest/Meta | Speedtest/Meta |
| Domain View | FO View | CXO View + BO View | FLM View + SP View | 隐藏 | CXO View |
| GIS Map | alarm/person/mw | 仅 mw（单页，无页签条） | alarm/person/mw | alarm/person/mw | alarm/person/mw |
| Knowledge QA | eflow/rag/assistant | eflow/rag/assistant | eflow/rag/assistant | eflow/rag/assistant | rag/assistant |
| Auto Report | 10 份 | 3 份 | 8 份 | 隐藏 | 隐藏 |
| OSS | 10 项 | 10 项 | 隐藏 | 10 项 | 隐藏 |
| Complaint | 显示 | 显示 | 显示 | 显示 | 隐藏 |
| Escalation | 显示 | 显示 | 显示 | 显示 | 显示 |
| Feedback | 显示 | 显示 | 显示 | 显示 | 显示 |

⚠️ **Benchmark 的隐藏是矩阵语义的结果，不是 bug。** Excel 里 Benchmark 域只勾了
`Speedtest` 与 `Meta`（仅 SMC / CXO），BO/FO/FLM 未勾 → 不显示。
⚠️ **OSS 的「10 项」是 Excel 的条目数**，门户目录里 Friends Link 分组有 11 条 ——
Excel 的「ZTE UME NMSCCN」对应目录里「ZTE UME NMS」+「CCN UME NMS」两条，
「UME iMonitor Screen」对应「UME iMonitor 大屏」+「OCS iMonitor Screen」两条。
`team-scope.js` 的 `OSS_SLOTS` 用 **url 片段**（`page=` / 主机名）匹配槽位，
**不匹配标题** —— 标题在门户目录里是可编辑的，模糊匹配会突然失效。

### 五、遗留与后续

  · **矩阵重新生成的入口**：`python scripts/gen_team_matrix.py`（读 Excel → 写 `team-matrix.js`）。
    Excel 改了必须重跑，否则门户显示的是旧矩阵。**`team-matrix.js` 勿手改**（会被静默覆盖）。
  · **`team_portal` 版 `olbr.js` 由脚本生成**：`scripts/patch_team_portal.py` 读上游
    `v3/olbrportal/assets/olbr.js`，施加 **23 处** scope 钩子，输出 `v3/team_portal/assets/olbr.js`。
    ⚠️ **上游 `olbr.js` 改动后必须重跑该脚本**，否则团队门户的钩子会与上游脱节。
    脚本有 `--check` 模式（只比对不写盘），可挂 CI；钩子原文片段找不到会**报错退出**，
    不会静默漏改。
  · **`v3/team_portal/` 已纳入 `vite.config.ts` 的 `server.watch.ignored`**
    （与 `**/olbrportal/**` 同一处理）—— 它同样是 nginx 直接 alias 的手写静态壳，
    漏在 watch 清单外会导致每次改团队门户的 `olbr.js` 都让 `/uniplam/` 整页刷新一次。
  · **`olbr-data.js`（QC 阈值等）仍是一份拷贝**在 `v3/team_portal/assets/`。
    它内容与上游相同，本次未改；将来若上游调阈值，需同步。
    可改为让 team_portal 直接引上游目录的文件，但 nginx `alias` 下要改相对路径，风险大于收益，本期不做。
  · **`globals.d.ts` 声明了三个团队门户专用全局**
    （`OLBR_TEAM_MATRIX` / `OLBR_SCOPE` / `OLBR_TEAM_REPORTS`）。
    上游 `v3/olbrportal/globals.d.ts` **未加**这些声明 —— 上游那页的 `window` 上
    本来就没有这三个对象，加了反而是给不存在的东西发类型。

## 九之十七、2026-10-29 团队门户访问控制：数据模型 + 服务端闸门 + 登录后跳转

**起因。** 账号被指派到某个团队后，该账号登录 `/v3/olbrportal/` 应**自动跳到**对应的
`/v3/<team>_portal/`；且**只能**进入自己那个团队门户，越权必须被服务端拦下。
上游 `/v3/olbrportal/` 仍是**一行未改**。

**结论：四层纵深防御，最外两层在服务端（不依赖 JS）。**

```
① 数据模型      users.team          'fo'|'bo'|'flm'|'smc'|'cxo'|NULL
② 会话 Cookie   olbr_token (HttpOnly) 登录时种下，登出时清掉
③ 服务端闸门    nginx auth_request → /uniplam/api/auth/team-gate/<team>
④ 跳转          nginx auth_request → /uniplam/api/auth/team-landing（403 + X-Team-Landing）
                 + 注入的 team-gate.js（登录**那一刻**的即时跳转）
```

### 一、数据模型：账号的团队归属

`server/auth/types.ts` 新增 `TeamId`（`'fo'|'bo'|'flm'|'smc'|'cxo'`）与
`TEAM_PORTAL_PATHS`（团队 id → 门户路径的**唯一**映射），
`StoredUser` / `PublicUser` / `PageProfilePatch` 各加一个 `team?: TeamId | null`。

`server/authDb.ts` 的 `users` 表加 `team TEXT` 列。⚠️ **老库必须迁移**：
`CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作，只改 schema 声明的话
新库有 `team`、老库没有，`saveUsers` 的 INSERT 会整批失败 ——
症状是「改了团队归属，保存后刷新又变回去」，且**只在老库上复现**。
故 `migrateSchema()` 查 `PRAGMA table_info(users)`，缺列就 `ALTER TABLE ADD COLUMN`
（幂等，每次启动都跑一遍）。本机实测迁移日志：
`[auth-db] 已为 users 表补加 team 列（团队归属，2026-10-29）`。

**取值语义**：`null` = 未指派 = **不跳转、且五个团队门户一律不放行**（fail-closed）。
没配置就没有团队身份，凭什么看某个团队的内容。

### 二、为什么要 Cookie 副本：让服务端在**页面导航**时也能认出用户

门户的会话 token 历来只存 **localStorage**（键 `liberia_noc_auth_v1`）。
但浏览器**直接访问一个 URL** 时不会带 localStorage 里的任何东西 ——
nginx 在处理页面请求时**看不到**登录态。若团队门户是静态文件（nginx alias 直发），
它自己的 JS 要到浏览器里跑完才知道身份，**那时内容已经发到客户端了** ——
那不是访问控制。

故登录成功时把**同一个 token** 再种一份 Cookie（`HttpOnly; SameSite=Lax; Path=/`）：
`server/auth/types.ts` 的 `setSessionCookie()` / `clearSessionCookie()` /
`readSessionToken()`（Authorization 头优先、Cookie 其次）。

⚠️ **两份是同一个 token 的两个载体，不是两份真相源。**
localStorage 那份**保留不动** —— 前端既有逻辑（`apiFetch` 附带 Authorization 头、
`viewer.html` 读同一个键）都依赖它。Cookie 由服务端种、由服务端清，前端 JS 读不到。

⚠️ **Cookie 里绝不能放团队 id。** 团队归属是**库里的属性**，管理员随时能改。
若把团队 id 也写进 Cookie，管理员改了归属而用户的旧 Cookie 还在时，
nginx 会按**过期的**团队 id 放行 —— 那正是权限事故。故 nginx 必须**回源问服务端**
「这个人现在属于哪个团队」。

### 三、服务端闸门：`auth_request` + `team-gate`

五个团队 location 各带一条闸门：

```nginx
location /v3/fo_portal/ {
    alias  ".../v3/team_portal/";
    auth_request /uniplam/api/auth/team-gate/fo;
    error_page   401 = @team_unauthorized;   # 未登录
    error_page   403 = @team_forbidden;       # 已登录但不是该团队
}
```

`GET /uniplam/api/auth/team-gate/<team>` 的判定（**fail-closed**）：

| 情形 | 状态码 | nginx 行为 |
| --- | --- | --- |
| 没有身份 | 401 | 回 401，页面引导登录 |
| 有身份、无团队归属 | 403 | 回 403 拒绝页 |
| 团队与请求的不一致 | 403 | 回 403 拒绝页 |
| 完全一致 | 200 | 放行 |

⚠️⚠️ **为什么用路径参数（`/team-gate/fo`）而不是查询参数（`?team=fo`）**
—— 这是本机 2026-10-29 实测踩出来的坑，不是风格偏好：

nginx 的 `auth_request` 指令里写的 URI 会被当成**内部子请求的 URI**，
其中出现的 `?` **不会被当作查询串分隔符**，而是被转义进路径里。
实测（独立 nginx 实例 + 回显上游）上游收到的是：

```
auth_request /probe?team=fo  →  上游看到 url = "/probe%3Fteam=fo"
```

也就是说 `?` 变成了 `%3F`，**后端拿不到 team 参数** → 后端返回 400 →
nginx 把非 2xx 当作拒绝 → **「合法用户访问自己的团队门户」被误判成 401**。
改成路径形式后子请求 URI 是干净的 `/team-gate/fo`，后端从路径末段取团队 id。

⚠️ **这两个 nginx 端点必须放在「未登录就 401」那道闸门之前**（`routes.ts` 里
`if (!caller)` 之前），原因有两条：
  ① nginx 的 auth_request **子请求不带 Authorization 头** —— 只带原始请求的 Cookie。
     `resolveCaller` 只认 Authorization 头，若放在闸门之后，caller 恒为 null →
     一律 401 → 「已登录但团队不对」与「压根没登录」被混成同一个结果。
     故这两个端点**自己**用 `readSessionToken()` 解析身份。
  ② `/team-landing` 的语义是「无团队归属 → 200 放行；未登录 → 也 200 放行」，
     若被闸门拦成 401，nginx 会当成拒绝 → 主门户对未登录用户也 401，
     那就把「主门户是公开入口」这个既有行为改掉了（回归事故）。

### 四、跳转：服务端 302（打开页面时）+ 客户端即时跳转（登录那一刻）

**服务端 302。** `/v3/olbrportal/` 带 `auth_request /uniplam/api/auth/team-landing`。
该端点：有团队归属 → **403** + `X-Team-Landing: /v3/fo_portal/`；
无归属或未登录 → **200**（无该头）。

⚠️ **为什么「有归属」要用 403 这个反直觉的状态码。** auth_request 没有
「拒绝但带信息」的第三种状态，只有 2xx / 非 2xx。我们要表达的是
「**别在这里服务，去那边**」—— 用 403 触发 `error_page 403 = @named`，
在 named location 里 `return 302 $team_landing`（content 相位，
`$upstream_http_x_team_landing` 已就位）。若返回 2xx，nginx 直接放行，
根本不会去看响应头。

⚠️⚠️ **相位陷阱（本机实测，2026-10-29）—— 这段写法为什么长这样**

nginx 的指令分属不同相位：
  · `if` / `return` → **rewrite 相位**（最早）
  · `auth_request`  → **preaccess 相位**（靠后）

故在同一个 location 里写 `auth_request ...; if ($v) { return 302 $v; }` 是**无效的**：
`if` 在 rewrite 相位就返回了 302，`auth_request` 根本没跑，$v 永远是空 →
实测得到 200 而不是 302。正确写法：**location 里不写 return**，让请求走完完整相位链；
用 `error_page` 把上游的 403 导向 named location，在 named location 里 return 302。

**客户端即时跳转。** 上面那套只覆盖「**打开页面时**」——
而「首次登录」这条路走不到它：用户打开本页时还没有 Cookie → nginx 放行
（主门户是公开入口）→ 用户在页面上填账号密码 → **页面早已加载完毕**，
nginx 那次请求早就结束了。nginx 无法拦截页面里发出的登录请求。

故新增 `v3/team-gate.js`：包住 `window.fetch`，盯住 `POST /uniplam/api/auth/login`
的响应，响应体里带 `user.team` → `location.replace('/v3/<team>_portal/')`。
三条触发路径：① 本地已有 token（刷新/收藏夹进入）→ `GET /api/auth/me` 取 team；
② 本地无 token → 不跳（还没登录，主门户是公开入口）；③ 登录成功那一刻 → 跳。

⚠️ **`clone()` 在 Response 上，不在 Promise 上。** `rawFetch()` 返回
`Promise<Response>`，`clone` 要等 Promise 兑现后才有。写成 `p.clone()`（p 是 Promise）
→ `clone is not a function` → 静默失败，登录成功却不跳转。必须用
`.then(function (res) { res.clone().json() ... })`。

**⚠️ 上游 `/v3/olbrportal/` 一行未改。** `team-gate.js` 由 nginx 用 `sub_filter`
在**响应下发时**注入 `</head>` 前（磁盘上的 `index.html` 一个字节都没动）：

```nginx
sub_filter_once on;
sub_filter '</head>' '<script src="/v3/team-gate.js"></script></head>';
```

注入点选 `</head>` 是因为它在 `olbr.js`（`</body>` 前的 `<script>`）**之前**，
这样脚本能赶在 olbr.js 发登录请求之前把 fetch 包起来。
脚本本体放在 `v3/team-gate.js`（**不在** `v3/olbrportal/` 里 —— 那一页不许改；
**不在** `v3/team_portal/` 里 —— 那五个 location 带闸门，未登录时连脚本都取不到，
而闸门页恰恰要引导去登录）。该 location **不加** `auth_request`：
它是公开静态脚本，不含任何敏感信息；真正的访问控制在服务端，与它无关（两者不重复）。

### 五、管理界面（**三个入口都支持**）

**关键前提：三处面板改的是同一行记录。**
`/uniplam/`、`/v3/olbrportal/`、`/myapp/` 的 User Management 都调
`/uniplam/api/auth/users` 与 `/uniplam/api/auth/users/profile` ——
**同一个门户后端、同一份 `auth-data/portal-auth.db`**。
my_app 虽有独立的会话表（`portal_sessions`，见 `backend/services/portal_auth.py`），
但**账号数据一律回调门户**，不落地第二份用户库。

三处面板各有独立实现，需要**同步维护**：

| 入口 | 实现文件 | 风格 |
| --- | --- | --- |
| `/uniplam/` | `src/components/UserManagementModal.tsx` | React 19 + Tailwind |
| `/v3/olbrportal/` | `v3/olbrportal/assets/olbr.js` | 原生 JS 手写面板 |
| `/myapp/` | `Task/my_app/frontend/src/components/PortalUserMenu.tsx` | React + Ant Design |

每处都加了「Team Portal / 团队门户」下拉框（`um.team` / `um.teamNone` / `um.team.<id>`，
中英两份字典都已加），提交时走 `POST /uniplam/api/auth/users/profile` 的 `team` 字段。

⚠️ **团队的「id → URL」映射在三处各有一份字面量**（后端 `server/auth/types.ts`
的 `TEAM_PORTAL_PATHS` 是唯一真相源）：
  · `src/auth/AuthContext.tsx` 的 `TEAM_PORTAL_PATHS`
  · `v3/olbrportal/assets/olbr.js` 的 `UM_TEAMS`
  · `Task/my_app/frontend/src/api.ts` 的 `TEAM_PORTAL_PATHS`
  · `v3/team-gate.js` 的 `TEAM_PORTAL`（纯静态脚本，不能 import 后端模块）
**改一处必须改其余各处。**

⚠️ **my_app 的 `landing` 字段类型曾与后端不一致**：后端存的是**对象**
`{view?, cardId?}`（`LandingTarget`），而 my_app 的 `PortalUser.landing` 声明成了
`string`。于是列表里 `{u.landing}` 把对象当子节点渲染 —— React 抛
**#31**（"Objects are not valid as a React child"）**整个页面白屏**。
2026-10-29 已修：类型改为 `PortalLandingTarget`，渲染走 `landingLabel()`，
编辑区改为「视图下拉 + 卡片 id 输入」两个字段（服务端按**整对象**替换，故一起提交）。


### 六、实测结果（2026-10-29，本机 9267 + nginx 80/443）

端到端脚本覆盖 65 项断言，**全部通过**：

| 场景 | 期望 | 实测 |
| --- | --- | --- |
| 五个团队账号登录 | 拿到 `olbr_token` Cookie，响应体带 team | ✅ |
| 带团队身份访问 `/v3/olbrportal/` | 302 → `/v3/<team>_portal/` | ✅ |
| 无团队归属 / 未登录访问主门户 | 200（不跳转） | ✅ |
| 访问**本**团队门户 | 200 | ✅ |
| 访问**他人**团队门户（20 组交叉） | 403 | ✅ |
| 未登录访问团队门户 | 401 | ✅ |
| 无团队归属账号访问团队门户 | 403 | ✅ |
| `sub_filter` 注入 | 首页含 `/v3/team-gate.js`，且在 `</head>` 前 | ✅ |
| 磁盘上的 `v3/olbrportal/index.html` | **不含** team-gate.js（未改动） | ✅ |

浏览器实测：清掉 localStorage 后在页面上登录 `team_fo` 账号 →
**自动跳到 `https://127.0.0.1/v3/fo_portal/`**；页面内 `window.OLBR_SCOPE.teamId`
为 `fo`，作用域与 Excel 矩阵一致（QC = alarm/cr/tt/wo，Domain View = FO View，
OSS = 10 项，Auto Report = 10 份）；同会话 fetch `/v3/bo_portal/` → **403** 拒绝页。

### 七、遗留与后续

  · **测试账号已删除。** 验证用的 `team_fo`/`team_bo`/…/`team_admin` 七个账号
    （口令已知）在验证结束后**立即从 `auth-data/portal-auth.db` 删除** ——
    留一个已知口令的账号在生产库是事故，不是遗留。
  · **`team-gate.js` 与后端的团队映射是两份字面量**（纯静态脚本不能 import 后端模块）。
    后端那份是 `server/auth/types.ts` 的 `TEAM_PORTAL_PATHS`（唯一真相源）；
    脚本那份在 `v3/team-gate.js` 的 `TEAM_PORTAL`。**改一处必须改另一处**。
  · **免登录旁路（开发模式）下团队门户一律 401** —— 免登录是「跳过登录」，
    不是「变成某个团队的人」。要在免登录模式下调试团队门户，正确做法是给测试账号配好 `team`。
  · **`v3/team-gate.js` 不在 `vite.config.ts` 的 `server.watch.ignored` 清单里** ——
    它在 `v3/` 根目录，不在 `v3/team_portal/` 或 `v3/olbrportal/` 里，
    故不在那两个 watch 忽略规则覆盖范围内（改它会触发一次 `/uniplam/` 整页刷新，可接受）。
  · **团队归属变更不即时踢下线。** 管理员改了某账号的 `team` 后，
    该账号**已登录的会话**在下一次访问团队门户时立刻按新归属判定
    （闸门每次都回源查库），但**主门户的 302 目标**同样每次重算 ——
    即**改归属立即生效，无需重新登录**。

### 八、三处管理入口补齐（2026-10-29 追加）

**起因**：原先只有 `/uniplam/` 能配置 Team Portal。管理员问「为什么只有这一个能调」——
根因是**三套前端各自实现了 User Management 面板**，而当时只改了 React 那套。
数据源本就是同一个（都走 `/uniplam/api/auth/*`），缺的只是控件。

本轮改动：

| 文件 | 改动 |
| --- | --- |
| `v3/olbrportal/assets/olbr.js` | 面板加团队下拉框（`UM_TEAMS` 映射 + `state.um.team` + 提交 `team` 字段 + change 事件委托） |
| `v3/olbrportal/assets/olbr-data.js` | 中英两份字典加 `um.team*` 六个键 |
| `Task/my_app/frontend/src/api.ts` | `PortalUser` 加 `team`；`landing` 类型改 `PortalLandingTarget`；`portalSetUserProfile` 的 patch 加 `team` |
| `Task/my_app/frontend/src/components/PortalUserMenu.tsx` | 面板加团队下拉框 + 表格加「团队门户」列；修 React #31 白屏 |
| `Task/my_app/frontend/src/i18n.tsx` | 中英两份字典加 `user.team*` 与 `user.landingView` / `user.landingCard` |

实测（三处面板，浏览器逐个点开确认）：

| 入口 | 下拉框选项 | 保存 | 列表显示 |
| --- | --- | --- | --- |
| `/uniplam/` | 未指派 + 5 个团队 | ✅ | — |
| `/v3/olbrportal/` | 未指派 + 5 个团队 | ✅（"Saved page setup for admin"） | — |
| `/myapp/` | 未指派 + 5 个团队 | ✅ | 表格「Team portal」列显示 `ZTE FLM Team` |

**零改动约束仍然成立**：`v3/olbrportal/index.html` 一行未动
（团队面板是 `olbr.js` 里的运行时渲染，不是页面内联）。


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
