# WhatsApp 出图接口（whatsapp_outbox）

为「WhatsApp 定时发图」Chrome 扩展（`Task/my_app/whatsapp_sender_extension/`）提供
图片拉取与「待发作业」的 HTTP 接口。它复用
`backend/services/whatsapp_service.py`（即 `/myapp/?page=sync` 的 **WhatsApp Message Send** 任务）
的图片目录与群组/备注配置，但**不走 Playwright**——发送由扩展在已登录的 WhatsApp Web 标签页里完成。
业务逻辑（扫描图片 / 备注规则 / 作业状态机）都在
`backend/services/whatsapp_ext_service.py`；本路由只做 HTTP 薄封装。

## 端点

所有端点都挂 `require_protected`（`backend/security.py`）。扩展与后端**同机**，
回环地址（127.0.0.1 / ::1 / localhost）自动放行，**无需 token**；远程访问才需 `X-API-Token`。

### GET `/api/whatsapp/outbox`
返回待发送清单：
```json
{
  "groups": ["test123", "Test234"],
  "items": [
    {
      "name": "ALL.png",
      "caption": "*ALL*",
      "mime": "image/png",
      "url": "/api/whatsapp/outbox/image?name=ALL.png"
    }
  ],
  "generated_at": "2026-08-31T17:05:00"
}
```
- `groups`：来自 `whatsapp_service.GROUPS`（环境变量 `WHATSAPP_GROUPS`，逗号分隔）。
- `items`：**每次请求重新扫描** `SITE_OUTAGE_DIR`，排除名字含 `debug` 的文件，按文件名排序。
- `caption`：有环境变量 `WHATSAPP_CAPTIONS` 时按序配对，否则取文件名 `*stem*`。

### GET `/api/whatsapp/outbox/image?name=<文件名>`
返回图片字节（`FileResponse`）。
- 只取 `name` 的 basename，且 `resolve()` 后必须仍在图片目录内，否则 404 —— **路径穿越防护**。
- 仅放行 `.png/.jpg/.jpeg`，其余 404。

### GET `/api/whatsapp/ext/job`
扩展轮询认领待发作业。有待发作业时返回（并把状态置为 `running`）：
```json
{ "pending": true, "job_id": "…", "groups": ["test123"], "items": [ /* 同 outbox.items */ ] }
```
无待发作业时返回 `{ "pending": false }`。

### POST `/api/whatsapp/ext/job/result`
扩展回报发送结果。请求体：
```json
{ "job_id": "…", "ok": true, "groups_sent": ["test123"], "errors": [], "elapsed_seconds": 42 }
```
- `job_id` 与当前作业不匹配时返回 `409`。
- 成功后把作业标记为 `completed`（`ok=false` 时为 `failed`）并落盘结果，
  供正在等待的任务 `whatsapp_send_ext` 读取。

## 与任务的关系
- 原任务 `whatsapp_send`（Playwright）**保持不变**。
- 新任务 `whatsapp_send_ext`（见 `task_registry.py`）通过
  `whatsapp_ext_service.run_whatsapp_send_ext()` 投递作业并等待扩展回报，
  在 sync 页面像普通任务一样显示成功 / 失败 / 耗时 / 历史。
- 本期只发**图片**。`items` 结构通用（带 `mime`），日后要附带最新 `site_outage` xlsx，
  只需在 `build_outbox_payload` 里加一个 item，扩展协议不变。

## 快速自测
```bash
curl http://localhost:8000/api/whatsapp/outbox
curl "http://localhost:8000/api/whatsapp/outbox/image?name=ALL.png" -o t.png
# 路径穿越应被拒绝（404）：
curl "http://localhost:8000/api/whatsapp/outbox/image?name=..%2F..%2Fmain.py"
# 无待发作业时返回 {"pending": false}：
curl http://localhost:8000/api/whatsapp/ext/job
```
