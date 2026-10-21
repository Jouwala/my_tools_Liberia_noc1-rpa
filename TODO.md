# 03 TODO.md —— 当前任务、优先级和开发进度

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录
> **本文只放"当前在办"的少数几项。** 历史清单与已完成规划**不进本文**——那些看 `git log`、
> `Task\my_app\PROJECT_DOCS.md`（历史档案）以及各子系统手册。

## 一、进度快照

| 系统 | 状态 |
| --- | --- |
| 统一门户 | **活跃开发中**。近期连续 6 次提交集中在门户：QC 看板改版、MS KPI/SP 报表、UME 大屏接口、FME 工程师排名、GIS 站点下钻、QC 弹窗拖拽、静态资源补全 |
| my_app | 运行中（后端 7038 + 多 worker + 看门狗）。近期以稳定性与数据正确性为主 |
| 门户后端 / 鉴权 | 已通过「用户管理」验收（见 `vite.config.ts_bak_20260920_用户管理已验收`），鉴权开关机制已落地 |
| FineBI 迁移 | 进行中。门户内 FineBI 条目仍有**目录占位链接**待替换 |
| SQLite → PostgreSQL 迁移 | **规划定稿，未执行**（`PROJECT_DOCS.md` §2）。执行前提见下 |
| 商用就绪度整改 | 有专项结论文档，未全部闭环（见 `MsPortal 商用就绪度检测 —— 结论与整改方案.md`） |

## 二、当前在办（按优先级）

### P0 —— 阻塞使用者，优先处理

- [ ] **替换门户内的 FineBI 占位链接。** 现状部分报表仍是目录占位（标签"链接待更新"、状态 beta），用户点了到不了实际报表。需在门户「编辑看板配置」逐条替换。（`README.md` 已明示此状态）
- [ ] **QC 面板改版的验收闭环。** 卡片改版（左侧状态竖条、纯白底、数字居中、标题/副行左对齐）已提交，需确认线上两档刷新节奏（全量 `:06:30` / 告警每 5 分钟）与失败态展示符合预期，并核对 `MsPortal\QC面板展示优化建议_20260922.md` 中的建议项是否已全部落地或明确不做。
- [ ] **商用就绪度整改项收口。** 按 `MsPortal 商用就绪度检测 —— 结论与整改方案.md` 逐条确认状态。

### P1 —— 数据正确性与稳定性

- [ ] **站点可用率取数改走本地 PG（2026-10-15，已定性、待观察上游）。** 站点可用率已从远端 UME HTTP（`192.168.100.19:8765`）改为**本地 PG 优先、远端回退**，代码在 `Task\my_app\backend\services\site_availability_service.py`（`PG_SPEC` / `_load_pg_tech` / `_load_tech`，快照 `..._bak_20261015_PG双模前`）。
  - **2G / 3G 两源等价**：重叠键 100% 一致、零值差异；且 PG 严格超集（另有 47 个站点在 `master_site_db` 里但远端查不到 —— 切换后这些站从"空白"变为有数据）。同时去掉对 .19 HTTP API 的运行时依赖。
  - **4G 已定性（2026-10-15 实测 UME 直查）**：用 MS SLA 的 FDD 模板对 2026-10 整月直查 UME 自身（`10.100.28.27:28001`）当裁判，5342 条：
    - 只切换 `indexfillingtype`（`default` vs `zeroDenominator`）→ **5342/5342 逐行完全相同**，故**该设置不是差异根因**（原假设已证伪）。
    - **UME == PG = 99.4%**（排除最新一天的同步滞后后达 **99.9%**，仅 4 条残差）；**UME == 远端 = 85.8%**，且排除最新几天后仍卡在 ~86%。
    - **结论：PG 就是 UME 的值，4G 走 PG 正确，无需回退远端。** 远端 `4G_Main_Kpi_Site_Daily`（`FDD_KPIs_ZTE_OLR_FB` 模板 + `layer: Sites`）的 4G 可用率**系统性偏高约 14%**，是独立的上游数据质量问题。
  **待办**：把"远端 4G 可用率偏高约 14%"作为**上游数据问题**反馈（本条不再阻塞本站点可用率看板）；`docs\manual\` 的站点可用率口径说明如需同步为"PG 与 UME 一致"，一并更新。**观察点**：PG 的 4G 当天值有增量同步滞后（当天可能尚未吸收终值，如 `2026-10-14` 有 27 条残差），看板若要求当天实时终值需另评估。
- [ ] **P1 告警推送加 ext 通道 fallback（2026-10-08）。** Baileys 主通道失败（群名解析不到 JID / 凭据过期 / WhatsApp 流控 428）时，自动把同一批 `messages` 投到 `data/tt_alert_job.json`，由已登录的 WhatsApp Web 扩展兜底。改动已落到 `Task\my_app\backend\services\tt_alarm_whatsapp_service.py`（新增 `try_ext_fallback`、在两个失败分支调用） + 4 条 stub 用例 + `architecture.md` 8.x ADR；**待验证**：① 重启 `m` 组 worker 后第一次跑 0 候选 → 任务历史页面要能看到新字段 `ext_fallback` 为空（`attempted: false`）；② 手动制造一次 Baileys 失败（把 `GROUPS` 临时改成一个不存在的群名跑一次）→ ext 通道应兜住（前提：Chrome 开着 + 扩展已登录）→ `out.success=True` + `warnings` 含"兜住 N/M 单"。**回滚手段**：revert 三个文件即可。
- [ ] **数据层裸连接治理（前置调研，非立即改造）。** 运行期已知存在绕过 `get_raw_connection` 的裸 `sqlite3.connect`（如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488`），是**图表数据源**，改造会静默坏图。当前动作：**不再新增**裸连接，并把已有点位登记成清单。
- [ ] **`eflow_tt` 双库归属固化。** 明确"同步只写 `app.db`、`eflow.sqlite3` 副本仅作只读快照"，避免后续有人读错库。结论已在 `PROJECT_DOCS.md` §2 Phase 0.5 闭环，待落到代码注释与手册。
- [ ] **五个关键进程的巡检常态化。** 确认 worker 分组 + 双看门狗在异常退出后确实自愈（步骤见 `docs\manual\13-operations.md`）。

### P2 —— 体验与工程规范

- [ ] **主开关「跳过手动停止」的后续项（2026-10-21 立）。** 功能与根因修复已落地
      （`task_runner.toggle_all_tasks` 双向跳过 `manually_stopped=1`；
      `tools/fix_task_schedule_dupes.py` 修掉 SQLite 缺主键导致 146 行的漂移）。
      遗留：
  1. **旋转那批仍在 git 历史里的明文口令**（`tests/test_engineering_guards.py` 的
     `_KNOWN_SECRETS` 17 条 + `docs/manual/13-operations.md` 曾写过 3 个 UME 口令）。
     源码已清、守卫已拦「再写回」，但**进过历史的口令只能轮换才算消除**，
     需拉运维在 UME / 各凭据后台改密，属仓库外的动作。
  2. **`MASTER_SWITCH_EXEMPT_IDS` 与 `manually_stopped` 的语义分层**：`whatsapp_send_ext`
     已于 2026-10-21 移出豁免名单（改由「用户手动关 + 主开关不覆盖」保证单通道）。
     若日后仍需「按业务长期钉死关闭」这一类，应新增独立的 `master_switch_pinned_off`
     概念，而不是把 ID 塞回豁免名单 —— 豁免（不参与主开关）与「参与但被用户手动关住」
     是两种意图，混用会再次出现 2026-10-20「关不掉 / 又自己跑起来」那类症状。
  3. **`task_schedule_config` 双库无自动同步**：本表靠约定人工保持 SQLite 与 PG 一致
     （`tools/sync_manual_stop_to_pg.py` 补 `manually_stopped`）。是否要加自动同步或
     干脆二选一，待定。
  4. **重启 7038 才会加载**：`MASTER_SWITCH_EXEMPT_IDS` 在 import 期求值，
     `whatsapp_send_ext` 移出豁免名单需重启后端才生效（worker 侧同理）。

- [ ] **7038 找个空闲时段重启，让 TT 快速分析的两项已落盘改动生效（2026-10-19 立，10-20 补充）。**
  1. **结论卡片正文还是旧文案** —— `> The AI model was unavailable…` 加末行
     `*Model failure reason: 程序化先行（/tt-ai-fast）…*`。磁盘代码是干净的（离线渲染已确认会输出
     `No model is involved` / `无模型参与`），旧文案只来自进程内的旧字节码。
  2. **`provider` 已从 `openwebui` 改成 `both`**（写在 `Task\my_app\backend\services\ai_model_config.json`），
     但 `ai_model_config._cached` 是进程内缓存，所以 `GET /api/ai-model-settings/chain` 仍回 `openwebui`。
     改这一项的原因：Open WebUI（.27，0.12.0）启用了 trusted-header SSO，邮箱密码登录被服务端**永久**关死
     （带真实账密试遍 11 个头名 + 3 组双头全是同一个 400，明细见 `Task\my_app\backend\services\openwebui_client.md`），
     而 `provider=openwebui` 时候选链里只有云端一档、本地 WorkBuddy 档根本不进链，一次 400 就整条失败；
     `both` 让 WorkBuddy 先进链（实测在线、一次对话约 2 秒）。
     **执行**（PowerShell 不支持 `&&`，逐行跑）：
     `netstat -ano | Select-String ':7038\s'` 取 PID → `Stop-Process -Id <PID> -Force`（`backend_watchdog` 数秒内自动拉起）。
     **自查**：
     `(Invoke-RestMethod "http://127.0.0.1:7038/api/eflow-qa/tt-ai-fast?tt=TT202610190094&lang=en").ai.conclusion | Select-String 'No model is involved'` 要命中；
     `(Invoke-RestMethod "http://127.0.0.1:7038/api/ai-model-settings/chain").provider` 要是 `both`。
     **回滚**：把该 json 里的 provider 改回 `openwebui`（文件不入库，只在本机生效）。
     界面不受这两项影响：`?page=eflow_qa` 已只调 `/tt-ai-fast`，线上包 `index-BQiCP-wf.js` 里查不到 `/tt-ai`；
     回归守卫 `tests\test_engineering_guards.py::test_tt_quick_analysis_is_programmatic_only` 已就位（1 passed）。

- [ ] **本 8 份文档体系的落地与首轮校验。** 根目录、门户 `docs\`、`Task\my_app\` 三处已建立；待办：确认三处文件名一致、互链可达，并把索引页接进门户导航。
- [ ] **门户移动端体验复查。** 二维码扫码要求同网段 WiFi，需确认现场网络条件下可用。
- [ ] **根目录过程产物清理。** 根目录残留大量 `tmp_qc*.txt`（76 个）、`_*` 探针与切片文件，属一次性产物。历史教训见 `7b1d33b`（98 个探针脚本误入库）。**清理前先确认无脚本引用。**
  > 2026-09-30 复核并扩范围：实测三处都有，`development.md` 自检 ⑥ 已给出可直接跑的命令与基线。
  > 根目录 78 个 / 359KB（其中 `tmp_qc*` 76 个，与上面一致）；`Task\my_app\` 根目录 4 个
  > （`_p.py` `_s.py` `_slice1.txt` `_tmp_view.txt` —— 落在 venv 根，正是第四节第 7 条禁止的位置）；
  > `Task\my_app\log\` 另有 7 个 `_probe_*.txt` / `_procs*.txt`（09-13/09-16）。门户侧已归零。
  > 计数时**必须排除** `Lib\site-packages\`（numpy/playwright 自己的 `_*` 模块 700+ 个）和
  > `backend\services\_playwright_utils.py`、`src\pages\_TemplatePage.tsx` 这类带下划线的真源码，
  > 否则数字全是假的。按既有约定同盘挪进 `_quarantine_*/`，不做删除。

- [ ] **版本库整洁收口（2026-09-30）。** 本条已提交为独立 chore 提交 `3eaecdb3`（只提索引，没夹带任何在途功能改动），保留在此是为了对照下一次的验收数字。
  1. **39 个运行时文件已退跟踪。** 明细：12 个 SQLite 边车（`Task\RAN\*`、`Task\ip_ran\`、`ticket_export_rpa\` 的 `.sqlite3-shm/-wal`）、`Task\my_app\backend\services\battary_kpi_fetch\output_socket\.email_send.lock`、门户 `scripts\whatsapp_analysis\reports\` 的 26 份日报。忽略规则同时补好（根 `.gitignore` 的 `*.sqlite3-shm/wal` + `*-journal`，门户 `.gitignore` 的 `scripts/whatsapp_analysis/reports/`），**磁盘一个文件都没删**（边车与 27 份报告仍在原位）。教训见 `development.md` 自检 ⑦：本会话第一次做完就被并发会话的 `git reset` 复原过一次，所以**只动索引的改动必须当次提交掉**。
     验收标准（`3eaecdb3` 之后）：`git ls-files -i -c --exclude-standard` 总数应 = **32**（全是真源码基线，一条都不许动），`_myapp_trash_20260913` 与 `git ls-files` 里的 `sqlite3-shm/wal`、`.email_send.lock`、`whatsapp_analysis/reports/` 均为 0；索引总文件数 **1498**。
  2. **`_myapp_trash_20260913` 的 3419 条跟踪 —— 已 `git rm --cached -r` 并随 `3eaecdb3` 提交，HEAD 里现在为 0。** 内容实测 3378 个在 `B_portal_profiles\`（Chrome profile 的 woff/ttf、`.tflite`、`.pb`），其余 41 个是 `A_root_junk`/`B_tmp`/`B_outputs` 的转储，没有一个是源码。退跟踪后索引从 4917 降到 **1498**，磁盘 21253 个文件原样不动（该路径是 09-25 建的符号链接，指向 `_quarantine_20260925\_myapp_trash_20260913`，**链接本身要留着** —— 它让历史记忆里记录的还原路径继续可解析）。⚠️ 顺序教训（本次验证过）：必须先 `git rm --cached -r`，再动这个链接；反了的话 git 会把它当普通目录，3419 条变成工作区删除噪声。
  3. **`Task\_fe_dist` 剪枝 —— 2026-09-30 已清完「月龄 ≥ 8 天」那一档，剩下两档待做。** 首次执行挪走 2741 个孤儿 chunk / 61.9MB 到 `_quarantine_20260930\fe_dist_stale\`（同盘 `rename`，**一个都没删**；清单 `_MANIFEST.tsv`、说明与还原命令 `_RESTORE.md`）。产物目录 12955 → **10214** 个文件、336 → **269 MB**。复跑审计在用集不变（14 HTML / 79 可达 chunk），14 个在用页面与入口引用的 7 个资源逐个 200，git 零影响（`_fe_dist/` 与 `/_quarantine_*/` 本来都在忽略清单里）。脚本已升级出 `--apply` / `--min-age-days` / `--dest`，默认仍是只读 dry-run，登记在 `development.md` 的可复用脚本表。
     ⚠️ 该目录是**线上服务目录**（7090 由 vite preview 读它，`nginx.conf` 里没有它的 alias），只能同盘挪、不能删；`emptyOutDir:false` 是实测约束（安全删除钩子会中断 vite 的 `prepare-out-dir`），**不许**改成 true —— 所以这件事**要周期性重跑，不会自己好**。剩余不可达 **10074 个 / 224.2MB**（0-1 天 4017、2-7 天 5991）。下一轮 `--min-age-days=2` 之前注意两点：a) 阈值参数拿不到默认值会变成 NaN，而 `age >= NaN` 恒假 → 候选归零（失败方向是安全的，但会让人误以为清过了；本次实测踩过，脚本已加显式校验）；b) 0-1 天那批里混着**当天正在被人验证的构建**，清它等于赌没人持有旧 `index.html` 的缓存，要挑没人看页面的时段做。
- [ ] **开源许可合规收尾（2026-09-28 核查后的剩余项）。** 已完成：`react-leaflet`（Hippocratic-2.1，非 OSI）连同 `@react-leaflet/core` 一并移除，改为 `Task\my_app\frontend\src\components\LeafletMap.tsx` 的原生 leaflet 封装；`@google/genai`（未使用）与 `@turf/*`（无依赖方）清理；`requirements.lock.txt` 补齐 8 个声明却缺失的运行时依赖。剩余：
  1. `Task\my_app\docs\THIRD-PARTY-NOTICES.md` 需补全 Apache-2.0 / MIT 的署名与许可全文义务，并核对 `xlsx`（SheetJS CDN 版）、`psycopg2-binary`（LGPL，动态链接）两项的表述；
  2. 把许可检查接进 lint / CI，避免再次引入非 OSI 许可（本次即为人工核查才发现）；
  3. **团队约定待写入手册**：`pymupdf`（AGPL-3.0/商业双许可）虽当前零引用，仍应明令 my_app 禁止 `import fitz`，改用 `pypdf`（BSD）；
  4. `GeoLite2-City.mmdb` 尚未落盘，将来下载时需接受 MaxMind EULA（见 `backend/services/ip_trace_service.py:55`）。
  > 本次修复的两个真实缺陷值得留档：`TileLayer`/`CircleMarker`/`Popup`/`Tooltip` 若把 `pane: undefined` 直接塞进 options，会覆盖 Leaflet 的类默认 pane，导致 `getPane()` 返回 `undefined` 并在 `appendChild` 处崩溃（**tsc 与 vite build 均无法发现，只有真实浏览器渲染才暴露**）。冒烟校验应包含「地图页能出瓦片 + 点站点能弹 Popup」。

### 待定 —— 需要决策后才能排期

- [ ] **SQLite → PostgreSQL 迁移是否启动。** 规划已定稿（单 PG 实例 + 每域一个 schema `app_`/`eflow_`、同机 Docker、连接池 `pool_size=20 / max_overflow=10`、低峰切流）。**执行前提**（四项全部落地才可动）：
  1. 回退保证 R7；
  2. 风险 10 / 11 有对策；
  3. 风险 R8 有对策；
  4. 队列层覆盖到位。
  > 范围注意：`db_ps_cs_cn` **整体移出迁移范围**（真数据在远端，经 HTTP 8765 读）；本地同名文件是 0 字节占位。
- [ ] **`db_ps_cs_cn` 本地占位文件是否删除。** 极易被误当数据源（读出来是空的而不是报错）。
- [ ] **门户与 my_app 的视觉规范是否合并为一份。** 目前总则在根 `DESIGN.md`，细节各自维护。
- [ ] **BP Cells Report：`2026-07-01 ~ 07-21` 的四个指标永久缺失，是否接受。**（2026-09-30 记）
  上游远端主日表 `4G_Main_Kpi_Cell_Daily` 在这 21 天是**真实空洞**，UME PM API 侧也只有
  `2026-07-02` 起的数据 —— 两个源都补不了。因此该区间的下钻明细里
  PRB 利用率 / DL 吞吐 / 活跃用户(忙时) / DL 流量 恒为 `—`，页面已按此显示。
  **待业务确认**：这个空洞是上游采集故障还是正常的保留期策略；
  若要补齐，需要上游侧先把这 21 天的历史重新入库。
  另：`2026-06-25 ~ 06-30` 远端有行但 **AU 取不到**，补数会把 `bp_cells` 清零，
  已明确排除（详见 `docs/manual/11-feature-guide.md` §30 的「四个指标只在近期有」）。
- [ ] **BP 历史回填的口径差异是否接受（−13%~−14%）。**（2026-09-30 记）
  已按用户确认完成 `2026-07-22 ~ 09-21`（62 天）的回填，走 bp-v3 忙时口径，
  **覆盖**了这些天原有的 Excel 值：`bp_cells` 系统性低约 13~14%，
  且 `total_cells`（BP 占比分母）从"umlaut 报告过的小区"变成"全网小区"。
  用户已明确接受该副作用。**待办**：确认历史曲线与对外报表的口径说明是否需要同步调整。
  回滚手段：`TMP/_bak_bp_report_*.sqlite3` 快照。

- [ ] **TT 分析「先快后准」备灾（2026-10-08）→ 已转正为纯程序化（2026-10-19）。** 本地规则引擎 + 毫秒级 `GET /api/eflow-qa/tt-ai-fast`
  + `TT_AI_LOCAL_ONLY=1` env 开关，三层兜底详见
  `Task\my_app\backend\routers\eflow_qa.py:564-719`、`backend\services\eflow_rules\tt_rule_evidence.py:858`。
  前端 `EflowQa.tsx` 原先是「fast 立即显示 → 原端点 AI 替换」模式；**2026-10-19 用户要求不再用 AI**，
  页面已改为**只调 `/tt-ai-fast`**，结论文案与徽标统一为「判定结论（本地规则引擎）/ 程序化判定，无模型参与」，
  模型路径 `/tt-ai` 保留但界面不再依赖（`openwebui_client` 仍服务「系统设置 → AI 模型」连通性测试）。
  **待办**：(1) `git status --porcelain` 复查
  `Task\my_app\frontend\src\pages\EflowQa.tsx`、`i18n.tsx`、`backend\routers\eflow_qa.py`
  改动在版本控制下；(2) 提交（`docs\manual\11-feature-guide.md` 14e / 14e-1 与
  `17-rule-engine-vs-llm.md` 17.2.2 已于 2026-10-19 改写为「页面只走程序化」；
  `04-task-system.md` 并没有「TT AI 兜底」一节，无需再等它）。
  回滚手段：`git revert` 本次提交；env `TT_AI_LOCAL_ONLY` 对本页已无作用。

## 三、已完成（近期，供对照）

| 提交 | 内容 |
| --- | --- |
| `e9ec342` | FME 工程师排名、GIS 站点下钻图表拆分与 QC 弹窗拖拽 |
| `58ab07a` | 补齐被引用但从未入库的静态资源，消除拉取后 404 |
| `e448816` | MS KPI/SP 报表、UME 大屏接口与看板深色改版 |
| `0cee167` | QC 看板改版并新增指标快照历史 |
| `7b1d33b` | 清理根目录 98 个一次性探针脚本 |
| `af64f44` / `b88a42b` | 鉴权与自动登录、用户权限、统一界面优化 |

## 四、维护本文的约定

1. **只留在办项。** 做完了就移到「已完成」或直接删掉——`git log` 已经是完整的完成记录，本文不需要再抄一遍。
2. **每条要可执行。** 写"改哪个文件、在哪个界面、验收标准是什么"，不写"优化一下体验"。
3. **标注阻塞原因。** 待定项必须写清"等什么决策/等什么前置"。
4. **定期与 `git log` 对齐。** 每次迭代结束时核对一次，避免本文变成过期的许愿池。
5. **不写敏感值。** 口令、Token、账号一律不出现。

## 五、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 完整提交历史 | `git log --oneline` |
| my_app 历史规划与复盘 | `Task\my_app\PROJECT_DOCS.md` |
| my_app 待清理残留清单 | `Task\my_app\docs\manual\90-appendix.md` |
| 商用就绪度整改 | `liberia-noc_soc-数据看板统一门户\MsPortal 商用就绪度检测 —— 结论与整改方案.md` |
| 迁移专项 | `Task\my_app\docs\FINEBI_MIGRATION.md` |
| 架构与已知风险 | `architecture.md` |
| 开发与回归清单 | `development.md` |

> **工具负责整理，人与 AI 负责协作执行。**
