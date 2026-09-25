# 鉴权与用户管理模块化设计（评审修订稿）

> 基准日期：2026-09-23　|　**2026-09-25 按评审意见修订，修订条目见第十节**　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 状态：**阶段 1 与阶段 2 已于 2026-09-25 执行完成**（执行记录见第十一节）。阶段 3（权限模型扩展）前提已明确，待排期。
> 上级：`AGENTS.md`（工作区总纲）、本目录 `AGENTS.md`、`architecture.md` 第八节

## 一、结论先行：这不是"要不要做"，而是"边界收口"

用户提出的诉求是「把用户管理与登录鉴权单独做一个模块，后面能很快加到新增的页面上」。核查代码后的结论：

**该模块已经存在且已验收**（`docs/TODO.md:17` 标注「鉴权 / 用户管理 / 改密 — 已验收」）。因此本设计**不新建模块**，只做两件事：

1. **收口契约** —— 把「新页面接入鉴权」从"读源码自己悟"变成"照抄一个显式契约"；
2. **修正边界** —— 现有代码存在 4 处会阻碍后续扩展的结构问题（见第三节），不改掉的话，"很快加"会越来越慢。

### 现有家底（实测，非推测）

| 层 | 文件 | 行数 | 已有能力 |
| --- | --- | --- | --- |
| 前端上下文 | `src\auth\AuthContext.tsx` | 317 | `status`/`user`/`login`/`logout`/`apiFetch`/`realLogin`，另有 `updateUser`/`setToken`/`authEnabled`/`refreshAuthMode` |
| 后端主逻辑 | `server\auth.ts` | 928 | scrypt、会话、限流、申请审批、白名单、路由分发、**免登录旁路** |
| 持久化 | `server\authDb.ts` | 734 | SQLite（WAL + 备份）+ JSON 回退；**建表只有 `CREATE TABLE IF NOT EXISTS`，全文件无 `ALTER TABLE`**（见阶段 3 前置 B） |
| 鉴权开关 | `server\authSwitch.ts` | 282 | 与 my_app 共享 `auth-switch.json`，含生产保护 |
| 门户其他端点的守卫 | `vite.config.ts:111-121` | — | `portal-default` 的 POST 自己写了一遍 Bearer→会话→旁路→role 判断，**是 `auth.ts` 同一套决策的第二份副本** |
| 手写静态壳 | `MsPortal\assets\portal.js`<br>`olbrportal\assets\olbr.js`<br>`v1\olbrportal\assets\olbr.js`<br>`MsPortal\assets\access.js` | 6905<br>3918<br>4780<br>133 | **各自完整的登录、`/me` 探针、登出、用户管理界面与白名单判定** —— 不是待建项，详见第二节形态 B |
| 跨系统 SSO | `Task\my_app\backend\services\portal_auth.py` | 522 | **真实的 token 回调校验**，非透传 |
| UI | `LoginView` / `UserManagementModal` / `ChangePasswordModal` / `AuthSwitchModal` / `PasswordInput` | — | 均在 `src\components\`，已实现 |

> **本次修订更正的第一处判断**：初稿的家底表只盘了 React 侧，把静态壳当成「拿不到 `AuthContext`、要专门适配层」的空白区。实测**四份壳文件都已各自实现完整鉴权**，加上 React 侧，同一份鉴权契约目前有 **5 份独立实现**。这反转了第二节的成本分级，也是第三节问题 4 的由来。

**已经具备复用价值的三个基础设施**（这是本次设计的地基，不是待建项）：

- `AuthProvider` 已在 `src\main.tsx:11` 包裹全树 → 任何新 React 页面 `useAuth()` 即可用；
- `apiFetch` 自动注入 `Bearer`，**任意请求 401 自动清会话回登录态**（`AuthContext.tsx:273-282`）——这正是"加到新页面就自动有鉴权"的目标形态；
- 后端路由已双挂载 `/api/auth` 与 `/uniplam/api/auth`（`vite.config.ts:192`），经 nginx 与直连行为一致。

## 二、「新页面接入契约」（本设计的核心交付物）

按新页面的**三种形态**分别定义接入方式。**这三种形态成本差异极大，选错会白做**。

### 形态 A：门户内的新 React 视图/页

门户目前是**单页四视图**（`grid`/`list`/`matrix`/`tasks`，服务端白名单见 `server\auth.ts:22-23`），**不是多路由结构**。

接入成本：**低**。

```tsx
// 1) 取身份（Provider 已全局包裹，零配置）
const { user, apiFetch } = useAuth();

// 2) 守卫：当前是 App.tsx:727-739 手写的两个 if，应抽成 <RequireAuth>
if (status === 'anon') return <LoginView />;   // 目标形态：<RequireAuth> 包一层

// 3) 调后端：一律走 apiFetch + PORTAL_API（绝不写 /api/*，否则 405）
const res = await apiFetch(`${PORTAL_API}/xxx`);
```

> **注意**：新增"视图"与新增"独立路由页"工作量差别很大。当前无路由库，若要做真正的多页面，需先引入路由（属新增依赖，按工作区原则第 7 条须先核查既有依赖）。**建议先明确这一点再动工。**

### 形态 B：`MsPortal\` / `olbrportal\` / `v1\olbrportal\` 类手写静态壳 ——**已实现，但是另外四份实现**

这些壳是手写静态 HTML + JS，**不是 React**，拿不到 `AuthContext`。初稿据此判断「很快接上目前不成立，需要专门的适配层」，**这条判断是错的**：适配层早就写好了，而且不止一份。

| 壳 | 已有实现 | 证据（实测行号） |
| --- | --- | --- |
| `MsPortal\assets\portal.js`（6905 行） | 登录、`/me` 探针、门户+my_app 双路登出、**完整用户管理界面**、按 `allowedGroups`/`allowedCards` 过滤 | `:4115` 登录、`:4157` `/uniplam/api/auth/me`、`:4166-4167` 登出、`:4278` `UM_API='/uniplam/api/auth'`、`:1007` 主体字段 |
| `olbrportal\assets\olbr.js`（3918 行） | 同时探门户与 my_app 两个 `/me`、登录登出、`state.um` 用户管理、回写白名单 | `:2311-2330`、`:2360`、`:2378-2380`、`:2581`、`:2948` |
| `v1\olbrportal\assets\olbr.js`（4780 行） | 同上，且**带类型**（`tsconfig.json` + `globals.d.ts`，`npm run lint:shells` 校验） | `:2903-2914`、`:3007` |
| `MsPortal\assets\access.js`（133 行） | FineBI 侧独立判定放行，已区分 `null`（未设限）与命中语义 | `:8`、`:114-121` |

`MsPortal\viewer.html_bak_20260920_查看器权限收口已验收` 这份快照名就是它的验收记录；`portal.js:323`/`:1065` 的注释还明确写了「本页只通过 `/uniplam/api/auth/*` 读写，所以两边改完立刻互相可见」——**壳侧与 React 侧同库同语义是既有设计意图，不是待建能力**。

接入成本：**复用低 / 改语义高**。新壳页面照抄 `portal.js` 的探针与登录即可，不需要新适配层。真正的成本在另一处：**同一契约现在 5 份实现，靠注释和人肉保持一致**，任何一次语义变更都要改 5 处，漏一处就是「React 侧管住了、壳侧照样能看」（第三节问题 4）。

**两个必须在动工前查清的事实差异**：

1. **`MsPortal` 到底由谁发布？** 初稿写「由 `nginx.conf:102/108` 直接 alias 发布」，实测只有 `olbrportal`（`:102`）与 `v1/olbrportal`（`:108`）在 nginx 里有 `location`；本仓库 `nginx.conf` **没有任何 `MsPortal` 的 `location`**，而 `vite.config.ts:217`（`/MsPortal/` 的用户管理接口一起 502）与 `:223-229`（改 `MsPortal/assets/*.js` 触发 `/uniplam/` 整页刷新）都表明它是**跟着 9267 的 vite 进程发的**。差别是实打实的：`olbrportal` 是纯静态，`MsPortal` 随 dev server 重启而有空窗。注意 `vite.config.ts:223-224` 的注释写着三者都「线上由 nginx 直接发静态文件」，与本仓库 `nginx.conf` 对不上 —— **先核实，再修正其中一处**（工作区总纲原则 3「改前先读，别猜」）。
2. **壳侧没有共同类型或测试**。四份 JS 实现只靠字符串契约对齐（`v1` 那份有 `globals.d.ts`，但它是独立 tsconfig），阶段 3 的字段扩展不能指望前端一致，**必须在服务端加校验兜底**（见前置 A）。

### 形态 C：远程系统深链（my_app 等）——**已实现**

这条路线**已经是完整可用的**，且实现质量高于预期，不是需要新建的部分：

```
门户登录 → localStorage.liberia_noc_auth_v1 取得 Bearer token
        → 深链拼 ?t=<token>（src\config.ts:141 getMyappLink / :170 resolveUrl）
        → my_app GET /api/auth/portal-login {token}
        → my_app 回调门户 GET /uniplam/api/auth/me 验证（portal_auth.py:315）
        → 验证通过签发 my_app 自己的 HttpOnly Cookie（portal_auth.py:334）
        → 门户 token 只进门一次，不落在 my_app 侧
```

这套设计是**正确的**：my_app 不信任 token 内容，而是回调门户验证；且门户 token 是内存态、无签名、my_app 无法离线验证——回调是唯一正解。**新接一个远程系统照抄这条链路即可**，这是三种形态里最成熟的。

## 三、必须先修的 4 个结构问题

### 问题 1：`server\auth.ts` 928 行，越过本项目 500 行红线

工作区原则第 2 条明确「新增/新建文件单个不超过 500 行」。该文件混了 **6 类职责**：用户 CRUD、账号申请审批、会话管理、登录限流、免登录旁路（`isAuthBypass` / `DEV_ADMIN`，`:565-589`）、HTTP 路由分发。

**影响**：继续往里加路由会先撞到这堵墙；新页面接入要在 928 行里找位置插 `if`。

### 问题 2：鉴权守卫没有独立入口，而且后端已经出现第二份副本

- **前端**：守卫硬编码在 `App.tsx:727-739`（`loading` 与 `anon`/`!user` 两个 `if`）。新页面无法"声明式"地要求登录，只能复制粘贴那段 `if`。
- **后端**：`vite.config.ts:111-121` 为 `portal-default` 的 POST 又写了一遍 `extractBearerToken` → `getUserByToken` → `isAuthBypass` → `role !== 'admin'` → 401/403，并在 `:87-91` 本地重新定义了 `sendJson`。这与 `auth.ts` 路由里的判断是**同一套决策的两份实现**，两份的旁路写法还不一致：`auth.ts:571` 用现成的 `DEV_ADMIN` 整体对象，`vite.config.ts:113` 现场造了个 `{role: 'admin'}`。

> 初稿只列了前端那一条。**后端这份副本才是 `guard` 收口最实的收益**：它每天跟着 `auth.ts` 的语义漂移，而现在没有任何机制能发现漂移。

### 问题 3：白名单在服务端**根本不生效**，页面级授权无从谈起

初稿写的是"权限模型表达不了页面级可见性"。**更准确的诊断是：现有白名单根本不构成权限边界。**

现有模型：`role`（仅 `admin`/`viewer` 两值）+ `allowedGroups` / `allowedCards` 白名单（`server\auth.ts:41-53`）。

- 字段定义、归一化、持久化都在服务端（`auth.ts:41-53` 定义、`:127` `sanitizeNames` 归一化、`authDb.ts:194-195` 落列），但**拒答不发生在服务端**：可见性过滤完全在浏览器里做（`App.tsx:635-645` 的 `filter`），服务端只负责在 `/me` 里回一份带白名单的主体。
- 因此"谁能看哪些看板"目前只是 UI 层的显示规则：任何能打开控制台的人都能拿到全量目录并绕过过滤。第五节 **S4 是同一件事的另一面** —— `portal-default` 的 GET 连登录都不要求。

**结论**：`allowedPages` 若不与服务端拒答同时落地，就是第 5 个只做装饰的字段，还会让后来者误以为"页面级权限已经有了"。**阶段 3 必须先回答「谁在服务端拒答」，再回答「加哪个字段」。**

### 问题 4：同一份鉴权契约有 5 份实现，靠人肉同步

`AuthContext.tsx`、`MsPortal\assets\portal.js`、`olbrportal\assets\olbr.js`、`v1\olbrportal\assets\olbr.js`、`MsPortal\assets\access.js` 各自实现了「取 token → 探 `/me` → 按 `null` / `[]` / 数组三态判定可见范围」。五份之间没有共同类型、没有共同测试，只靠注释对齐（`portal.js:323`、`auth.ts:160`、`authDb.ts:318` 三处各写了一遍同一条三态语义）。

**影响**：这才是"很快加到新页面"的真实瓶颈 —— 不是接不上，而是**每加一个面，就多一处会漏改的地方**。

**收口方式不是把五份合成一份**（静态壳不能引 React 代码，合并要引入构建步骤，见第六节），而是把契约变成两份可核对的东西：

- **契约面**：`GET /uniplam/api/auth/me` 的响应字段与三态语义，写进 `architecture.md` 第八节，作为唯一规范文本；
- **强制面**：服务端对不可见资源直接拒答（问题 3），使五份前端的过滤退化为纯体验优化 —— 漏改不再等于越权。

## 四、分阶段方案（评审通过后执行）

### 阶段 1：拆分后端 + 抽出守卫（不改行为）

```
server/auth/
  ├── types.ts      类型与常量：Role / PortalViewMode / LandingTarget / StoredUser /
  │                 PublicUser / PageProfilePatch / RegistrationRequest / Session /
  │                 各上限值 + toPublic / toPublicRequest
  │                 （现 auth.ts:19-101、152-177 —— 见下方"237 行归属"）
  ├── password.ts   scrypt 哈希与校验（现 auth.ts:104-124）
  ├── store.ts      AuthStore 类：用户 / 申请 / 会话 / 限流（现 auth.ts:193-511）
  ├── guard.ts      resolveCaller(req) + 免登录旁路  ← 新页面复用的唯一入口
  └── routes.ts     HTTP 路由分发与 vite 插件挂载（现 auth.ts:127-151、179-191、
                    515-558、560-910、912-928）
```

**「237 行归属」是本次修订补上的**（初稿的拆分表只覆盖了 691 行：21 + 319 + 351）。剩下的 237 行若不指认归属，拆完必然留一个装杂物的大文件，`< 500 行` 的验收形同虚设。

**`guard` 不能按 Express 中间件设计**（初稿写的 `requireAuth / requireAdmin 中间件` 在本仓库做不出来）：门户后端是 vite 的 connect 中间件，`server.middlewares.use(path, (req, res) => ...)`，**没有 `next()`**（见 `vite.config.ts:85`、`:176`、`auth.ts:912`）。守卫必须写成显式解析 + 调用方自己回包的形态：

```ts
// guard.ts —— 解析调用者（含免登录旁路），返回 null 表示未登录
export function resolveCaller(req: IncomingMessage, store: AuthStore): PublicUser | null
```

配套收口两件事，都属本阶段：

1. `vite.config.ts:111-121` 那份副本改调 `resolveCaller`（问题 2），`sendJson` 也不再本地重定义；
2. **免登录旁路统一归属 `guard.ts`**，消除 `auth.ts:565-589`（用 `DEV_ADMIN`）与 `vite.config.ts:112-113`（现造 `{role:'admin'}`）的两种写法。

**关键**：`server\auth.ts` 已是既验收模块，拆分属**纯结构重构，行为必须零变化**。按工作区原则第 9 条，动大文件前先建 `_bak_<当天日期>_鉴权拆分前` 快照（初稿写的 `20260923` 是本文档基准日，执行时按当天命名），拆完跑完整回归：`npm run lint` + `npm run build` + 第七节验收表列出的**五条**手工链路（初稿正文写"四条"、验收表写"五条"，本次统一为五条，含免登录模式）。

### 阶段 2：前端守卫组件化 + 契约文本化

- 抽出 `<RequireAuth>` 与 `<RequireAdmin>`（替换 `App.tsx:727-739` 的两个裸 `if`）；
- 提供 `src\pages\_TemplatePage.tsx` 作为新页面模板。
- **把契约写成文本**（问题 4 的"契约面"，否则四份壳永远只能靠注释对齐）：在 `architecture.md` 第八节补一节「鉴权契约」，内容就两样 —— `GET /uniplam/api/auth/me` 的响应字段清单，与 `null` / `[]` / 数组的三态语义。壳侧没有类型系统，**文档是它们之间唯一的共享接口定义**。

> **⚠ 下划线模板文件会被 git 静默忽略 —— 本次修订实测推翻初稿的保证。** 初稿写「参照 my_app 的先例，`_*` 规则不得误伤它」，但两边的规则形态根本不是一回事：门户 `.gitignore:29` 是**非根锚定**的 `_*`（任意层级匹配），`:30-33` 的反向豁免只写了 `!src/_*` 与 `!server/_*`，而 gitignore 的 `*` **不跨 `/`**，豁免够不到 `src/pages/`。my_app 那边用的是根锚定 `/_*`（工作区总纲第四节第 4 条明确写了"刻意没有写成 `**/_*`"），本来就碰不到 `pages/` 下的文件 —— **类比不成立**。
>
> 机器验证（`git check-ignore -v`）：
>
> ```
> $ git check-ignore -v src/pages/_TemplatePage.tsx
> .gitignore:29:_*        src/pages/_TemplatePage.tsx     ← 被忽略，永远进不了库
> $ git check-ignore -v src/_Test.tsx
> .gitignore:32:!src/_*   src/_Test.tsx                   ← 豁免生效
> ```
>
> 落地三步，缺一步就会重演总纲第七节记录的"提交后才发现"：
>
> 1. `.gitignore` 豁免改成可递归：`!src/**/_*`、`!server/**/_*`；
> 2. **同步 `vite.config.ts` 的 watch 清单**：`:264` 有 `'**/_*'` 这条忽略，`:236-237` 写着「已确认 src/ server/ assets/ 下没有任何以 `_` 开头的文件」—— 建完模板这句就过期了。`.gitignore` 与 watch 清单是**同一套判断的两个副本，改一个必须改另一个**（总纲第四节第 4 条）；
> 3. 把「模板文件真的进了 git 视野」写进阶段 2 验收（见第七节），用 `git check-ignore -v` 无输出 + `git status --porcelain` 能看到该文件双向确认。

### 阶段 3：权限模型扩展（两条前置，缺一条就是空中楼阁）

**前置 A —— 服务端拒答**（问题 3）。在 `guard.ts` 之上，让返回受控清单的端点按调用者白名单裁剪或直接 403，使五份前端的过滤降级为体验优化。这条不做，`allowedPages` 只是第 5 个装饰字段。

**前置 B —— `authDb` 的列升级（本次修订新增，且是硬阻断）。** `authDb.ts:186-195` 只有 `CREATE TABLE IF NOT EXISTS`，**全文件没有任何 `ALTER TABLE`**（已 grep 验证），而 `:347` 的 INSERT 是显式列清单。在**已存在的现网库**上新增 `allowed_pages` 的后果是：建表语句被跳过 → INSERT 引用不存在的列 → **用户管理的所有写操作直接报错**（建号、改密、增删一起废）。门户侧没有 alembic，必须自己写幂等自愈：

```ts
// 启动时：PRAGMA table_info(users) 探测，缺列则 ALTER TABLE users ADD COLUMN allowed_pages TEXT
```

并把这条明确列入阶段 3 回归：**必须在一份旧的 `portal-auth.db` 副本上跑一次启动**，验证缺列自愈 + 老账号数据不丢 —— 删库重建不算通过。

**字段本身**，语义对齐现有 `allowedGroups`（`null` = 不限制，`[]` = 什么都不给看，两者必须区分；同一条语义已在 `auth.ts:160` 与 `authDb.ts:318` 各写过一遍注释）：

```ts
allowedPages?: string[] | null;   // 页面级白名单
```

**但先回答「页面指什么」**（第八节待确认事项 2）。现有模型里已经有三个维度能承载"页面"：`landing.view`（四个门户视图，服务端有 `PORTAL_VIEW_MODES` 白名单校验，`auth.ts:22-23`）、`allowedCards`（**按看板卡片授权，本身已是单页粒度**）、`allowedGroups`（按分组）。若新页面就是这四个视图之一或某张卡片，再加 `allowedPages` 就是**叠在现有维度上的第二真相源**。真正需要新字段的只有一种情况：门户引入路由之后的**独立页面**（第二节形态 A 的注意事项）。

**配套改动清单（阶段 3 全量，初稿只列了第 1、3 条）**：

| # | 面 | 改哪里 |
| --- | --- | --- |
| 1 | 服务端 | `StoredUser` / `PublicUser` / `PageProfilePatch` / `toPublic`（`auth.ts:41-67`、`:152-163`）、`setProfile`（`:311`）、新增 `sanitizePages` 归一化（对齐 `sanitizeNames:127`） |
| 2 | 持久化 | `authDb.ts` 列升级（前置 B）+ `UserRow`（`:160-170`）+ 读（`:318-319`）写（`:347-370`）两处 |
| 3 | React | `AuthContext.tsx:35-39` 字段 + `UserManagementModal` 勾选区 + `i18n.tsx` 的 `zh` 与 `en` 两份字典同时加键（本项目硬性约束第 2 条） |
| 4 | **静态壳四处** | `MsPortal\assets\portal.js`（`UM_API` 那套界面，`:4278`）、`olbrportal\assets\olbr.js`（`state.um`，`:2581`、`:2948`）、`v1\olbrportal\assets\olbr.js`（同构）、`MsPortal\assets\access.js`（`:114-121` 的放行判定）—— **漏一处即"React 管住、壳侧照样能看"** |
| 5 | 强制面 | 服务端拒答（前置 A）与列升级（前置 B） |

## 五、本次核查发现的安全问题

以下问题**多数不在本次需求范围内**（例外是 S4，它就是阶段 3 前置 A 的另一面），但核查中确实发现，按工作区原则第 8 条（保留已知缺陷上下文）必须记录：

| # | 问题 | 位置 | 说明 |
| --- | --- | --- | --- |
| S1 | **门户 token 经 URL query 传递** | `src\config.ts:141,170` | `?t=<token>` 会进入浏览器历史、Referer 头、nginx access log。token 本身是 64 hex 内存态凭证，泄漏后可直用到 12h 滑动续期结束 |
| S2 | 会话仅存门户进程内存 | `server\auth.ts:94-99` | 门户进程重启 → 全部会话失效（my_app 侧已用 SQLite 落盘解决，门户侧未做）。日常运维重启会打断所有在线用户 |
| S3 | **限流与申请配额在 nginx 之后共用同一个 IP 桶**（本次修订由"可能"改为**已证实**） | `server\auth.ts:592,620` | 代码只读 `req.socket.remoteAddress`。nginx 在 `location /uniplam/` 明确设了 `X-Real-IP` 与 `X-Forwarded-For`（`nginx.conf:360-366`）而门户**不读它们**，且 nginx 与 9267 同机 —— 所以**所有经门户访问的用户共用 `'127.0.0.1'` 这一个桶**。后果不是初稿写的"互相误伤"，而是：任何人连续 10 次登录失败 → **全站登录锁死 60s**（`LOGIN_MAX_FAILURES=10` / `LOGIN_LOCK_MS=60_000`，`:100-101`）；`MAX_PENDING_PER_IP=5`（`:91`）同步退化成**全站只能有 5 条待审申请**。且计数只在内存，重启清零（同 S2）。修法只有几行：只信任本机 nginx 前置时取 `X-Real-IP` |
| S4 | **全局看板目录未登录可读**（本次修订新增） | `vite.config.ts:93-106` | `GET /uniplam/api/portal-default` 的 GET 分支**零校验**（同一文件的 POST 分支反倒写了完整守卫），未登录即可取到全量看板目录：所有看板名称 + FineBI / my_app 的相对路径。与问题 3 同源 —— 门户的鉴权目前管得住"写"，管不住"读" |

> **优先级判断（本次修订更新）**：S3 与 S4 比初稿评估的更确定、更靠近可用性，建议直接进 `docs/TODO.md`（S3 → P1；S4 → P1，并与阶段 3 的前置 A 合并立项）。
>
> S1 仍是暴露面最广的一条：`config.ts:141`（`getMyappLink`）与 `:170`（`resolveUrl`）**两处实测都把 token 拼进了 query**，会进浏览器历史、Referer 与 nginx access log；token 是 64 hex 内存态凭证，泄漏后可直用到 12h 滑动续期结束。修法通常是改为 POST 换票 + 短时一次性票据（`Task\my_app` 的 `create_client_login_ticket` / `consume_client_login_ticket` 已是这个模式的先例，可复用其思路）。
>
> 上表仅登记事实与影响，**任何修复都需另立任务并单独评审**，不与本次结构化改动混在一起。

## 六、明确不做的事（避免过度设计）

按工作区原则第 1 条「抽象延迟到第二个真实用例出现」：

- **不引入 JWT**。当前内存 token + 回调校验已满足"门户是唯一签发方"的场景，JWT 会引入密钥管理负担而无收益；
- **不引入 OIDC / 第三方身份提供方**。无此需求；
- **不引入前端状态库**（Redux/Zustand）。`AuthContext` 是唯一状态源，`architecture.md:121` 已明确不引入；
- **不做细粒度 RBAC 权限矩阵**。在 `allowedPages` 出现第二个真实授权维度之前，`role` + 三个白名单足够。
- **不把四份静态壳的鉴权实现合成一份**（对应问题 4）。`portal.js` / `olbr.js` / `v1\olbrportal\olbr.js` / `access.js` 是手写 JS、没有构建步骤、由 nginx 或 vite 直接发文件；抽公共模块会给静态壳引入构建依赖，收益（少几处重复）远小于代价（壳侧不再"改完即上线"）。改以「契约定文档 + 服务端拒答兜底」收口。

## 七、验收标准

| 阶段 | 验收 |
| --- | --- |
| 1 | `npm run lint` 与 `npm run build` 通过；**五条链路行为与拆分前完全一致**：登录、改密、用户管理增删、鉴权开关、免登录模式；`server\auth\` 五个文件均 < 500 行**且无未归属代码**（拆分前后总行数对得上，`git diff --stat` 复核）；`vite.config.ts` 里**不再有第二份** `getUserByToken` + role 判断（改调 `resolveCaller`）；免登录旁路全仓库只有一处写法 |
| 2 | 新页面照抄 `_TemplatePage.tsx` 后 `useAuth()` 可用、未登录自动回登录页、`apiFetch` 401 自动登出；**`git check-ignore -v src/pages/_TemplatePage.tsx` 无输出且 `git status --porcelain` 能看到该文件**（下划线陷阱，见阶段 2）；`.gitignore` 豁免与 `vite.config.ts` watch 清单两处同步改完，`:236-237` 那句"src 下没有 `_` 开头文件"的注释一并更正；`architecture.md` 第八节出现「鉴权契约」小节（`/me` 字段清单 + 三态语义），四处壳侧的同义注释改为引用该节 |
| 3 | **在一份旧 `portal-auth.db` 副本上**启动：缺列自愈成功、老账号与老白名单数据不丢；管理员可为账号勾选可见页面；`allowedPages=null` 与 `=[]` 行为可区分；**服务端真的拒答** —— 用未授权账号**直连接口**验证拿不到数据，而不是只验"页面上没显示"；壳侧四处判定同步（`portal.js` / `olbr.js` / `v1\olbrportal\olbr.js` / `access.js`，`v1` 那份跑 `npm run lint:shells`）；`zh` 与 `en` 两份字典键集一致（本项目无 `check:i18n` 脚本，需人工或临时脚本比对，脚本落 `TMP\` 并按总纲原则 7 自清） |

## 八、待确认事项

1. **「新页面」主要指哪种形态？**（A 门户内 React / B 静态壳 / C 远程深链）—— 决定阶段 2 的优先级。**注意前提已变**：初稿此问是为了判断"B 是否空白"，实测 B 已实现（四份壳侧代码），所以这条现在真正的问法是 —— 新页面是"再接一份壳"（复用 `portal.js` 探针，成本低），还是"门户内新视图/新路由页"（走形态 A + 阶段 2）；
2. **阶段 3 的「页面」到底指什么？** 四个门户视图（`landing.view` 已能表达）、某张看板卡片（`allowedCards` 已是单卡片粒度），还是引入路由后的独立页面？三选一才决定是否真的需要 `allowedPages` 这个新字段（见阶段 3）；
3. **是否要做真正的多路由结构？** 当前门户是四个 `ViewMode`（`auth.ts:22-23`），无路由库；若要独立页面，先按工作区原则第 7 条核查既有依赖，再决定引库；
4. **服务端是否开始拒答**（阶段 3 前置 A）以及拒答范围：只裁剪 `portal-default` 目录，还是连 FineBI / my_app 的跳转地址一起裁 —— 只有后者才真正解决 S4；
5. **`MsPortal` 的实际发布方**（形态 B 差异 1）：本仓库 `nginx.conf` 无对应 `location`，而 `AGENTS.md` 与 `vite.config.ts:223-224` 都写"由 nginx alias 发布"，三者与配置不一致，需核实并修正其中两处；
6. **S1 / S2 / S3 / S4 是否单独立项**及优先级（本次修订建议：S3、S4 直接进 `docs/TODO.md` P1，S1 次之，S2 与运维重启窗口一起评估）。

## 九、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 工作区总纲 | `D:\01_RPA\AGENTS.md` |
| 本项目约束 | `AGENTS.md` |
| 鉴权架构现状 | `architecture.md` 第八节 |
| 当前待办 | `TODO.md` |
| 鉴权开关 | `D:\01_RPA\AUTH_SWITCH.md` |
| 远端 SSO 实现 | `Task\my_app\backend\services\portal_auth.py` |
| **静态壳侧的鉴权实现** | `MsPortal\assets\portal.js`（`:4115` 登录 / `:4157` `/me` / `:4278` `UM_API`）、`olbrportal\assets\olbr.js`（`:2311-2330` / `:2581` / `:2948`）、`v1\olbrportal\assets\olbr.js`（`:2903-2914` / `:3007`）、`MsPortal\assets\access.js`（`:114-121`） |
| **门户其他端点的守卫副本** | `vite.config.ts:85-180`（`portal-default`：GET 无校验、POST 有完整守卫） |
| 静态壳的实际发布方式 | `nginx-1.28.0\nginx-1.28.0\conf\nginx.conf:84-113`（`/olbrportal/`、`/v1/olbrportal/`）、`:360-366`（`/uniplam/` 反代与 `X-Real-IP` / `X-Forwarded-For`） |
| 本次修订前的原文 | `auth-module-design.md_bak_20260925_评审修订前`（同目录，`*_bak_*` 已在 `.gitignore:47` 忽略，不入库，**仅本机回滚手段**） |

## 十、本次修订记录（2026-09-25）

逐条对应评审意见，全部结论均已用 `文件:行号` 或 `git check-ignore` 实测复核：

| # | 修订 | 落在哪节 |
| --- | --- | --- |
| 1 | 家底表补 `MsPortal` / `olbrportal` / `v1\olbrportal` / `access.js` 四行；问题由"壳侧接不上"更正为"**同一契约 5 份实现**"，并给出契约面（阶段 2 文档化）与强制面（前置 A）两条收口 | 一、二、三（新增问题 4）、四、六 |
| 2 | 形态 B 整段重写：成本从"中／不成立"改为"复用低、改语义高"，并补两条动工前必须查清的事实差异 | 二 |
| 3 | 问题 3 改判为"**服务端根本不拒答**"，与新增的 S4 合并为阶段 3 的前置 A | 三、五 |
| 4 | 阶段 1 补 `types.ts` 收留**未归属的 237 行**；`guard` 由"Express 中间件"改为 `resolveCaller(req)`；纳入 `vite.config.ts:111-121` 副本去重与旁路统一 | 三、四 |
| 5 | 阶段 2 推翻"`_*` 不会误伤"的保证，给出 `.gitignore` 可递归豁免 + watch 清单同步 + `git check-ignore` 验收三步 | 四、七 |
| 6 | 阶段 3 补**前置 B：`authDb` 无 `ALTER TABLE`，现网库加列会让写操作全崩**；配套清单由 3 处扩到 5 面 | 四、七 |
| 7 | S3 由"可能共用 IP"改为已证实并升 P1；新增 S4（目录未登录可读） | 五 |

另修三处措辞与引用：`auth.ts:22-23` 是**四**个视图（初稿写"三视图"）、守卫行号更正为 `App.tsx:727-739`、阶段 1 手工链路与验收表统一为**五条**（初稿正文四条 / 表内五条）。

## 十一、执行记录（2026-09-25）

阶段 1、阶段 2 已执行完毕。**所有结论均经运行时实测**，非仅静态检查。

### 已完成

| # | 事项 | 结果 |
| --- | --- | --- |
| 1 | 拆分 `server\auth.ts`（928 行）→ `server\auth\` 六文件 | 最大 `routes.ts` 420 行，**全部 < 500 行**；旧文件已删除（不留兼容层） |
| 2 | 收口 `vite.config.ts` 的守卫副本 | 改为调用 `resolveCaller`；`sendJson` 也不再本地重定义 |
| 3 | 统一免登录旁路 | 占位身份 `DEV_ADMIN` 收归 `guard.ts` 单一定义（此前两处写法不一致） |
| 4 | **修 S3**（限流分桶） | `clientIp()` 在回环直连时读 `X-Real-IP`，保留 socket 回退防伪造 |
| 5 | 修拆分**引入的循环依赖** | `authDb.ts` 改指 `auth/types`（原指 `auth` barrel 会成环） |
| 6 | 新增 `src\components\RequireAuth.tsx` | `<RequireAuth>` / `<RequireAuth admin>`，含无权限提示（非白屏） |
| 7 | 新增 `src\pages\_TemplatePage.tsx` | 新页面接入模板，含竞态作废 / 三态渲染 / 正确 API 前缀示范 |
| 8 | **修 `.gitignore` 下划线豁免失效** | `!src/_*` 只豁免一级目录，**改 `!src/**/_*`**（见下） |
| 9 | 同步 `vite.config.ts` 的 `watch.ignored` | 弃用 `**/_*`（会吞掉模板），改为逐前缀列举 |
| 10 | i18n 双向字典 | 新增 `auth.noPermission*` 与 `tpl.*`，`zh`/`en` 各 6 键 |
| 11 | 文档同步 | 本文件、`docs/AGENTS.md` 文件地图、`architecture.md` 第八节 |

### 实测证据（运行时验证，非静态推断）

在**隔离实例**（9270 端口 + 独立 `auth-data` + 独立 `auth-switch.json`）上验证，
生产实例（9267）全程未受影响：

- **鉴权五条链路**：登录 ✓、错误口令 401 ✓、`/me` ✓、viewer 读 `/users` 403 ✓、增删用户 ✓；
- **改密**：旧 token 失效 401 ✓、新 token 生效 ✓、旧密码失效 ✓；
- **白名单三态**（原始 JSON 实测）：`["核心网","传输网"]` / `null`（不限制）/ `[]`（什么都不给看）三者可区分 ✓；
- **中文组名往返**：写入与读回一致 ✓；`remap-group` 实测 `核心网 → 承载网` 迁移成功（`affected:1`）✓；
- **输入防护**：非法 `view` 被丢弃 ✓、弱口令 400 ✓、重名 409 ✓、白名单去重 `A,A,'',B → A,B` ✓；
- **S3 修复前/后对比**：IP-A 连错 10 次后被锁（429），**IP-B 用正确口令仍能登录（200）** ——
  修前两者共用 `127.0.0.1` 一个桶，单人即可锁死全站；现锁定只对本人生效 ✓；
- **构建**：`npm run build` 通过（1392 KB / gzip 304 KB）；`tsc --noEmit` 除已知损坏的
  `v1\olbrportal\assets\olbr.js`（他人未提交的在途改动，与本次无关）外无错误。

### 执行中发现并修掉的一个额外缺陷

**`.gitignore` 的下划线豁免实际失效。** 规则写的是 `_*`（递归匹配）+ `!src/_*` / `!server/_*`
（只豁免**一级**子项），两者不对称。实测 `git check-ignore`：

```
src/_Test.tsx                  → 命中 !src/_*      （一级，豁免成功）
src/pages/_TemplatePage.tsx    → 命中 _*           （嵌套，豁免失败 → 被静默忽略）
```

这正是第 30-31 行注释**想防**的失败模式，只是没防住嵌套层级。已改为 `!src/**/_*` /
`!server/**/_*`，并以 `git status --porcelain` 确认模板文件现在可见（此前完全不可见）。
`vite.config.ts` 的 `watch.ignored` 同步调整 —— 注意 vite 的 `ignored` **不支持 `!` 反选**，
故不能照抄 `.gitignore` 写法，只能在原 `**/_*` 位置改为逐前缀列举。

### 未做（保持原状，避免范围蔓延）

- **阶段 3（`allowedPages` 权限模型）**：需按前置 B 在旧 `portal-auth.db` 副本上验证
  `ALTER TABLE`（`authDb.ts` 只有 `CREATE TABLE IF NOT EXISTS`，现网库加列会让写操作全崩）。
  该前置要求不变，待排期。
- **S1 / S2 / S4**：保持登记状态，未修（S3 已在本次修掉）。
- **`App.tsx` 的守卫未改用 `RequireAuth`**：守卫之后大量逻辑依赖非空 `user`，而
  `RequireAuth` 是「包住子树」无法收窄类型，改了反而要加断言。已在代码注释写明原因。

> **工具负责整理，人与 AI 负责协作执行。**
