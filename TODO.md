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

- [ ] **数据层裸连接治理（前置调研，非立即改造）。** 运行期已知存在绕过 `get_raw_connection` 的裸 `sqlite3.connect`（如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488`），是**图表数据源**，改造会静默坏图。当前动作：**不再新增**裸连接，并把已有点位登记成清单。
- [ ] **`eflow_tt` 双库归属固化。** 明确"同步只写 `app.db`、`eflow.sqlite3` 副本仅作只读快照"，避免后续有人读错库。结论已在 `PROJECT_DOCS.md` §2 Phase 0.5 闭环，待落到代码注释与手册。
- [ ] **五个关键进程的巡检常态化。** 确认 worker 分组 + 双看门狗在异常退出后确实自愈（步骤见 `docs\manual\13-operations.md`）。

### P2 —— 体验与工程规范

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

- [ ] **版本库整洁收口（2026-09-30，三件事都只等一次提交）。**
  1. **39 个运行时文件已退跟踪，但成果只在索引里，会被下一次 `git reset` 冲掉。** 明细：12 个 SQLite 边车（`Task\RAN\*`、`Task\ip_ran\`、`ticket_export_rpa\` 的 `.sqlite3-shm/-wal`）、`Task\my_app\backend\services\battary_kpi_fetch\output_socket\.email_send.lock`、门户 `scripts\whatsapp_analysis\reports\` 的 26 份日报。忽略规则已同时补好（根 `.gitignore` 的 `*.sqlite3-shm/wal` + `*-journal`，门户 `.gitignore` 的 `scripts/whatsapp_analysis/reports/`），**磁盘一个文件都没删**（边车与 27 份报告仍在原位）。教训见 `development.md` 自检 ⑦：本会话第一次做完就被并发会话的 `git reset` 复原过一次。
     验收标准：`git ls-files -i -c --exclude-standard` 总数 = 3419（隔离桶）+ 32（真源码基线，一条都不许动）= **3451**；`git ls-files` 里不再出现 `sqlite3-shm/wal`、`.email_send.lock`、`whatsapp_analysis/reports/`。
  2. **`_myapp_trash_20260913` 的 3419 条跟踪 —— 2026-09-30 已 `git rm --cached -r` 退干净，等提交。** 内容实测 3378 个在 `B_portal_profiles\`（Chrome profile 的 woff/ttf、`.tflite`、`.pb`），其余 41 个是 `A_root_junk`/`B_tmp`/`B_outputs` 的转储，没有一个是源码。退跟踪后索引从 4917 降到 **1498**，磁盘 21253 个文件原样不动（该路径是 09-25 建的符号链接，指向 `_quarantine_20260925\_myapp_trash_20260913`，**链接本身要留着** —— 它让历史记忆里记录的还原路径继续可解析）。⚠️ 顺序教训（本次验证过）：必须先 `git rm --cached -r`，再动这个链接；反了的话 git 会把它当普通目录，3419 条变成工作区删除噪声。
  3. **`Task\_fe_dist` 剪枝**：可达性审计（`node Task\my_app\TMP\_audit_fe_dist.mjs`，只读）2026-09-30 实测总 12889 个文件 / 308.1MB，其中**在用**只有 14 个 HTML 入口 + 79 个可达 chunk（合计 10.3MB），**不可达 chunk 12749 个 / 284.7MB**，按月龄分布为 0-1天 4017 个(86.3MB)、2-7天 5991 个(136.4MB)、8-30天 2741 个(61.9MB) —— 数字每天随构建继续涨。⚠️ 该目录是**线上服务目录**（7090 由 vite preview 读它，`nginx.conf` 里没有它的 alias），只能同盘挪进隔离区、不能删；`emptyOutDir:false` 是实测约束（安全删除钩子会中断 vite 的 `prepare-out-dir`），**不许**改成 true，所以陈旧产物只能靠外部清扫 —— 建议把那个审计脚本升级出 `--prune` 模式与月龄阈值。
     ⚠️ 两个必须先确认的点：a) 审计的可达集**只跟 `assets/` 引用与相对 chunk import**，`lib\leaflet\*`、`legacy-*.css`、`*.geo.json`、`favicon.*` 这 40 个被单独归到「其他」桶，不在剪枝候选里（好事，别手动把它们加进清单）；b) 挪走孤儿 chunk 会让**浏览器里缓存的旧 `index.html`** 报 404 直到硬刷新 —— 所以首轮只清「月龄 ≥2 天」的，0-1 天那 4017 个留给下一次构建自然淘汰。
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
