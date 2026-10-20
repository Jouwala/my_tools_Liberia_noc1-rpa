"""HTTP 边界的英文文案翻译层（只管 HTTPException 的 detail）。

后端内部一律以中文为准：日志、错误上下文、上游数据都保持原样，
只在响应离开进程之前，把**已登记的纯展示句子**换成英文。

为什么不走「每个 raise 点建 i18n 键」：实测 detail 有 122 种说法 / 168 处 /
分布在 26 个路由文件，逐点改造要给 168 个 handler 注入 request 并改签名，
回归面远超收益；而 detail 全部落在 main.py 的 StarletteHTTPException
处理器这一个咽喉点上，在此翻译一处即可覆盖全部。

【边界，务必遵守】这里登记的必须是**只给人看的句子**。凡是前端拿来做的士
值匹配（如复盘的 creator_kind「系统自动」、owner「系统/流程」、状态「已过时」）
一律不得进本表 —— 那些值被改写后，前端的精确匹配会静默失效（表现为「界面
不报错但数据不对」）。那类字段要走后端码 + 前端映射，不在本模块范围内。

未登记的串原样返回，因此新增中文 detail 的最坏后果是「英文界面看到中文」，
不会造成故障。移除条件：若将来 detail 全面改为发码，本表可整体删除。
"""

import re

from fastapi import Request

# ---------------- 精确匹配：不含变量 ----------------
_EXACT = {
    "站点表不存在": "Site table does not exist",
    "eflow_wo 表不存在": "The eflow_wo table does not exist",
    "person 表不存在": "The person table does not exist",
    "master_site_db 表不存在": "The master_site_db table does not exist",
    "单号格式非法": "Invalid ticket number format",
    "非法文件名": "Invalid file name",
    "非法路径": "Invalid path",
    "路径越界": "Path outside the allowed directory",
    "人员标识为空": "Person identifier is empty",
    "仅支持 .xlsx, .xls, .csv 文件": "Only .xlsx, .xls and .csv files are supported",
    "仅支持 .kml 文件": "Only .kml files are supported",
    "仅允许下载 Excel 文件": "Only Excel files may be downloaded",
    "分析记录不存在": "Analysis record not found",
    "文件不存在": "File not found",
    "图片不存在": "Image not found",
    "文件为空": "The file is empty",
    "未提供文件": "No file provided",
    "列清单不能为空": "The column list must not be empty",
    "所选列在表中均不存在": "None of the selected columns exist in the table",
    "表为空，无数据可导出": "The table is empty; nothing to export",
    "表为空，无法分析": "The table is empty; cannot analyse",
    "表名不能为空": "Table name must not be empty",
    "表名不能以 _ 开头（_ 为内部表保留命名空间）":
        "Table name must not start with _ (reserved for internal tables)",
    "模板名称不能为空": "Template name must not be empty",
    "format 必须为 xlsx 或 csv": "format must be xlsx or csv",
    "CSV 文件没有工作表，无需指定 sheet": "A CSV has no worksheets; do not specify sheet",
    "文件内容为空，无可导入数据": "The file content is empty; no data to import",
    "没有解析到有效的 WO 单号（格式：WO+12位数字）":
        "No valid WO number parsed (expected WO followed by 12 digits)",
    "job_id 不匹配或已被新作业取代": "job_id does not match or has been superseded by a newer job",
    "未登录：请通过统一门户登录": "Not signed in: please sign in through the unified portal",
    "缺少门户 token": "Missing portal token",
    "未启用常驻会话（未设置 MYAPP_KIOSK_KEY）":
        "Kiosk session not enabled (MYAPP_KIOSK_KEY is not set)",
    "常驻会话密钥不正确": "Kiosk session key is incorrect",
    "Forbidden: 需从本机访问或携带正确的 X-API-Token 头":
        "Forbidden: access must come from this host or carry a valid X-API-Token header",
    "该门户不支持客户端会话登录": "This portal does not support client-side session sign-in",
    "登录票据无效或已过期": "Sign-in ticket is invalid or expired",
    "门户会话获取失败，请稍后重试": "Failed to obtain the portal session, please retry later",
    "门户登录验证失败：请先在门户登录后重试": "Portal sign-in check failed: sign in on the portal first, then retry",
    "请填写用户名和密码": "Please enter both username and password",
    "用户名或密码错误": "Incorrect username or password",
    "服务器内部错误，请稍后重试": "Internal server error, please retry later",
    # ---- 门户登录任务进度（routers/portals.py 的 login/status；前端只展示，
    #      匹配用的是 state 字段，因此翻译 message 安全）----
    "正在启动浏览器...": "Launching the browser...",
    "正在直接鉴权...": "Authenticating directly...",
    "未找到该任务（可能已过期）": "Job not found (it may have expired)",
    # ---- TT 复盘面板：只登记「纯展示字段」的句子 ----
    # wo_people[].step（表格直接 dataIndex 显示，前端不匹配它）
    "WO 接单": "WO accepted",
    "出发": "Departure",
    "到场": "Arrival on site",
    "现场处理": "On-site work",
    "离场": "Leave site",
    "WO 确认": "WO confirmed",
    # suggested_actions 里嵌入的阶段名，措辞与前端字典 ttPm.node.* 保持一致，
    # 避免同一个节点在页面两处出现两种译法。
    "告警发生": "Alarm raised",
    "TT 自动建单": "TT auto-created",
    "派单路由决定": "Dispatch route decided",
    "FO Accept 接单": "FO Accept",
    "WO 派单": "WO dispatched",
    "现场处置": "On-site action",
    "告警清除/自愈": "Alarm cleared / self-healed",
    "FO Process 填报": "FO Process report",
    "Confirm 关单": "Confirm close",
    # 「时间瓶颈」建议里嵌入的阶段名，取自 services/tt_postmortem 的 _PHASE_LABEL
    "建单时延": "ticket creation delay",
    "接单等待": "acceptance wait",
    "派单": "dispatch",
    "现场响应等待": "on-site response wait",
    "现场作业": "on-site work",
    "告警清除": "alarm clearing",
    "提交关单": "close report submission",
    "关单确认": "close confirmation",
    "其他": "other",
    # suggested_actions 的整句（无变量部分）
    "建议追溯该站上联传输链路（MW 微波 / PTN / 光纤），核查是否为链路反复中断":
        "Trace this site's uplink transmission path (MW / PTN / fibre) and check whether the link keeps flapping",
    "该单告警码不在任何 ACTIVE 推单规则命中范围，需新增兜底或人工甄别":
        "This ticket's alarm codes are not covered by any ACTIVE dispatch rule; add a fallback rule or triage manually",
    "建议针对该阶段做专项分析": "Recommend a dedicated analysis of this stage",
    "当前处理人也为空": "The current handler is also empty",
    "提交关单耗时过长：建议核查 FO 填报环节的作业与审批阻塞点":
        "Submitting the close report took too long: check the work and approval blockers in the FO reporting step",
    "关单确认耗时过长：建议核查确认/自动关闭规则（ttAutoCloseRule）是否生效":
        "Closing confirmation took too long: check whether the confirm / auto-close rule (ttAutoCloseRule) is in effect",
    "告警清除耗时过长：告警长时间未恢复，建议核查现场处置质量与恢复确认流程":
        "The alarm took too long to clear: check the quality of on-site work and the restoration confirmation process",
    "现场作业耗时过长：建议核查备件、上站条件与作业工时":
        "On-site work took too long: check spare parts, site access conditions and labour hours",
    "现场响应等待过长：WO 派出后长时间无人到场，且**未见指派到个人**。建议先解决派单到人，再建立「到场时限 + 超时自动升级/改派」机制":
        "On-site response waited too long: a WO was dispatched but nobody arrived and **no individual was assigned**. "
        "Fix dispatch-to-a-person first, then set an arrival deadline with automatic escalation/reassignment on timeout",
    # 时间瓶颈句里按阶段给出的建议
    "建单时延过长：告警发生到建单耗时显著，建议核查告警采集/建单规则（ttLevelRule）的触发时延与积压":
        "Ticket creation is slow: the gap from alarm raised to ticket creation is significant, "
        "check the trigger delay and backlog of the alarm collection / creation rule (ttLevelRule)",
    "接单等待过长：TT 建好后长时间无人接单，建议对 FO 通道设置接单超时提醒与值班兜底":
        "Acceptance waited too long: nobody accepted the TT for a long time after creation; "
        "set an acceptance timeout alert and a duty fallback for the FO channel",
    # ---- TT&WO 看板的故障域建议与口径说明（routers/tt_wo_dashboard.py）----
    "未找到该工单": "Ticket not found",
    "无建议": "No suggestion",
    "建议核查站点供电（市电 / 油机 / 电池），确认是否为真实断电":
        "Check the site power supply (mains / genset / battery) and confirm whether the outage is real",
    "建议结合告警明细进一步定位（小区级 / 板件级）":
        "Use the alarm detail to narrow it down further (cell level / board level)",
    "eflow_tt.alarm_reason_type（系统字段，无告警链路佐证）":
        "eflow_tt.alarm_reason_type (system field, no alarm-chain evidence)",
    # ---- 事件总览的电话/短信/AI 回执（services/incident_overview_service.py）----
    "电话通知已发送": "Voice notification sent",
    "短信已发送": "SMS sent",
    "电话通知已发送（模拟模式）": "Voice notification sent (dry-run mode)",
    "短信已发送（模拟模式）": "SMS sent (dry-run mode)",
    "当前为模拟模式，未实际拨打电话。配置 PHONE_SERVICE_PROVIDER 选择服务商。":
        "This is a dry run - no call was placed. Set PHONE_SERVICE_PROVIDER to choose a provider.",
    "当前为模拟模式，未实际发送。配置 SMS_SERVICE_PROVIDER 选择服务商。":
        "This is a dry run - nothing was sent. Set SMS_SERVICE_PROVIDER to choose a provider.",
    "Twilio 配置不完整": "Twilio is not configured completely",
    "Twilio 库未安装，请运行: pip install twilio": "The Twilio SDK is missing, run: pip install twilio",
    "阿里云语音服务未启用（需 aliyun-python-sdk-core）":
        "Aliyun voice service is not enabled (requires aliyun-python-sdk-core)",
    "腾讯云语音服务未启用（需 tencentcloud-sdk-python）":
        "Tencent Cloud voice service is not enabled (requires tencentcloud-sdk-python)",
    "未配置 Gemini API key，已回退本地规则":
        "No Gemini API key configured, fell back to local rules",
    # ---- 任务执行器（services/task_runner.py，经 /api/tasks/* 上到任务管理页）----
    # STOPPED_BY_USER 前缀是判定标记，必须原样留在英文里。
    "STOPPED_BY_USER: 用户手动停止执行": "STOPPED_BY_USER: execution stopped manually",
    "任务未注册": "The task is not registered",
    "任务未处于运行/排队状态，无需停止": "The task is neither running nor queued; nothing to stop",
    "任务已在队列中等待或执行": "The task is already queued or running",
    "任务正在运行中": "The task is currently running",
    "已取消排队中的任务": "The queued task was cancelled",
    "非队列模式不支持停止运行中的任务（请启用 MY_APP_TASK_QUEUE=1）":
        "Stopping a running task is not supported outside queue mode (set MY_APP_TASK_QUEUE=1)",
    "configs 必须是数组": "configs must be an array",
    "配置项必须是对象": "Each configuration entry must be an object",
    "缺少 task_id": "Missing task_id",
    "cron 必须是字符串": "cron must be a string",
    "enabled 必须是布尔值": "enabled must be a boolean",
    # ---- BP 报表口径说明（services/bp_report_service.py 的 caliber.notes）----
    # 这几条是给值班解释统计口径的，数字必须逐字保留，不得改写事实。
    "行数等于该期 trend[].detail_cells；与 BP Cells List 同源":
        "The row count equals trend[].detail_cells for that period; same source as the BP Cells List",
    "流量按明细行求和，与 Excel 的 Total Traffic 口径不同":
        "Traffic is summed over the detail rows, which is a different basis from Excel's Total Traffic",
    "BP Cells List 只导出 2024~2026：2023 无明细，2024 缺 13,553 行（整天缺失）。"
    "这些期只能看汇总，下钻入口应置灰。":
        "The BP Cells List was only exported for 2024-2026: 2023 has no detail and 2024 is missing "
        "13,553 rows (whole days absent). For those periods only the summary is meaningful; "
        "the drill-down entry should be greyed out.",
    "Excel 各 sheet 本身不一致：2025/2026 的 Overall 恒低于 Regional（分别差 2,263 / 2,115 行）；"
    "2024 的 BP Cells List 少于 Regional。展示值统一取 Overall - Daily（连续且权威），明细仅供下钻。":
        "The Excel sheets are inconsistent with each other: Overall is always below Regional for "
        "2025/2026 (short by 2,263 / 2,115 rows respectively); the 2024 BP Cells List is smaller "
        "than Regional. Displayed values always come from Overall - Daily (continuous and "
        "authoritative); the detail is for drill-down only.",
    "周判定需 7 天全有数据；月判定需 ≥4 个完整周。因此「本周未过完」与「本月只有 3 个完整周」"
    "都会得到「不可判定」，但两者性质不同：前者等时间走完即可判定，后者是这个月**永远**判不出来"
    "（口径与日历错配）。逐期成因见 trend[].verdict_reason。":
        "A weekly verdict needs data for all 7 days; a monthly verdict needs at least 4 complete "
        "weeks. So both \"this week is not over yet\" and \"this month has only 3 complete weeks\" "
        "come back as undecidable, for different reasons: the first resolves once the period "
        "completes, the latter can **never** be decided (the caliber does not line up with the "
        "calendar). Per-period reasons are in trend[].verdict_reason.",
    "登录尝试过于频繁，请稍后再试": "Too many sign-in attempts, please retry later",
    "加载 inspect_tt.py 失败": "Failed to load inspect_tt.py",
    "文件名不在报告白名单内": "The file name is not in the report allow-list",
    "kml_mw_links 暂无数据，请先导入 KML": "kml_mw_links has no data yet, please import a KML first",
    "kml_mw_links 暂无数据": "kml_mw_links has no data yet",
    "GeoJSON 生成失败": "Failed to generate GeoJSON",
    "未找到本地 echarts.min.js": "Local echarts.min.js not found",
    "缺少 cron 表达式": "Missing cron expression",
    "至少提供 cron 或 enabled 之一": "Provide at least one of cron or enabled",
    "catalog 必须是对象": "catalog must be an object",
    "catalog.items 必须是数组": "catalog.items must be an array",
    "catalog.groups 必须是数组": "catalog.groups must be an array",
    "catalog.order 必须是对象": "catalog.order must be an object",
    "catalog.subGroups 必须是对象": "catalog.subGroups must be an object",
    "catalog.tabLabels 必须是对象": "catalog.tabLabels must be an object",
    "catalog.groups 的条目必须是对象": "Each entry of catalog.groups must be an object",
    "看板目录不能为空（如需清空请用 DELETE 接口）":
        "The board catalog must not be empty (use the DELETE endpoint to clear it)",
    "layout 必须是对象": "layout must be an object",
    "layout.groups 必须是非空数组": "layout.groups must be a non-empty array",
    "目录必须是对象": "The directory must be an object",
    "目录缺少 key": "The directory is missing its key",
    "keys 必须是数组": "keys must be an array",
    "keys 含非法项": "keys contains an invalid entry",
    "myapp 无法连接统一门户校验登录态（门户回调地址不可达）。这是服务端配置问题，"
    "请联系管理员检查 UNIPLAM_ME_URL 是否指向门户所在机器。":
        "myapp cannot reach the unified portal to verify the sign-in state (the portal callback "
        "URL is unreachable). This is a server-side configuration issue - ask the administrator "
        "to check that UNIPLAM_ME_URL points at the machine hosting the portal.",
    "myapp 无法连接统一门户校验登录（门户登录接口不可达）。这是服务端配置问题，"
    "请联系管理员检查 UNIPLAM_LOGIN_URL / UNIPLAM_ME_URL 是否指向门户所在机器。":
        "myapp cannot reach the unified portal to sign in (the portal sign-in endpoint is "
        "unreachable). This is a server-side configuration issue - ask the administrator to "
        "check that UNIPLAM_LOGIN_URL / UNIPLAM_ME_URL point at the machine hosting the portal.",
}

# ---------------- 模板匹配：含变量，按顺序出现 ----------------
# 中文与英文里的 {} 数量与顺序必须一致，导入时校验。
_TEMPLATES = [
    ("表 {} 不存在", "The table {} does not exist"),
    ("表不存在: {}", "Table does not exist: {}"),
    ("未知表: {}", "Unknown table: {}"),
    ("未知明细类型: {}", "Unknown detail type: {}"),
    ("未知门户: {}", "Unknown portal: {}"),
    ("未知报告源: {}", "Unknown report source: {}"),
    ("未知 metric: {}", "Unknown metric: {}"),
    ("未知工具块 key: {}", "Unknown widget block key: {}"),
    ("工具块 key 重复: {}", "Duplicate widget block key: {}"),
    ("非法列名: {}", "Invalid column name: {}"),
    ("非法排序列名: {}", "Invalid sort column name: {}"),
    ("站点 {} 不存在", "Site {} does not exist"),
    ("任务 {} 未找到", "Task {} not found"),
    ("任务 {} 无配置文件管理", "Task {} has no managed configuration file"),
    ("删除失败: {}", "Delete failed: {}"),
    ("导入失败: {}", "Import failed: {}"),
    ("文件解析失败: {}", "Failed to parse the file: {}"),
    ("导出失败: {}", "Export failed: {}"),
    ("读取凭据失败: {}", "Failed to read credentials: {}"),
    ("获取流程配置失败: {}", "Failed to load flow configuration: {}"),
    ("流程模块不可用：{}", "Flow module unavailable: {}"),
    ("查询失败：{}", "Query failed: {}"),
    ("流程骨架构建失败：{}", "Failed to build the process skeleton: {}"),
    ("规则读取失败：{}", "Failed to read rules: {}"),
    ("文档不存在: {}", "Document not found: {}"),
    ("分析模块不存在: {}", "Analysis module not found: {}"),
    ("非法表名: {}（只能含字母、数字、下划线，且以字母或下划线开头）",
     "Invalid table name: {} (letters, digits and underscores only, starting with a letter or underscore)"),
    ("表已存在: {}（勾选「覆盖已存在表」可替换）",
     "The table already exists: {} (tick Overwrite existing table to replace it)"),
    ("工作表不存在: {}（可用: {}）", "Worksheet not found: {} (available: {})"),
    ("工作表名不唯一（仅首尾空格不同）: {}（可用: {}）",
     "Worksheet name is not unique (differs only in surrounding spaces): {} (available: {})"),
    ("{} 超出纬度范围 [-90,90]", "{} is outside the latitude range [-90,90]"),
    ("{} 超出经度范围 [-180,180]", "{} is outside the longitude range [-180,180]"),
    ("门户 {} 未配置 nginx 反代", "Portal {} has no nginx reverse proxy configured"),
    ("缺少 openpyxl，无法导出 Excel: {}", "openpyxl is missing, cannot export Excel: {}"),
    ("排序的父分组数超过上限 {}", "The number of parent groups to sort exceeds the limit {}"),
    ("子分组的父分组数超过上限 {}", "The number of parent groups for sub-groups exceeds the limit {}"),
    ("一级分组数超过上限 {}", "The number of top-level groups exceeds the limit {}"),
    ("看板数超过上限 {}", "The number of boards exceeds the limit {}"),
    ("catalog.order[{}] 必须是数组", "catalog.order[{}] must be an array"),
    ("catalog.order[{}] 条目数超过上限 {}", "catalog.order[{}] exceeds the entry limit {}"),
    ("catalog.subGroups[{}] 必须是数组", "catalog.subGroups[{}] must be an array"),
    ("catalog.subGroups[{}] 的子分组数超过上限 {}",
     "catalog.subGroups[{}] exceeds the sub-group limit {}"),
    ("catalog.subGroups[{}] 的条目必须是对象", "Each entry of catalog.subGroups[{}] must be an object"),
    ("catalog.tabLabels[{}] 必须是对象", "catalog.tabLabels[{}] must be an object"),
    ("第 {} 条看板缺少标题或合法链接", "Board #{} is missing a title or a valid link"),
    ("看板编号重复: {}", "Duplicate board id: {}"),
    ("目录数超过上限 {}", "The number of directories exceeds the limit {}"),
    ("目录 key 重复: {}", "Duplicate directory key: {}"),
    ("目录 {} 的 items 必须是数组", "The items of directory {} must be an array"),
    ("目录 {} 页面数超过上限", "Directory {} exceeds the page limit"),
    ("目录 {} 含非法页面项", "Directory {} contains an invalid page entry"),
    ("页面 {} 在目录 {} 内重复", "Page {} is duplicated inside directory {}"),
    ("keys 必须恰好 {} 项", "keys must contain exactly {} entries"),
    ("取大屏布局失败: {}", "Failed to fetch the screen layout: {}"),
    ("取大屏数据失败: {}", "Failed to fetch the screen data: {}"),
    ("取子模板清单失败: {}", "Failed to fetch the sub-template list: {}"),
    ("取背景图失败: {}", "Failed to fetch the background image: {}"),
    ("异常: {}", "Error: {}"),
    # ---- TT 复盘的带变量句子 ----
    # 建单环节那条建议里，「群组池」与「后续指派」两段是紧挨着拼在一起的（中间没有
    # 分隔符），单靠 {}{} 无法切分；因此按「带后续指派」在前、「无后续指派」在后登记
    # 两条，用字面量 ；后续已由 WO 作为切分锚点。顺序颠倒会让第一条永远匹配不上。
    ("建单环节**未指派到任何个人**（`Assign To` / `Assignee Group` 均为空），{}；"
     "后续已由 WO `{}` 指派到个人（{}）。建议为 FO 通道配置带时限的轮值/派单到人规则，"
     "缩短从建单到有人接手的时间",
     "The create stage **assigned no individual** (`Assign To` / `Assignee Group` both empty), {}; "
     "a later WO `{}` assigned it to a person ({}). Configure a time-boxed rotation / "
     "dispatch-to-a-person rule for the FO channel to shorten the create-to-accept wait"),
    ("建单环节**未指派到任何个人**（`Assign To` / `Assignee Group` 均为空），{}。"
     "建议为 FO 通道配置带时限的轮值/派单到人规则，缩短从建单到有人接手的时间",
     "The create stage **assigned no individual** (`Assign To` / `Assignee Group` both empty), {}. "
     "Configure a time-boxed rotation / dispatch-to-a-person rule for the FO channel "
     "to shorten the create-to-accept wait"),
    ("仅落入群组池 `{}`", "only landed in the group pool `{}`"),
    ("时间瓶颈：「{}」占 {}%（{}h），责任方 {}。{}",
     "Time bottleneck: {} accounts for {}% ({}h), owner {}. {}"),
    ("现场响应等待过长：WO 已指派到 {}，但从派单到出发耗时 {}h，"
     "属**已派单但未及时出发**。建议核查值班/派工通知是否送达、"
     "建立「到场时限 + 超时自动升级/改派」机制",
     "On-site response waited too long: the WO was assigned to {}, but dispatch-to-departure took {}h - "
     "**assigned but not departing in time**. Check that duty / dispatch notifications are delivered, "
     "and set an arrival deadline with automatic escalation/reassignment on timeout"),
    ("契约要求该动作必须出现，但库中 {} 为空/无法解析",
     "The contract requires this action, but {} is empty or unparsable in the database"),
    ("覆盖该单告警码的推单规则已停用（覆盖码：{}），需评估恢复或新增兜底规则",
     "The dispatch rule covering this ticket's alarm codes is disabled (covered codes: {}); "
     "assess restoring it or adding a fallback rule"),
    ("推单规则「{}」对本单本应命中但已停用（描述：{}，最后更新 {}）；"
     "若该组合确实需要自动派现场，需评估恢复此规则",
     "Dispatch rule \"{}\" should have matched this ticket but is disabled "
     "(description: {}, last updated {}); if this combination really needs automatic field "
     "dispatch, assess restoring this rule"),
    ("该组合（siteSubtype={} + 断站）按规则「{}」**设计即为人工处理**，不自动建 WO；"
     "若要改为自动派现场，需新增/修改推单规则",
     "This combination (siteSubtype={} + site down) is **manual by design** under rule \"{}\", "
     "so no WO is created; to automate field dispatch, add or change a dispatch rule"),
    ("FO Process 阶段耗时 {}h，建议加 'Night Accept → Day Handover' 硬约束",
     "The FO Process stage took {}h; consider adding a hard 'Night Accept -> Day Handover' constraint"),
    # ---- 事件总览带变量的回执 ----
    ("Twilio 调用失败: {}", "Twilio call failed: {}"),
    ("AI 调用失败: {}", "AI call failed: {}"),
    ("不支持的 AI 提供商: {}", "Unsupported AI provider: {}"),
    ("{} 短信服务未启用，请配置对应 SDK 与凭证",
     "The {} SMS service is not enabled; configure the matching SDK and credentials"),
    # ---- 任务执行器带变量回执 ----
    ("任务 {} 已禁用", "Task {} is disabled"),
    ("任务 {} 已启用", "Task {} is enabled"),
    ("任务 {} 调度已更新为: {}", "The schedule of task {} is updated to: {}"),
    ("任务队列暂不可用：{}", "The task queue is temporarily unavailable: {}"),
    ("投递队列失败: {}", "Failed to enqueue the task: {}"),
    ("停止任务失败: {}", "Failed to stop the task: {}"),
    # ---- BP 口径说明里带小区数的一条 ----
    ("Excel 口径的全网小区数，未提供名单；明细表只覆盖 {} 个曾在 BP Cells List 出现的小区。"
     "ume 来源的期可下钻（分母即明细行数），excel 来源的期不可下钻 —— 见 trend[].total_drillable",
     "Network-wide cell count on the Excel basis; no cell list was provided. The detail table "
     "covers only the {} cells that ever appeared in the BP Cells List. Periods sourced from ume "
     "can be drilled into (the denominator is the detail row count); periods sourced from excel "
     "cannot - see trend[].total_drillable"),
]

_ESC = re.escape


def _compile(pattern_text: str, english: str):
    parts = pattern_text.split("{}")
    if len(parts) - 1 != english.count("{}"):
        raise ValueError(f"占位符数量不一致：{pattern_text!r} / {english!r}")
    regex = "^" + "(.+?)".join(_ESC(p) for p in parts) + "$"
    return (re.compile(regex, re.DOTALL), english)


_PATTERNS = [_compile(zh, en) for zh, en in _TEMPLATES]


def _english_of(text: str):
    hit = _EXACT.get(text)
    if hit is not None:
        return hit
    for rx, en in _PATTERNS:
        m = rx.match(text)
        if m:
            # 捕获组里可能还嵌着一整句中文（复盘的「时间瓶颈」建议就是这样拼出来的），
            # 递归再翻一次；翻不动的原样保留 —— 那部分是人名、单号、规则描述等上游数据。
            groups = [(_english_of(g) or g) for g in m.groups()]
            out = en
            for g in groups:
                out = out.replace("{}", g, 1)
            return out
    return None


def lang_of(request: Request) -> str:
    """与各路由 _req_lang 保持同一规则：Accept-Language 以 en 开头才走英文。"""
    accept = (request.headers.get("Accept-Language") or "").lower()
    return "en" if accept.startswith("en") else "zh"


def translate_text(text, request: Request):
    """英文请求且该句已登记才翻译；非字符串（如 422 的 errors 列表）原样返回。"""
    if not isinstance(text, str) or lang_of(request) != "en":
        return text
    return _english_of(text) or text


UI_KEYS = ("error", "message", "note", "basis", "suggested_action")
# 值为「字符串数组」的展示键：口径说明、告警列表、建议列表
UI_LIST_KEYS = ("notes", "warnings", "suggested_actions")


def translate_ui_fields(payload, request: Request, _depth: int = 0):
    """递归翻译白名单键（UI_KEYS / UI_LIST_KEYS）下的中文句子，供 200 响应出口调用。

    刻意不含 label / status / owner / creator_kind / step：那些值前端要拿来做
    精确匹配或反查，改写不会报错但会让归类静默出错。step 只在复盘表格里纯展示，
    由 translate_postmortem 单独处理。
    """
    if lang_of(request) != "en" or _depth > 6:
        return payload
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if isinstance(v, str) and k in UI_KEYS:
                out[k] = translate_text(v, request)
            elif isinstance(v, list) and k in UI_LIST_KEYS:
                out[k] = [translate_text(x, request) if isinstance(x, str)
                          else translate_ui_fields(x, request, _depth + 1) for x in v]
            else:
                out[k] = translate_ui_fields(v, request, _depth + 1)
        return out
    if isinstance(payload, list):
        return [translate_ui_fields(x, request, _depth + 1) for x in payload]
    return payload


def translate_postmortem(report, request: Request):
    """翻译 TT 复盘报告里**只用于展示**的三个字段。

    刻意不做整棵树递归：timeline 的 label、people.creator_kind、owner、dev 的
    detail 都是前端做精确匹配 / 反查的依据（TtPostmortemPanel 比较
    creator_kind === '系统自动'，ttVocab 用 BY_ZH 反查 label、用
    startsWith('缺少「') 解析 dev 明细）。改写这些值不会报错，只会让匹配
    静默失效 —— 表现为「界面看着正常但归类全错」，所以按字段白名单逐个翻译。
    """
    if not isinstance(report, dict) or lang_of(request) != "en":
        return report
    actions = report.get("suggested_actions")
    if isinstance(actions, list):
        report["suggested_actions"] = [translate_text(s, request) for s in actions]
    for item in report.get("missing_actions") or []:
        if isinstance(item, dict):
            item["reason"] = translate_text(item.get("reason"), request)
    people = report.get("people")
    if isinstance(people, dict):
        for row in people.get("wo_people") or []:
            if isinstance(row, dict):
                row["step"] = translate_text(row.get("step"), request)
    return report
