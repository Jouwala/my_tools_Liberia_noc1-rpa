# 日常开发：一键启停用户鉴权（/uniplam/ 与 /myapp/）

> 目标：本地/联调时不必反复登录门户，就能直接打开 `/uniplam/` 门户与 `/myapp/` 看板；
> 需要验证真实登录流程时再一键打开。两个应用共用一个开关，不会出现「门户免登录、
> myapp 还要求登录」的错配。

## 0. 页面按钮（推荐，管理员）

门户页面右上角 → 用户菜单 → **鉴权开关**（仅管理员可见）：

- 打开后显示当前状态（鉴权已开启 / 鉴权已关闭·免登录），一键切换；
- 关闭鉴权时**需要二次确认**；
- 鉴权处于关闭状态时，页面顶部会常驻一条橙色警示条，上面直接有「恢复鉴权」按钮，
  避免忘了把鉴权打开；
- 切换后**无需重启任何进程**，门户立即生效，myapp 最迟 3 秒自动跟上。

权限是**不对称**的，这是刻意的设计：

| 操作 | 需要的身份 | 原因 |
|---|---|---|
| 关闭鉴权（危险方向） | **必须是真实管理员登录态** | 免登录的占位身份 `dev-admin` 不算数，防止「随手就能把系统打开」 |
| 开启鉴权（安全方向） | 无要求，谁都能点 | 否则免登录状态下会陷入「没法把鉴权开回来」的死结 |

**用户数据一定保留**：这个按钮只改 `auth-switch.json` 一个文件，写前还会自动把上一版
留成 `auth-switch.json.prev`。它**不会**新增/修改/删除任何用户账号、密码、角色、看板
权限，也**不会**清除现有登录会话——切回鉴权后原来的登录状态照常有效。弹窗里也写明了
这三点。

### ⚠ 关于 `auth-switch.json` 的缺失与 `.prev`（2026-10-06 补充）

**文件不存在 = 开启鉴权，这不是故障。** 两个应用的解析顺序都是
「环境变量 `AUTH_ENABLED` > 开关文件 > 缺省 `true`」，所以没有这个文件时两侧一律
走"要求登录"这一安全默认。删掉它**不会**放开系统。

**`auth-switch.json.prev` 是"上一次写入前的旧值"，不是"建议恢复的值"。**
2026-10-06 排查时发现它曾停在 2026-09-13、内容为 `authEnabled: false`，而主文件早已
不在——如果谁把它当成"配置备份"照抄回去，就会**静默关掉两边的登录**。产生原因是：

| 写入方 | 写前是否滚动备份 |
|---|---|
| 门户页面按钮 / `server/authSwitch.ts` | ✅ 一直有 |
| `auth_switch.py`（命令行） | ❌ 此前没有 —— 2026-10-06 已补齐 |

两个写入方行为不一致，正是 `.prev` 会"过期"的原因。现已对齐：`auth_switch.py` 的
`save()` 同样滚动备份 `.prev` 并改用「临时文件 + 改名」原子写。

那份陈旧文件已改名为 `auth-switch.json.prev_stale_20260913_archived` 保留现场，
**不要**用它的内容去恢复配置。

排查时用 `status` 看 `exists` 与 `source` 两个字段，区分"文件写着 true"和"文件根本不在"：

```
file    : D:\01_RPA\auth-switch.json
exists      : False
authEnabled : True
source      : default  (file missing -> safe default: auth required)
mode        : enforced (login required)
```

`auth-switch.json` / `.prev` 已加入 `.gitignore`：它是**本机运行态**，不同机器可以合法地
取不同值，不应入库。

---

## 1. 命令行用法（等价手段）

```bat
cd /d D:\01_RPA

python auth_switch.py status     :: 查看当前开关
python auth_switch.py off        :: 关闭鉴权 -> /uniplam/ 与 /myapp/ 都免登录
python auth_switch.py on         :: 开启鉴权 -> 恢复正常登录校验
python auth_switch.py toggle     :: 反转当前状态
```

也可以直接双击 `auth_switch.bat`（等价于 `python auth_switch.py status`）。

命令行改完需要**重启进程**（脚本直接改文件，进程要等 TTL 或重启才重读）：

| 进程 | 端口 | 重启方式 |
|---|---|---|
| uniplam 门户（Vite） | 9267 | 门户目录的 `start.bat` / `start_hidden.ps1` |
| myapp 后端（FastAPI） | 7038 | `Task\my_app\start.bat` / `start_hidden.ps1` |

重启后确认日志里出现这一行，即表示开关已按预期生效：

```
[auth-switch] 鉴权已关闭(免登录) | 环境=development 来源=file 开关文件=D:\01_RPA\auth-switch.json
```

## 2. 开关的真相源与优先级

配置文件：`D:\01_RPA\auth-switch.json`

```json
{
  "authEnabled": true,
  "updatedAt": "2026-09-13T10:28:04+00:00",
  "note": "..."
}
```

解析优先级（高 → 低）：

1. 环境变量 `AUTH_ENABLED`（`1/true/on/yes` = 开启；`0/false/off/no` = 关闭）
2. 上面的开关文件 `authEnabled` 字段
3. 缺省 = `true`（保持原有行为，安全默认）

可选环境变量：

| 变量 | 作用 | 默认 |
|---|---|---|
| `AUTH_ENABLED` | 直接覆盖开关（优先级最高，适合临时调试/CI） | 空（不覆盖） |
| `AUTH_SWITCH_FILE` | 换一份开关文件（如起隔离实例做验证） | `<仓库根>/auth-switch.json` |
| `AUTH_SWITCH_ENV` | 显式声明运行环境；`production`/`prod` 触发生产保护 | 依次回退 `NODE_ENV` → `APP_ENV` → `development` |

## 3. 生产保护

当运行环境判定为 `production` / `prod` 时，即使配了关闭鉴权，**也会被强制回「开启鉴权」**
并打印 `严重告警`，避免误操作把线上放开：

```
[auth-switch] 严重告警：运行环境为 production，已忽略「关闭鉴权」配置并强制开启。
```

## 4. 免登录时各层的行为

| 位置 | 鉴权开启（默认） | 鉴权关闭（日常开发） |
|---|---|---|
| 门户 `/uniplam/` 页面 | 未登录显示登录页 | 直接以 `dev-admin` 进入 |
| 门户 `/uniplam/api/auth/me` | 需有效 Bearer token | 返回 `dev-admin` |
| 门户 `/uniplam/api/auth/login` | 校验账号密码 | 直接返回占位 token |
| 门户鉴权开关 `GET/POST /api/auth/switch` | 需登录；关闭需真实管理员 | 关闭需真实管理员，**开启放行** |
| 门户保存默认目录（`POST /api/portal-default`） | 需管理员 token | 免 token，但**仍限本机 localhost** |
| myapp 数据接口 `/api/**` | 需会话 Cookie，否则 401 | 整体放行 |
| myapp `/api/auth/me` | 需会话 | 返回 `dev-admin` |
| myapp `/api/auth/portal-login` | 回调门户 `/me` 验证 token | 直接返回 `dev-admin`，不回调 |

统一用 `dev-admin`（`role=admin`）作为占位身份，保证依赖「当前用户/角色」的业务逻辑
在免登录下仍能走通，不会拿到空用户。

**免登录不等于放开所有限制**：本机回环校验、`X-API-Token` 保护、`/api/auth/kiosk`
密钥等独立机制不随该开关放宽。

**用户数据不受任何影响**：开关只读写 `auth-switch.json`，用户账号、密码、角色、看板
权限（`auth-data/portal-auth.db`）与登录会话（`portal_sessions`）全程不被触碰。

## 5. 排查接口

两个应用都提供公开的模式探测接口，用于确认「当前到底是不是免登录」：

```bash
curl http://127.0.0.1:9267/uniplam/api/auth/mode     # 门户
curl http://127.0.0.1:7038/api/auth/mode             # myapp 后端
```

```json
{ "authEnabled": false, "mode": "bypass", "source": "file", "env": "development" }
```

`source` 说明结论来源：`env`（环境变量）、`file`（开关文件）、`default`（缺省）、
`guard`（被生产保护强制回开启）。

管理员视角的详细状态（含「谁在什么时候改的」与能否关闭）：

```bash
curl http://127.0.0.1:9267/uniplam/api/auth/switch -H "Authorization: Bearer <管理员token>"
```

```json
{ "authEnabled": false, "mode": "bypass", "source": "file", "env": "development",
  "envOverride": false, "reason": null, "canDisable": false, "canEnable": true,
  "realLogin": false, "updatedAt": "2026-09-13T10:49:08.649Z", "updatedBy": "admin" }
```

切换：

```bash
curl -X POST http://127.0.0.1:9267/uniplam/api/auth/switch \
  -H "Content-Type: application/json" -H "Authorization: Bearer <管理员token>" \
  -d '{"enabled":false}'
```

## 6. 改动清单

新增：

| 文件 | 说明 |
|---|---|
| `auth-switch.json` | 共享开关文件（两个应用共读） |
| `auth_switch.py` / `auth_switch.bat` | 命令行一键启停脚本 |
| `liberia-noc_soc-数据看板统一门户/server/authSwitch.ts` | 门户侧开关解析 + 写入（含滚动备份、TTL 热生效） |
| `Task/my_app/backend/auth_switch.py` | myapp 侧开关解析（只读，语义与上面完全一致） |
| `liberia-noc_soc-数据看板统一门户/src/components/AuthSwitchModal.tsx` | 页面上的鉴权开关弹窗 |

修改：

| 文件 | 改动 |
|---|---|
| `liberia-noc_soc-数据看板统一门户/server/auth.ts` | 新增公开 `GET /api/auth/mode`、管理员 `GET/POST /api/auth/switch`；免登录时 `/login`、`/me` 及各管理员接口按 `DEV_ADMIN` 放行；启动打印鉴权模式 |
| `liberia-noc_soc-数据看板统一门户/vite.config.ts` | `POST /api/portal-default` 鉴权门在免登录时按开发管理员放行（本机限制保留） |
| `liberia-noc_soc-数据看板统一门户/src/auth/AuthContext.tsx` | 无本地 token 时先探测 `/auth/mode`，免登录则直接进入；轮询模式变化，管理员切换后各标签页自动跟上 |
| `liberia-noc_soc-数据看板统一门户/src/components/Navbar.tsx` | 管理员用户菜单新增「鉴权开关」入口，免登录时带橙色角标 |
| `liberia-noc_soc-数据看板统一门户/src/App.tsx` | 免登录时页面顶部常驻警示条 + 一键「恢复鉴权」；挂载开关弹窗 |
| `liberia-noc_soc-数据看板统一门户/src/i18n.tsx` | 新增中英文文案 |
| `Task/my_app/backend/services/portal_auth.py` | `current_user` 免登录返回开发管理员；新增 `GET /api/auth/mode`；`portal-login` 免登录短路 |
| `Task/my_app/backend/main.py` | 鉴权中间件免登录时整体放行 |
| `Task/my_app/frontend/src/api.ts` | 新增 `getAuthMode()` |
| `Task/my_app/frontend/src/App.tsx` | 启动探测模式，免登录时不弹登录引导 |

所有被修改文件均已备份为 `<原名>_bak_20260913_authswitch`。

## 7. 回滚

**方式一（推荐，最小改动）**：页面按钮或 `python auth_switch.py on`，命令行方式需重启两个进程。

**方式二（彻底回滚代码）**：

```bat
cd /d D:\01_RPA
copy /y "liberia-noc_soc-数据看板统一门户\server\auth.ts_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\server\auth.ts"
copy /y "liberia-noc_soc-数据看板统一门户\server\authSwitch.ts_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\server\authSwitch.ts"
copy /y "liberia-noc_soc-数据看板统一门户\vite.config.ts_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\vite.config.ts"
copy /y "liberia-noc_soc-数据看板统一门户\src\auth\AuthContext.tsx_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\src\auth\AuthContext.tsx"
copy /y "liberia-noc_soc-数据看板统一门户\src\App.tsx_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\src\App.tsx"
copy /y "liberia-noc_soc-数据看板统一门户\src\components\Navbar.tsx_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\src\components\Navbar.tsx"
copy /y "liberia-noc_soc-数据看板统一门户\src\i18n.tsx_bak_20260913_authswitch" "liberia-noc_soc-数据看板统一门户\src\i18n.tsx"
copy /y "Task\my_app\backend\services\portal_auth.py_bak_20260913_authswitch" "Task\my_app\backend\services\portal_auth.py"
copy /y "Task\my_app\backend\main.py_bak_20260913_authswitch" "Task\my_app\backend\main.py"
copy /y "Task\my_app\backend\auth_switch.py_bak_20260913_authswitch" "Task\my_app\backend\auth_switch.py"
copy /y "Task\my_app\frontend\src\api.ts_bak_20260913_authswitch" "Task\my_app\frontend\src\api.ts"
copy /y "Task\my_app\frontend\src\App.tsx_bak_20260913_authswitch" "Task\my_app\frontend\src\App.tsx"
```

`src\App.tsx`（门户）的备份 `src\App.tsx_bak_20260913_authswitch` 是本次改动前的版本，
已用 diff 逐行核对过：与当前文件的差异**只包含鉴权开关相关的新增**，可安全用于回滚。

回滚不涉及数据库、不涉及业务权限模型，仅运行配置与代码。
