# 全仓代码审计报告 · D:\01_RPA

| 项目 | 值 |
|---|---|
| 审计日期 | 2026-08-03 |
| 仓库根 | `D:\01_RPA` |
| Git remote | `https://github.com/Jouwala/my_tools_Liberia_noc1-rpa.git`（分支 `master`，27 次提交） |
| 已跟踪文件 | 464 个 / 约 14.0 MB |
| 工作区实际体积 | 约 8.7 GB（含未跟踪的 DB / 安装包） |
| 扫描口径 | 排除 `.git / node_modules / __pycache__ / .venv / chrome-win / whatsapp_session / dist*` |
| **整体健康度** | **3.4 / 10（D 级 — 高风险，需立即处置）** |

---

## 1. 仓库结构与规模统计

### 1.1 顶层目录职责

| 目录 | 性质 | 职责 | 代码行 | 文件数 |
|---|---|---|---:|---:|
| `Task/my_app/` | **核心产品** | FastAPI + React 数据洞察平台：20 个定时任务调度、GIS 地图、告警看板、TT/WO 看板、SP 看板 | ~30,000 | 130+ |
| `Task/MTN_Comsal/my_app/` | **整体分叉** | `my_app` 的近乎完整副本（另一客户实例），后端 routers/前端 pages 大量逐字节相同 | ~9,000 | 40+ |
| `Task/RAN`, `Task/ip_ran`, `Task/ccn_ume`, `Task/ran_ume`, `Task/sp` | 数据管道（旧版） | UME/CNN/IPRAN KPI 拉取脚本，多数已被 `my_app/backend/services` 内联替代但未删除 | ~12,000 | 60+ |
| `Task/data_base/` | 远程写服务 | `db_writer_api.py`（对应 192.168.100.19:8765 的本地副本） | ~1,200 | 10 |
| `Unified_Tools/` | 工具集合 | `incident_overview`、`IP_Trace_Tool`、5 套 `WareHouseDashBoard_*` Flask 应用 | 1,762,799※ | 91 |
| `WareHouseDashBoard/` | **重复目录** | 与 `Unified_Tools/WareHouseDashBoard/` 逐字节相同 | 6,144 | 13 |
| `ticket_export_rpa/` | RPA 脚本 | 影刀转 Python 的 eFlow 工单导出（含 `- Copy` 副本） | 10,953 | 11 |
| `Site_outage/`, `orange_email/`, `whatsapp/` | 独立小工具 | 站点中断截图、邮件、WhatsApp 推送 | ~2,200 | 11 |
| `nginx-1.28.0/` | **第三方源码** | nginx 完整发行包被提交进仓库（33 个跟踪文件） | 465 | 6 |
| `openclaw_api_selector/` | 运维工具 | API 选优脚本 | 1,733 | 6 |
| `TMP/`, `V_Tmp/`, `debug/`, `data/`, `report/` | 临时区 | 探针脚本、下载缓存、调试快照 | ~1,900 | 51 |

※ `Unified_Tools` 的 176 万行中，171 万行来自 `IP_Trace_Tool/data/*.json` 三个抓包快照，非源码。

### 1.2 语言分布（源码口径）

| 语言 | 文件数 | 代码行 | 注释行 | 注释率 |
|---|---:|---:|---:|---:|
| Python | 246 | 78,982 | 4,961 | 6.3% |
| HTML（含模板） | 37 | 40,241 | 2,457 | 6.1% |
| TypeScript(React) | 26 | 8,821 | 227 | **2.6%** |
| Markdown | 40 | 3,909 | — | — |
| JavaScript | 41 | 1,043 | 4 | 0.4% |
| Batch / PowerShell | 15 | 640 | 0 | 0% |
| TypeScript(非组件) | 10 | 207 | 25 | 12% |
| CSS | 6 | 38 | 8 | — |
| JSON（数据快照） | 26 | 1,718,475 | — | — |
| **源码合计** | **~380** | **~134,000** | | |

### 1.3 最大源文件 TOP 10

| 行数 | 文件 |
|---:|---|
| 2,455 | `ticket_export_rpa/yingdao_to_python_V2.py` |
| 2,261 | `Task/my_app/backend/services/ms_sla_service.py` |
| 2,163 | `Task/my_app/backend/services/eflow_api_client.py` |
| 1,992 | `ticket_export_rpa/get_eflow_table.py` |
| 1,762 | `Task/RAN/MS_SLA/update_contract_kpis_report.py` |
| 1,460 | `Unified_Tools/IP_Trace_Tool/ip_detect_tool.py` |
| 1,339 | `WareHouseDashBoard/app_sp_optimized.py`（× 2 份） |
| 1,336 | `Unified_Tools/incident_overview/app.py` |
| 1,233 | `Task/my_app/frontend/src/pages/DataSync.tsx` |
| 1,048 | `Task/my_app/frontend/src/pages/GISMap.tsx` |

---

## 2. 后端代码质量

### 2.1 异常处理缺陷（最严重的质量问题）

全仓共 **1,783 个 except 处理器**，其中 **1,086 个（60.9%）存在缺陷**：

| 缺陷类型 | 数量 | 说明 |
|---|---:|---|
| 裸捕获 `except:` | 83 | 会吞掉 `KeyboardInterrupt` / `SystemExit`，进程无法正常终止 |
| `except ...: pass` | 384 | 完全静默，故障不可观测 |
| 捕获后既不抛出也不记录 | 619 | 错误被降级为"看起来成功" |
| `my_app/backend` 子集 | 286 | 核心产品内的缺陷占比 |

**关键位置（带行号）：**

| 文件:行 | 代码 | 影响 |
|---|---|---|
| `Task/my_app/backend/routers/analysis.py:148,224,265,294` | `except:` + `pass` | JSON 反序列化失败静默，前端拿到原始字符串而非对象 |
| `Task/my_app/backend/routers/upload.py:145` | `except: return {"uploads": []}` | 上传历史查询失败伪装成"空历史" |
| `Task/my_app/backend/routers/gis.py:160,463,491,509,784,805` | `except Exception: pass` | 工单/WO 查询失败时下钻面板静默缺数据，用户无从察觉 |
| `Task/my_app/backend/routers/gis.py:91` | 几何解析失败 `return None` | 区域边界丢失但无日志 |
| `Task/my_app/backend/services/auth_manager.py:38-48` | 文件锁失败 `pass` | Windows 文件锁失效后仍继续读写 token 缓存，并发下 token 可能被撕裂 |
| `Task/my_app/backend/services/atomic_write.py:47,75,91,148,170,203` | 原子写失败静默 | **原子写工具本身不原子**：清理/诊断/降级路径全部吞异常 |
| `Task/my_app/backend/services/ms_sla_service.py` | 50 处缺陷 | 单文件最高，SLA 计算链路错误全被吸收 |
| `Task/my_app/backend/services/site_outage_service.py` | 39 处缺陷 | 站点中断统计可静默产出错误数字 |
| `Unified_Tools/incident_overview/app.py` | **73 处缺陷** | 全仓最差文件 |

**错误传播断裂链示例** —— `gis.py:455-464`：
```python
        except Exception:
            pass          # WO 查询整段失败，wo_list 保持空
    # SLA统计
    sla_cursor = conn.execute(...)   # 继续往下算，返回 200 OK + 残缺数据
```
调用方无法区分"没有工单"与"查询挂了"。

### 2.2 高圈复杂度函数（CC ≥ 20 共 192 个）

| CC | 行数 | 位置 | 函数 |
|---:|---:|---|---|
| **112** | 892 | `ticket_export_rpa/yingdao_to_python_V2.py:1658` | `wait_my_export_and_download` |
| 87 | 205 | `Unified_Tools/incident_overview/app.py:241` | `_get_severity_data` |
| 83 | 326 | `Unified_Tools/IP_Trace_Tool/ip_detect_tool.py:1127` | `analyze_with_local_rules` |
| 66 | 405 | `ticket_export_rpa/yingdao_to_python_V2.py:462` | `run_export_flow` |
| **59** | 231 | `Task/my_app/backend/services/ran_ume_network_kpi.py:909` | `import_to_database` |
| **58** | 242 | `Task/data_base/db_writer_api.py:192` | `write_data`（远程写服务核心） |
| **55** | 180 | `Task/my_app/backend/routers/gis.py:534` | `get_realtime_sites` |
| 53 | 133 | `Task/my_app/backend/routers/analysis.py:169` | `_generate_chart_config` |
| **51** | 181 | `Task/my_app/backend/routers/gis.py:185` | `get_sites` |
| 48 | 254 | `Task/my_app/backend/routers/gis.py:877` | `get_region_boundaries` |
| 48 | 162 | `Task/my_app/backend/routers/alarm_dashboard.py:358` | `alarm_dashboard_overview` |
| — | 336 | `Task/my_app/backend/main.py:89` | `_register_all_tasks`（20 个任务硬编码在一个函数里） |

> 业界阈值：CC > 10 需重构，CC > 20 视为不可测试。本仓 192 个函数越线，其中 12 个 CC > 50。

### 2.3 重复代码

| 类型 | 数量 | 说明 |
|---|---:|---|
| 逐字节相同的源文件簇 | 28 簇 / 40 个冗余文件 | 见下表 |
| 12 行以上重复代码块（跨文件） | 2,907 处 | 主要来自 5 套 WareHouseDashBoard 与 my_app/MTN_Comsal 双份 |

**完全相同文件（应立即合并）：**

| 大小 | 份数 | 路径 |
|---:|---:|---|
| 124.7 KB | 2 | `Unified_Tools/WareHouseDashBoard/templates/index.html` = `WareHouseDashBoard/templates/index.html` |
| 60.7 KB | 2 | `.../app_sp_optimized.py` 同上两处 |
| 46.2 KB | 2 | `ticket_export_rpa/mail_126.py` = `TMP/mail_126.py` |
| 19.8 KB | 2 | `Task/ip_ran/_configs_generated.py` = `Task/my_app/backend/services/ipran_configs_generated.py` |
| 18.6 KB | 2 | `Task/MTN_Comsal/.../tt_wo_dashboard.py` = `Task/my_app/.../tt_wo_dashboard.py` |
| 15.9 KB | 2 | `Task/auth_manager.py` = `Task/my_app/backend/services/auth_manager.py` |
| 6.4 KB | **4** | `sftp2excel6pm.py` / `sp.py` 四处副本（**均含同一明文 SFTP 口令**） |
| 5.4 KB | **4** | `captrue_sp_dashboard.py` × 4 个 WareHouseDashBoard 变体 |

### 2.4 资源管理

`Task/my_app/backend` 内 **62 处**打开 DB 连接但无 `try/finally` 或 `with` 保护，异常路径下连接泄漏。典型：`tables.py:40 get_table_data`、`gis.py:185 get_sites`、`analysis.py:31 create_analysis`、`alarm_dashboard.py:358`。SQLite 单文件下表现为句柄堆积 + `database is locked`。

---

## 3. 安全隐患（分级）

### 3.1 🔴 高危（P0，需 24h 内处置）

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| S1 | **明文凭据硬编码并已提交到 Git 远程** | 43 处 Python + 6 处 JSON | 见下方清单。已推送到 `origin/master`，存在于 27 次提交的历史中，`git rm` 无法消除 |
| S2 | **后端零鉴权** | `Task/my_app/backend/**` 全部 6 个 router + `main.py` 所有端点 | 全仓无一处 `Depends`/`OAuth2`/`APIKeyHeader`。任何能连到 7038 端口的人可读全部业务数据 |
| S3 | **未授权触发任务执行** | `main.py:550 POST /api/tasks/{task_id}/run` | 无鉴权即可远程触发 20 个重任务，包括**向真实收件人名单群发邮件报告**、拉取上游 UME（单账号会被互踢） |
| S4 | **未授权覆盖数据库表** | `routers/upload.py:34-91` | 无鉴权上传；`df.to_sql(table_name, if_exists='replace')`，表名由文件名推导 → 上传 `master_site_db.xlsx` 即可**整表覆盖**站点主表 |
| S5 | **CORS 通配 + 允许凭据** | `main.py:42-48` `allow_origins=["*"]` + `allow_credentials=True` | Starlette 会回显请求 Origin，等价于任意站点可带凭据跨域调用全部 API |

**明文凭据清单（节选，全部已进 Git 历史）：**

| 凭据类型 | 值特征 | 出现位置（部分） |
|---|---|---|
| ZTE UME 网管口令 | `Zte@2025!` | `ran_ume_network_kpi.py:61`、`ran_ume_main_kpi.py:61`、`ms_sla_service.py:111`、`auth_manager.py:14`、`Task/ran_ume/ran_ume_login.py:40`、`Task/RAN/MS_SLA/ran_ume_sla.py:59` |
| IPRAN UME 口令 | `Zte@lbr202607` | `ipran_ume_kpi_service.py:56`、`Task/ip_ran/ipran_ume_kpi.py:60` |
| CCN UME 口令 | `Mwebazeaaron@25` | `ccn_ume_kpi_service.py:54`、`Task/ccn_ume/ccn_ume_kpi.py:53` |
| eFlow 口令 | `Brysj*8*` | `ticket_export_rpa/*.py` × 6、`Site_outage/*.py` × 2 |
| SFTP 口令 | `UbuntU1!2@3#4$` | `sp.py`、`sftp2excel6pm.py`、`sp_remote_check.py` 等 **8 处** |
| 126 邮箱授权码 | `LQcTaMMuWmhvAfRB` | `mail_126.py` × 3、`sp_remote_126mial.py` × 2 |
| OpenAI API Key | `sk-proj-VZKSR4s7...` | `Unified_Tools/IP_Trace_Tool/ip_detect_tool.py:25` |
| NVIDIA API Key | `nvapi-YCowbBHk...` | `test_more_models.py:8`、`openclaw.json` |
| Agnes API Key | `sk-p2urnUzv9gy...` | `test_more_models.py:59` |
| Google API Key | `AIzaSyBbkE6SAQ...` | `openclaw.json` |
| PushPlus / Server酱 Token | `f9cf7778...` / `SCT389311...` | `weixin_notifier.py:38,41` |
| CodeBuddy Key + gateway token | `sk-cp-tPLgq6Ls...`（125 字符） | `Task/PS_CS_CORE_Scripts/openclaw_new.json` |
| 默认弱口令 | `admin/admin123` | `captrue_sp_dashboard.py:89,229`（× 4 份） |

> ✅ 缓解事实：`https://github.com/Jouwala/my_tools_Liberia_noc1-rpa` 当前返回 404（私有或已删除），尚未确认对匿名公众暴露。但凭据已离开本机、存在于托管远程的历史中，**必须按"已泄露"处理并全部轮换**。

### 3.2 🟠 中危（P1）

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| S6 | **SQL 注入：ORDER BY 拼接** | `routers/tables.py:69` | `f' ORDER BY "{sort_by}" ...'`，`sort_by` 为未校验 Query 参数，双引号可闭合逃逸 |
| S7 | **SQL 注入：列名拼接** | `routers/tables.py:131` | `f'SELECT "{column}" FROM ...'`，`column` 为路径参数，无白名单 |
| S8 | 路径穿越 | `routers/upload.py:43-44` | `safe_name = f"{uuid}_{file.filename}"` 后直接 `UPLOAD_DIR / safe_name`；`filename` 含 `\..\` 时可写出目录 |
| S9 | 上传无大小/行数限制 | `routers/upload.py:46` | `await file.read()` 一次性读进内存，可 OOM |
| S10 | **禁用 TLS 校验** | `ipran_ume_kpi_service.py:830`、`ticket_export_rpa/yingdao_to_python*.py:1583/1654`、`TMP/probe_*.py` 共 12 处 | `verify=False`，可被中间人劫持网管会话 |
| S11 | `shell=True` 子进程 | `Task/my_app/TMP/restart_watch.py:37,66` | 目前参数为常量，但模式本身危险 |
| S12 | 前端 `xlsx@0.18.5` | `frontend/package.json` | 该版本存在原型污染 CVE-2023-30533 与 ReDoS CVE-2024-22363，npm 上无修复版本 |
| S13 | 依赖全部使用 `>=` 下限约束 | 15 个 `requirements.txt` | 无 lockfile，`pip install` 结果不可复现，供应链风险 |

### 3.3 🟡 低危（P2）

| # | 问题 | 位置 |
|---|---|---|
| S14 | 大量 f-string 拼接表名/列名（126 处在 `my_app/backend`） | 来源为内部 schema 探测，非用户输入，但缺少标识符白名单兜底 |
| S15 | 错误详情回显到客户端 | `upload.py:58` `detail=f"文件解析失败: {str(e)}"` 泄漏内部路径 |
| S16 | `@app.on_event("startup")` 已废弃 | `main.py:463`，应迁移 `lifespan` |
| S17 | `nginx.pid` 被提交 | `nginx-1.28.0/nginx-1.28.0/logs/nginx.pid` |
| S18 | 未发现不安全反序列化 | ✅ 全仓 0 处 `pickle.load` / `eval` / `exec` / `yaml.load` — 该项通过 |

---

## 4. 前端代码质量

技术栈：React 19 + TypeScript 6 + Vite 8 + antd 6 + ECharts 6 + Leaflet。

### 4.1 组件拆分与复用性 —— ❌ 差

| 文件 | 行数 | useState | useMemo | 组件数 |
|---|---:|---:|---:|---:|
| `src/pages/DataSync.tsx` | 1,233 | **22** | 0 | 1 |
| `src/pages/GISMap.tsx` | 1,048 | **24** | 11 | 1 |
| `src/pages/AlarmDashboard.tsx` | 733 | 10 | 9 | 1 |
| `src/pages/TTWODashboard.tsx` | 676 | 14 | 12 | 1 |
| `src/components/` | — | — | — | **仅 1 个共享组件**（`DraggableClickModal`） |

10 个页面共 8,821 行，共享组件目录只有 1 个文件。图表配置、筛选栏、KPI 卡片、表格列定义在各页面内重复实现。

### 4.2 状态管理 —— ❌ 混乱

- 全仓 **175 个 `useState`**，`useEffect` 仅 39 个，**无任何状态库**（Redux/Zustand/Jotai/React Query 均未使用）。
- 唯一的全局状态是 `TaskStatusContext.tsx`（62 行，1 个 state）。
- `GISMap.tsx` 单文件 24 个独立 `useState` 管理筛选器/图层/弹窗/加载态，任一变更触发整页 1,048 行组件重渲染。
- 服务端数据无缓存/失效层，`src/cache.ts` 仅 42 行手写 Map 缓存。
- `DataSync.tsx` 22 个 state 且 **0 个 `useMemo`**，派生数据每次渲染重算。

### 4.3 类型安全 —— ❌ 差

| 指标 | 值 |
|---|---|
| `tsconfig.json` | `"strict": false` |
| 缺失的严格项 | `noImplicitAny`、`strictNullChecks`、`noUnusedLocals`、`noUnusedParameters` 全未开启 |
| `any` 出现次数 | **496 次**（`GISMap.tsx` 140 次、`MTN_Comsal/GISMap.tsx` 130 次、`TTWODashboard.tsx` 49 次） |
| API 响应类型定义 | 无 —— `src/api.ts` 仅 14 行，无一个 interface |
| `@ts-ignore` | 0（说明不是"压制错误"，而是**根本没开检查**） |

### 4.4 可访问性 —— ❌ 差

| 指标 | 值 |
|---|---|
| `aria-*` 属性总数 | **1 个**（全部 26 个 TSX 文件） |
| 可点击的 `<div>/<span>`（无 `role`/`tabIndex`/键盘处理） | 6 处（`AlarmDashboard.tsx` 4 处、两个 `GISMap.tsx` 各 1 处） |
| `<img>` 无 `alt` | 0/0（未使用 img 标签） |
| 键盘可达性、焦点管理 | 未实现 |

### 4.5 样式与依赖

- **558 处内联 `style={{...}}`**，而 `src/theme.ts`（57 行设计令牌）形同虚设 → 主题无法统一切换，且与既有 ECharts 主题坑（工厂函数）叠加。
- `dependencies` 中混入 devDeps：`@types/react`、`@types/react-dom`、`@types/leaflet`、`@vitejs/plugin-react` 应移入 `devDependencies`。
- 装了 4 个 `@turf/*` 包（bezier-spline / buffer / helpers / intersect）仅服务于 GIS 蒙层，构建体积可观（`dist` 中 antd 1.1 MB + echarts 1.1 MB + vendor 320 KB）。
- 无 ESLint、无 Prettier、无前端测试。

---

## 5. 仓库卫生

| 问题 | 数量 | 详情 |
|---|---:|---|
| **构建产物被跟踪** | **51 个文件** | `frontend/dist_test/` 与 `frontend/dist_rebuild/` 两套完整构建输出，含 4 个 >1 MB 的 bundle（`antd-*.js` 1,155 KB × 2、`echarts-*.js` 1,110 KB × 2）。占已跟踪总量的 **~40%** |
| **第三方源码被跟踪** | 33 个文件 | 整个 `nginx-1.28.0/` 发行包，含 `CHANGES.ru`(496 KB)、`nginx.vim`(111 KB)、`nginx.pid` |
| **生成的报告被跟踪** | 12 个 HTML | `Unified_Tools/scripts/data_report_2026*.html` × 6、`Task/RAN/MS_SLA/*Daily Report_2026-07-23.html` × 2、`incident_overview/index_part_1~4.html` |
| **`- Copy` 副本文件** | 5 个 | `get_eflow_table - Copy.py`、`get_eflow_realtime_alarm - Copy.py`、`gernarate_sp_report - Copy (2).py` 等 |
| **乱码文件名** | 2 个 | `index - ╕▒▒╛.html`、`app - ╕▒▒╛.py`（GBK "副本" 被误编码） |
| **含密钥的配置被跟踪** | 2 个 | `openclaw.json`（4 个 key）、`Task/PS_CS_CORE_Scripts/openclaw_new.json`（2 个 key） |
| 大数据快照被跟踪 | 1 个 | `Liberia.json` 444 KB |

### `.gitignore` 覆盖缺口

现有 78 行规则已覆盖 `*.xlsx/*.db/*.log/node_modules/dist/` 等，但存在以下缺口：

| 缺口 | 建议追加规则 |
|---|---|
| `dist_test/`、`dist_rebuild/`（`dist/` 未匹配到带后缀的目录） | `dist*/`、`**/dist_*/` |
| nginx 第三方源码 | `nginx-*/` |
| 生成的 HTML 报告 | `**/data_report_*.html`、`**/*Daily Report_*.html`、`**/index_part_*.html` |
| `.env` 仅根级匹配 | 改为 `**/.env`、`**/.env.*`、`!**/.env.example` |
| OpenClaw 配置（含密钥） | `openclaw*.json` |
| `*.pid`、`*.orig`、`*.bak`、`*.tmp` | 追加 |
| `- Copy` 副本 | `**/*[Cc]opy*.py`（或直接删除文件） |
| `.trae/` 未忽略（`.qoder/`、`.workbuddy/` 已忽略） | `.trae/` |

### 工程化缺失

| 项 | 状态 |
|---|---|
| CI/CD（`.github/`） | ❌ 无 |
| Lint 配置（eslint / ruff / flake8） | ❌ 无 |
| 格式化（prettier / black） | ❌ 无 |
| `pyproject.toml` / `setup.cfg` | ❌ 无 |
| pre-commit hook | ❌ 无 |
| 依赖锁定（Python） | ❌ 15 个 `requirements.txt` 全用 `>=` |
| 测试 | 🟡 有 `Task/my_app/tests/`（9 个测试文件，含 e2e），但无覆盖率统计、不在 CI 中运行 |

---

## 6. 问题热点汇总与重构建议

### 6.1 问题密度排名（按缺陷计数）

| 排名 | 文件 | 缺陷数 | 主要问题 | 建议 |
|---:|---|---:|---|---|
| 1 | `Unified_Tools/incident_overview/app.py` | 73 | 吞异常 73、CC 87 函数 | 拆分 `_get_severity_data`，统一异常边界 |
| 2 | `Unified_Tools/incident_overview/app - ╕▒▒╛.py` | 71 | **整个文件是副本** | **直接删除** |
| 3 | `Task/my_app/backend/services/ms_sla_service.py` | 59 | 2,261 行、50 处吞异常、明文口令 | 拆分为 fetch/transform/report 三层 |
| 4 | `ticket_export_rpa/yingdao_to_python_V2.py` | 58 | CC 112 / 892 行单函数、明文口令、`verify=False` | 已被 `my_app` 内联替代 → 归档或删除 |
| 5 | `ticket_export_rpa/yingdao_to_python.py` | 53 | 同上（旧版本） | **直接删除** |
| 6 | `Task/my_app/backend/services/site_outage_service.py` | 39 | 39 处吞异常 | 引入统一异常装饰器 |
| 7 | `Task/my_app/backend/routers/gis.py` | 36 | 1,000+ 行、4 个 CC>45 函数、6 处 `pass`、连接泄漏 | **优先重构**（详见 R3） |
| 8 | `Task/RAN/MS_SLA/update_contract_kpis_report.py` | 30 | 1,762 行、`main()` 280 行 | 与 `my_app` 版本合并 |
| 9 | `WareHouseDashBoard/app_sp_optimized.py` ×2 | 26×2 | 逐字节重复 | 删除一份 |
| 10 | `Task/my_app/backend/services/sync_from_eflow_api.py` | 24 | 吞异常 | 补错误传播 |

### 6.2 优先级重构方案

| ID | 优先级 | 行动 | 工作量 | 预期收益 | 风险 |
|---|---|---|---|---|---|
| **R1** | 🔴 P0 立即 | **凭据全量轮换 + 外置**：① 轮换全部 13 类凭据（UME×3、eFlow、SFTP、126 邮箱、OpenAI/NVIDIA/Agnes/Google Key、PushPlus/Server酱、CodeBuddy）；② 所有值改读 `os.getenv`，本地放 `.env`（已 gitignore）；③ `git filter-repo` 清洗历史并强推；④ 确认 GitHub 仓库为 private 或删除 | 1–2 天 | 消除全部 P0 泄露面 | 高：历史重写会使已有 clone 失效；轮换 UME 口令需同步 6+ 个脚本，漏改会导致定时任务批量失败 → **建议先做 ①②，③ 单独安排窗口** |
| **R2** | 🔴 P0 | **加最小鉴权层**：FastAPI 全局 `Depends(verify_api_key)`（读环境变量的静态 token），`/api/health` 白名单；uvicorn 由 `0.0.0.0` 改绑 `127.0.0.1` + nginx 反代加 Basic Auth | 0.5 天 | 关闭 S2/S3/S4 三个高危；防止误触发邮件群发 | 中：前端需带 header，需同步改 `src/api.ts`；重启后端会中断当前任务窗口（避开 03:35/05:35 批次） |
| **R3** | 🟠 P1 | **修 SQL 注入 + 连接泄漏**：`tables.py:69/131` 改列名白名单（从 `PRAGMA table_info` 取合法列做集合校验）；用 `contextlib.closing` 或依赖注入包装 62 处连接 | 1 天 | 关闭 S6/S7；消除 `database is locked` 类偶发故障 | 低：纯局部改造，可单元测试覆盖 |
| **R4** | 🟠 P1 | **CORS 收紧**：`allow_origins` 改显式白名单（前端实际域名 + `http://localhost:5173`） | 0.5 h | 关闭 S5 | 极低 |
| **R5** | 🟠 P1 | **删除冗余**：40 个逐字节重复文件、5 个 `- Copy`、2 个乱码副本、`ticket_export_rpa/yingdao_to_python*.py`（已被内联替代）；`WareHouseDashBoard/` 与 `Unified_Tools/WareHouseDashBoard/` 二选一 | 0.5 天 | 源码量减少 ~15%，热点榜 TOP10 直接消掉 4 项 | 中：需先确认哪份是"活的"——建议按 `git log -1 --format=%ci <file>` 与调度器引用关系判定 |
| **R6** | 🟠 P1 | **仓库瘦身**：`git rm -r --cached` 掉 `dist_test/`、`dist_rebuild/`、`nginx-1.28.0/`、12 个生成报告、2 个含密钥 JSON；补齐 `.gitignore`（见 §5） | 2 h | 跟踪体积 14 MB → ~6 MB，clone 提速 | 低 |
| **R7** | 🟠 P1 | **统一异常边界**：新增 `backend/services/errors.py`，提供 `@guard(reraise=True, log=logger)` 装饰器 + FastAPI `exception_handler`；分批把 286 处 `my_app/backend` 缺陷替换（先 routers，后 services） | 3–5 天 | 故障可观测；`task_execution_log` 里的 error 字段真正有内容；排障时间显著下降 | 中：改动面广，需分模块灰度；部分 `pass` 是**刻意**的兼容分支，替换时须逐个判断，不能批量 sed |
| **R8** | 🟡 P2 | **拆 `gis.py`**：1,000 行 → `gis/schema.py`（探测）+ `gis/sites.py` + `gis/realtime.py` + `gis/boundaries.py`；`get_sites`(CC51) / `get_realtime_sites`(CC55) 抽出筛选器构建与结果组装 | 2–3 天 | 4 个超高 CC 函数降到 <15，可单测 | 中：GIS 是主看板，需 e2e 回归（已有 `test_frontend_e2e.py` 可复用） |
| **R9** | 🟡 P2 | **拆 `main.py:_register_all_tasks`(336 行)**：改为 `backend/tasks/registry.py` + 每任务一个模块，用声明式表注册 | 1 天 | 新增任务不再改 336 行函数；降低改错风险 | 低 |
| **R10** | 🟡 P2 | **前端类型化**：`strict: true` 分步开启（先 `noImplicitAny`），为 API 响应写 interface（可由 FastAPI OpenAPI schema 生成）；496 处 `any` 分批消除 | 3–5 天 | 编译期拦截大部分前端 bug | 中：开 strict 会一次冒出数百错误，须按文件用 `// @ts-nocheck` 渐进 |
| **R11** | 🟡 P2 | **前端组件化 + 状态收敛**：抽 `components/`（FilterBar / KpiCard / ChartPanel / DataTable）；引入 TanStack Query 管理服务端状态，替换手写 `cache.ts`；`GISMap.tsx` 24 个 state 用 `useReducer` 收敛 | 5–8 天 | 页面均行数从 1,000+ 降到 300 以内；重渲染次数下降 | 中高：GIS/告警看板是核心界面 |
| **R12** | 🟡 P2 | **升级 `xlsx`**：改用 SheetJS 官方 CDN 源（`https://cdn.sheetjs.com/xlsx-x.y.z/...`）或换 `exceljs` | 0.5 天 | 关闭 CVE-2023-30533 / CVE-2024-22363 | 低 |
| **R13** | 🟡 P2 | **补工程化基线**：`ruff` + `black`（Python）、`eslint` + `prettier`（前端）、`pre-commit` 装 `detect-secrets`、Python 依赖改 `pip-compile` 生成 lock | 1–2 天 | 防止新的密钥/低质量代码进仓；依赖可复现 | 低 |
| **R14** | 🟢 P3 | **移除 `verify=False`**：12 处改为配置内网 CA 或 `verify=<ca_bundle>` | 0.5 天 | 关闭 S10 | 中：内网自签证书可能导致请求直接失败，需先备好 CA |

### 6.3 建议执行顺序（4 个批次）

| 批次 | 内容 | 周期 | 出口标准 |
|---|---|---|---|
| **批次 1 — 止血** | R1(①②) → R2 → R4 → R6 | 3 天 | 代码中 0 个明文密钥；所有 API 需鉴权；跟踪体积 <7 MB |
| **批次 2 — 清障** | R3 → R5 → R12 → R13 | 4 天 | 0 个 SQL 注入点；0 个逐字节重复文件；pre-commit 生效 |
| **批次 3 — 治本** | R7 → R9 → R8 | 2 周 | `my_app/backend` 吞异常降到 <30 处；无 CC>25 函数 |
| **批次 4 — 前端** | R10 → R11 → R14 | 2–3 周 | `strict: true` 通过；单页 <400 行；`any` <50 处 |
| **收尾** | R1(③) git 历史清洗 | 独立窗口 | `git log -p` 中 0 个密钥 |

---

## 7. 整体健康度评估

| 维度 | 评分 | 等级 | 判据 |
|---|---:|---|---|
| **安全** | **1.5 / 10** | **F** | 43 处明文凭据已进 Git 远程；全站零鉴权；未授权可覆盖主数据表与群发邮件；CORS 通配+凭据 |
| **后端质量** | 3.5 / 10 | D | 60.9% 的 except 有缺陷；192 个 CC≥20 函数；62 处连接泄漏；2,907 处重复块 |
| **前端质量** | 4.0 / 10 | D+ | `strict:false` + 496 个 `any`；无状态库、175 个 useState；1 个共享组件；a11y 近乎为零 |
| **仓库卫生** | 3.0 / 10 | D | 51 个构建产物 + 33 个第三方源码 + 12 个生成报告 + 2 个密钥 JSON 被跟踪；40 个重复文件 |
| **架构与模块化** | 4.0 / 10 | D+ | 核心 `my_app` 分层清晰（routers/services/models）✅，但被 `MTN_Comsal` 整体分叉、5 套 WareHouseDashBoard 并存拖累 |
| **工程化** | 2.5 / 10 | F+ | 无 CI、无 lint、无格式化、无依赖锁；有测试目录但不在流水线中 |
| **可维护性** | 4.5 / 10 | C- | 中文注释详实、README/方案文档齐备 ✅；但单文件过大、命名混乱（乱码文件名、`- Copy`） |
| **可观测性** | 4.0 / 10 | D+ | 有 `task_execution_log`（含 result/error）与结构化日志 ✅；但 1,086 处吞异常使日志大面积失真 |
| **加权总分** | **3.4 / 10** | **D** | — |

### 一句话结论

> 这是一个**业务价值高、交付节奏快、但工程债严重超载**的运维自动化仓库。功能层面（20 个定时任务、多看板、多数据源打通）已经跑通并产生真实价值；但**安全基线基本为零**——凭据明文入库并推送到托管远程、后端全部端点无鉴权、上传接口可覆盖主数据表——任何一条被利用都会造成生产事故。建议以 **3 天止血批次（R1/R2/R4/R6）** 为最高优先级，其余重构可按批次滚动推进。

### 需要立即人工确认的三件事

1. `https://github.com/Jouwala/my_tools_Liberia_noc1-rpa` 当前是 private 还是已删除？若曾经是 public，**必须假定全部凭据已泄露**。
2. 后端 7038 端口的实际监听范围（`0.0.0.0` vs `127.0.0.1`）与网络可达范围——决定 S2/S3/S4 是"内网风险"还是"已暴露"。
3. `WareHouseDashBoard/` 与 `Unified_Tools/WareHouseDashBoard/`、`ticket_export_rpa/yingdao_to_python*.py` 哪一份仍在被调度器实际调用——决定 R5 删哪一份。

---

*审计方法：Python AST 静态分析（异常处理 / 圈复杂度 / 危险调用模式）+ MD5 全文件去重 + 12 行滑窗重复块检测 + 正则密钥扫描 + Git 跟踪状态与历史比对 + 关键文件人工阅读。分析脚本位于 `TMP/audit_stats.py`、`TMP/audit_py.py`、`TMP/audit_fe.py`，原始结果 `TMP/audit_py.json`。*
