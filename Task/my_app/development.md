# 07 development.md —— 开发方式、命令和回归清单

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\development.md`

> **完整步骤以手册为权威**：`docs\manual\10-quickstart.md`（环境、依赖、建表、构建、启停）、`12-configuration.md`（配置项）。
> 本文补充**纪律、命令速查与回归清单**。

## 一、环境要求（`docs\manual\10-quickstart.md`）

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows | 启停脚本是 `.bat`/`.ps1`/`.vbs`，非跨平台 |
| Python | **3.12**（`pythonw.exe`） | 启动脚本按 `pythonw → PATH → %LOCALAPPDATA%\Programs\Python\Python312 → Python311 → C:\Python312 → $base\Scripts\pythonw.exe` 顺序探测（`start_hidden.ps1:88-103`），找不到直接 FAIL |
| Node | v24 已验证可用 | 前端构建与通知 CLI 依赖 |
| PostgreSQL | 16，装在 `C:\Program Files\PostgreSQL\16` | 自启脚本**硬编码**了 `bin`/`data` 路径 |

> ⚠️ **两个不要使用的解释器**：仓库根 `pyvenv.cfg` 是 **3.13.14**，`.venv-test` 是 **3.12.10**（后者只被 `backend/migrations/smoke_test_pg.py:44` 用）。运行时实际用的是脚本探测到的**系统 Python 3.12**。

## 二、命令

### 第一次装

```powershell
# 1) 后端依赖
pip install -r requirements.txt          # 区间版：装当前兼容的最新
pip install -r requirements.lock.txt     # 精确锁版：完全复刻现网（由系统 Python 3.12 全量锁定）

# 2) 配置：新建 backend\.env（键名参照 10-quickstart.md 的"最小可用 .env"）
#    ⚠️ 不要把带真实值的 .env 提交或外发

# 3) 建表
python backend/scripts/init_db.py
alembic upgrade head

# 4) 前端构建（产物目录必须是 _fe_dist，否则后端找不到静态文件）
cd frontend
npm install
npm run build
```

### 最小可用 `.env`（放在 `backend\.env`）

```ini
MY_APP_DB_MODE=pg
DATABASE_URL=postgresql+psycopg://<user>:<pass>@<host>:5432/<db>
MY_APP_WORKER_GROUPS=u,n,s,w,m,c,v,x,g,p
# 可选：对外暴露接口时启用
# MY_APP_API_TOKEN=<随机长串>
# 可选：覆盖 CORS 白名单
# MY_APP_CORS_ORIGINS=http://localhost:7090,http://localhost:7038
```

> `MY_APP_DB_MODE=sqlite` 可脱离 PG 单机试跑（退回本地 `db/app.db`）。

### 启动与停止

| 场景 | 命令 | 行为 |
| --- | --- | --- |
| 日常手动启动 | `start.bat` | 清 `stopped.flag` → 调 `start_hidden.ps1` → 轮询 7038 就绪 → 校验 worker 看门狗 PID → 打印访问地址 |
| 静默启动（开机自启用） | `start_hidden.vbs` → `start_hidden.ps1 -Quiet` | 无窗口，尊重 `stopped.flag` |
| 5 分钟一次的保活 | `start_ensure.bat`（计划任务） | `-Quiet -Force`，端口被占也抢回来 |
| 端口被非托管进程占用 | `start_hidden.ps1 -Force` | 先杀掉 7038 的进程再启 |
| 停止 | `stop.bat` | 树杀看门狗 PID，连带 worker 一起停（不会复活） |

### 其他

```powershell
# 国际化一致性检查（漏键 / t(key,{defaultValue}) 错签名 / 残留 tpl.*）
# 已内置进 npm run build：不通过会直接中断构建
cd frontend && npm run check:i18n

# 帮助文档生成（改了 helpContent.ts / helpTaskDocs.ts 之后）
cd frontend && node scripts\generate-help-doc.mjs

# worker 重启
python restart_workers.py
```

## 三、改代码前的纪律

1. **新增功能页 → 三处同步**：`frontend\src\App.tsx` 菜单数组 + `frontend\src\i18n.tsx`（中英**两处**）+ `docs\manual\11-feature-guide.md`。漏一处手册与界面就对不上。
2. **新增定时任务 → 登记 `TASK_SPECS`**（`backend\task_registry.py`），否则**不会被执行**；同时更新 `docs\manual\04-task-system.md` 的分组表。
3. **新增 worker 分组 → 三处同步**：`GROUP_TASK_MAP` + `start_hidden.ps1` + `restart_workers.py`。**新增任务未归组会 pending 卡死。**
4. **帮助内容改了要重新生成**，不要手改 `docs\manual\15-user-help*.md`。
5. **前端产物目录保持 `_fe_dist`**，改了会白屏。
6. **不新增裸 `sqlite3.connect`**（绕过统一数据访问层，会静默坏图）。
7. **不写敏感值**：可写配置项名称、环境变量键名、分组 key；不可写口令、Token、授权码、账号。
8. **不入库**：`db\`、`log\`、`TMP\`、`Lib\`、`Scripts\`、`auth_cache\`、`*.pid`、`*.bak_*`、`_myapp_trash_*\`、`backend\data\native_board_cache\`、`backend\app.db`（空占位）。
9. **改大文件前建 `_bak_<日期>_<说明>` 快照**（本项目既有习惯）。
10. **中文注释**；每条论断带 `文件:行号` 出处。

## 四、回归清单

改完逐项验证，**打勾前请真的跑过**。

### A. 测试

- [ ] `tests\` 下的测试通过（`python tests\run_all_tests.py` / `run_backend_tests.py`）
- [ ] **`tests\test_worker_group_coverage.py` 通过** —— 这条专门校验 worker 分组覆盖，**新增任务后必跑**（未归组的任务会 pending 卡死）。2026-10-15 起它同时校验**五处**组清单一致（`GROUP_TASK_MAP`、`start_hidden.ps1` 两处、`restart_workers.py` 兜底、`start.bat` 自检计数、`helpTaskDocs.ts`）
- [ ] 改 `eflow_active_alarm` 的 cron（现 `*/1`）时，**必须同步复核 `AUTH_TOKEN_TTL`** —— 二者是一对联动的参数（TTL 应远大于调度周期），单独改任一个都可能退化成「每个周期真实登录一次」打崩 eFlow，详见 `docs\manual\05-security-and-credentials.md`
- [ ] 涉及任务时：`tests\test_task_runner.py` 通过
- [ ] 涉及告警健康时：`tests\test_task_health_alert.py` / `test_task_health_detect.py` 通过
- [ ] 前端改动：类型检查 / `npm run build` 通过（**`build` 已内置 `check:i18n`**）
- [ ] **`npm run check:i18n` 通过** —— 拦截漏键、`t(key,{defaultValue})` 错签名、残留 `tpl.*` 三类问题（详见 `docs\manual\16-new-page-guide.md` 3.6）

### B. 进程与任务

- [ ] 后端能起来（`7038` 就绪）
- [ ] **五个关键进程都在**（worker 各组 + 双看门狗，巡检步骤见 `docs\manual\13-operations.md`）
- [ ] 新增/修改的任务能在任务列表看到，且**能真正跑起来**（不是一直 pending）
- [ ] 手动触发一次，确认进队列 → 认领 → 执行 → 写 `task_execution_log` 全链路通

### C. 数据正确性（高风险区）

- [ ] **没有新增绕过 `get_raw_connection` 的裸 `sqlite3.connect`**
- [ ] 涉及图表时：**图表真的出图**（不是空白）—— 已知有绕过统一数据访问层的图表数据源
- [ ] 确认没读错库：`eflow_tt` 双库（写 `app.db`）、`db_ps_cs_cn` 真数据在远端（本地 0 字节占位）、`backend\app.db` 是空占位
- [ ] 涉及 PG/SQLite 双模时：两种模式都验，方言差异看 `dialect_helpers.py`
- [ ] 涉及迁移时：`alembic upgrade head` 能干净跑通

### D. 前端

- [ ] **深色与浅色两套主题都看过**（`theme.ts` 是双套令牌，只验一套等于漏测一半）
- [ ] **ECharts 图表取色正确**：DOM 层用 `WH`（CSS 变量），**Canvas 层必须用 `DARK`/`LIGHT` 实值**。图表配置写成 `WH.xxx` 会拿到 `var(--wh-teal)` 字符串，渲染异常
- [ ] **中英文都切过**，没有显示成 key 原文的文案
- [ ] 新增功能页时：`App.tsx` 菜单 + `i18n.tsx` 中英 + `11-feature-guide.md` 三处都改了
- [ ] 页面**不白屏**（产物目录仍是 `_fe_dist`）

### E. 帮助与文档

- [ ] 改了帮助内容 → 已重跑 `generate-help-doc.mjs`，站内帮助与 MD **同源一致**
- [ ] 新任务 → `04-task-system.md` 分组表已更新
- [ ] 新功能页 → `11-feature-guide.md` 已加一节

### F. 提交卫生

- [ ] `git status --porcelain` 复查：没有 `db\`、`log\`、`TMP\`、`auth_cache\`、`*.pid`、`native_board_cache\`、`backend\app.db` 混入
- [ ] 没有提交带真实值的 `.env`
- [ ] 没有提交敏感值

## 五、常见陷阱

| 陷阱 | 后果 | 正确做法 |
| --- | --- | --- |
| 新任务没登记 `TASK_SPECS` | **永远不会被执行** | 登记并更新分组表 |
| 新任务没归 worker 分组 | **pending 卡死** | 三处同步分组映射；跑 `test_worker_group_coverage.py` |
| 前端产物目录改名 | 后端找不到静态文件，白屏 | 保持 `_fe_dist` |
| 帮助改了 TS 没重新生成 | 站内帮助与 MD 不一致 | 跑 `generate-help-doc.mjs` |
| **`t('key', { defaultValue: '兜底' })`** | **`t()` 第二参数是插值参数不是 options；键不存在时原样返回 key，界面直接显示 `xxx.yyy`** | **把键加进 zh/en，写 `t('xxx.yyy')`** |
| **键只加进 `zh` 没加 `en`** | **中文正常，切英文露出 key 原文** | **两处都加；`npm run check:i18n` 会自动拦下** |
| ECharts 配置用 `WH.xxx` | 图表拿到 `var(--wh-teal)` 字符串，渲染异常 | Canvas 层用 `DARK`/`LIGHT` 实值 |
| 只验一套主题 | 漏测一半 | 深浅两套都看 |
| 新增裸 `sqlite3.connect` | 绕过统一层，迁移/改造静默坏图 | 用 `get_raw_connection()` |
| 误用 `backend\app.db` | 那是**空占位**，读到空的但不报错 | 真库是 `db\app.db` |
| 误用本地 `db_ps_cs_cn.sqlite3` | 0 字节占位，得到空结果而非报错 | 真数据在远端（HTTP 8765） |
| 用 `pyvenv.cfg` 的 3.13 或 `.venv-test` | 不是运行时的解释器 | 用系统 Python 3.12 |
| **用 `Set-Content`/`Out-File` 批量改含中文的源文件** | **编码被破坏：中文注释变成 `åŽŸç”¨` 之类的乱码，且 git 视为「无改动」，`git checkout` 救不回来** | **一律用编辑器工具改；禁用 PowerShell 重定向写源文件**（详见 §七） |
| 改 `.env` 后不重启 | 配置不生效 | `.env` 改动需重启；界面能改的才免重启 |
| 直接改 `15-user-help.md` | 下次生成被覆盖 | 改 TS 源再生成 |
| 把现状写回 `PROJECT_DOCS.md` | 制造第二个真相源 | 现状进手册，历史留在归档 |

## 六、源码编码纪律（真实事故复盘）

> **背景**：2026-09 一次 Excel 导出迁移中，用 PowerShell 批量改写 6 个页面文件，
> 导致这些文件里的**中文注释全部损坏**，并已被提交（`051b77b`）。

### 6.1 现象

文件里的中文从 `原用 XLSX.utils.json_to_sheet` 变成 `åŽŸç”¨ XLSX.utils.json_to_sheet`——
即 UTF-8 字节被按 Latin-1 解读后又存成 UTF-8，术语叫 **mojibake（乱码）**。

### 6.2 为什么危险（三层）

1. **编译不报错**。乱码在注释里，`tsc` 与 `vite build` 全部通过，**CI 发现不了**。
2. **git 视为无改动**。因为工作区和 HEAD 都是「已损坏」的同一份内容，
   `git status` 显示 clean，`git checkout` 会把损坏版本再写回来 —— **常规手段救不回来**。
3. **需要考古**。必须逐提交比对乱码字符数，找到**引入损坏前**的最后一个干净提交。

```powershell
# 逐提交检查某文件的乱码情况，找最后一个干净版本
foreach ($c in @('051b77b','e448816','3b77bb0')) {
  $t = git show "${c}:Task/my_app/frontend/src/pages/BatteryDashboard.tsx" | Out-String
  "{0}  乱码={1,-5} 汉字={2}" -f $c,
    ([regex]::Matches($t,'[åæçè]')).Count, ([regex]::Matches($t,'[\u4e00-\u9fff]')).Count
}
```

### 6.3 根因

PowerShell 的 `Set-Content` / `Out-File` / `>` 重定向在**读写源文件时不保证 UTF-8**，
会按当前代码页（中文 Windows 常为 GBK/936）解读字节。用它改写含中文的 `.ts`/`.tsx`/`.md` 即触发。

### 6.4 纪律

1. **禁止**用 `Set-Content`、`Out-File`、`>`、`-replace` 回写的方式批量修改**源文件**（`.ts/.tsx/.css/.md/.py`）。
   改文件一律用编辑器工具（本项目的 `edit` / `write` 工具）。
2. **只读**用 PowerShell 没问题（`Select-String`、`Get-Content` 查看）。
3. 脚本类批量改写若不可避免，显式指定编码并**改完立即验证**：
   ```powershell
   $enc = New-Object System.Text.UTF8Encoding($false)   # 本项目源文件为 UTF-8 无 BOM
   [System.IO.File]::WriteAllText($path, $text, $enc)
   ```
4. **改完必检**：对含中文的文件，扫描乱码字符，正常汉字数应远大于 0。
   ```powershell
   $t = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
   "乱码={0} 汉字={1}" -f ([regex]::Matches($t,'[åæçèéêëìíîïòóôõùúûüýÿœž]')).Count,
                        ([regex]::Matches($t,'[\u4e00-\u9fff]')).Count
   ```
   **判读**：出现 `å/æ/ç/è` 这类字符且「汉字」为 0 → 已损坏。
5. **还原时要字节精确**：本项目源文件是 **UTF-8 无 BOM + LF**。
   用 `git show <commit>:<path>` 经 cmd 重定向取原始字节再 `WriteAllBytes`，
   不要用 `Out-File`（会加 BOM、可能丢换行）。
   ```powershell
   cmd /c "git show e448816:$f > `"$tmp`" 2>nul"
   [System.IO.File]::WriteAllBytes($dest, [System.IO.File]::ReadAllBytes($tmp))
   git hash-object -- $f          # 与 git rev-parse e448816:$f 比对，一致才算还原
   ```

> **教训**：注释里的乱码不影响运行，所以**没有任何自动化信号会告诉你出了事**。
> 只有人打开文件才会发现。因此这一步必须靠纪律，不能靠检查。

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 快速上手（权威） | `docs\manual\10-quickstart.md` |
| 配置项与开关（权威） | `docs\manual\12-configuration.md` |
| 运维与排障 | `docs\manual\13-operations.md` |
| 测试说明 | `tests\README_tests.md`、`tests\DEEP_FINDINGS_AND_SUGGESTIONS.md` |
| 代码清理指南 | `docs\CODE_CLEANUP_GUIDE.md` |
| Excel 导出规范 | `docs\EXCEL_EXPORT_STANDARD.md` |
| 接口与任务速查 | `docs\manual\90-appendix.md` |
| worker 内部设计 | `backend\WORKER.md` |
| AI 上手须知 | `AGENTS.md` |
| 全域开发规范 | `D:\01_RPA\development.md` |

> **工具负责整理，人与 AI 负责协作执行。**
