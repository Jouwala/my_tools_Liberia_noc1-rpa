# WhatsApp Image Sender（Chrome 扩展）

my_app 的第二种 WhatsApp 发图通道：直接运行在**用户已登录的 WhatsApp Web 标签页**里，
定时把 `site_outage` 截图发送到配置好的群组。与后端任务 **WhatsApp Message Send**
（`backend/services/whatsapp_service.py`，Playwright 自启浏览器）**并行存在**，
共用同一份图片目录与群组/备注配置。

> 0.1.1（2026-09-01 晚间）代码审查修复：
> 1. **认领顺序**：`claimAndRunJob` 现在先查「发送进行中」再认领后端作业。
>    旧顺序会在发送进行中时把作业领走又放弃，作业被空占直到 600s 超时判失败。
> 2. **停用开关真正生效**：顶层闹钟恢复改用已保存配置（旧代码传 DEFAULTS，
>    用户停用定时后 TICK 闹钟每分钟都会被重建回来）；`syncAlarms` 改为幂等创建
>    （旧代码每次 SW 唤醒都 create，会把下一次触发不断往后推、拖慢 tick）。
> 3. **防双发**：定时去重窗口改按 `finished_at`（完成时刻）计算——旧逻辑按开始
>    时刻算，长发送（>2 分钟）+ 相邻分钟命中 cron 时窗口早已过期，会双发。
> 4. **侧栏「清空输入框/页面诊断」自动补注入** content script（标签页早于扩展
>    打开/扩展刚重载时不再直接报「无法通信」）。
> 5. 发送结束自动清理 `下载目录/wa_ext_tmp/` 临时图片与下载记录（旧版需手动删）。
> 6. `performSend` 先确认 WhatsApp 标签页存在再拉图（页面没开时不白下载）。
> 7. 侧栏连接检测对后端返回缺 `groups/items` 字段时容错。

## 文件

| 文件 | 职责 |
| --- | --- |
| `manifest.json` | MV3 清单：storage / alarms / sidePanel / scripting / **debugger** / **downloads** 权限，web.whatsapp.com 与 localhost（nginx 80，备选 7038/8000）的 host 权限 |
| `background.js` | service worker：按 cron 定时触发、认领后端作业、拉取图片字节、激活标签页/恢复窗口、探活与补注入、代等（`wa:sleep`）、**CDP 调试器发送引擎（主发送路径）**、记录 `last_run` |
| `content.js` | 仅注入 WhatsApp Web 页面：搜索并打开群组、页面诊断、清场；合成事件发送路径仅作降级兜底 |
| `sidepanel.html/.js/.css` | 侧栏面板：后端地址/定时调度（cron）/启用开关、「立即发送」、「认领后端作业」、「清空输入框」、「页面诊断」、最近执行结果 |

## 安装

1. 确认 my_app 后端已在运行（与 `http://localhost/myapp/` 同一个后端，扩展默认走
   `http://localhost` 的 nginx 反代，**无需单独的 8000 服务**）。
2. Chrome 打开 `chrome://extensions` → 开启右上角「开发者模式」。
3. 「加载已解压的扩展程序」→ 选择本目录（`Task/my_app/whatsapp_sender_extension`）。
4. 打开并登录一个 WhatsApp Web 标签页（`https://web.whatsapp.com`）。
5. 点击扩展图标打开侧栏，确认「后端状态」为**可连接**。

## 三种触发方式

1. **定时发送（cron，与 sync 页面同格式）**
   侧栏配置调度表达式，格式与 `/myapp/?page=sync` 的任务调度一致：**5 段式
   分 时 日 月 周**（如 `0 8 * * *` = 每天 8 点、`0 */4 * * *` = 每 4 小时、
   `30 7 * * 1-5` = 工作日 7:30），侧栏提供快捷预设与人性化预览。
   扩展每 1 分钟检查一次，命中时刻直接从 `GET /api/whatsapp/outbox` 拉图发送；
   若该时刻后端恰有待发作业则改为认领作业（避免双发）。默认 `0 3 * * *`，
   与后端任务 `whatsapp_send_ext` 的 default_cron 一致。
2. **后端任务触发（拉取/工人模型）**
   后端任务 `whatsapp_send_ext`（WhatsApp 消息发送（扩展））运行时投递一个「待发作业」；
   扩展每分钟检查并认领 `GET /api/whatsapp/ext/job`，发送完成后把结果回报给后端，
   使任务在 `/myapp/?page=sync` 页面正常显示成功/失败/耗时。
3. **侧栏「立即发送」（手动）**
   不经过作业队列，直接从 `GET /api/whatsapp/outbox` 拉取最新图片清单并发送，便于测试。

## 后端接口（均在本机回环自动放行，无需 token）

- `GET /api/whatsapp/outbox` — 群组 + 图片清单
- `GET /api/whatsapp/outbox/image?name=<文件名>` — 图片字节（带路径穿越防护）
- `GET /api/whatsapp/ext/job` — 认领待发作业
- `POST /api/whatsapp/ext/job/result` — 回报发送结果

详见 `backend/routers/whatsapp_outbox.md`。

## 配置来源

- 群组：环境变量 `WHATSAPP_GROUPS`（逗号分隔，默认 `test123,Test234`）。
- 备注：环境变量 `WHATSAPP_CAPTIONS`（按序配对），缺省为 `*文件名*`。
- 图片目录：`backend/services/data/site_outage/`（排除名字含 `debug` 的文件）。

以上与原任务完全一致，见 `backend/services/whatsapp_service.py`。

## 已知限制

- 依赖 **Chrome 运行中、WhatsApp Web 标签页已打开且已登录**；浏览器或标签页关闭时无法发送
  （与 Playwright 任务自启浏览器不同）。
- **页面无需保持前台显示**（2026-09-01 修复）：此前 content script 的等待全部基于
  页面内 `setTimeout`，标签页隐藏 5 分钟后触发 Chrome「密集节流」（定时器最快 1 次/分钟），
  发送耗时膨胀数十倍，导致后端 300s 内收不到回报。现在所有等待经由 background
  service worker 代等（`wa:sleep` 消息往返），页面最小化、被遮挡、锁屏状态下
  均可正常发送；后台作业等待窗口默认放宽为 600s（`WHATSAPP_EXT_WAIT_SECONDS` 可调）。
- **备注不再堆在输入框**（2026-09-01 修复）：事故根因是「发送媒体」预览根本没弹出，
  备注选择器退化匹配到聊天输入框，备注被逐条打进聊天框、叠加成 `*REGULAR**ERA*…`。
  现在：备注只写预览里的备注框（`#main` 聊天区的元素一律跳过）；每张图发送前强制清空、
  发送后校验送达、失败即清场。图片进预览有四路尝试（文件选择 input → 粘贴 → 拖放 →
  附件菜单），预览始终不弹时会明确报错而不是乱打字。侧栏另有「清空输入框」按钮
  可随时清掉任何残留。
- **发送主路径已改为调试器/CDP 可信事件**（2026-09-01 晚间）：实测现版 WhatsApp Web
  无视 content script 派发的合成事件（文件注入/粘贴/拖放四路全灭、预览不弹），
  故改为 `chrome.debugger` 对标签页下发与 Playwright 等价的可信事件。按页面诊断的
  实测 DOM 定序：临时文件下载 + `DOM.setFileInputFiles` 直接注入合成器里隐藏的
  `input[type="file"][accept="image/*"]`（兜底：系统剪贴板 + 真实 Ctrl+V）、
  `Input.insertText` 写备注、真实鼠标点击发送。预览是否弹出用「可编辑框注入前后
  差异」判定（不再猜 aria 文案）；每个群进入后还会核验聊天输入框 aria 内嵌的群名，
  不匹配即跳过该群，防止误发进别的会话。附带现象：发送期间标签页短暂出现
  「WhatsApp Image Sender 已开始调试此浏览器」横幅（发完自动消失）；主路径会向
  `浏览器下载目录/wa_ext_tmp/` 写入临时图片（可手动删除）；若该标签页开着 DevTools，
  调试器无法附加，会降级回合成事件路径（大概率失败，先关 De