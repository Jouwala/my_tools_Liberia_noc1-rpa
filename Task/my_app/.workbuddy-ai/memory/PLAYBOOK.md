# 验证约定与排障套路（从 MEMORY.md 拆出，主文件已超注入上限）

> 用法：写/改代码要验证时、以及排查线上异常时先读本文件。

## 5. 验证约定
- 后端纯逻辑：系统 Python312 做 FastAPI TestClient（**只挂目标 router，不加载 main**——`main.app` 带鉴权中间件，TestClient 的 `testserver` 不被视为回环会 401）；新端点查 `/openapi.json`。
- 前端真实交互：Playwright（工作区 venv `./Scripts/python.exe`，`--no-proxy-server` + `locale="zh-CN"`）。坑：无头 `--dump-dom` 默认 en，grep 中文全落空；antd 空表格空态也是 1 个 `tbody tr`，统计要排除 `.ant-table-placeholder`。
- 同一消息对同一文件的多个 Edit 必须串行。判「成功」别 grep 中文小标题，用稳定元素 + 关键结论串。
- `/api/eflow-qa/inspect-tt` 真实耗时 ≈85s，curl `--max-time` 给 ≥150s。判链路通不通先用 `/api/health`。
- **确认前端改动真上线**：`_fe_dist/assets` 堆很多历史 chunk，要顺 `index.html → index-*.js → 目标 chunk` 找**当前被 import 的那个**；压缩后数字字面量会变（`2000→2e3`），grep 源码写法会落空。
- 帮助文档链路：`frontend/src/pages/helpContent.ts`（页面）/`helpTaskDocs.ts`（定时任务，按 `id:'<task_id>'` 定位，zh+en 都改）→ `node scripts/generate-help-doc.mjs` → `node scripts/generate-manual-html.mjs` → **必须 vite build** 才进 `_fe_dist`。
- Excel 导出统一用 `frontend/src/utils/excelReport.ts` 的 `exportReport(specs, filename)` / `exportAoaReport(...)`，别裸用 `XLSX.utils.aoa_to_sheet`。**导出按钮挂在结果表格自己的工具条上**，内容必须与表格当前所见一致（有筛选就只导筛后）。**模板说明文字里绝不能出现真实样式的单号**（解析器扫全单元格）。
- **改 `sp_report_gen/gernarate_sp_report.py` 后要本地验证又不碰生产明细**：临时脚本 `import` 该模块，打桩 `sftp_download`（跳过下载）、`_save_detail_xlsx`（过滤只在内存生效、**不写回** `data/sp_email/data`）、`_cleanup_old_reports`，再把 `OUT_DIR` 指到临时目录跑 `main()`——参考 `TMP/t_sp_replenish_verify.py`，全量约 33s。校验方式：读产出 xlsx 按同口径**独立复算 + 逐行 merge 比对**，再裁 PNG 看渲染（PNG 很高，裁头部/底部即可）。
- **改 xlsx 模板又要保住图表/条件格式**：别用 openpyxl 保存（会丢 CF 扩展）；复制后直接改内部 sheet XML 数值单元格。校验三步：① `zipfile` 逐部件 md5 对比（只应有目标 sheet + workbook.xml 变化，charts/drawings/styles 全等）② `ET.fromstring` 解析每份改过的 XML ③ **win32com 只读真机打开**读回公式计算值（`Workbooks.Open(p, ReadOnly=True, UpdateLinks=0)` → `Close(SaveChanges=False)`；用户已开 Excel 时别 `Quit`）。

## 6. 排障套路
- **「前端报错但后端零日志」**：先按状态码统计 `grep -oE '" [0-9]{3} ' log/backend_runtime_*.log | sort | uniq -c`；**若该端点全 200 且无 500/Traceback → 请求没到 uvicorn → 查 nginx/传输层**。日志里 `client port = 0`（`127.0.0.1:0`）= 经 nginx 反代。这类「首次失败、重试就好」基本是 nginx→7038 瞬时 502，修法是前端对无响应与 5xx 做有限次自动重试（延迟 800/2000/4000ms，4xx 不重试）+ 失败态给「重试」按钮。
- **区分「网络不通」与「代理污染」**：`os.environ.pop` 掉全部 proxy 变量后再探一次；两次都失败 = 真网络问题。走代理时错误里会出现**代理主机**或 `ProxyError`，直连超时只出现目标主机。参考 `TMP/t_ews_proxy_ab.py`。
- **`/api/tasks/history` 的时间参数必须带 `.000Z`**（`start=2026-09-15T00%3A00%3A00.000Z`），写 `T00:00:00` 会返回空而不报错。字段是 `success`(bool) + `error`/`error_trace`，不是 `status`。
- **任务被禁用会静默跳过**：开关在 PG 表 `task_schedule_config.enabled`；日志形如 `跳过执行：任务 xxx 已禁用（trigger=auto_retry）`，手动执行会 0.04s 空失败。查任务是否真跑过用 `task_execution_log`（有 `success`/`error`，**没有 `message` 字段**）。
- **Orange 邮件网关 `exchmail.orange-cit.ci` 不可达**（09-15 起，**外部故障**）：判断邮件是否漏发先跑 `probe_ews_reachable()`，别急着重跑任务（**已证伪**：不是代理污染）。补发机制可靠（`services/email_recovery.py`）：EWS 不可用期间**只探测、绝不消耗重试次数**；恢复后立即补发（每次最多 3 条）；窗口 24h 按每条失败各自计时。当前状态看 `TMP/email_recovery_state.json` 的 `__ews_probe__`。已知间歇性自愈、无需处理的失败：`site_outage_screenshot` 偶发 iframe 定位失败；`whatsapp_send` 约 13% 页面未就绪抖动。
