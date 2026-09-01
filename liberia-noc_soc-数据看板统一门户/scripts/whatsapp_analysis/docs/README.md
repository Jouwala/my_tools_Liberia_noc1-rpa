# WhatsApp @我 消息智能助手

在多个 WhatsApp 群里自动找出 **@我** 的消息，结合上下文提取"谁让我做什么、哪个站点、什么问题、截止时间"，分类为 🔴紧急 / 🟡待跟进 / 🟢FYI，同站点消息自动合并，并每天定时生成 Daily Action Report。

> **合规边界**：只读取你已登录的 WhatsApp Web 会话，**不自动发送任何消息**；所有数据只保存在本机
> （`data/assistant.db` 与 `reports/`），唯一对外发送的数据是你在 `.env` 中自行配置的 AI API。
> 使用前请确认公司信息安全政策允许将群聊内容发送到该 AI 服务。

## 组成

| 组件 | 位置 | 说明 |
|------|------|------|
| Chrome 扩展 | `extension/` | MV3，无构建步骤；扫描 WhatsApp Web 页面，侧边栏展示待办 |
| 本地分析服务 | `server/` | Express + SQLite + node-cron，端口 9268 |
| 门户视图 | 项目根 `src/components/WhatsAppTasksView.tsx` | 数据看板门户中的「WhatsApp @我 待办」视图 |

## 快速开始

### 1. 启动本地服务（需要 Node ≥ 23.4，使用内置 SQLite）

```bash
cd scripts/whatsapp_analysis
npm install
cp .env.example .env     # Windows: copy .env.example .env
npm run dev              # 监听 http://localhost:9268
```

未配置 AI 时，服务以**规则模式**运行（正则提取站点/关键词），不会报错。

### 2. 配置 AI（可选，二选一）

编辑 `.env`：

```ini
# 方式 A：任意 OpenAI 兼容接口（含公司内网网关）
AI_API_TYPE=openai
AI_BASE_URL=https://your-gateway/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini

# 方式 B：Google Gemini
AI_API_TYPE=gemini
AI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash
```

改完重启服务。`GET http://localhost:9268/api/health` 可查看 `aiConfigured` 是否生效。

### 3. 安装 Chrome 扩展

1. 打开 `chrome://extensions`，开启右上角「开发者模式」
2. 点击「加载已解压的扩展程序」，选择 `scripts/whatsapp_analysis/extension` 目录
3. 打开 [web.whatsapp.com](https://web.whatsapp.com) 并登录
4. 点击浏览器工具栏的扩展图标打开侧边栏

### 4. 使用

- 打开某个群聊 → 侧边栏点「分析当前会话」
- 或点「分析所有提及会话」：自动逐个打开左侧带 @提及 徽章的会话并扫描
- 结果按 🔴/🟡/🟢 分组，可「标记完成」或「忽略」
- 「我」的名字：扩展首次运行自动从页面读取并缓存；如识别不准，可在
  `.env` 设置 `SELF_NAME=你的名字`

### 5. 每日报告

- 服务启动后按 `REPORT_CRON`（默认每天 08:00）自动生成，落盘 `reports/日期.md`
- 手动触发：`npm run report` 或 `POST /api/report/generate`
- 门户中：筛选栏「WhatsApp @我 待办」按钮（带文字标签）进入待办视图，
  可生成并查看当日报告（门户页面需能访问到本机 9268 端口）

### 固定输出格式

任务在所有出口（扩展侧边栏卡片、门户待办视图、每日报告）都按**固定 9 字段**输出，
顺序不变，没找到的字段照常显示标签、值留空：

```text
Requester:    提出 @我 请求的人
MessageTime:  @我 那条消息的时间戳（服务器端从片段原文回填，不依赖 AI 抄写）
SiteID:       站点数字编号（如果找到）
SiteName:     站点名称（如果找到）
TT_ID:        TT 工单号（如果找到）
Alarm_Name:   告警名称，如 Site Down / Power OFF（如果找到）
Group:        来源群名（服务器端回填）
Issue:        问题描述
Deadline:     截止时间 YYYY-MM-DD（如果找到）
```

其中 `MessageTime` / `Group` 由服务器直接回填（取 @我 消息的时间戳与所在群名），
`SiteID / SiteName / TT_ID / Alarm_Name / Deadline` 由 AI 提取、规则模式兜底正则提取，
保证任何一条任务都输出完整字段骨架。

### 从聊天截图提取 TT 单号与告警

扫描时扩展会自动把 **@我 消息上下文里出现的聊天截图**（告警面板截图、TT 工单截图等）
一并带回，与文字一起发给 AI（多模态识别）：

- 每个上下文最多 2 张、单次扫描最多 8 张；图片降采样到长边 ≤1280px 后以 JPEG 发送，
  保证 TT 号等文字仍可辨认；头像/表情等小图（<200×120）自动过滤
- AI 提示词要求：截图里出现 TT 单号或告警名称时**优先以截图为准**填入 `TT_ID / Alarm_Name`
- 任务正文里以 `【截图 N】` 标记截图归属，AI 按 `block` 字段把任务挂回对应片段/群
- 你配置的模型不支持看图（或拒绝图片）时，自动去掉图片用纯文本重试，分析不中断
- 注意：截图会随文字一起发送到你 `.env` 里配置的 AI API，请确认公司信息安全政策允许

### 6. 我的排查结果（笔记 + 附件）

- 门户待办视图的每张任务卡片下方有「我的排查结果」文本框，填写后点「保存」
- 点「添加图片/文件」可上传截图、日志等附件（单个 ≤16MB，可多选）；
  图片显示缩略图，点击新窗口查看；悬停附件右上角 ✕ 可删除
- 附件仅保存在本机 `data/attachments/` 目录，不随聊天内容外发

## API 一览（本地服务）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 服务状态与 AI 配置情况 |
| POST | `/api/analyze` | 接收扩展抓取的消息块，返回结构化任务 |
| GET | `/api/tasks` | 任务列表（含 `my_result` 与 `attachments`，可按 `status` / `since` 过滤） |
| PATCH | `/api/tasks/:id` | 更新任务状态（pending/done/dismissed）和/或 `my_result` |
| POST | `/api/tasks/:id/attachments` | 上传附件（JSON：filename/mime/dataBase64，≤16MB） |
| GET | `/api/attachments/:id` | 下载/预览附件 |
| DELETE | `/api/attachments/:id` | 删除附件（含磁盘文件） |
| POST | `/api/report/generate` | 立即生成日报 |
| GET | `/api/reports/latest` | 最近一次日报 |

## 已知限制

- WhatsApp Web 的 DOM 结构是混淆的且会不定期变更；若抓取失败，侧边栏会提示诊断信息，
  选择器集中在 `extension/content.js` 顶部的 `SELECTORS` 对象，便于维护
- 消息列表是虚拟滚动的，扩展会自动向上滚动加载历史（最多 10 屏），超长会话可能不完整
- 规则模式（无 AI）的提取精度有限，建议配置 AI 后使用

## 常见问题排查

- **出现重复任务卡片**：多为历史残留数据。服务端已做「归一化合并键 + 响应去重」，
  新扫描不会再产生；存量脏数据可清掉未完成任务：
  `node -e "const {DatabaseSync}=require('node:sqlite');const db=new DatabaseSync('data/assistant.db');db.prepare(\"DELETE FROM tasks WHERE status='pending'\").run();"`
  （在 `scripts/whatsapp_analysis` 目录下执行，只删待办不影响已完成记录）
- **侧边栏显示「未捕获截图」但群里确有截图**：WhatsApp Web 是虚拟列表，已改为
  「滚动采集时同步快照可见截图」（此前滚完后 DOM 已卸载导致几乎抓不到图）。
  若仍提示未捕获，说明截图在更早的历史里（超过向上 10 屏）：先在 WhatsApp Web 里
  手动滚到该截图让其渲染，再点「分析当前会话」
- **截图已捕获但 TT_ID 仍为空**：确认截图里确实印有 TT 号（形如 TT1234567）；
  服务端日志会打印随附截图数量。网关视觉能力可用本仓库 AI 实测（已验证
  agnes-2.5-flash 能从图片读出 TT 号）
- **Requester / MessageTime 为空**：频道/公告类会话没有发送人和时间戳，属于正常；
  个人群消息应有值。服务端会自动用上下文最近的时间戳近似回填 MessageTime
