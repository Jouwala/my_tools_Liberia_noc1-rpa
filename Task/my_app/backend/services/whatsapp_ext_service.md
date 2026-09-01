# WhatsApp 扩展发送服务（whatsapp_ext_service）

与 `whatsapp_service.run_whatsapp_send`（Playwright 自启浏览器，即 `/myapp/?page=sync` 的
**WhatsApp Message Send** 任务）**并行**的第二种发送实现。两者共用同一份图片目录
（`SITE_OUTAGE_DIR`）与群组/备注配置（`GROUPS` / `WHATSAPP_CAPTIONS`）；**原任务保持不动**。

## 工作模型（拉取 / 工人）
1. 任务 `whatsapp_send_ext` 运行（手动或定时）→ `run_whatsapp_send_ext()` 投递一个
   「待发作业」并阻塞等待。
2. Chrome 扩展（`Task/my_app/whatsapp_sender_extension`，运行在已登录的 WhatsApp Web 标签页）
   定期轮询 `GET /api/whatsapp/ext/job` 认领作业、在浏览器里逐群逐图发送。
3. 扩展完成后 `POST /api/whatsapp/ext/job/result` 回报；任务收到回报（或超时）后返回结果，
   在 sync 页面像普通任务一样显示成功 / 失败 / 耗时 / 历史。

## 作业状态如何跨进程共享
作业状态写在 `backend/services/data/whatsapp_ext_job.json`，用「临时文件 + `os.replace`」原子写。
队列模式（`MY_APP_TASK_QUEUE=1`）下，任务可能跑在 Worker 进程、而 HTTP 端点在 Web 进程，
该文件与 DB 无关，因此 `sqlite` / `pg` 两种 `MY_APP_DB_MODE` 都适用。

作业状态机：`pending`（任务投递）→ `running`（扩展认领）→ `completed` / `failed`（扩展回报）。

## 环境变量
| 变量 | 默认 | 说明 |
|---|---|---|
| `WHATSAPP_GROUPS` | `test123,Test234` | 目标群组（与任务共用，逗号分隔） |
| `WHATSAPP_CAPTIONS` | 空→文件名 `*stem*` | 图片备注（与任务共用） |
| `SITE_OUTAGE_DIR` | `…/services/data/site_outage` | 图片目录（与任务共用） |
| `WHATSAPP_EXT_WAIT_SECONDS` | `300` | 任务最长等待扩展回报的秒数 |
| `WHATSAPP_EXT_POLL_INTERVAL` | `1.0` | 任务侧轮询作业文件的间隔（秒） |

## 主要函数
- `build_outbox_payload()`：返回 `{groups, items:[{name,caption,mime,url}], generated_at}`，
  每次调用都**重新扫描**图片目录（保证拿到最新截图）。
- `resolve_image_path(name)`：按文件名解析图片真实路径，**防路径穿越**；供出图端点用。
- `create_pending_job() / claim_pending_job() / complete_job()`：作业投递 / 认领 / 回报。
- `run_whatsapp_send_ext()`：任务入口，投递作业并等待回报，返回
  `{success, method:"extension", groups_sent, errors, elapsed_seconds}`。

## 直接自测
```bash
python -m backend.services.whatsapp_ext_service
# 会投递一个作业并等待（若没有开扩展，将在 WHATSAPP_EXT_WAIT_SECONDS 后超时返回）
```
