# CR 同步静默停更 7 周 —— 定位与修复（2026-11-03）

> 现象：MsPortal「Quality Control」面板的 **未关闭变更单 (CR)** 长期显示 **86**，实际系统里已关闭的单仍在被统计。
> 结论：**不是面板缓存问题，是 `eflow_cr` 表自 2026-09-14 起就没再更新过**，面板每次都在如实 COUNT 一份 7 周前的快照。
> 处理：CR 抓取改走列表接口直查（绕开上游已损坏的异步导出）+ 补齐两处静默失败守卫。

---

## 一、结论速览

| 项 | 事实 |
| --- | --- |
| 面板读数 | 86（`portal_qc._CR_OPEN` = `status NOT IN ('Closed','Canceled')` 实时 COUNT） |
| `eflow_cr` 最后成功同步 | **2026-09-14 01:00**（`max(_sync_time)`） |
| 同期 TT / WO / PM | 正常同步至事故当天（`_sync_time` 为当天 18:07） |
| 10/26–11/03 抓取结果 | 失败 **222 次，成功 0 次**，每次日志只有一行 `跳过 eflow_cr: API 未返回数据` |
| 任务整体状态 | 每轮 `success=True` —— 失败被当成「上游暂时没数据」 |

**86 到底错在哪**（用 `base/list` 直查上游 323 条做对照）：

| 分类 | 条数 |
| --- | --- |
| 86 条中，上游现已 `Closed`（已关闭却还在数） | **36** |
| 86 条中，上游已查不到（已归档/删除） | 1 |
| 86 条中，确实仍在途 | 49 |
| 上游真实未关闭总数 | **79** |
| 9/14 之后新增、库里**完全没有**的在途单 | 30 |

→ 多算 37、少算 30，净差 86 vs 79。面板既高估了已关闭的单，又漏掉了新单。

---

## 二、根因链（四层，最后一层决定"没人发现"）

1. **上游导出任务自身失败。**
   `/api/eflow-asset/v1/export/async/eflow-cr` 建的任务在 `export/list` 里始终是
   `status=failed`、`rate=20%`、无 `ftpFilePath`。同代码的 TT/WO/PM 导出一轮 15–30s 完成，
   只有 CR 卡在 20%。**这是真正的断点，且在上游侧。**

2. **客户端只认成功、不认失败。**
   `eflow_api_client._wait_export_ready` 的判定是
   `status in ('success','sucess') or rate == '100%'`，`failed` 被直接忽略；
   轮询 8 次 × 15s（`EXPORT_POLL_MAX_WAIT=120`）耗尽后 **返回空字符串**而不是抛错。

3. **拿空路径去下载 → 500。**
   `_download_export_zip` 用空 `ftpFilePath` 请求下载端点，上游回
   `HTTP/1.1 500 Server Error`，异常向上抛成 `cr pipeline failed`，
   最终只体现为 `fetch_all_data` 里没有 `eFlow CR` 这个键。

4. **失败被归类为"可缺失"。**
   `sync_from_eflow_api.REQUIRED_API_KEYS` 原本只有 `{eFlow TT, eFlow WO}`（注释写着
   "CR/PM/Site/Person 允许缺失"），于是 CR 缺失只打 INFO、不记 `result["errors"]`，
   任务继续 `success=True`。**7 周无人被告警。**

---

## 三、修复内容

### 3.1 CR 改走列表接口直查（`eflow_data_mapper._fetch_cr_via_list`）

- 数据源换成 `/api/eflow-asset/v1/eflow-cr/base/list`（实测可用：323 条、2 页拉完）。
  字段沿用原导出的那套（`CR_FIELDS` + 16 个非 Detail 字段），过滤器仍是 `CR_STATUS_FILTER`。
- **不带时间过滤**：CR 体量小（全量 300 余条、2 个请求），全量直查才能自愈 ——
  停更 7 周期间大量 CR 的 `lastModifiedTime` 早已落在 delta 窗口外，带窗口过滤永远补不回来。
- **状态代码 → 显示名**：列表接口返回 `WaitL5Approve` 这类代码，而库、门户、
  `cr_caliber`（`OPEN_SQL`、里程碑按 `CM HEAD APPROVAL` 大写名匹配）全部建立在显示名上。
  映射由「库内 9/14 快照 × 上游当前代码」交叉比对反推，**6 项全部 N/N 一致**：

  | 上游代码 | 库内显示名 | 一致度 |
  | --- | --- | --- |
  | `WaitL2Approve` | Domain TD Approval | 9/9 |
  | `WaitL3Approve` | BO/FO Head Approval | 4/4 |
  | `WaitL5Approve` | CM Head Approval | 25/25 |
  | `WaitImplement` | Waiting for Implement | 10/10 |
  | `WaitUpdate` | Waiting for Update | 1/1 |
  | `Closed` | Closed | — |

  未映射的代码保留原值并**只告警一次**（不刷日志），避免静默乱标。
- **表头逐字对齐历史导出**（`CR_LIST_HEADER_MAP`）：下游 `_sync_generic` 用
  `_clean_column_name` 把表头转 snake_case，现有列名（`change_request_id`、
  `request_registration_time`、`ne_node_name`…）都是这条规则产出的。已核对：
  39 个清洗后列名 **全部命中现有列，零新增列**。
- **时间显式按 UTC 转换**，不用 `datetime.fromtimestamp(ts)`（跟随进程时区）。
  旧数据口径已核对：`CR2026080500003` 库内 `2026-08-05 17:23:45` 与上游
  `createTime=1785950625715` 的 UTC 值逐字相同。
- 旧导出管道保留：`EFLOW_CR_SOURCE=export` 可切回（上游修好后用）。

### 3.2 两处静默失败守卫（`sync_from_eflow_api`）

- **`REQUIRED_API_KEYS` 补入 `eFlow CR`** —— CR 是门户 QC 面板的唯一数据源，
  再缺失就是故障，不能只打 INFO。
- **新增停更守卫 `_check_table_freshness`** —— 同步结束后逐表看
  `max(_sync_time)` 距今多久，`eflow_tt/wo/cr/pm` 任一超过
  `EFLOW_STALE_GUARD_HOURS`（默认 6h，设 0 关闭）即记入 `result["errors"]`。
  这一层不依赖任何管道实现细节，专挡"任务成功但数据没动"。

---

## 四、验证

| 验证项 | 结果 |
| --- | --- |
| CR 直查抓取 | 323 条（上游 total=323），状态全部翻成显示名 |
| 列名对齐 | 39 列全部命中现有列，**零新增列** |
| 落库 | 写入 323 行，表内 324 行（含 1 条上游已消失的历史单，按 delta 表设计不删） |
| 面板接口 `/api/portal-qc/summary` | `cr` 由 **86 → 80** |
| 停更守卫 | 用阈值 0.001h 试跑，四张表全部被正确判陈旧 |
| 工作流分析 `cr_workflow_service.build_workflow` | 正常出里程碑，无异常 |

面板 80 而真实 79，差的 1 条是 `CR202609020001`（上游已查不到、本地停在
`BO/FO Head Approval`）—— delta 表"只增不删"的必然结果，保留证据不做篡改。

---

## 五、遗留与注意

1. **`*Detail` 明细列缺失**：列表接口一请求这 20 个 `CreateDetail`/`ClosedDetail` 等
   长文本字段就返回 **400**（实测 57 字段全量 → 400，去掉 Detail → 200）。
   因此 9/14 之后新写入的 CR 这些列为空，`cr_workflow_service` 的**逐单工作流历史**
   对它们无节点（页面不报错，降级为默认步骤）；存量 CR 的历史明细不受影响。
   若之后需要逐单流程历史，得另找单据详情接口补，或等上游修好导出切回。
2. **上游导出仍是坏的**：本次是绕过，不是修好。`export/list` 里 CR 任务依旧
   `failed / 20%`，值得同步反馈给 eFlow 侧。
3. **诊断脚本**：`TMP/cr_fix_20261103/`（导出状态、真实分布、86 差异、状态映射反推、落库验证）。
